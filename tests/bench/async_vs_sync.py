"""
Microbenchmark comparing the sync and async ORM paths of ``django-ldapdb2``.

Run from the repo root with the LDAP test server running:

    .venv/bin/python tests/bench/async_vs_sync.py

What it measures
----------------
Three scenarios, each timed sync and async:

1. **Single get** — one ``LDAPUser.objects.get(...)`` (sync) and one
   ``await LDAPUser.objects.aget(...)`` (async). Expect async to be slightly
   slower due to event-loop overhead.
2. **Fan-out get x N** — N sequential ``get`` (sync) vs ``asyncio.gather`` of
   N ``aget`` (async). On localhost, the speedup is modest because Python
   per-call overhead dominates each ``get``. On a network-latent server, it
   should scale roughly with N up to the server's concurrent-request limit.
3. **Concurrent search x N** — same pattern but with the lower-level
   ``LDAPClient`` directly, side-stepping the prefetched-cursor bridge so
   you can see the raw msgid-multiplexing benefit.

Wall-time numbers are local-only and only meaningful as a *relative* signal.
The benchmark prints median-of-K runs so a single outlier doesn't dominate.
"""

from __future__ import annotations

import asyncio
import os
import statistics
import sys
import time
from pathlib import Path

# Make the project root importable regardless of cwd.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# This is a benchmark: running ORM code from inside ``asyncio.run(...)``
# without a full Django ASGI stack means ``sync_to_async`` falls back to the
# main thread, which has a running event loop, which trips
# ``async_unsafe`` on ``connection.cursor()``. The check exists to protect
# user code; for a benchmark we bypass it.
os.environ.setdefault('DJANGO_ALLOW_ASYNC_UNSAFE', '1')

import django  # noqa: E402

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'example.settings')
django.setup()

# Quiet the per-query DEBUG logger that the example settings turn on; it
# floods benchmark output with the compiled LDAPSearch for every call.
import logging  # noqa: E402

logging.getLogger('django.db.backends').setLevel(logging.WARNING)
logging.getLogger('ldapdb').setLevel(logging.WARNING)

import ldap  # noqa: E402
from ldap.ldapobject import ReconnectLDAPObject  # noqa: E402

from example.models import LDAPUser  # noqa: E402
from ldapdb.backends.ldap.connection import LDAPClient  # noqa: E402


URI = 'ldap://localhost'
BIND_DN = 'uid=admin,ou=Users,dc=example,dc=org'
BIND_PW = 'adminpassword'
USERS_BASE = 'ou=Users,dc=example,dc=org'

USERNAMES = ['admin', 'user1', 'user2']
RUNS = 25  # samples per scenario for the median
N_FANOUT = 10  # how many concurrent ops in the fan-out scenarios


def _median_ms(samples_seconds: list[float]) -> float:
    return statistics.median(samples_seconds) * 1000.0


# --------------------------------------------------------------------- #
# Scenario 1: single get                                                #
# --------------------------------------------------------------------- #


def bench_single_sync() -> float:
    samples = []
    for _ in range(RUNS):
        t0 = time.perf_counter()
        LDAPUser.objects.get(username='user1')
        samples.append(time.perf_counter() - t0)
    return _median_ms(samples)


async def bench_single_async() -> float:
    samples = []
    for _ in range(RUNS):
        t0 = time.perf_counter()
        await LDAPUser.objects.aget(username='user1')
        samples.append(time.perf_counter() - t0)
    return _median_ms(samples)


# --------------------------------------------------------------------- #
# Scenario 2: fan-out N gets via the ORM                                #
# --------------------------------------------------------------------- #


def bench_fanout_sync(n: int) -> float:
    samples = []
    for _ in range(RUNS):
        t0 = time.perf_counter()
        for _i in range(n):
            LDAPUser.objects.get(username='user1')
        samples.append(time.perf_counter() - t0)
    return _median_ms(samples)


async def bench_fanout_async(n: int) -> float:
    samples = []
    for _ in range(RUNS):
        t0 = time.perf_counter()
        await asyncio.gather(
            *[LDAPUser.objects.aget(username='user1') for _ in range(n)]
        )
        samples.append(time.perf_counter() - t0)
    return _median_ms(samples)


# --------------------------------------------------------------------- #
# Scenario 3: raw client (skip the ORM bridge)                          #
# --------------------------------------------------------------------- #


def _raw_conn() -> ReconnectLDAPObject:
    conn = ReconnectLDAPObject(uri=URI, retry_max=3, retry_delay=0.5, bytes_mode=False)
    conn.set_option(ldap.OPT_X_TLS_REQUIRE_CERT, ldap.OPT_X_TLS_NEVER)
    conn.set_option(ldap.OPT_X_TLS_NEWCTX, 0)
    conn.simple_bind_s(BIND_DN, BIND_PW)
    return conn


