from ldapdb.models.fields import CharField

from example.models import BaseLDAPUser
from example.tests.base import LDAPTestCase, get_new_ldap_search
from example.tests.generator import create_random_ldap_user


class LDAPUserWithMultiValueField(BaseLDAPUser):
    base_filter = '(objectClass=inetOrgPerson)'

    multi_value_field = CharField(db_column='x-user-multiValue', multi_valued_field=True)


class MultiValueFieldTestCase(LDAPTestCase):
    def setUp(self):
        self.instance = create_random_ldap_user(
            model_cls=LDAPUserWithMultiValueField, multi_value_field=['testvalue', 'testvalue2']
        )

    def test_ldapuser_filter_lookup_in_multi_value_field_single(self):
        queryset = LDAPUserWithMultiValueField.objects.filter(multi_value_field__in=['testvalue'])
        expected_ldap_search = get_new_ldap_search(
            model_cls=LDAPUserWithMultiValueField, filterstr='(|(x-user-multiValue=testvalue))'
        )
        self.assertLDAPSearchIsEqual(queryset, expected_ldap_search)

    def test_ldapuser_filter_lookup_in_multi_value_field_multi(self):
        queryset = LDAPUserWithMultiValueField.objects.filter(multi_value_field__in=['testvalue', 'testvalue2'])
        expected_ldap_search = get_new_ldap_search(
            model_cls=LDAPUserWithMultiValueField,
            filterstr='(|(x-user-multiValue=testvalue)(x-user-multiValue=testvalue2))',
        )
        self.assertLDAPSearchIsEqual(queryset, expected_ldap_search)
