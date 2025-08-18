from ldapdb.models.fields import BooleanField

from example.tests.base import BaseLDAPTestUser, LDAPTestCase
from example.tests.generator import generate_random_username


class BooleanTestModel(BaseLDAPTestUser):
    is_active = BooleanField(db_column='x-user-isActive')


class BooleanFieldTests(LDAPTestCase):
    def test_boolean_field_true(self):
        """Test that 'TRUE' from LDAP converts to True."""
        instance = BooleanTestModel(is_active=True, username=generate_random_username())
        instance.full_clean()
        instance.save()
        instance.refresh_from_db()
        self.assertEqual(instance.is_active, True)
