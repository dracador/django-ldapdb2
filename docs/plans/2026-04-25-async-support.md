# Async LDAP Support Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Do not proceed past Phase 0 without explicit confirmation that the spike validated the assumptions.

**Goal:** Add a true asyncio-native code path to django-ldapdb2 so that LDAP queries issued from async Django views/ORM calls run on the event loop without blocking a thread, enabling concurrent fan-out queries (`asyncio.gather`) within a single request.

**Approach:** Stay on `python-ldap`. Drive concurrency by using the existing non-blocking `*_ext` request methods (`search_ext`, `add_ext`, `modify_ext`, etc.) and integrating the LDAP socket with asyncio's event loop via `loop.add_reader(conn.fileno(), ...)`. A msgid → `asyncio.Future` map dispatches incoming results to the awaiting coroutine. No transport switch (no `bonsai`, no `ldap3`), so all existing controls (SSSVLV, paging, transactions) keep working.

**Why this approach over alternatives:**
- `bonsai`: would force re-validation of every control we use; SSSVLV support is limited.
- `ldap3` async strategy: not actually asyncio-native, just message-id polling.
- Cooperative `result3(timeout=0)` polling with `asyncio.sleep`: wastes CPU, adds latency.
- Threadpool-wrapping sync calls (`sync_to_async`): no real concurrency benefit beyond what gthread workers already give Django; doesn't unlock `asyncio.gather` within a single request.

**Tech stack:** `python-ldap` (existing), `asyncio` (stdlib), Django async ORM hooks (`aget`, `afilter`, `aiterator`).

**Out of scope for this plan:**
- Replacing the sync code path. Sync stays as the default; async is additive.
- Async write operations beyond simple add/modify/delete (e.g., async transaction support — defer until sync transaction work in `controls.py` stabilizes).
- Async schema introspection — introspection happens once at startup, sync is fine.
- Connection pooling. Initially: one async connection per event loop, same lifetime semantics as current sync.

---

## Phase 0: Validation Spike (BLOCKING)

**Purpose:** Prove the core assumption — that `python-ldap`'s socket fd can be hooked into asyncio's event loop reliably, including with TLS — before committing to the full implementation. **If the spike fails or reveals showstoppers, abandon this plan and reconsider (`bonsai`, threadpool-only, etc.).**

### Task 0.1: Verify `LDAPObject.fileno()` returns a usable socket fd

**Files:**
- Create: `tests/spikes/test_async_fileno.py` (throwaway, do not commit unless useful as a regression test)

**Steps:**

1. Bind a connection to the test OpenLDAP server (`tests/openldap-server`).
2. Call `conn.fileno()`. Confirm:
   - Returns an integer.
   - The integer matches `conn.get_option(ldap.OPT_DESC)` if that option is exposed (sanity check).
   - Issuing `os.read()` directly on it fails (libldap should own the read; we just want it for `select`/`epoll` registration).
3. Repeat after `start_tls_s()`. Confirm fd is still valid (TLS may replace the underlying socket internally).
4. Repeat after `ReconnectLDAPObject` reconnects (force a disconnect — kill server, restart). Confirm fd may change. **This is critical:** the async wrapper must re-register on reconnect.

**Pass criteria:** fd is exposed, register-able, and we know whether TLS or reconnect changes it.

**Failure mode:** If `fileno()` is not exposed or unstable, abandon Phase 1+ and reopen the bonsai discussion.

### Task 0.2: PoC msgid → Future dispatch with `add_reader`

**Steps:**

1. Build a minimal harness:
   ```python
   class MiniAsyncLDAP:
       def __init__(self, conn):
           self.conn = conn
           self.waiters: dict[int, asyncio.Future] = {}
           asyncio.get_event_loop().add_reader(conn.fileno(), self._on_readable)

       def _on_readable(self):
           # Drain everything available
           while True:
               rtype, rdata, rmsgid, ctrls = self.conn.result3(msgid=ldap.RES_ANY, timeout=0)
               if rtype is None:
                   return
               fut = self.waiters.pop(rmsgid, None)
               if fut and not fut.done():
                   fut.set_result((rtype, rdata, ctrls))

       async def search(self, base, scope, filterstr):
           msgid = self.conn.search_ext(base, scope, filterstr)
           fut = asyncio.get_event_loop().create_future()
           self.waiters[msgid] = fut
           return await fut
   ```
