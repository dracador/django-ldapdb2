from django.db import connections
from django.test import TestCase
from ldapdb.backends.ldap.cursor import _sort_and_slice_ldap_results
from ldapdb.backends.ldap.lib import LDAPSearchControlType

from .base import LDAPTestCase
from .constants import TEST_LDAP_AVAILABLE_USERS


def _compile_query_with_forced_control(queryset, control_type):
    """Compile a queryset and override the control type on the resulting ldap_search."""
    sql_compiler = queryset.query.get_compiler(using=queryset.db)
    query = sql_compiler.as_sql()[0]
    query.ldap_search.control_type = control_type
    return query


class TestSortAndSlice(TestCase):
    SAMPLE_RESULTS = [
        ('uid=charlie,ou=Users,dc=test,dc=org', {'uid': [b'charlie'], 'cn': [b'Charlie']}),
        ('uid=alice,ou=Users,dc=test,dc=org', {'uid': [b'alice'], 'cn': [b'Alice']}),
        ('uid=bob,ou=Users,dc=test,dc=org', {'uid': [b'bob'], 'cn': [b'Bob']}),
    ]

    def test_sorts_ascending_by_attribute(self):
        result = _sort_and_slice_ldap_results(
            self.SAMPLE_RESULTS,
            ordering_rules=[('uid', 'caseIgnoreOrderingMatch')],
            offset=0,
            limit=0,
        )
        usernames = [r[1]['uid'][0] for r in result]
        self.assertEqual(usernames, [b'alice', b'bob', b'charlie'])

    def test_sorts_descending_by_attribute(self):
        result = _sort_and_slice_ldap_results(
            self.SAMPLE_RESULTS,
            ordering_rules=[('-uid', 'caseIgnoreOrderingMatch')],
            offset=0,
            limit=0,
        )
        usernames = [r[1]['uid'][0] for r in result]
        self.assertEqual(usernames, [b'charlie', b'bob', b'alice'])

    def test_applies_limit(self):
        result = _sort_and_slice_ldap_results(
            self.SAMPLE_RESULTS,
            ordering_rules=[('uid', 'caseIgnoreOrderingMatch')],
            offset=0,
            limit=2,
        )
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0][1]['uid'][0], b'alice')
        self.assertEqual(result[1][1]['uid'][0], b'bob')

    def test_applies_offset(self):
        result = _sort_and_slice_ldap_results(
            self.SAMPLE_RESULTS,
            ordering_rules=[('uid', 'caseIgnoreOrderingMatch')],
            offset=1,
            limit=0,
        )
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0][1]['uid'][0], b'bob')

    def test_applies_offset_and_limit_together(self):
        result = _sort_and_slice_ldap_results(
            self.SAMPLE_RESULTS,
            ordering_rules=[('uid', 'caseIgnoreOrderingMatch')],
            offset=1,
            limit=1,
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0][1]['uid'][0], b'bob')

    def test_no_ordering_no_limit_returns_all_results_unchanged(self):
        result = _sort_and_slice_ldap_results(
            self.SAMPLE_RESULTS,
            ordering_rules=[],
            offset=0,
            limit=0,
        )
        self.assertEqual(result, self.SAMPLE_RESULTS)

    def test_sorts_by_dn(self):
        result = _sort_and_slice_ldap_results(
            self.SAMPLE_RESULTS,
            ordering_rules=[('dn', 'distinguishedNameMatch')],
            offset=0,
            limit=0,
        )
        dns = [r[0] for r in result]
        self.assertEqual(dns, sorted(r[0] for r in self.SAMPLE_RESULTS))

    def test_multiple_ordering_rules_tiebreak(self):
        results = [
            ('uid=b,dc=test', {'uid': [b'b'], 'cn': [b'Z']}),
            ('uid=a,dc=test', {'uid': [b'a'], 'cn': [b'Z']}),
            ('uid=a,dc=test', {'uid': [b'a'], 'cn': [b'A']}),
        ]
        result = _sort_and_slice_ldap_results(
            results,
            ordering_rules=[('uid', 'caseIgnoreOrderingMatch'), ('cn', 'caseIgnoreOrderingMatch')],
            offset=0,
            limit=0,
        )
        self.assertEqual(result[0][1]['cn'][0], b'A')
        self.assertEqual(result[1][1]['cn'][0], b'Z')
        self.assertEqual(result[2][1]['uid'][0], b'b')

    def test_missing_attribute_sorts_before_present(self):
        results = [
            ('uid=b,dc=test', {'uid': [b'b']}),
            ('uid=a,dc=test', {}),
        ]
        result = _sort_and_slice_ldap_results(
            results,
            ordering_rules=[('uid', 'caseIgnoreOrderingMatch')],
            offset=0,
            limit=0,
        )
        # Missing attribute (empty bytes) sorts before 'b'
        self.assertEqual(result[0][1], {})
        self.assertEqual(result[1][1]['uid'][0], b'b')


