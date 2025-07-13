from django.db import NotSupportedError

from example.models import LDAPUser
from .base import LDAPTestCase
from .generator import create_random_ldap_user


class SQLDeleteCompilerTestCase(LDAPTestCase):
    user_to_delete: LDAPUser = None
    user_to_delete_2: LDAPUser = None
    user_to_keep: LDAPUser = None

    @classmethod
    def setUpTestData(cls):
        if not cls.user_to_delete:
            cls.user_to_delete = create_random_ldap_user()
            # cls.user_to_delete.save()
        if not cls.user_to_delete_2:
            cls.user_to_delete_2 = create_random_ldap_user()
        #    cls.user_to_delete_2.save()
        if not cls.user_to_keep:
            cls.user_to_keep = create_random_ldap_user()
        #    cls.user_to_keep.save()
        # TODO: cls.user_to_delete.save() and others completely breaks the *whole* test suite somehow

    def test_delete_single_instance(self):
        num, details = LDAPUser.objects.filter(username=self.user_to_delete.username).delete()
        self.assertEqual(num, 1)
        self.assertFalse(LDAPUser.objects.filter(username=self.user_to_delete.username).exists())
        self.assertTrue(LDAPUser.objects.filter(username=self.user_to_keep.username).exists())

    def test_delete_missing_returns_zero(self):
        num, _ = LDAPUser.objects.filter(username='does_not_exist').delete()
        self.assertEqual(num, 0)

    def test_bulk_delete_not_supported(self):
        with self.assertRaises(NotSupportedError):
            # TODO: Implement bulk delete support
            # Fow now we only support single-instance deletion
            LDAPUser.objects.all().delete()

    def test_instance_delete(self):
        # TODO: Fix test
        #  NotSupportedError('UPDATE/DELETE must be filtered by the primary key.')
        obj = LDAPUser.objects.get(username=self.user_to_delete_2.username)
        obj.delete()
        self.assertFalse(LDAPUser.objects.filter(username=self.user_to_delete_2.username).exists())