2. Run two `asyncio.gather`-ed searches against the test server. Verify they:
   - Both complete.
   - Return correct (non-swapped) results.
   - Total wall time ≈ max(individual) not sum(individual).
3. Run with TLS enabled. Verify same behavior — readable events under TLS may fire spuriously (TLS record boundaries vs. application data). The drain-loop pattern above should tolerate spurious wakeups, but **measure**: count `_on_readable` calls vs. message arrivals.

**Pass criteria:**
- Concurrent searches resolve correctly.
- TLS works without deadlock or stuck waiters.
- Spurious-wakeup rate is reasonable (< 2x per real message).

**Failure mode (TLS):** If TLS readable events misbehave (e.g., never fire, or fire endlessly), evaluate whether `conn.set_option(ldap.OPT_X_TLS_*)` flags help. If not, async-on-python-ldap-with-TLS is not viable — abandon, re-evaluate bonsai.

### Task 0.3: PoC paged search

**Steps:**

1. Adapt `_execute_with_simple_paging` from `cursor.py:177` into an async version using the harness above. Each page boundary is a separate `search_ext` + `await result()`.
2. Verify paging completes correctly with > 1 page of results.

**Pass criteria:** Paged results match sync output exactly.

### Task 0.4: Spike report

**Output:** A short markdown summary in `docs/plans/2026-04-25-async-support-spike-results.md` documenting:
- Findings from 0.1–0.3.
- TLS behavior observed.
- Reconnect behavior observed.
- Decision: proceed to Phase 1, or abandon.

**Halt point:** Do not start Phase 1 without explicit user approval based on this report.

---

## Phase 1: Async Connection Wrapper

**Goal:** A reusable `AsyncLDAPConnection` class that owns the event-loop integration and msgid dispatch, callable from async code.

### Task 1.1: Skeleton `AsyncLDAPConnection`

**Files:**
- Create: `ldapdb/backends/ldap/async_connection.py`

**Responsibilities:**
- Wrap a `ldap.ldapobject.ReconnectLDAPObject` (NOT a new connection class — reuse).
- Hold the `dict[int, asyncio.Future]` waiter map.
- Register `add_reader(self.conn.fileno(), self._drain)` on first use; re-register on reconnect.
- Provide `async def search(...)`, `async def add(...)`, `async def modify(...)`, `async def delete(...)`, each returning the awaited result tuple.
- Provide `async def bind(bind_dn, bind_pw)` using `simple_bind` (non-`_s` variant) + `await result()`.
- Provide `close()` that unregisters the reader and unbinds.

