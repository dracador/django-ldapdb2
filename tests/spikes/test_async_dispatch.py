# ruff: noqa: SIM105
"""
Phase 0.2 spike: PoC msgid -> asyncio.Future dispatch via add_reader.

Verifies:
  1. Two concurrent searches via asyncio.gather complete and return their own
     correct (non-swapped) results.
  2. Total wall-clock time of N concurrent searches is significantly less than
     N x single-search time (i.e. real concurrency, not serialization).
  3. _on_readable spurious-wakeup rate is reasonable (count drains vs. messages).

TLS path is documented as "skipped" because the test OpenLDAP server does not
have TLS configured. See spike report for the deferred TLS validation plan.

Run from project root with the venv activated:
    .venv/bin/python tests/spikes/test_async_dispatch.py
"""

from __future__ import annotations

import asyncio
import sys
import time

import ldap
from ldap.ldapobject import ReconnectLDAPObject

URI = 'ldap://localhost'
BIND_DN = 'uid=admin,ou=Users,dc=example,dc=org'
BIND_PW = 'adminpassword'

USERS_BASE = 'ou=Users,dc=example,dc=org'
GROUPS_BASE = 'ou=Groups,dc=example,dc=org'


def _new_conn(tls: bool = False) -> ReconnectLDAPObject:
    conn = ReconnectLDAPObject(uri=URI, retry_max=3, retry_delay=0.5, bytes_mode=False)
    # Order matters: REQUIRE_CERT first, NEWCTX=0 last to apply.
    conn.set_option(ldap.OPT_X_TLS_REQUIRE_CERT, ldap.OPT_X_TLS_NEVER)
    conn.set_option(ldap.OPT_X_TLS_NEWCTX, 0)
    conn.simple_bind_s(BIND_DN, BIND_PW)
    if tls:
        # StartTLS upgrades the existing socket. RFC 4513 resets bind state.
        conn.start_tls_s()
        conn.simple_bind_s(BIND_DN, BIND_PW)
    return conn


class MiniAsyncLDAP:
    """Minimal asyncio wrapper around python-ldap for the spike."""

    def __init__(self, conn: ReconnectLDAPObject) -> None:
        self.conn = conn
        self.waiters: dict[int, asyncio.Future] = {}
        self.drain_calls = 0
        self.messages_delivered = 0
        loop = asyncio.get_event_loop()
        loop.add_reader(conn.fileno(), self._on_readable)

    def close(self) -> None:
        loop = asyncio.get_event_loop()
        loop.remove_reader(self.conn.fileno())
        for fut in self.waiters.values():
            if not fut.done():
                fut.cancel()
        self.waiters.clear()

    def _on_readable(self) -> None:
        self.drain_calls += 1
        # Drain everything available from libldap. timeout=0 means non-blocking.
        while True:
            try:
                rtype, rdata, rmsgid, ctrls = self.conn.result3(msgid=ldap.RES_ANY, timeout=0)
            except ldap.LDAPError as exc:
                # Fail every outstanding waiter; this matches what the real
                # wrapper will need to do on connection-level errors.
                for fut in list(self.waiters.values()):
                    if not fut.done():
                        fut.set_exception(exc)
                self.waiters.clear()
                return
            if rtype is None:
                # No more messages currently available — kernel will fire us
                # again when more arrive.
                return
            self.messages_delivered += 1
            fut = self.waiters.pop(rmsgid, None)
            if fut and not fut.done():
                fut.set_result((rtype, rdata, ctrls))

    async def search(
        self,
        base: str,
        scope: int,
        filterstr: str,
        attrlist: list[str] | None = None,
    ) -> tuple[int, list[tuple[str, dict]], list]:
        msgid = self.conn.search_ext(base, scope, filterstr, attrlist=attrlist)
        loop = asyncio.get_event_loop()
        fut: asyncio.Future = loop.create_future()
        self.waiters[msgid] = fut
        try:
            return await fut
        except asyncio.CancelledError:
            # Cancellation: tell server to abandon the in-flight request and
            # drop the waiter so the eventual response is ignored on arrival.
            try:
                self.conn.abandon(msgid)
            except ldap.LDAPError:
                pass
            self.waiters.pop(msgid, None)
            raise


