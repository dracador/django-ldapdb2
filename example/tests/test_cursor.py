from django.forms.models import model_to_dict

from example.models import LDAPUser
from .base import LDAPTestCase, transform_ldap_model_dict
from .constants import TEST_LDAP_AVAILABLE_USERS, TEST_LDAP_USER_1


class TestDatabaseCursor(LDAPTestCase):
    def test_ldapuser_all_result_count(self):
        """On a broken Cursor implementation, we might get a wrong result count when iterating"""
        expected_count = len(TEST_LDAP_AVAILABLE_USERS)
        queryset = LDAPUser.objects.all()
        self.assertEqual(len(list(queryset)), expected_count)

    def test_model_field_order(self):
        """This test is supposed to be run a lot of times to ensure the order of fields is correct"""
        model_instance_from_const = model_to_dict(TEST_LDAP_USER_1)

        for _ in range(1000):
            model_instance_from_db = model_to_dict(LDAPUser.objects.get(username=TEST_LDAP_USER_1.username))
            model_instance_from_db = transform_ldap_model_dict(model_instance_from_db)  # XXX: TEMPORARY!
            self.assertDictEqual(model_instance_from_const, model_instance_from_db)
