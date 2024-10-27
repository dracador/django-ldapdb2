from itertools import chain
from typing import TYPE_CHECKING

import ldap
from django.db.models import QuerySet
from django.test import TestCase
from ldapdb.backends.ldap import LDAPSearch, LDAPSearchControlType

from example.models import LDAPUser

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

        # XXX: TEMPORARY! Remove this line when we're able to transform LDAP search results the correct way
        dict_from_b = transform_ldap_model_dict(dict_from_b)

        self.assertDictEqual(dict_from_a, dict_from_b)
