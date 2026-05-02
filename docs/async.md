# Async LDAP Support

Status: experimental, on the `async-support` branch.

`django-ldapdb2` supports asyncio-native LDAP access alongside the existing
sync API. **Both** code paths now share one I/O contract: every operation
goes through python-ldap's non-blocking `*_ext` request methods plus
`result3`. The two flavors differ only in how they wait for a response:

- **Sync**: `result3(msgid, timeout=-1)` blocks the calling thread.
- **Async**: the LDAP socket is hooked into asyncio's event loop via
  `loop.add_reader(conn.fileno(), ...)`. A `msgid -> asyncio.Future` map
  fans incoming results out to the awaiting coroutine, so multiple
  in-flight requests on the same connection are multiplexed by message ID.

Reconnect on `SERVER_DOWN` is handled in one place
(`LDAPClient._sync_call` / `LDAPClient._before_async_request`) instead of
relying on `ReconnectLDAPObject._apply_method_s`, which only fires for
`*_s` calls and didn't cover the paged-search path.

## What's supported

| Operation                     | Async API                              | Notes                                                                                |
|-------------------------------|----------------------------------------|--------------------------------------------------------------------------------------|
| `Model.objects.aget(...)`     | yes                                    | Raises `DoesNotExist` / `MultipleObjectsReturned` like sync `.get()`                 |
| `qs.acount()`                 | yes                                    | Counts rows from the async-fetched result set                                        |
| `qs.afirst()`                 | yes                                    | Returns `None` on empty                                                              |
| `qs.aexists()`                | yes                                    | Limits the search to one entry                                                       |
| Direct cursor access          | `AsyncDatabaseCursor` + `aexecute`     | All three control modes (no_control / simple_paged / sssvlv)                         |
| Direct client access          | `LDAPClient` + `asearch`/`aadd`/...    | One class for sync + async; pick the method flavor you need                           |
| StartTLS                      | yes                                    | The wrapper does not need to re-register the reader; the fd is stable across upgrade |

## What's not supported (yet)

- `aiterator()` over a queryset (planned).
- Async writes via the ORM (`asave`, `adelete`). The sync write compilers
  still execute on the sync side of the unified `LDAPClient`. They benefit
  from the unified reconnect logic, but they're not parallelizable across
  coroutines yet.
- Async transactions (deferred until the sync transaction work in
  `controls.py` stabilizes).

## Example views

The example app ships two demo views under `example/views.py` that you can
hit to compare sync and async fan-out side by side:

- `GET /users/sync/` — sequential `LDAPUser.objects.get(...)` over three
  seed users.
- `GET /users/async/` — `asyncio.gather(*[LDAPUser.objects.aget(...)])` over
  the same three users.

Both return the same JSON shape (`mode`, `count`, `elapsed_ms`, `users`).
Run the example app under an ASGI server (e.g. `uvicorn example.asgi:application`)
to see the async path behave as a real ASGI request would.

## The point: `asyncio.gather` over a single connection

The sync API already supports one query at a time. The reason to use the
async API is to fan out multiple queries inside a single request without
blocking a thread per query. For example:

```python
# Resolve a tree of group memberships with N concurrent searches.
async def expand_groups(group_dns):
    groups = await asyncio.gather(
        *[LDAPGroup.objects.aget(dn=dn) for dn in group_dns]
    )
    return groups
```

All N `aget` calls go on the wire at the same time over **one** LDAP
connection, multiplexed by msgid. The event loop awaits all responses
together, so the wall time is approximately one query's worth of latency,
not N.

A sync `for` loop or a `sync_to_async`-wrapped sync `get` would either run
serially or fan out to a thread pool — neither leverages LDAP's native
multiplexing.

## Connection model

Each event loop that runs async ORM calls gets its own async `LDAPClient`
(cached on the `DatabaseWrapper`). `add_reader` registrations are
loop-local, so clients cannot be shared across loops.

Within one loop, the client is reused for the lifetime of that loop;
multiple coroutines on the same loop multiplex onto the same socket. To
explicitly close per-loop async clients at shutdown:

```python
from django.db import connections
await connections['ldap'].aclose_async_clients()
```

The sync side has its own client too, accessed via
`connections['ldap'].ldap_client`. The update/insert/delete compilers and
`LDAPModel.save()` all go through it; you generally don't interact with
it directly.

## TLS configuration gotcha

When configuring TLS via `CONNECTION_OPTIONS` in `settings.py`, the order of
the options matters. python-ldap (libldap) caches a TLS context internally;
to make `OPT_X_TLS_REQUIRE_CERT` (or any other TLS option) actually take
effect, you must set `OPT_X_TLS_NEWCTX = 0` *after* the other TLS options:

