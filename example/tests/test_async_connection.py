"""
Tests for the async surface of :class:`ldapdb.backends.ldap.connection.LDAPClient`.

These tests bind directly to the test OpenLDAP server (started via
tests/openldap-server/docker-compose.yaml) using python-ldap, wrap that
connection with :class:`LDAPClient`, and exercise the asyncio-native code path
without going through Django's ORM.

Note on test base class: these use ``django.test.SimpleTestCase`` plus
``async def`` test methods (Django runs each on its own loop). We deliberately
avoid ``unittest.IsolatedAsyncioTestCase`` because instances of that class
hold a ``contextvars.Context`` reference, which fails to pickle and breaks
Django's multiprocess parallel test runner.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import socket
import subprocess
import time
import unittest

import ldap
from django.test import SimpleTestCase
from ldap.controls import SimplePagedResultsControl
from ldap.ldapobject import ReconnectLDAPObject
from ldapdb.backends.ldap.connection import LDAPClient

URI = 'ldap://localhost'
BIND_DN = 'uid=admin,ou=Users,dc=example,dc=org'
BIND_PW = 'adminpassword'

USERS_BASE = 'ou=Users,dc=example,dc=org'
GROUPS_BASE = 'ou=Groups,dc=example,dc=org'
ROOT_BASE = 'dc=example,dc=org'


def _new_conn(*, tls: bool = False) -> ReconnectLDAPObject:
    conn = ReconnectLDAPObject(uri=URI, retry_max=3, retry_delay=0.5, bytes_mode=False)
    # Order matters: REQUIRE_CERT first, NEWCTX=0 last to apply.
    conn.set_option(ldap.OPT_X_TLS_REQUIRE_CERT, ldap.OPT_X_TLS_NEVER)
    conn.set_option(ldap.OPT_X_TLS_NEWCTX, 0)
    conn.simple_bind_s(BIND_DN, BIND_PW)
    if tls:
        conn.start_tls_s()
        # RFC 4513: bind state is reset by StartTLS; re-bind.
        conn.simple_bind_s(BIND_DN, BIND_PW)
    return conn


@contextlib.asynccontextmanager
async def _async_conn(*, tls: bool = False):
    """Context-manager that yields a ready async :class:`LDAPClient`.

    Used in place of asyncSetUp/asyncTearDown so that test classes don't
    inherit from :class:`unittest.IsolatedAsyncioTestCase` (see module
    docstring for why).
    """
    sync = _new_conn(tls=tls)
    ac = LDAPClient(sync, loop=asyncio.get_event_loop())
    try:
        yield sync, ac
    finally:
        await ac.aclose()


class AsyncLDAPConnectionTests(SimpleTestCase):
    databases: set[str] = set()

    async def test_single_search_returns_expected_dns(self) -> None:
        async with _async_conn() as (_sync, ac):
            rtype, rdata, _ctrls = await ac.asearch(
                USERS_BASE, ldap.SCOPE_ONELEVEL, '(objectClass=*)', ['dn']
            )
            self.assertEqual(rtype, ldap.RES_SEARCH_RESULT)
            dns = sorted(dn for dn, _ in rdata)
            self.assertIn('uid=admin,ou=Users,dc=example,dc=org', dns)
            self.assertGreaterEqual(len(dns), 1)

    async def test_concurrent_searches_do_not_swap_results(self) -> None:
        async with _async_conn() as (_sync, ac):
            (_, users, _), (_, groups, _) = await asyncio.gather(
                ac.asearch(USERS_BASE, ldap.SCOPE_ONELEVEL, '(objectClass=*)', ['dn']),
                ac.asearch(GROUPS_BASE, ldap.SCOPE_ONELEVEL, '(objectClass=*)', ['dn']),
            )
        user_dns = [dn for dn, _ in users]
        group_dns = [dn for dn, _ in groups]
        self.assertTrue(user_dns)
        self.assertTrue(group_dns)
        self.assertTrue(all(USERS_BASE in dn for dn in user_dns))
        self.assertTrue(all(GROUPS_BASE in dn for dn in group_dns))
        self.assertFalse(set(user_dns) & set(group_dns), 'results were swapped')

    async def test_gather_of_many_searches(self) -> None:
        async with _async_conn() as (_sync, ac):
            results = await asyncio.gather(
                *[
                    ac.asearch(USERS_BASE, ldap.SCOPE_SUBTREE, '(objectClass=*)', ['dn'])
                    for _ in range(10)
                ]
            )
        self.assertEqual(len(results), 10)
        for _rtype, rdata, _ctrls in results:
            self.assertTrue(rdata)

    async def test_cancellation_clears_waiter_and_calls_abandon(self) -> None:
        async with _async_conn() as (_sync, ac):
            task = asyncio.create_task(
                ac.asearch(USERS_BASE, ldap.SCOPE_SUBTREE, '(objectClass=*)', ['dn'])
            )
            await asyncio.sleep(0)
            self.assertEqual(len(ac._waiters), 1)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            self.assertEqual(ac._waiters, {})

    async def test_close_is_idempotent(self) -> None:
        async with _async_conn() as (_sync, ac):
            await ac.aclose()
            await ac.aclose()  # must not raise

    async def test_request_after_close_raises(self) -> None:
        async with _async_conn() as (_sync, ac):
            await ac.aclose()
            with self.assertRaises(ldap.LDAPError):
                await ac.asearch(USERS_BASE, ldap.SCOPE_ONELEVEL, '(objectClass=*)', ['dn'])

    async def test_reconnect_detection_fails_in_flight_waiters(self) -> None:
        async with _async_conn() as (sync, ac):
            await ac.asearch(USERS_BASE, ldap.SCOPE_BASE, '(objectClass=*)', ['dn'])
            # Inject a stuck waiter (simulating "in-flight").
            fake_fut: asyncio.Future = asyncio.get_event_loop().create_future()
            ac._waiters[999_999] = fake_fut
            # Simulate reconnect.
            sync._reconnects_done = sync._reconnects_done + 1
            # Next operation triggers detection.
            rtype, _rdata, _ctrls = await ac.asearch(
                USERS_BASE, ldap.SCOPE_BASE, '(objectClass=*)', ['dn']
            )
            self.assertEqual(rtype, ldap.RES_SEARCH_RESULT)
            self.assertTrue(fake_fut.done())
            self.assertIsInstance(fake_fut.exception(), ConnectionResetError)

    async def test_paged_search_via_async(self) -> None:
        async with _async_conn() as (sync, ac):
            cookie = b''
            all_rows: list[tuple[str, dict]] = []
            pages = 0
            while True:
                pages += 1
                ctrl = SimplePagedResultsControl(criticality=True, size=2, cookie=cookie)
                _rtype, rdata, ctrls = await ac.asearch(
                    ROOT_BASE, ldap.SCOPE_SUBTREE, '(objectClass=*)', None, serverctrls=[ctrl]
                )
                all_rows.extend(rdata)
                paged = next(
                    (c for c in ctrls if c.controlType == SimplePagedResultsControl.controlType),
                    None,
                )
                if not paged or not paged.cookie:
                    break
                cookie = paged.cookie
            self.assertGreater(pages, 1)
            sync_rows = sync.search_s(ROOT_BASE, ldap.SCOPE_SUBTREE, '(objectClass=*)', None)
        self.assertEqual(
            sorted(dn for dn, _ in all_rows),
            sorted(dn for dn, _ in sync_rows),
        )

    async def test_modify_returns_success_msg(self) -> None:
        async with _async_conn() as (_sync, ac):
            new_desc = b'async-test-' + os.urandom(4).hex().encode()
            rtype, _rdata, _ctrls = await ac.amodify(
                BIND_DN, [(ldap.MOD_REPLACE, 'description', [new_desc])]
            )
            self.assertEqual(rtype, ldap.RES_MODIFY)
            _rt, rdata, _c = await ac.asearch(
                BIND_DN, ldap.SCOPE_BASE, '(objectClass=*)', ['description']
            )
            self.assertEqual(rdata[0][1]['description'], [new_desc])
            await ac.amodify(BIND_DN, [(ldap.MOD_DELETE, 'description', None)])


class AsyncLDAPConnectionTLSTests(SimpleTestCase):
    """Same coverage exercised over StartTLS."""

    databases: set[str] = set()

    async def test_search_over_tls(self) -> None:
        try:
            cm = _async_conn(tls=True)
            sync, ac = await cm.__aenter__()
        except ldap.LDAPError as exc:
            raise unittest.SkipTest(f'StartTLS not available: {exc}') from exc
        try:
            rtype, rdata, _ = await ac.asearch(
                USERS_BASE, ldap.SCOPE_ONELEVEL, '(objectClass=*)', ['dn']
            )
            self.assertEqual(rtype, ldap.RES_SEARCH_RESULT)
            self.assertTrue(rdata)
        finally:
            await cm.__aexit__(None, None, None)

    async def test_concurrent_searches_over_tls(self) -> None:
        try:
            cm = _async_conn(tls=True)
            sync, ac = await cm.__aenter__()
        except ldap.LDAPError as exc:
            raise unittest.SkipTest(f'StartTLS not available: {exc}') from exc
        try:
            results = await asyncio.gather(
                *[
                    ac.asearch(USERS_BASE, ldap.SCOPE_SUBTREE, '(objectClass=*)', ['dn'])
                    for _ in range(5)
                ]
            )
        finally:
            await cm.__aexit__(None, None, None)
        self.assertEqual(len(results), 5)
        for _rtype, rdata, _ in results:
            self.assertTrue(rdata)


@unittest.skipUnless(
    os.environ.get('RUN_RECONNECT_TEST') == '1',
    'set RUN_RECONNECT_TEST=1 to run the docker-restart-based end-to-end reconnect test',
)
class AsyncLDAPConnectionReconnectE2ETests(SimpleTestCase):
    """End-to-end reconnect test that restarts the docker container.

    Disabled by default because it (a) is slow (~5s per run) and (b) requires
    docker. The reconnect-detection logic itself is covered by
    :meth:`AsyncLDAPConnectionTests.test_reconnect_detection_fails_in_flight_waiters`.
    """

    databases: set[str] = set()
    DOCKER_CONTAINER = 'django-ldapdb2-openldap'

    @staticmethod
    async def _wait_for_port(port: int, timeout: float = 30) -> None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            ok = False
            with contextlib.suppress(OSError), socket.create_connection(('localhost', port), timeout=1):
                ok = True
            if ok:
                return
            await asyncio.sleep(0.2)
        raise TimeoutError(f'port {port} did not come back up within {timeout}s')

    async def test_reconnect_then_resume(self) -> None:
        async with _async_conn() as (sync, ac):
            await ac.asearch(USERS_BASE, ldap.SCOPE_BASE, '(objectClass=*)', ['dn'])
            subprocess.run(
                ['docker', 'restart', '-t', '0', self.DOCKER_CONTAINER],
                check=True,
                capture_output=True,
            )
            await self._wait_for_port(389)
            with contextlib.suppress(ldap.LDAPError):
                sync.simple_bind_s(BIND_DN, BIND_PW)
            rtype, rdata, _ = await ac.asearch(
                USERS_BASE, ldap.SCOPE_BASE, '(objectClass=*)', ['dn']
            )
            self.assertEqual(rtype, ldap.RES_SEARCH_RESULT)
            self.assertTrue(rdata)
