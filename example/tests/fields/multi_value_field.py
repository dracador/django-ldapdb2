from unittest.mock import MagicMock

from django.test import TestCase
from ldapdb.models.fields import CharField, IntegerField

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


class IntegerFieldMultiValueUnitTests(TestCase):
    """Unit tests for IntegerField.from_db_value() with multi_valued_field=True."""

    def setUp(self):
        self.connection = MagicMock()
        self.connection.charset = 'utf-8'

    def test_from_db_value_multi_valued_returns_list_of_ints(self):
        """from_db_value() must return a list of ints, not crash with TypeError."""
        field = IntegerField(db_column='uidNumber', multi_valued_field=True, null=True)
        result = field.from_db_value([b'1', b'2', b'3'], None, self.connection)
        self.assertEqual(result, [1, 2, 3])

    def test_from_db_value_single_value_returns_int(self):
        field = IntegerField(db_column='uidNumber', null=True)
        result = field.from_db_value([b'42'], None, self.connection)
        self.assertEqual(result, 42)

    def test_from_db_value_none_returns_none(self):
        field = IntegerField(db_column='uidNumber', null=True)
        result = field.from_db_value(None, None, self.connection)
        self.assertIsNone(result)
