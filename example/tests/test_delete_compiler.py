from django.db import NotSupportedError

from example.models import LDAPUser
from example.tests.base import LDAPTestCase


class LDAPDeleteCompilerTests(LDAPTestCase):
    def test_delete_single_instance(self):
        deletion_username = 'deletion_user'
        LDAPUser.objects.create(
            username=deletion_username,
            name='Deletion User',
            first_name='Deletion',
            last_name='User',
            mail='deletion_user@example.com',
        )
        keep_deletion_username = 'keep_deletion_user'
        LDAPUser.objects.create(
            username=keep_deletion_username,
            name='Keep Deletion User',
            first_name='Keep',
            last_name='User',
            mail='keep_deletion_user@example.com',
        )

        num, details = LDAPUser.objects.filter(username=deletion_username).delete()
        self.assertEqual(num, 1)
        self.assertFalse(LDAPUser.objects.filter(username=deletion_username).exists())
        self.assertTrue(LDAPUser.objects.filter(username=keep_deletion_username).exists())

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
        username = 'deletion_user_2'
        LDAPUser.objects.create(
            username=username,
            name='Deletion User 2',
            first_name='Deletion',
            last_name='User 2',
            mail='deletion_user2@example.com',
        )

        obj = LDAPUser.objects.get(username=username)
        obj.delete()
        self.assertFalse(LDAPUser.objects.filter(username=username).exists())
