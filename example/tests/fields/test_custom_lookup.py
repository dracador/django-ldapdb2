from example.fields import IsActiveWithCustomLookupField
from example.models import BaseLDAPUser
from example.tests.base import LDAPTestCase, get_new_ldap_search


class CustomLookupTestModel(BaseLDAPUser):
    base_filter = '(objectClass=inetOrgPerson)'
    is_active = None
    optional_is_active = IsActiveWithCustomLookupField(db_column='x-user-isActive')


class CustomActiveFieldLookupTestCase(LDAPTestCase):
    def test_active_field_with_custom_lookup_true(self):
        queryset = CustomLookupTestModel.objects.filter(optional_is_active=True)  # exact lookup
        expected_ldap_search = get_new_ldap_search(filterstr='(!(x-user-isActive=FALSE))')
        self.assertLDAPSearchIsEqual(queryset, expected_ldap_search)

    def test_active_field_with_custom_lookup_false(self):
        queryset = CustomLookupTestModel.objects.filter(optional_is_active=False)  # exact lookup
        expected_ldap_search = get_new_ldap_search(filterstr='(x-user-isActive=FALSE)')
        self.assertLDAPSearchIsEqual(queryset, expected_ldap_search)

    def test_active_field_with_custom_lookup_isnull(self):
        # should still work as a normal BooleanField
        queryset = CustomLookupTestModel.objects.filter(optional_is_active__isnull=True)
        expected_ldap_search = get_new_ldap_search(filterstr='(!(x-user-isActive=*))')
        self.assertLDAPSearchIsEqual(queryset, expected_ldap_search)
