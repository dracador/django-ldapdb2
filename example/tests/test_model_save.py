from django.db import IntegrityError

from example.models import LDAPUser
from example.tests.base import LDAPTestCase
from example.tests.constants import TEST_LDAP_USER_1


class QueryResolverTestCase(LDAPTestCase):
    @staticmethod
    def _get_user_1_object():
        return LDAPUser.objects.get(username=TEST_LDAP_USER_1.username)

    def test_create_user_fail_on_object_schema_error(self):
        """
        The objectClass inetOrgPerson requires the sn attribute to be set.
        Check that the ldap.OBJECT_CLASS_VIOLATION is propagated up to an IntegrityError
        """
        with self.assertRaises(IntegrityError):
            _ = LDAPUser.objects.create(username='user98', name='User 98', mail='user98@example.com')

    def test_create_user(self):
        user = LDAPUser.objects.create(username='user99', name='User 99', mail='user99@example.com', sn='NinetyNine')
        self.assertIsNotNone(user, 'User should be created successfully.')
        user = LDAPUser.objects.get(username='user99')
        self.assertEqual(user.username, 'user99', "User's username should match the created value.")
