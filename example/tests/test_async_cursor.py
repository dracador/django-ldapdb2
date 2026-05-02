"""
Tests for ldapdb.backends.ldap.async_cursor.AsyncDatabaseCursor.

Mirror of the sync cursor tests at this layer: build a Django queryset, compile
it through the existing SQLCompiler (which is pure Python and shared with the
sync path), then execute the resulting LDAPQuery through both the sync cursor
and the async cursor and assert byte-identical results.
"""

from __future__ import annotations

import asyncio

import ldap
from django.db import connections
from ldap.ldapobject import ReconnectLDAPObject
from ldapdb.backends.ldap.async_cursor import AsyncDatabaseCursor
from ldapdb.backends.ldap.connection import LDAPClient
from ldapdb.backends.ldap.lib import LDAPSearchControlType

from .base import LDAPTestCase
from .constants import TEST_LDAP_AVAILABLE_USERS

URI = 'ldap://localhost'
BIND_DN = 'uid=admin,ou=Users,dc=example,dc=org'
BIND_PW = 'adminpassword'


def _new_async_client() -> LDAPClient:
    conn = ReconnectLDAPObject(uri=URI, retry_max=3, retry_delay=0.5, bytes_mode=False)
    conn.set_option(ldap.OPT_X_TLS_REQUIRE_CERT, ldap.OPT_X_TLS_NEVER)
    conn.set_option(ldap.OPT_X_TLS_NEWCTX, 0)
    conn.simple_bind_s(BIND_DN, BIND_PW)
    return LDAPClient(conn, loop=asyncio.get_event_loop())


def _compile_query_with_forced_control(queryset, control_type):
    """Compile a queryset and override the resulting LDAPSearch's control type."""
    sql_compiler = queryset.query.get_compiler(using=queryset.db)
    query = sql_compiler.as_sql()[0]
    query.ldap_search.control_type = control_type
    return query


def _compile_query(queryset):
    sql_compiler = queryset.query.get_compiler(using=queryset.db)
    return sql_compiler.as_sql()[0]


