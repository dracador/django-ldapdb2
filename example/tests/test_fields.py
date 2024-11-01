from ldapdb.fields import BooleanField

from .base import BaseLDAPTestUser, LDAPTestCase


class BooleanTestModel(BaseLDAPTestUser):
    ldap_boolean = BooleanField()


class BooleanFieldTests(LDAPTestCase):
    def test_boolean_field_true(self):
        """Test that 'TRUE' from LDAP converts to True."""
        instance = BooleanTestModel(username='username', ldap_boolean=True)
        instance.full_clean()
        self.assertTrue(instance.ldap_boolean)
