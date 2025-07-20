from itertools import chain
from typing import TYPE_CHECKING

import ldap
from django.db.models import QuerySet
from django.test import TestCase
from ldapdb.backends.ldap import LDAPSearch, LDAPSearchControlType
from ldapdb.models import LDAPModel
from ldapdb.models.fields import CharField

from example.models import LDAPGroup, LDAPUser
from example.tests.constants import TEST_LDAP_AVAILABLE_USERS, TEST_LDAP_GROUP_1, TEST_LDAP_USER_1

if TYPE_CHECKING:
    from ldapdb.models import LDAPQuery


def full_model_to_dict(instance, fields: list = None, exclude: list = None) -> dict:
    """
    Since there are fields that are not editable, they won't show up in the
    django.forms.model_to_dict() method, since it's supposed to be used for forms.

    Original docstring:
    Return a dict containing the data in ``instance`` suitable for passing as
    a Form's ``initial`` keyword argument.

    ``fields`` is an optional list of field names. If provided, return only the named.

    ``exclude`` is an optional list of field names. If provided, exclude the
    named from the returned dict, even if they are listed in the ``fields``
    argument.
    """
    opts = instance._meta
    data = {}
    for f in chain(opts.concrete_fields, opts.private_fields, opts.many_to_many):
        if fields is not None and f.name not in fields:
            continue
        if exclude and f.name in exclude:
            continue
        data[f.name] = f.value_from_object(instance)
    return data


def queryset_to_ldap_search(queryset: QuerySet) -> LDAPSearch:
    sql_compiler = queryset.query.get_compiler(using=queryset.db)
    query: LDAPQuery = sql_compiler.as_sql()[0]
    return query.ldap_search


def get_new_ldap_search(
    base: str = 'ou=Users,dc=example,dc=org',
    filterstr: str | None = None,
    attrlist: list[str] | None = None,
    scope: int = None,
    ordering_rules: list[tuple[str, str]] | None = None,
    limit: int = 0,
    offset: int = 0,
    ignore_base_filter: bool = False,
):
    base_filter = LDAPUser.base_filter
    if base_filter and not ignore_base_filter:
        filterstr = f'(&{base_filter}{filterstr})' if filterstr else base_filter

    return LDAPSearch(
        attrlist=attrlist or [field.column for field in LDAPUser._meta.get_fields()],
        base=base,
        control_type=LDAPSearchControlType.SSSVLV,
        filterstr=filterstr or LDAPUser.base_filter,
        limit=limit,
        offset=offset,
        ordering_rules=ordering_rules or [('uid', 'caseIgnoreOrderingMatch')],  # Default to pk field for SSSVLV
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

    @staticmethod
    def _get_group_1_object():
        return LDAPGroup.objects.get(name=TEST_LDAP_GROUP_1.name)

    @staticmethod
    def _get_user_1_object():
        return LDAPUser.objects.get(username=TEST_LDAP_USER_1.username)

    @staticmethod
    def get_testuser_objects():
        return LDAPUser.objects.filter(username__in=[u.username for u in TEST_LDAP_AVAILABLE_USERS])

    def assertDiffDict(self, real, expected, msg=None):
        # Could also use self.assertDictEqual, but this provides a little more readable output
        mismatches = []
        for key in real.keys() | expected.keys():
            v1 = real.get(key, '<MISSING>')
            v2 = expected.get(key, '<MISSING>')
            if v1 != v2:
                mismatches.append(f"- Key '{key}': expected {v2!r}, got {v1!r}")
        if mismatches:
            standard_msg = '\n' + '\n'.join(mismatches)
            self.fail(self._formatMessage(msg, standard_msg))

    def assertLDAPSearchIsEqual(self, queryset: QuerySet, expected_ldap_search: LDAPSearch):
        generated_ldap_search = queryset_to_ldap_search(queryset)
        self.assertIsNotNone(generated_ldap_search)
        self.assertIsInstance(generated_ldap_search, LDAPSearch)

        # Using .serialize() here allows assertEqual to provide a more detailed error message
        self.assertEqual(expected_ldap_search.serialize(), generated_ldap_search.serialize())

    def assertLDAPModelObjectsAreEqual(
        self,
        left_model_instance: LDAPUser,  # Should be a constant from constants.py (or a dict with fields)
        right_model_instance: LDAPUser | dict,  # Should be a model instance from the database or a dict with fields
        fields: list[str] = None,
        exclude: list[str] = None,
    ):
        if isinstance(left_model_instance, dict):
            dict_from_a = left_model_instance
        else:
            dict_from_a = full_model_to_dict(left_model_instance, fields=fields, exclude=exclude)

        if isinstance(right_model_instance, dict):
            dict_from_b = right_model_instance
        else:
            dict_from_b = full_model_to_dict(right_model_instance, fields=fields, exclude=exclude)

        self.assertDiffDict(dict_from_b, dict_from_a)


class BaseLDAPTestUser(LDAPModel):
    """
    Subset of LDAPUser fields for testing purposes.
    Until we can order by dn, we need a pk field.
    """

    base_dn = 'ou=Users,dc=example,dc=org'
    object_classes = ['inetOrgPerson', 'organizationalPerson', 'x-extendedUser']

    username = CharField(db_column='uid', primary_key=True)
    last_name = CharField(db_column='sn', default='default_last_name')
    name = CharField(db_column='cn', default='default_name')

    class Meta:
        abstract = True