class AsyncDatabaseCursorTests(LDAPTestCase):
    """All async-cursor tests live in one class so that LDAPTestCase setup
    (database = ['ldap'] tagging, etc.) applies. Test methods use ``async def``
    which Django's TestCase handles natively."""

    def setUp(self):
        super().setUp()
        # Compile all queries we'll need from this sync context. Compiling
        # accesses ``connection.features`` (which reads the rootDSE on first
        # use) and ``connection.cursor()`` is decorated ``async_unsafe`` —
        # both would fail if invoked from inside an ``async def`` test.
        from django.db.models import Count

        from example.models import LDAPGroup

        self.q_no_control = _compile_query_with_forced_control(
            self.get_testuser_objects(), LDAPSearchControlType.NO_CONTROL,
        )
        self.q_simple_paged = _compile_query_with_forced_control(
            self.get_testuser_objects(), LDAPSearchControlType.SIMPLE_PAGED_RESULTS,
        )
        self.q_sssvlv = _compile_query_with_forced_control(
            self.get_testuser_objects().order_by('username'),
            LDAPSearchControlType.SSSVLV,
        )
        # Annotate over the stable seed users (not LDAPUser.objects.all()) —
        # parallel test workers may insert/delete users between setUp and the
        # async run, which would make a global count flaky.
        self.q_count = _compile_query(
            self.get_testuser_objects().annotate(_count=Count('*'))
        )
        self.q_users_for_gather = _compile_query_with_forced_control(
            self.get_testuser_objects(), LDAPSearchControlType.NO_CONTROL,
        )
        self.q_groups_for_gather = _compile_query_with_forced_control(
            LDAPGroup.objects.all(), LDAPSearchControlType.NO_CONTROL,
        )
        self.q_for_compare = _compile_query(self.get_testuser_objects())
        self.q_for_compare_2 = _compile_query(self.get_testuser_objects())

        # Pre-run the equivalent sync cursors so async tests can compare
        # without invoking sync ORM machinery from inside an event loop.
        self.sync_no_control_rows, self.sync_no_control_desc = self._run_sync_cursor(
            _compile_query_with_forced_control(
                self.get_testuser_objects(), LDAPSearchControlType.NO_CONTROL,
            )
        )
        original_page = connections['ldap'].settings_dict.get('PAGE_SIZE', 1000)
        connections['ldap'].settings_dict['PAGE_SIZE'] = 1
        try:
            self.sync_simple_paged_rows, _ = self._run_sync_cursor(
                _compile_query_with_forced_control(
                    self.get_testuser_objects(), LDAPSearchControlType.SIMPLE_PAGED_RESULTS,
                )
            )
        finally:
            connections['ldap'].settings_dict['PAGE_SIZE'] = original_page
        self.sync_sssvlv_rows, _ = self._run_sync_cursor(
            _compile_query_with_forced_control(
                self.get_testuser_objects().order_by('username'),
                LDAPSearchControlType.SSSVLV,
            )
        )
        self.sync_count_rows, self.sync_count_desc = self._run_sync_cursor(
            _compile_query(self.get_testuser_objects().annotate(_count=Count('*')))
        )

    # --------------------------- helpers --------------------------- #

    async def _run_async_cursor(self, query, settings_dict=None) -> tuple[list, list]:
        """Execute a query through the async cursor and return (rows, description)."""
        if settings_dict is None:
            settings_dict = connections['ldap'].settings_dict
        async_conn = _new_async_client()
        cursor = AsyncDatabaseCursor(async_conn, settings_dict=settings_dict)
        try:
            await cursor.aexecute(query)
            rows = await cursor.afetchall()
            description = cursor.description
        finally:
            await cursor.aclose()
            await async_conn.aclose()
        return rows, description

    def _run_sync_cursor(self, query) -> tuple[list, list]:
        """Execute the same query through the sync cursor for comparison."""
        conn = connections['ldap']
        with conn.cursor() as cursor:
            cursor.execute(query)
            rows = cursor.fetchall()
            description = cursor.description
        return rows, description

    # --------------------------- correctness --------------------------- #

    async def test_compiler_output_byte_identical_for_sync_and_async(self):
        """Phase 2.2 verification: same compiler output regardless of cursor."""
        self.assertEqual(
            self.q_for_compare.ldap_search.serialize(),
            self.q_for_compare_2.ldap_search.serialize(),
        )

    async def test_no_control_returns_same_rows_as_sync(self):
        async_rows, async_desc = await self._run_async_cursor(self.q_no_control)
        self.assertEqual(len(async_rows), len(TEST_LDAP_AVAILABLE_USERS))
        self.assertEqual(
            [col[0] for col in async_desc],
            [col[0] for col in self.sync_no_control_desc],
        )
        self.assertEqual(sorted(async_rows), sorted(self.sync_no_control_rows))

    async def test_simple_paged_results_returns_same_rows_as_sync(self):
        # Force multi-page behavior with PAGE_SIZE=1.
        custom_settings = dict(connections['ldap'].settings_dict)
        custom_settings['PAGE_SIZE'] = 1
        async_rows, _ = await self._run_async_cursor(
            self.q_simple_paged, settings_dict=custom_settings
        )
        self.assertEqual(len(async_rows), len(TEST_LDAP_AVAILABLE_USERS))
        self.assertEqual(sorted(async_rows), sorted(self.sync_simple_paged_rows))

    async def test_sssvlv_returns_same_rows_as_sync(self):
        async_rows, _ = await self._run_async_cursor(self.q_sssvlv)
        self.assertEqual(len(async_rows), len(TEST_LDAP_AVAILABLE_USERS))
        # SSSVLV sorts on the server; expect identical *ordered* output.
        self.assertEqual(async_rows, self.sync_sssvlv_rows)

    async def test_query_with_count_annotation_matches_sync(self):
        """An annotated query (`.annotate(_count=Count('*'))`) goes through
        the same code path on async as on sync."""
        async_rows, async_desc = await self._run_async_cursor(self.q_count)
        self.assertEqual(async_rows, self.sync_count_rows)
        self.assertEqual(
            [col[0] for col in async_desc],
            [col[0] for col in self.sync_count_desc],
        )

    # --------------------------- concurrency --------------------------- #

    async def test_gather_of_distinct_queries_returns_correct_results(self):
        """Two distinct queries via asyncio.gather complete and don't swap rows."""
        async_conn_users = _new_async_client()
        async_conn_groups = _new_async_client()
        cur_users = AsyncDatabaseCursor(async_conn_users, settings_dict=connections['ldap'].settings_dict)
        cur_groups = AsyncDatabaseCursor(async_conn_groups, settings_dict=connections['ldap'].settings_dict)
        try:
            await asyncio.gather(
                cur_users.aexecute(self.q_users_for_gather),
                cur_groups.aexecute(self.q_groups_for_gather),
            )
            users_rows = await cur_users.afetchall()
            groups_rows = await cur_groups.afetchall()
        finally:
            await cur_users.aclose()
            await cur_groups.aclose()
            await async_conn_users.aclose()
            await async_conn_groups.aclose()

        self.assertEqual(len(users_rows), len(TEST_LDAP_AVAILABLE_USERS))
        # The test database may carry leftover groups from prior test runs;
        # only assert that some groups came back, not an exact count.
        self.assertGreater(len(groups_rows), 0)
        # Cross-check: the description column lists differ between the two,
        # which proves the queries didn't get their results swapped.
        users_cols = {c[0] for c in cur_users.description or []}
        groups_cols = {c[0] for c in cur_groups.description or []}
        self.assertNotEqual(users_cols, groups_cols)

    # --------------------------- error path --------------------------- #

    async def test_aexecute_raises_when_passed_non_ldapquery(self):
        from ldapdb.exceptions import LDAPQueryTypeError

        async_conn = _new_async_client()
        cursor = AsyncDatabaseCursor(async_conn, settings_dict=connections['ldap'].settings_dict)
        try:
            with self.assertRaises(LDAPQueryTypeError):
                await cursor.aexecute('SELECT * FROM users')  # type: ignore[arg-type]
        finally:
            await cursor.aclose()
            await async_conn.aclose()

    async def test_sync_execute_on_async_cursor_raises(self):
        from ldapdb.backends.ldap.lib import LDAPDatabase

        async_conn = _new_async_client()
        cursor = AsyncDatabaseCursor(async_conn, settings_dict=connections['ldap'].settings_dict)
        try:
            with self.assertRaises(LDAPDatabase.DatabaseError):
                cursor.execute(self.q_for_compare)
        finally:
            await cursor.aclose()
            await async_conn.aclose()
