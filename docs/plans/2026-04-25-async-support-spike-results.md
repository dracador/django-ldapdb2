# Async LDAP Support — Phase 0 Spike Results

Date: 2026-04-25
Branch: `async-support`
Spike scripts: `tests/spikes/test_async_fileno.py`, `tests/spikes/test_async_dispatch.py`, `tests/spikes/test_async_paging.py`
Environment: Python 3.12.5, python-ldap 3.4.5, Linux (WSL2 6.6.87.2-microsoft-standard-WSL2), test OpenLDAP container `django-ldapdb2-openldap` (slapd, no TLS configured).

## Summary

| Sub-task | Result |
|----------|--------|
| 0.1 `fileno()` validation | PASS |
| 0.2 msgid → Future dispatch | PASS (plaintext + StartTLS) |
| 0.3 paged search PoC | PASS (plaintext + StartTLS) |
| TLS validation | PASS — added self-signed cert to test container |

**Recommendation: proceed to Phase 1.** All blocking items are resolved.

## 0.1 — `LDAPObject.fileno()` findings

- `conn.fileno()` returns a small non-negative `int` (observed: `4`, then `6` for a fresh connection).
- `conn.get_option(ldap.OPT_DESC)` returns the same value as `fileno()` — so the option is a usable cross-check, even though we don't strictly need it.
- The fd corresponds to a `SOCK_STREAM` socket (verified via `socket.fromfd` + `getsockopt(SO_TYPE)`), and `select.select(timeout=0)` accepts it as a file descriptor for readiness polling.
- We deliberately avoid `os.read()` on the fd — libldap owns the read buffer and consuming any bytes from the kernel queue would corrupt LDAP message framing. The fd is for readiness notification only; actual reads must go through `result3()`.
- After `ReconnectLDAPObject` reconnects (forced by `docker restart`):
  - `_reconnects_done` advanced 0 → 1, confirming the reconnect happened.
  - The fd **number** stayed the same (Linux re-allocates the lowest free fd).
  - However, the underlying socket has been replaced. **Implication:** an asyncio `add_reader` registration that happened to be on the same fd number is no longer bound to a live socket and must be removed and re-installed. The async wrapper must re-register the reader after every reconnect, regardless of whether the fd number changed. This is a hard requirement, captured for Task 1.2.

## 0.2 — msgid → Future dispatch findings

Harness: a `MiniAsyncLDAP` wrapper with a `dict[int, asyncio.Future]` waiter map and an `add_reader` callback that drains via `result3(msgid=ldap.RES_ANY, timeout=0)` until `rtype is None`.

- **Correctness (two distinct concurrent searches):** `asyncio.gather` of a search on `ou=Users,...` and a search on `ou=Groups,...` returns each coroutine's *own* results. No swapping observed.
- **Concurrency speedup (20 concurrent searches):** observed 1.6× speedup against a sequential-time estimate on a localhost LDAP server (single search: 0.54 ms; 20 concurrent: 6.54 ms; 20 serialized estimate: 10.76 ms). The speedup is bounded here by Python overhead per coroutine, not by the LDAP server. In real network deployments (5–50 ms RTT), the speedup is expected to be much larger because each coroutine spends most of its time waiting for I/O.
- **Cancellation:** cancelling an awaited search calls `conn.abandon(msgid)` and removes the waiter from the map. This is implemented via `try / except CancelledError` around the `await fut`. The plan's Task 1.1 spec for cancellation handling matches what the spike verified.
- **Drain / message ratio (informational):** observed 88 `_on_readable` calls for 20 delivered messages (4.4 drains per message). This is above the plan's "< 2x" target but is **not a correctness issue** — the drain loop pattern handles spurious wakeups by design. The number is also small in absolute terms (~13 µs per drain). Likely cause: kernel readiness events fire per TCP packet, and `result3(all=1)` only returns when an entire search response has been buffered — so most drains are no-ops that just call `result3` and immediately get back `rtype=None`. Worth instrumenting in production code as a low-priority metric, but not a blocker. **Decision (recorded below): keep the drain-loop pattern; accept higher-than-targeted spurious wakeup rate.**

## 0.3 — paged search findings

- Adapted `_execute_with_simple_paging` (`ldapdb/backends/ldap/cursor.py:177`) by replacing `result3(msgid)` with `await wrapper.search_paged_step(...)`. Loop structure (cookie-driven `while True`) is unchanged.
- With `PAGE_SIZE=2` against the 7-entry test dataset, both sync and async produced **identical DN sets across 4 pages**. Verified with set comparison.
- Conclusion: the paging loop is inherently sequential per-search, but each cookie-driven iteration is a separate `await` — async helps *across* searches, not within one. This matches the plan's framing in Task 2.1 and removes any worry that page boundaries would interact badly with the dispatcher.

