from django.db import IntegrityError

from example.models import LDAPUser
from example.tests.base import LDAPTestCase
from example.tests.constants import TEST_LDAP_USER_1, THUMBNAIL_PHOTO_BYTES
from example.tests.generator import create_random_ldap_user


class SQLInsertCompilerTestCase(LDAPTestCase):
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
        created_user = create_random_ldap_user(is_active=True, thumbnail_photo=THUMBNAIL_PHOTO_BYTES)
        self.assertIsNotNone(created_user, 'User should be created successfully.')
        user = LDAPUser.objects.get(username=created_user.username)
        self.assertEqual(user.username, created_user.username, "User's username should match the created value.")

    def test_update_user_non_primary_field(self):
        new_mail = 'aftervaluechange@example.com'
        user = create_random_ldap_user(mail='beforevaluechange@example.com')
        user.mail = new_mail
        user.save()
        user.refresh_from_db()
        self.assertEqual(user.mail, new_mail)
