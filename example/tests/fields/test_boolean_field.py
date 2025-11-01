from django.db import connections, transaction
from ldapdb.models.fields import BooleanField

from example.tests.base import BaseLDAPTestUser, LDAPTestCase
from example.tests.generator import generate_random_username
from django.test import TransactionTestCase, TestCase

def _dump(label=""):
    c = connections["ldap"]
    print(f"[{label}] id={id(c)} autocommit={c.get_autocommit()} "
          f"in_atomic={c.in_atomic_block} needs_rb={c.needs_rollback} "
          f"dbg={getattr(c, '_dbg_calls', None)}")

class BooleanTestModel(BaseLDAPTestUser):
    is_active = BooleanField(db_column='x-user-isActive')


class BooleanFieldTests(TransactionTestCase):
    databases = ['ldap']

    def test_commit_path(self):
        _dump("start")
        with transaction.atomic(using="ldap"):
            _dump("inside-entry")
            obj = BooleanTestModel(is_active=True, username=generate_random_username())
            obj.save()
            _dump("inside-after-save")
        _dump("after-exit")  # ← commit SHOULD have run here

    def test_boolean_field_true(self):
        """Test that 'TRUE' from LDAP converts to True."""
        with transaction.atomic(using="ldap"):
            instance = BooleanTestModel(is_active=True, username=generate_random_username())
            instance.full_clean()
            instance.save()
            print(instance.username)
            print(instance.pk)
        instance.refresh_from_db()
        self.assertEqual(instance.is_active, True)