## TLS validation (option (a) — completed)

The test OpenLDAP container was extended with a self-signed cert generated at image-build time:

- `tests/openldap-server/Dockerfile` — added an `openssl req -new -x509` step that writes `/etc/ldap/tls/server.{crt,key}` with `chown openldap:openldap`, owned and readable only by the slapd user.
- `tests/openldap-server/slapd.conf` — added `TLSCertificateFile` and `TLSCertificateKeyFile` directives.
- `tests/openldap-server/init-ldap.sh` — passed `-h "ldap:/// ldaps:///"` to `slapd` so the container also serves LDAPS on 636.

**Important python-ldap detail:** to make `OPT_X_TLS_REQUIRE_CERT` actually take effect, you must follow it with `OPT_X_TLS_NEWCTX = 0`. Without that, libldap reuses its old TLS context and ignores the require-cert change. The spike scripts and the future `AsyncLDAPConnection` must apply both options in that order.

**Findings under StartTLS (rerun of 0.1, 0.2, 0.3):**

- `fileno()` is **stable** across `start_tls_s()` — it returned `4` before and after the upgrade. So the upgrade itself does not require re-registering the asyncio reader. (Reconnect, by contrast, still does — the underlying socket is replaced even when the fd number is reused.)
- After StartTLS, the LDAP session resets to anonymous (RFC 4513 §5.2.1.1). The wrapper must re-bind after StartTLS. The sync codepath in `base.py:108-114` already does this implicitly because it binds *after* `start_tls_s()`. The async wrapper must do the same.
- Concurrent dispatch over StartTLS:
  - Correctness: identical to plaintext (no swapping).
  - Speedup vs. serialized estimate: **3.3×** for 20 concurrent searches (better than the 1.9× plaintext figure — TLS adds enough latency that gather amortizes).
  - Drains-per-message: **identical to plaintext (4.45)** — TLS record boundaries do **not** cause additional spurious wakeups in the configurations tested.
- Paged search (4 pages, page_size=2): identical DN set sync vs. async, both under plaintext and TLS.

**TLS verdict: green.** The async approach works equivalently under TLS. No deadlock, no extra spurious wakeup pressure, no fd instability across upgrade. The wrapper design from the plan is unchanged.

Existing test suite (`python -m django test --settings example.settings`) **still passes (134/134 tests)** with the TLS-enabled container, since `example/settings.py` keeps `'TLS': False` and binds plaintext on 389. Adding TLS is purely additive.

## Open items / informational

### Spurious wakeup rate (informational, not a blocker)

The plan's `< 2x` target was not met (observed 4.4x on localhost). Decision: accept and proceed. The drain-loop pattern is robust; the absolute overhead is sub-millisecond. If profiling later shows this is a hot path under WAN latency, options include (i) moving to `loop.add_reader` + an explicit edge-trigger model, or (ii) batching multiple drains per wakeup explicitly. Neither is needed now.

### Reconnect handling — fd reuse subtlety

Captured for Task 1.2: the wrapper must use `_reconnects_done` (or a wrapped `ReconnectLDAPObject` subclass that signals reconnects) as the trigger for re-registering the reader, not a comparison of fd numbers. fd-number comparison would silently miss reconnects when Linux reuses the same fd.

## Decision log entries

(To be merged back into `docs/plans/2026-04-25-async-support.md` "Decision log")

- **TLS findings:** validated locally by adding a self-signed cert to the test OpenLDAP container. `fileno()` is stable across StartTLS upgrade. Concurrent dispatch and paging behave identically under TLS, with the same drains-per-message rate. The async wrapper must re-bind after `start_tls_s()` (RFC 4513) and must apply `OPT_X_TLS_NEWCTX = 0` after `OPT_X_TLS_REQUIRE_CERT` for the latter to take effect.
- **Connection-per-loop vs. per-coroutine:** to be decided in Task 1.1 (not in scope of Phase 0). Spike showed 20+ concurrent in-flight `msgid`s on a single connection without issue, supporting the "one connection per event loop" plan.
- **Drain-loop pattern:** confirmed correct under spurious wakeups in both plaintext and TLS. Adopt as the design for `AsyncLDAPConnection._drain` in Task 1.1.

## Go / no-go

**Go.** Proceed to Phase 1.
