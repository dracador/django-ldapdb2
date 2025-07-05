from django.db import IntegrityError

from example.models import LDAPUser
from example.tests.base import LDAPTestCase
from example.tests.constants import TEST_LDAP_USER_1, THUMBNAIL_PHOTO_BYTES


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
        user = LDAPUser.objects.create(
            department_number=99,
            description='Test user 99',
            is_active=True,
            last_name='NinetyNine',
            mail='user99@example.com',
            name='User 99',
            username='user99',
            thumbnail_photo=THUMBNAIL_PHOTO_BYTES,
        )
        self.assertIsNotNone(user, 'User should be created successfully.')
        user = LDAPUser.objects.get(username='user99')
        self.assertEqual(user.username, 'user99', "User's username should match the created value.")

    def test_update_user_non_primary_field(self):
        new_mail = 'useronehundred@example.com'
        user = LDAPUser.objects.create(
            is_active=False,
            last_name='One Hundred',
            mail='user100@example.com',
            name='User One Hundred',
            username='user100',
        )
        user.mail = new_mail
        user.save()
        user.refresh_from_db()
        self.assertEqual(user.mail, new_mail)