class TestSimplePagedResults(LDAPTestCase):
    def test_returns_all_results_with_default_page_size(self):
        query = _compile_query_with_forced_control(
            self.get_testuser_objects(),
            LDAPSearchControlType.SIMPLE_PAGED_RESULTS,
        )
        conn = connections['ldap']
        with conn.cursor() as cursor:
            cursor.execute(query)
            results = cursor.fetchall()
        self.assertEqual(len(results), len(TEST_LDAP_AVAILABLE_USERS))

    def test_collects_all_results_across_multiple_pages(self):
        query = _compile_query_with_forced_control(
            self.get_testuser_objects(),
            LDAPSearchControlType.SIMPLE_PAGED_RESULTS,
        )
        conn = connections['ldap']
        original_page_size = conn.settings_dict.get('PAGE_SIZE', 1000)
        conn.settings_dict['PAGE_SIZE'] = 1  # one result per page
        try:
            with conn.cursor() as cursor:
                cursor.execute(query)
                results = cursor.fetchall()
        finally:
            conn.settings_dict['PAGE_SIZE'] = original_page_size
        self.assertEqual(len(results), len(TEST_LDAP_AVAILABLE_USERS))


class TestNoControlOrdering(LDAPTestCase):
    def test_results_sorted_ascending(self):
        queryset = self.get_testuser_objects().order_by('username')
        query = _compile_query_with_forced_control(queryset, LDAPSearchControlType.NO_CONTROL)

        conn = connections['ldap']
        with conn.cursor() as cursor:
            cursor.execute(query)
            results = cursor.fetchall()

        uid_index = query.ldap_search.attrlist.index('uid')
        usernames = [row[uid_index][0] for row in results]
        self.assertEqual(usernames, sorted(usernames))

    def test_results_sorted_descending(self):
        queryset = self.get_testuser_objects().order_by('-username')
        query = _compile_query_with_forced_control(queryset, LDAPSearchControlType.NO_CONTROL)

        conn = connections['ldap']
        with conn.cursor() as cursor:
            cursor.execute(query)
            results = cursor.fetchall()

        uid_index = query.ldap_search.attrlist.index('uid')
        usernames = [row[uid_index][0] for row in results]
        self.assertEqual(usernames, sorted(usernames, reverse=True))

    def test_slicing_returns_correct_first_element(self):
        queryset = self.get_testuser_objects().order_by('username')
        query = _compile_query_with_forced_control(queryset, LDAPSearchControlType.NO_CONTROL)
        query.ldap_search.limit = 1
        query.ldap_search.offset = 0

        conn = connections['ldap']
        with conn.cursor() as cursor:
            cursor.execute(query)
            results = cursor.fetchall()

        self.assertEqual(len(results), 1)
        uid_index = query.ldap_search.attrlist.index('uid')
        expected_username = sorted(u.username for u in TEST_LDAP_AVAILABLE_USERS)[0]
        self.assertEqual(results[0][uid_index][0].decode(), expected_username)

    def test_slicing_with_offset(self):
        queryset = self.get_testuser_objects().order_by('username')
        query = _compile_query_with_forced_control(queryset, LDAPSearchControlType.NO_CONTROL)
        query.ldap_search.limit = 1
        query.ldap_search.offset = 1

        conn = connections['ldap']
        with conn.cursor() as cursor:
            cursor.execute(query)
            results = cursor.fetchall()

        self.assertEqual(len(results), 1)
        uid_index = query.ldap_search.attrlist.index('uid')
        expected_username = sorted(u.username for u in TEST_LDAP_AVAILABLE_USERS)[1]
        self.assertEqual(results[0][uid_index][0].decode(), expected_username)


class TestQuerySetOrdering(LDAPTestCase):
    """End-to-end tests using the normal QuerySet API — control type chosen by server capabilities."""

    def test_order_by_ascending_returns_sorted_results(self):
        users = list(self.get_testuser_objects().order_by('username'))
        usernames = [u.username for u in users]
        self.assertEqual(usernames, sorted(usernames))

    def test_order_by_descending_returns_sorted_results(self):
        users = list(self.get_testuser_objects().order_by('-username'))
        usernames = [u.username for u in users]
        self.assertEqual(usernames, sorted(usernames, reverse=True))

    def test_slicing_returns_correct_first_element(self):
        all_users = list(self.get_testuser_objects().order_by('username'))
        first = list(self.get_testuser_objects().order_by('username')[0:1])
        self.assertEqual(len(first), 1)
        self.assertEqual(first[0].username, all_users[0].username)

    def test_slicing_with_offset(self):
        all_users = list(self.get_testuser_objects().order_by('username'))
        second = list(self.get_testuser_objects().order_by('username')[1:2])
        self.assertEqual(len(second), 1)
        self.assertEqual(second[0].username, all_users[1].username)