def bench_raw_sync_search(n: int) -> float:
    client = LDAPClient(_raw_conn())
    samples = []
    try:
        for _ in range(RUNS):
            t0 = time.perf_counter()
            for _i in range(n):
                client.search(USERS_BASE, ldap.SCOPE_SUBTREE, '(objectClass=*)', ['dn'])
            samples.append(time.perf_counter() - t0)
    finally:
        client.close()
    return _median_ms(samples)


async def bench_raw_async_search(n: int) -> float:
    client = LDAPClient(_raw_conn(), loop=asyncio.get_event_loop())
    samples = []
    try:
        for _ in range(RUNS):
            t0 = time.perf_counter()
            await asyncio.gather(*[
                client.asearch(USERS_BASE, ldap.SCOPE_SUBTREE, '(objectClass=*)', ['dn'])
                for _ in range(n)
            ])
            samples.append(time.perf_counter() - t0)
    finally:
        await client.aclose()
    return _median_ms(samples)


# --------------------------------------------------------------------- #
# Main                                                                  #
# --------------------------------------------------------------------- #


def _hr(label: str) -> None:
    print()
    print(f'== {label} ==')


def _row(name: str, ms: float, *, ref: float | None = None) -> None:
    if ref is None:
        print(f'  {name:<28s} {ms:8.2f} ms')
    else:
        ratio = ref / ms if ms > 0 else float('inf')
        print(f'  {name:<28s} {ms:8.2f} ms  ({ratio:.2f}x sync)')


async def main_async() -> int:
    # Pre-warm the features cache on the sync_to_async worker thread.
    # Django's connection handler is per-thread; the prewarm in main()
    # only populated the main thread, but ORM compiles inside aget run on
    # the sync_to_async worker. Without this, the first compile there
    # would call connection.cursor() (async_unsafe) and crash.
    from asgiref.sync import sync_to_async  # noqa: PLC0415

    await sync_to_async(_prewarm_features, thread_sensitive=True)()

    print(f'Runs per scenario: {RUNS}')
    print(f'Fan-out width: {N_FANOUT}')
    print(f'Server: {URI} (binding as {BIND_DN!r})')

    _hr('Scenario 1: single get')
    sync_single = bench_single_sync()
    async_single = await bench_single_async()
    _row('sync get(username="user1")', sync_single)
    _row('async aget(username="user1")', async_single, ref=sync_single)

    _hr(f'Scenario 2: fan-out {N_FANOUT} ORM gets')
    sync_fanout = bench_fanout_sync(N_FANOUT)
    async_fanout = await bench_fanout_async(N_FANOUT)
    _row(f'sync: {N_FANOUT} sequential get', sync_fanout)
    _row(f'async: gather of {N_FANOUT} aget', async_fanout, ref=sync_fanout)
    if sync_fanout > 0:
        speedup = sync_fanout / async_fanout if async_fanout > 0 else float('inf')
        print(f'  → ORM fan-out speedup: {speedup:.2f}x')

    _hr(f'Scenario 3: fan-out {N_FANOUT} raw LDAPClient searches')
    sync_raw = bench_raw_sync_search(N_FANOUT)
    async_raw = await bench_raw_async_search(N_FANOUT)
    _row(f'sync: {N_FANOUT} sequential search', sync_raw)
    _row(f'async: gather of {N_FANOUT} asearch', async_raw, ref=sync_raw)
    if sync_raw > 0:
        speedup = sync_raw / async_raw if async_raw > 0 else float('inf')
        print(f'  → raw fan-out speedup: {speedup:.2f}x')

    print()
    print('Notes:')
    print('  - All numbers are localhost; expect larger fan-out speedups when')
    print('    the LDAP server is network-latent (5+ ms RTT).')
    print('  - Single-call async is slightly slower than sync — event-loop +')
    print('    sync_to_async overhead. The win shows up when you fan out.')
    print('  - The "raw" scenario isolates the msgid-multiplexing benefit from')
    print('    the prefetched-cursor / sync_to_async overhead in the ORM path.')
    return 0


def _prewarm_features() -> None:
    """Force the rootDSE / features cache to populate from a sync context.

    Also runs one real sync ``get`` so any per-thread connection state
    initialization happens before we start timing. Otherwise the first
    compile from an async path can hit code (``connection.cursor()``,
    ``features.rootdse_data``) that's decorated ``async_unsafe`` and
    refuses to run when there's a running event loop on the same thread.
    """
    from django.db import connections  # noqa: PLC0415

    features = connections['ldap'].features
    _ = features.supports_sssvlv
    _ = features.supports_simple_paged_results
    # Touch the ORM once to force any other lazy state to populate.
    LDAPUser.objects.get(username='user1')


def main() -> int:
    _prewarm_features()
    return asyncio.run(main_async())


if __name__ == '__main__':
    sys.exit(main())