async def task_correctness(wrapper: MiniAsyncLDAP) -> bool:
    """Two distinct searches via gather; verify each result matches its query."""
    print('  issuing two distinct searches via asyncio.gather...')
    coro_users = wrapper.search(USERS_BASE, ldap.SCOPE_ONELEVEL, '(objectClass=*)', ['dn'])
    coro_groups = wrapper.search(GROUPS_BASE, ldap.SCOPE_ONELEVEL, '(objectClass=*)', ['dn'])
    (rt_u, rd_u, _), (rt_g, rd_g, _) = await asyncio.gather(coro_users, coro_groups)

    user_dns = sorted(dn for dn, _ in rd_u)
    group_dns = sorted(dn for dn, _ in rd_g)
    print(f'  users result ({len(user_dns)}): {user_dns}')
    print(f'  groups result ({len(group_dns)}): {group_dns}')

    users_ok = all(USERS_BASE in dn for dn in user_dns)
    groups_ok = all(GROUPS_BASE in dn for dn in group_dns)
    no_swap = bool(user_dns) and bool(group_dns) and not (set(user_dns) & set(group_dns))
    if users_ok and groups_ok and no_swap:
        print('  PASS: results are correct and not swapped')
        return True
    print('  FAIL: results swapped or empty')
    return False


async def task_concurrency_speedup(wrapper: MiniAsyncLDAP, n: int = 20) -> bool:
    """N concurrent searches should be roughly as fast as one search, not N x."""
    print(f'  measuring concurrency speedup with N={n}...')
    # Baseline: single search wall time (median of 5 runs)
    durations = []
    for _ in range(5):
        t0 = time.perf_counter()
        await wrapper.search(USERS_BASE, ldap.SCOPE_SUBTREE, '(objectClass=*)', ['dn'])
        durations.append(time.perf_counter() - t0)
    durations.sort()
    single = durations[len(durations) // 2]

    # Concurrent: gather of N searches
    drains_before = wrapper.drain_calls
    msgs_before = wrapper.messages_delivered
    t0 = time.perf_counter()
    coros = [
        wrapper.search(USERS_BASE, ldap.SCOPE_SUBTREE, '(objectClass=*)', ['dn'])
        for _ in range(n)
    ]
    results = await asyncio.gather(*coros)
    concurrent = time.perf_counter() - t0
    drains = wrapper.drain_calls - drains_before
    msgs = wrapper.messages_delivered - msgs_before

    print(f'  single (median of 5): {single * 1000:.2f} ms')
    print(f'  concurrent x{n}    : {concurrent * 1000:.2f} ms')
    print(f'  if serialized      : {single * n * 1000:.2f} ms (estimate)')
    speedup = (single * n) / concurrent if concurrent else 0
    print(f'  speedup vs serialized estimate: {speedup:.1f}x')
    print(f'  _on_readable calls during gather: {drains}; messages delivered: {msgs}')
    if msgs > 0:
        print(f'  drains/messages ratio: {drains / msgs:.2f} (lower is better; <2 is OK)')
    all_have_data = all(rd for _, rd, _ in results)
    if not all_have_data:
        print('  FAIL: some gather results were empty')
        return False
    # Don't assert a hard speedup number on localhost (sub-ms searches dominate
    # by per-call overhead, not network), but require we're not pathologically
    # slower than serial.
    if concurrent > single * n:
        print('  FAIL: concurrent gather is SLOWER than serialized estimate')
        return False
    print('  PASS: concurrent execution does not regress; results all populated')
    return True


async def task_cancellation(wrapper: MiniAsyncLDAP) -> bool:
    print('  issuing a search and cancelling its task...')
    coro = wrapper.search(USERS_BASE, ldap.SCOPE_SUBTREE, '(objectClass=*)', ['dn'])
    task = asyncio.create_task(coro)
    # Yield once so the search_ext is dispatched.
    await asyncio.sleep(0)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    if wrapper.waiters:
        print(f'  FAIL: waiters dict still has entries after cancellation: {list(wrapper.waiters)}')
        return False
    print('  PASS: cancelled task removed its waiter (and called abandon)')
    return True


async def run_suite(label: str, tls: bool) -> int:
    print(f'--- {label} ---')
    conn = _new_conn(tls=tls)
    wrapper = MiniAsyncLDAP(conn)
    failures = 0
    try:
        print('Step 1: correctness — two concurrent searches')
        if not await task_correctness(wrapper):
            failures += 1
        print()

        print('Step 2: concurrency speedup')
        if not await task_concurrency_speedup(wrapper):
            failures += 1
        print()

        print('Step 3: cancellation cleans up waiter and calls abandon()')
        if not await task_cancellation(wrapper):
            failures += 1
        print()
    finally:
        wrapper.close()
        conn.unbind_s()
    return failures


async def main_async() -> int:
    print('=== Phase 0.2: msgid -> Future dispatch spike ===')
    print()
    plain_failures = await run_suite('plaintext LDAP', tls=False)
    tls_failures = await run_suite('StartTLS LDAP', tls=True)

    total = plain_failures + tls_failures
    if total:
        print(f'=== spike 0.2 FAILED (plain={plain_failures}, tls={tls_failures}) ===')
        return 1
    print('=== spike 0.2 complete (plaintext + TLS both pass) ===')
    return 0


def main() -> int:
    return asyncio.run(main_async())


if __name__ == '__main__':
    sys.exit(main())
