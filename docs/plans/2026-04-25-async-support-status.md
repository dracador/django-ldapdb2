# Async LDAP Support — Implementation Status

Last updated: 2026-04-26
Branch: `async-support` (forked from `main` @ 4374b33)
Plan: `docs/plans/2026-04-25-async-support.md`
Phase 0 spike report: `docs/plans/2026-04-25-async-support-spike-results.md`
User-facing docs: `docs/async.md`

## Phase status

| Phase | Status | Notes |
|-------|--------|-------|
| 0 — Validation spike | done | All sub-tasks pass plaintext + StartTLS. |
| 1 — Async connection | done | Folded into the unified `LDAPClient` (see refactor below). |
| 2 — Async cursor | done | `AsyncDatabaseCursor` thin-delegates to `LDAPClient.asearch`. |
| 3 — Backend integration | done | `LDAPQuerySet.aget`/`acount`/`afirst`/`aexists` + connection routing + 13 ORM tests. |
| Unified `*_ext` refactor | **done** | One `LDAPClient` for both modes; sync `*_s` calls eliminated outside connection setup. |
| 4 — Documentation & example | partial | `docs/async.md`, CLAUDE.local.md, and the example async view in `example/views.py` (+ smoke tests in `example/tests/test_views.py`) all done. README async section still pending. |
| 5 — Performance validation | done | `tests/bench/async_vs_sync.py` runs three scenarios; numbers documented in `docs/async.md`. |

Total: **167 tests pass** serially (`python -m django test --settings example.settings`) and with `--parallel=4` (3 consecutive runs green). One test (`AsyncLDAPConnectionReconnectE2ETests.test_reconnect_then_resume`) is gated behind `RUN_RECONNECT_TEST=1` because it restarts the docker container.

## Files added or modified

