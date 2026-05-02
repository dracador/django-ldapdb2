"""
Phase 0.3 spike: PoC paged search using the async dispatch harness.

Adapts ``DatabaseCursor._execute_with_simple_paging`` (cursor.py:177) to async
form and compares against the sync implementation. Uses page_size=2 against
the test server so that the seed data spans multiple pages.

Run from project root:
    .venv/bin/python tests/spikes/test_async_paging.py
"""

from __future__ import annotations

import asyncio
import sys

import ldap
from ldap.controls import SimplePagedResultsControl
from ldap.ldapobject import ReconnectLDAPObject

URI = 'ldap://localhost'
BIND_DN = 'uid=admin,ou=Users,dc=example,dc=org'
BIND_PW = 'adminpassword'

BASE = 'dc=example,dc=org'
PAGE_SIZE = 2  # forces multiple pages on the small seed dataset


def _new_conn(tls: bool = False) -> ReconnectLDAPObject:
    conn = ReconnectLDAPObject(uri=URI, retry_max=3, retry_delay=0.5, bytes_mode=False)
    conn.set_option(ldap.OPT_X_TLS_REQUIRE_CERT, ldap.OPT_X_TLS_NEVER)
    conn.set_option(ldap.OPT_X_TLS_NEWCTX, 0)
    conn.simple_bind_s(BIND_DN, BIND_PW)
    if tls:
        conn.start_tls_s()
        conn.simple_bind_s(BIND_DN, BIND_PW)
    return conn


class MiniAsyncLDAP:
    def __init__(self, conn: ReconnectLDAPObject) -> None:
        self.conn = conn
        self.waiters: dict[int, asyncio.Future] = {}
        loop = asyncio.get_event_loop()
        loop.add_reader(conn.fileno(), self._on_readable)

    def close(self) -> None:
        loop = asyncio.get_event_loop()
        loop.remove_reader(self.conn.fileno())

    def _on_readable(self) -> None:
        while True:
            try:
                rtype, rdata, rmsgid, ctrls = self.conn.result3(msgid=ldap.RES_ANY, timeout=0)
            except ldap.LDAPError as exc:
                for fut in list(self.waiters.values()):
                    if not fut.done():
                        fut.set_exception(exc)
                self.waiters.clear()
                return
            if rtype is None:
                return
            fut = self.waiters.pop(rmsgid, None)
            if fut and not fut.done():
                fut.set_result((rtype, rdata, ctrls))

    async def search_paged_step(
        self,
        base: str,
        scope: int,
        filterstr: str,
        attrlist: list[str] | None,
        serverctrls: list,
    ) -> tuple[int, list[tuple[str, dict]], list]:
        msgid = self.conn.search_ext(
            base, scope, filterstr, attrlist=attrlist, serverctrls=serverctrls
        )
        loop = asyncio.get_event_loop()
        fut: asyncio.Future = loop.create_future()
        self.waiters[msgid] = fut
        return await fut


def sync_paged_search(conn: ReconnectLDAPObject) -> list[tuple[str, dict]]:
    cookie = b''
    results: list[tuple[str, dict]] = []
    pages = 0
    while True:
        pages += 1
        ctrl = SimplePagedResultsControl(criticality=True, size=PAGE_SIZE, cookie=cookie)
        msgid = conn.search_ext(BASE, ldap.SCOPE_SUBTREE, '(objectClass=*)', None, serverctrls=[ctrl])
        _rtype, rdata, _rmsgid, serverctrls = conn.result3(msgid)
        results.extend(rdata)
        paged = next(
            (c for c in serverctrls if c.controlType == SimplePagedResultsControl.controlType),
            None,
        )
        if not paged or not paged.cookie:
            break
        cookie = paged.cookie
    print(f'  sync: {pages} pages, {len(results)} entries')
    return results


async def async_paged_search(wrapper: MiniAsyncLDAP) -> list[tuple[str, dict]]:
    cookie = b''
    results: list[tuple[str, dict]] = []
    pages = 0
    while True:
        pages += 1
        ctrl = SimplePagedResultsControl(criticality=True, size=PAGE_SIZE, cookie=cookie)
        _rtype, rdata, serverctrls = await wrapper.search_paged_step(
            BASE, ldap.SCOPE_SUBTREE, '(objectClass=*)', None, [ctrl]
        )
        results.extend(rdata)
        paged = next(
            (c for c in serverctrls if c.controlType == SimplePagedResultsControl.controlType),
            None,
        )
        if not paged or not paged.cookie:
            break
        cookie = paged.cookie
    print(f'  async: {pages} pages, {len(results)} entries')
    return results


def normalize(rows: list[tuple[str, dict]]) -> list[str]:
    return sorted(dn for dn, _ in rows)


async def run_one(label: str, tls: bool) -> int:
    print(f'--- {label} ---')
    print('Sync paged search:')
    sync_conn = _new_conn(tls=tls)
    sync_rows = sync_paged_search(sync_conn)
    sync_conn.unbind_s()
    print()

    print('Async paged search:')
    async_conn = _new_conn(tls=tls)
    wrapper = MiniAsyncLDAP(async_conn)
    try:
        async_rows = await async_paged_search(wrapper)
    finally:
        wrapper.close()
        async_conn.unbind_s()
    print()

    sync_norm = normalize(sync_rows)
    async_norm = normalize(async_rows)
    print(f'Sync DNs : {sync_norm}')
    print(f'Async DNs: {async_norm}')
    if sync_norm == async_norm:
        print('PASS: sync and async paged searches return identical DN sets')
        print()
        return 0
    print('FAIL: sync and async results differ')
    print(f'  only in sync : {set(sync_norm) - set(async_norm)}')
    print(f'  only in async: {set(async_norm) - set(sync_norm)}')
    print()
    return 1


async def main_async() -> int:
    print('=== Phase 0.3: paged search spike ===')
    print(f'(page_size = {PAGE_SIZE})')
    print()

    plain = await run_one('plaintext LDAP', tls=False)
    tls = await run_one('StartTLS LDAP', tls=True)

    if plain or tls:
        print('=== spike 0.3 FAILED ===')
        return 1
    print('=== spike 0.3 complete (plaintext + TLS both pass) ===')
    return 0


def main() -> int:
    return asyncio.run(main_async())


if __name__ == '__main__':
    sys.exit(main())