**Key design decisions to settle in this task:**
- **Connection ownership:** one wrapper per `(event_loop, settings_dict)`? Per-coroutine? → Decide: one per event loop (matches Django's per-thread connection model, mapped to event loops for async). Rationale: avoids bind-storm; LDAP servers usually fine with multiplexed in-flight requests.
- **Cancellation:** if a coroutine is cancelled while awaiting a Future, the msgid still has an in-flight server response. Need to call `conn.abandon(msgid)` in the cancellation path and pop the waiter. Implement as a `try/finally` around the `await`.
- **Error mapping:** `result3` raises `ldap.LDAPError` subclasses. These must propagate through the Future. Catch in `_drain` and `set_exception` instead of `set_result`.

### Task 1.2: Reconnect handling

**Steps:**

1. Subclass or wrap `ReconnectLDAPObject` to detect when libldap has reconnected (fd may have changed).
2. On reconnect, unregister old fd, register new one. Re-bind. Fail any in-flight futures with a `ConnectionResetError`-equivalent — caller decides whether to retry.

**Validation:** kill the test server mid-search, restart it, verify next search succeeds.

### Task 1.3: Tests

**Files:**
- Create: `example/tests/test_async_connection.py`

**Coverage:**
- Single search awaits correctly.
- 10 concurrent searches via `asyncio.gather` complete; total time ≈ max single time + small overhead.
- Cancellation calls `abandon` (mock or check msgid not in waiters).
- Reconnect mid-flight raises a sensible exception, next search succeeds.
- TLS path runs (if test server has TLS configured — if not, skip with a `@unittest.skipUnless`).

---

## Phase 2: Async Cursor

**Goal:** A cursor that mirrors `DatabaseCursor` but uses the async connection. Same compiler output (`LDAPSearch`), same result formatting — just async I/O.

### Task 2.1: `AsyncDatabaseCursor`

**Files:**
- Create: `ldapdb/backends/ldap/async_cursor.py`
- Reference: `ldapdb/backends/ldap/cursor.py` for sync structure.

**Approach:**
- Mirror the public surface of `DatabaseCursor`: `aexecute`, `afetchone`, `afetchmany`, `afetchall`.
- Reuse `_sort_and_slice_ldap_results`, `set_description`, `format_results` from sync `cursor.py` (extract to a shared module if they aren't already module-level — check `cursor.py:23` for `_sort_and_slice_ldap_results`, it's already module-level, good).
- Three execution mode methods: `_aexecute_without_ctrls`, `_aexecute_with_simple_paging`, `_aexecute_with_sssvlv`. Each is the sync version with `await self.aconn.search(...)` instead of `self.connection.search_st(...)` + `result3(...)`.
- Paging loop stays a `while True` — it's inherently sequential per-search. Async helps *across* searches, not within one.

### Task 2.2: Compiler reuse verification

**Steps:**

1. Confirm `SQLCompiler.as_sql()` (`compiler.py`) is pure Python with no I/O. Spot-check by reading the class.
2. The async cursor consumes the same `query.ldap_search` object the sync cursor does. No compiler changes needed.

**Validation:** Run an async test that compiles a complex query (annotations, multi-attr ordering, paging) and compare its `LDAPSearch` to the sync output. They must be byte-identical.

### Task 2.3: Tests

**Files:**
- Create: `example/tests/test_async_cursor.py`

**Coverage:**
- All three control modes (no_ctrl, simple_paged, sssvlv) execute and return correct rows.
- Concurrent `asyncio.gather` over distinct queries returns correct, non-mixed results.
- Count queries (the special-case at `cursor.py:138-152`) work.

---

## Phase 3: Backend Integration

**Goal:** Wire the async cursor into Django's database machinery so that `await Model.objects.aget(...)` actually uses our async path instead of falling through to `sync_to_async`.

### Task 3.1: Investigate Django's async ORM dispatch

**This is research, not code.** Output a short note in this plan (or as a comment in code) documenting:

- Where Django's `aget` actually ends up calling the backend. Last verified: it goes through `QuerySet._aexecute()` which, as of Django 6.0, *still* wraps the sync compile/execute in `sync_to_async`. **There is no clean hook to inject an async cursor.** This is the central problem.

- Possible workarounds:
  1. **Override `aget`/`afilter`/`aiterator` at the manager/queryset level** for `LDAPModel`. Provide a custom `LDAPManager` whose async methods call our async cursor directly, bypassing Django's threadpool wrapper.
  2. **Patch `BaseDatabaseWrapper.aexecute_sql`** (if it exists in current Django; verify) to delegate to our async cursor when the connection's vendor is `'ldap'`.
  3. **Custom queryset class** with `__aiter__` that streams via the async cursor.

**Decision criterion:** Whichever approach works without monkey-patching Django internals is preferred. If all require Django patches, prefer (1) — manager-level — as it's local to ldapdb2.

### Task 3.2: Manager-level async methods

**Files:**
- Modify: `ldapdb/models/base.py` — add `LDAPManager` (subclass of `models.Manager`) and assign it as `objects` on `LDAPModel`.
- Add: `aget`, `afilter` (returns a coroutine yielding a list, or an async-iterable queryset), `aiterator`.

**Implementation sketch:**
```python
class LDAPManager(models.Manager):
    async def aget(self, **kwargs):
        qs = self.filter(**kwargs)
        # Use our compiler to build LDAPSearch, then run via async cursor.
        ldap_search = qs.query.ldap_search  # populated by compiler
        async with get_async_cursor(self.db) as cursor:
            await cursor.aexecute(qs.query)
            rows = await cursor.afetchall()
        # Reuse iterables.LDAPModelIterable to materialize models from rows.
        ...
```

The hard part is reusing `LDAPModelIterable` (`ldapdb/iterables.py`) which currently iterates sync. May need an `AsyncLDAPModelIterable` or factor out the row-to-model conversion as a pure function.

### Task 3.3: Connection routing

**Files:**
- Modify: `ldapdb/backends/ldap/base.py` — add `get_async_connection()` method on `DatabaseWrapper` that lazy-creates an `AsyncLDAPConnection` per event loop.
- Modify: `ldapdb/router.py` if needed — async queries route to the LDAP database same as sync.

**Caveat:** `DatabaseWrapper.connection` is per-thread (Django manages this). Per-event-loop async connections need their own storage — likely a `dict[asyncio.AbstractEventLoop, AsyncLDAPConnection]` on the wrapper, with cleanup on loop close.

### Task 3.4: Tests

**Files:**
- Create: `example/tests/test_async_orm.py`

**Coverage:**
- `await LDAPUser.objects.aget(uid='x')` returns the user.
- `asyncio.gather` of 5 `aget` calls completes in ~1× single-query time, not 5×.
- `async for user in LDAPUser.objects.aiterator(): ...` streams correctly.
- Errors (DoesNotExist, MultipleObjectsReturned) raise correctly through the async path.

---

## Phase 4: Documentation & Example

### Task 4.1: User-facing docs

**Files:**
- Create: `docs/async.md` — explain how to use async ORM with `LDAPModel`, what's supported, what isn't, performance expectations.
- Update: `README.md` — short async section with a fan-out example (`asyncio.gather` over multiple `aget`s).

### Task 4.2: Example app async view

**Files:**
- Modify: `example/urls.py`, add an async view.
- Create: `example/views.py` if not present, with a demo async fan-out view.

**Purpose:** Smoke test integration end-to-end and serve as copy-paste reference for users.

### Task 4.3: CLAUDE.local.md update

**Files:**
- Modify: `CLAUDE.local.md` — add an "Async" section under Architecture pointing to `ldapdb/backends/ldap/async_connection.py` and `async_cursor.py`, and the manager hooks in `models/base.py`.

---

## Phase 5: Performance Validation

### Task 5.1: Benchmark

**Files:**
- Create: `tests/bench/async_vs_sync.py` (throwaway/dev-only).

**Scenarios:**
1. Single `get` — sync vs. async. Expect: async is slightly slower (event loop overhead).
2. Fan-out of 10 independent `get`s — sync sequential vs. `asyncio.gather`. Expect: 5–10× speedup (latency-bound, server fast enough).
3. Group hierarchy traversal (representative of elewom's `LDAPGroupGraph`) — sequential sync vs. async-parallel. Expect: large speedup proportional to tree fan-out.

### Task 5.2: Document results

Update `docs/async.md` with measured numbers. If speedups fall short of expectations, investigate before declaring done.

---

## Risk register

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| TLS readable-event behavior breaks dispatch | Medium | High | Phase 0 spike validates this first. |
| `LDAPObject.fileno()` not stable across reconnect | Medium | Medium | Phase 0.1 + reconnect handling in Task 1.2. |
| Django's async ORM hooks don't actually call our async cursor | High | Medium | Phase 3.1 research; fallback is manager-level methods. |
| Cancellation leaks msgids server-side | Low | Low | `abandon()` in cancellation path (Task 1.1). |
| `ReconnectLDAPObject` re-bind happens during a search and silently breaks dispatch | Medium | Medium | Wrap reconnect to invalidate fd registration. |

---

## Decision log (filled in as we go)

- (placeholder — record TLS findings here after Phase 0)
- (placeholder — record connection-per-loop vs. per-coroutine decision rationale here after Task 1.1)
- (placeholder — record the chosen async ORM dispatch strategy after Task 3.1)
