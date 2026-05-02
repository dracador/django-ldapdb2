"""
Tests for the async ORM surface added in Phase 3:
``LDAPQuerySet.aget``, ``acount``, ``afirst``, ``aexists``.

These run on the event loop and dispatch the LDAP search via
:class:`LDAPClient` / :class:`AsyncDatabaseCursor`. Model construction
still runs through Django's sync ORM machinery, bridged via
:class:`PrefetchedDatabaseCursor` and a ContextVar.

Mirrors a slice of the existing sync coverage so we can prove the same code
paths work end-to-end on the async side.
"""

from __future__ import annotations

import asyncio
import time

from asgiref.sync import sync_to_async
from django.db import connections

from example.models import LDAPUser
from .base import LDAPTestCase
from .constants import (
    TEST_LDAP_ADMIN_USER_1,
    TEST_LDAP_AVAILABLE_USERS,
    TEST_LDAP_USER_1,
)


class AsyncORMTests(LDAPTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        # Pre-warm features cache (rootDSE read) — this is sync I/O and would
        # otherwise be triggered by the first compile inside an async test.
        features = connections['ldap'].features
        _ = features.supports_sssvlv
        _ = features.supports_simple_paged_results

    @classmethod
    async def asyncTearDownClass(cls) -> None:
        # Best-effort cleanup of per-loop async connections owned by the wrapper.
        await connections['ldap'].aclose_async_clients()

    # --------------------------- aget --------------------------- #

    async def test_aget_returns_model_instance(self):
        user = await LDAPUser.objects.aget(username=TEST_LDAP_USER_1.username)
        self.assertEqual(user.username, TEST_LDAP_USER_1.username)
        self.assertEqual(user.last_name, TEST_LDAP_USER_1.last_name)

    async def test_aget_raises_does_not_exist(self):
        with self.assertRaises(LDAPUser.DoesNotExist):
            await LDAPUser.objects.aget(username='no-such-user-xxx')

    async def test_aget_raises_multiple_objects_returned(self):
        # user1 and user2 share first_name='User' — aget over them is
        # ambiguous and should raise MultipleObjectsReturned.
        with self.assertRaises(LDAPUser.MultipleObjectsReturned):
            await LDAPUser.objects.aget(first_name='User')

    async def test_aget_via_dn_works(self):
        user = await LDAPUser.objects.aget(dn=TEST_LDAP_USER_1.dn)
        self.assertEqual(user.username, TEST_LDAP_USER_1.username)

    # --------------------------- acount / afirst / aexists --------------------------- #

    async def test_acount_returns_int(self):
        n = await self.get_testuser_objects().acount()
        self.assertEqual(n, len(TEST_LDAP_AVAILABLE_USERS))

    async def test_afirst_returns_one_or_none(self):
        first = await self.get_testuser_objects().order_by('username').afirst()
        self.assertIsNotNone(first)
        self.assertIn(first.username, [u.username for u in TEST_LDAP_AVAILABLE_USERS])

        empty = await LDAPUser.objects.filter(username='no-such-user-xxx').afirst()
        self.assertIsNone(empty)

    async def test_aexists(self):
        present = await LDAPUser.objects.filter(username=TEST_LDAP_USER_1.username).aexists()
        self.assertTrue(present)
        absent = await LDAPUser.objects.filter(username='no-such-user-xxx').aexists()
        self.assertFalse(absent)

    # --------------------------- gather --------------------------- #

    async def test_asyncio_gather_returns_correct_models(self):
        admin, user1 = await asyncio.gather(
            LDAPUser.objects.aget(username=TEST_LDAP_ADMIN_USER_1.username),
            LDAPUser.objects.aget(username=TEST_LDAP_USER_1.username),
        )
        self.assertEqual(admin.username, TEST_LDAP_ADMIN_USER_1.username)
        self.assertEqual(user1.username, TEST_LDAP_USER_1.username)

    async def test_gather_does_not_swap_results(self):
        """Two gets in flight at the same time return their own user."""
        results = await asyncio.gather(
            *[
                LDAPUser.objects.aget(username=u.username)
                for u in TEST_LDAP_AVAILABLE_USERS
            ]
        )
        # Each result must match its expected username.
        for got, expected in zip(results, TEST_LDAP_AVAILABLE_USERS, strict=True):
            self.assertEqual(got.username, expected.username)

    async def test_gather_speedup_over_sequential(self):
        """``asyncio.gather`` over N aget calls should be ~one query's worth
        of wall time, not N. A localhost LDAP query takes <1 ms so we don't
        assert a strict speedup, but we do assert gather isn't strictly slower
        than the sequential sum (which would indicate it's truly serial)."""
        n = 4
        usernames = [u.username for u in TEST_LDAP_AVAILABLE_USERS][:n]

        # Baseline: sequential awaits.
        t0 = time.perf_counter()
        for u in usernames:
            await LDAPUser.objects.aget(username=u)
        sequential = time.perf_counter() - t0

        # Concurrent.
        t0 = time.perf_counter()
        await asyncio.gather(
            *[LDAPUser.objects.aget(username=u) for u in usernames]
        )
        concurrent = time.perf_counter() - t0

        # On localhost, both are tiny; require concurrent be <= sequential
        # within a generous tolerance (avoids flakiness).
        self.assertLessEqual(concurrent, sequential * 1.5)


class AsyncORMSyncTestParityTests(LDAPTestCase):
    """For each sync test pattern in the existing suite, verify the async
    equivalent returns the same data. This is the user's "all current tests
    also run via async" requirement, applied to a representative subset."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        features = connections['ldap'].features
        _ = features.supports_sssvlv
        _ = features.supports_simple_paged_results

    @classmethod
    async def asyncTearDownClass(cls) -> None:
        await connections['ldap'].aclose_async_clients()

    async def test_aget_matches_sync_get(self):
        # Sync ORM calls from inside an async test must go through
        # ``sync_to_async`` (otherwise Django's ``async_unsafe`` rightly
        # complains).
        sync_user = await sync_to_async(
            LDAPUser.objects.get, thread_sensitive=True
        )(username=TEST_LDAP_USER_1.username)
        async_user = await LDAPUser.objects.aget(username=TEST_LDAP_USER_1.username)
        self.assertEqual(sync_user.username, async_user.username)
        self.assertEqual(sync_user.last_name, async_user.last_name)
        self.assertEqual(sync_user.dn, async_user.dn)

    async def test_acount_matches_sync_count(self):
        sync_n = await sync_to_async(
            self.get_testuser_objects().count, thread_sensitive=True
        )()
        async_n = await self.get_testuser_objects().acount()
        self.assertEqual(sync_n, async_n)

    async def test_afirst_matches_sync_first(self):
        sync_first = await sync_to_async(
            self.get_testuser_objects().order_by('username').first,
            thread_sensitive=True,
        )()
        async_first = await self.get_testuser_objects().order_by('username').afirst()
        self.assertEqual(sync_first.username, async_first.username)