```python
DATABASES = {
    'ldap': {
        'ENGINE': 'ldapdb.backends.ldap',
        # ...
        'CONNECTION_OPTIONS': {
            ldap.OPT_X_TLS_REQUIRE_CERT: ldap.OPT_X_TLS_NEVER,
            ldap.OPT_X_TLS_NEWCTX: 0,  # MUST come last to apply the above
        },
    },
}
```

Without `OPT_X_TLS_NEWCTX = 0`, libldap silently reuses its prior TLS
context and ignores your new options.

## How model construction stays sync

Model materialization (rows → `LDAPUser` instances) still goes through
Django's sync ORM machinery (the compiler, `LDAPModelIterable`,
`Model.from_db`). The async manager methods pre-fetch rows via the async
cursor, then bridge them into the sync ORM via a `PrefetchedDatabaseCursor`
parked on a `ContextVar`. Inside `sync_to_async(qs.get)`, Django's
`DatabaseWrapper.create_cursor` returns the prefetched cursor (rows already
loaded) instead of opening a real one — so the sync ORM produces a model
without a second network round-trip.

This means:
- The expensive part (LDAP I/O) runs on the event loop.
- The cheap part (Python-side row-to-model) runs in `sync_to_async`'s
  thread executor — but it's all in-memory, so it doesn't block.

## Reconnect behavior

Both flavors of `LDAPClient` handle `SERVER_DOWN` themselves rather than
relying on `ReconnectLDAPObject._apply_method_s` (which only fires for
`*_s` calls — the `*_ext` methods we use exclusively don't trip it).

- **Sync**: on `SERVER_DOWN`, the client force-unbinds, calls
  `conn.reconnect(uri, retry_max, retry_delay)` (which re-binds with the
  original credentials), and retries the operation once. If reconnect
  itself fails after `retry_max` attempts, the original `SERVER_DOWN`
  propagates. This mirrors the semantics `_apply_method_s` provided for
  the `*_s` paths, and it now also covers paged searches and any other
  `*_ext`-based path that previously had no transparent retry.
- **Async**: reconnects are detected observationally via the
  `_reconnects_done` counter. On a detected reconnect, the wrapper fails
  any in-flight request futures with `ConnectionResetError` and
  re-registers the `add_reader` callback on the (possibly new) fd. The
  wrapper does not transparently retry on the loop — the caller decides
  whether to retry. Transparent loop-side retry would require dispatching
  the (blocking) reconnect to an executor, which we deliberately defer.

Note that on Linux the fd *number* may be reused even though the
underlying socket has been replaced — fd-comparison alone is not a
reliable reconnect signal. Use the counter.

## Performance expectations

- Single `aget` is roughly the same wall time as sync `get` on localhost.
  Event-loop overhead is real but small; `sync_to_async` round-trip
  dominates either way.
- `asyncio.gather` over N independent `aget`s is faster than N sequential
  awaits by a factor that scales with the server's RTT. On localhost
  (sub-millisecond network) the speedup is modest; on a network-latent
  server (5–50 ms RTT typical for corporate AD) it should approach N.
- Spurious wakeup rate (drains-per-message) measured at ~4.4 on localhost
  for both plaintext and StartTLS — well within the asyncio overhead
  budget for typical workloads. The drain-loop pattern is robust to this.

### Measured numbers (localhost, OpenLDAP 2.6 in Docker)

`tests/bench/async_vs_sync.py` measures the median of 25 runs per scenario.
Numbers below are illustrative — local hardware, in-process LDAP, no
network latency.

| Scenario                                       | Sync (ms) | Async (ms) | Async/Sync |
|------------------------------------------------|-----------|------------|------------|
| Single `get` / `aget`                          |     3.21  |     3.26   | 0.99×      |
| Fan-out × 10 ORM gets (sequential vs `gather`) |    27.98  |    20.14   | **1.39×**  |
| Fan-out × 10 raw client searches               |    41.93  |    38.89   | 1.08×      |

The fan-out speedup is **modest on localhost** because the per-call Python
overhead (compile, format, materialize) dominates when the network round-trip
is ~0 ms. The whole point of `asyncio.gather` is to amortize latency across
in-flight requests; with localhost latency below a millisecond, there's not
much to amortize. Expect the speedup to scale up to roughly N for an LDAP
server with non-trivial RTT.

For the methodology and the validation spike that established the design,
see `docs/plans/2026-04-25-async-support-spike-results.md`.