### New code (committed-worthy)
- `ldapdb/backends/ldap/connection.py` — **NEW** `LDAPClient`, the unified sync + async I/O wrapper. All I/O goes through `*_ext + result3`; sync mode retries on `SERVER_DOWN`, async mode surfaces `ConnectionResetError`.
- `ldapdb/backends/ldap/async_cursor.py` — `AsyncDatabaseCursor`, now a thin delegator to `LDAPClient.asearch` (collapsed from ~250 lines to lighter logic; same per-control-mode dispatch as the sync cursor).
- `ldapdb/backends/ldap/cursor.py` — `DatabaseCursor` rewired to take an `LDAPClient` (sync paged search picks up reconnect support it didn't have before); also `PrefetchedDatabaseCursor` + ContextVar bridge.
- `ldapdb/backends/ldap/base.py` — `DatabaseWrapper.ldap_client` (sync) and `aget_async_client` / `aclose_async_clients` (async per loop). `create_cursor` honors the prefetched-cursor contextvar.
- `ldapdb/backends/ldap/compiler.py` — `SQLUpdateCompiler` / `SQLInsertCompiler` / `SQLDeleteCompiler` now use `client.search/modify/add/delete` instead of `*_s`.
- `ldapdb/backends/ldap/lib.py` — added a comment explaining that `LDAPDatabase.ProgrammingError` (and friends) are tuples for `issubclass`-based translation, not raisable classes.
- `ldapdb/models/base.py` — `LDAPQuerySet.aget` / `acount` / `afirst` / `aexists` use the async `LDAPClient` via `aget_async_client`. `LDAPModel.save`'s rename uses `client.rename`.
- **DELETED**: `ldapdb/backends/ldap/async_connection.py` (subsumed by `connection.py`).

### Test infra
- `tests/openldap-server/Dockerfile` — generates a self-signed cert at image build
- `tests/openldap-server/slapd.conf` — added `TLSCertificateFile` / `TLSCertificateKeyFile`
- `tests/openldap-server/init-ldap.sh` — slapd now serves both `ldap:///` and `ldaps:///`

### Tests
- `example/tests/test_async_connection.py` (12) — connection-level coverage including TLS and gated reconnect
- `example/tests/test_async_cursor.py` (8) — three control modes vs sync, gather, count-annotation parity
- `example/tests/test_async_orm.py` (13) — `aget`/`acount`/`afirst`/`aexists` + sync-vs-async parity + gather concurrency

### Spikes (kept as regression checks)
- `tests/spikes/test_async_fileno.py`
- `tests/spikes/test_async_dispatch.py`
- `tests/spikes/test_async_paging.py`

### Documentation
- `docs/async.md` — user-facing async API doc
- `docs/plans/2026-04-25-async-support-spike-results.md` — Phase 0 report
- `CLAUDE.local.md` — added "Async support (in progress on `async-support` branch)" section under Architecture

## Pending work

### Phase 4 — Documentation & Example
- **4.1 (partial):** README async section is not yet written — `docs/async.md` exists but isn't linked from the README.
- **4.2 (done):** `example/views.py` contains `users_sync` and `users_async` demonstrating fan-out via `asyncio.gather`. Wired into `example/urls.py` at `/users/sync/` and `/users/async/`. Smoke tests in `example/tests/test_views.py` verify both endpoints return the same user set.

### Phase 5 — Performance validation (done)
- **5.1 (done):** `tests/bench/async_vs_sync.py` runs three scenarios — single `get`, fan-out × 10 ORM gets, and fan-out × 10 raw `LDAPClient` searches. Run via `.venv/bin/python tests/bench/async_vs_sync.py` (LDAP server must be running).
- **5.2 (done):** Localhost numbers documented in `docs/async.md`. Modest fan-out speedup (1.39× ORM, 1.08× raw) because per-call Python overhead dominates sub-ms localhost RTT — the speedup will scale roughly with N on a network-latent server.

### Async ORM gaps (out of scope for this PR but worth tracking)
- `aiterator()` over a queryset.
- Async writes via ORM (`asave`, `adelete`).
- Async transactions.

## Decisions made (record for future reference)

- **Unified `LDAPClient` on top of `*_ext`** — sync and async share one I/O contract; reconnect is handled in one place. Sync paged search now picks up reconnect support that `_apply_method_s` never gave it.
- **`rename` (not `rename_ext`)** — python-ldap exposes the non-blocking RDN-modify as `rename` (no `_ext` suffix). The other operations use `*_ext`. Idiosyncrasy of python-ldap; signature otherwise matches.
- **Prefetched-cursor + ContextVar bridge** for `aget` (vs. duplicating Django's row-to-model machinery). Trade-off: simple and reuses Django's compiler/iterables/from_db, at the cost of a `sync_to_async` hop after the I/O completes (cheap — pure Python work).
- **`acount` / `aexists` / `afirst` do not use the prefetched-cursor bridge** — they call `_async_fetch_rows` directly because Django's sync `count()`/`exists()` modify the query internally (e.g. count adds a `COUNT(*)` annotation), which would conflict with prefetched rows.
- **Per-event-loop connection cache, not per-coroutine.** Validated by the spike: 20+ concurrent in-flight msgids on one connection works fine.
- **Reconnect signal is `_reconnects_done`, not fd comparison.** Linux can reuse the same fd number for the new socket.
- **`OPT_X_TLS_NEWCTX = 0` must come *after* other TLS options** (libldap caches its TLS context).
- **`unittest.IsolatedAsyncioTestCase` cannot be used** for async tests in this project — it stashes a `contextvars.Context` on test instances which fails to pickle in Django's parallel test runner. Use `django.test.SimpleTestCase` (or `LDAPTestCase`) with `async def` test methods instead, plus an `@asynccontextmanager` helper for setup/teardown.
- **`LDAPDatabase.ProgrammingError` is a tuple, not a class** (used by Django's `DatabaseErrorWrapper` for `issubclass`-based translation). You can `except` it, but you cannot `raise` it. The cursor's `_check_closed` paths and `AsyncDatabaseCursor.execute` now raise `LDAPDatabase.DatabaseError` (a real class). A comment in `lib.py` documents this. A future cleanup could split each error category into a class + a matching tuple, but that touches every existing site and was deferred.

## How to resume

1. `git checkout async-support`
2. Start the LDAP test server: `docker compose -f ./tests/openldap-server/docker-compose.yaml up -d`
   (rebuild if the Dockerfile changed: `docker compose ... build`)
3. Run tests to confirm green: `.venv/bin/python -m django test --settings example.settings`
4. Pick up at Phase 4.1/4.2 (example async view + README) or 5.1 (benchmarks).
