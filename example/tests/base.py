import ldap
from django.db.models import QuerySet
from django.test import TestCase
from ldapdb.backends.ldap import LDAPSearch, LDAPSearchControlType

from example.models import LDAPUser


def queryset_to_ldap_search(queryset: QuerySet):
    sql_compiler = queryset.query.get_compiler(using=queryset.db)
    return sql_compiler.as_sql()[0]


def get_new_ldap_search(
    base=None,
    filterstr=None,
    attrlist=None,
    scope=None,
    ordering_rules=None,
    limit=0,
    offset=0,
    ignore_base_filter=False,
):
    base_filter = LDAPUser.base_filter
    if base_filter and not ignore_base_filter:
        filterstr = f'(&{base_filter}{filterstr})' if filterstr else base_filter

    return LDAPSearch(
        attrlist=attrlist or [field.column for field in LDAPUser._meta.get_fields()],
        base=base or 'ou=Users,dc=example,dc=org',
        control_type=LDAPSearchControlType.SSSVLV,
        filterstr=filterstr or LDAPUser.base_filter,
        limit=limit,
        offset=offset,
        ordering_rules=ordering_rules,
        scope=scope or ldap.SCOPE_SUBTREE,
    )


def transform_ldap_model_dict(instance_data: dict):
    # Funny temporary little helper method to transform LDAP search results from a list to single values until
    # we're able to transform them the correct way. Only works with single-value attributes for now.
    formatted_attrs = {}
    for key, value in instance_data.items():
        value = value[0] if len(value) == 1 else value
        if isinstance(value, bytes):
            value = value.decode('utf-8')
        formatted_attrs[key] = value
    return formatted_attrs


class LDAPTestCase(TestCase):
    databases = ['ldap']

    def assertLDAPSearchIsEqual(self, queryset: QuerySet, expected_ldap_search: LDAPSearch):
        generated_ldap_search = queryset_to_ldap_search(queryset)
        self.assertIsNotNone(generated_ldap_search)
        self.assertIsInstance(generated_ldap_search, LDAPSearch)

        # Using .serialize() here allows assertEqual to provide a more detailed error message
        self.assertEqual(expected_ldap_search.serialize(), generated_ldap_search.serialize())
