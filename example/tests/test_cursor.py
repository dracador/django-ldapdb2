from .base import LDAPTestCase
from .constants import TEST_LDAP_AVAILABLE_USERS


class TestDatabaseCursor(LDAPTestCase):
    def test_ldapuser_all_result_count(self):
        """On a broken Cursor implementation, we might get a wrong result count when iterating"""
        expected_count = len(TEST_LDAP_AVAILABLE_USERS)
        queryset = self.get_testuser_objects()
        self.assertEqual(len(list(queryset)), expected_count)
