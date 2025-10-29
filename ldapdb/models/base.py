from typing import TYPE_CHECKING

import ldap
from django.db import DEFAULT_DB_ALIAS, NotSupportedError, connections, models as django_models
from django.db.models import QuerySet
from django.db.models.sql import Query

from ldapdb.exceptions import LDAPModelTypeError
from ldapdb.iterables import (
    LDAPFlatValuesListIterable,
    LDAPModelIterable,
    LDAPNamedValuesListIterable,
    LDAPValuesIterable,
    LDAPValuesListIterable,
)
from .fields import DistinguishedNameField

if TYPE_CHECKING:
    from ldapdb.backends.ldap import LDAPSearch


class LDAPQuery(Query):
    model: 'LDAPModel'

    def __init__(self, model, **kwargs):
        super().__init__(model, **kwargs)

        if not issubclass(model, LDAPModel):
            raise LDAPModelTypeError(model)

        self.annotation_aliases: list = []
        self.ldap_search: LDAPSearch | None = None

    def __str__(self) -> str:
        """
        Normal __str__ method calls self.sql_with_params(),
        which is not compatible with LDAP.
        """
        return f'{self.__class__}.ldap_search: {self.ldap_search.serialize()}'


class LDAPQuerySet(QuerySet):
    query: LDAPQuery

    def __init__(self, model=None, query=None, using=None, hints=None):
        if query is None:
            query = LDAPQuery(model)
        super().__init__(model=model, query=query, using=using, hints=hints)
        self._iterable_class = LDAPModelIterable

    def update(self, **kwargs):
        pk_name = self.model._meta.pk.attname
        if pk_name in kwargs:
            raise NotSupportedError(
                'Updating the primary key requires an LDAP rename. '
                'Assign the field on the instance and call .save() to rename entries, instead.'
            )
        return super().update(**kwargs)

    def values(self, *fields, **expressions):
        qs = super().values(*fields, **expressions)
        qs._iterable_class = LDAPValuesIterable
        return qs

    def values_list(self, *fields, **kwargs):
        flat = kwargs.get('flat', False)
        named = kwargs.get('named', False)

        qs = super().values_list(*fields, **kwargs)

        if named:
            qs._iterable_class = LDAPNamedValuesListIterable
        elif flat:
            qs._iterable_class = LDAPFlatValuesListIterable
        else:
            qs._iterable_class = LDAPValuesListIterable
        return qs

    def raw(self, *_args, **_kwargs):
        # Maybe allow raw to take an LDIF input or an LDAPSearch instance?
        raise AssertionError('Raw queries not supported with LDAP backend')


class LDAPModel(django_models.Model):
    base_dn: str = None
    base_filter: str = '(objectClass=*)'  # the base filter will be always be applied to all queries
    search_scope: int = ldap.SCOPE_SUBTREE
    object_classes: list[str] = None  # TODO: object_classes should be a ListField of some sort

    objects = LDAPQuerySet.as_manager()

    dn = DistinguishedNameField(db_column='dn', unique=True, read_only=True, hidden=True)

    class Meta:
        abstract = True

        # Force base manager to use LDAPQuery instances.
        # Will also trickle down to subclasses without them having it explicitly set in model._meta.
        base_manager_name = 'objects'

    @classmethod
    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)

        cls._check_non_abstract_inheritance()
        cls._check_required_attrs()

    def save(self, *args, **kwargs):
        """
        If the PK (RDN) changed, perform an LDAP rename first,
        then proceed with Django's normal save/update.
        """
        using = kwargs.get('using') or self._state.db or DEFAULT_DB_ALIAS

        if not self._state.adding and getattr(self, 'dn', None):
            old_dn = self.dn
            new_dn = self._desired_dn()
            if new_dn != old_dn:
                new_rdn = new_dn.split(',', 1)[0]
                conn = connections[using]
                with conn.wrap_database_errors, conn.cursor() as cursor:
                    ldap_conn = cursor.db.connection
                    ldap_conn.rename_s(old_dn, new_rdn)
                self.dn = new_dn

        return super().save(*args, **kwargs)

    @classmethod
    def _check_required_attrs(cls):
        if not cls._meta.abstract:
            for required_attribute in ['base_dn', 'object_classes', 'search_scope']:
                if getattr(cls, required_attribute, None) is None:
                    raise ValueError(f'{cls.__name__} is missing the required attribute {required_attribute}')

    @classmethod
    def _check_non_abstract_inheritance(cls):
        """
        This function is to make sure no non-abstract Django model is subclassed.
        The default Django behavior is to create a new table for each subclass and reference the parent model
        via an automatically generated OneToOneField.
        Since we don't have tables in LDAP, we don't want to allow this behavior.
        Users will have to opt to using abstract models instead.
        """
        for base in cls.__bases__:
            if issubclass(base, django_models.Model) and not base._meta.abstract and base != django_models.Model:
                raise TypeError(
                    f'Cannot subclass non-abstract model "{base.__name__}" in "{cls.__name__}". '
                    'Only abstract models can be subclassed in this LDAP backend.'
                )

    @classmethod
    def build_rdn(cls, rdn_value):
        pk_field = cls._meta.pk
        return f'{pk_field.column}={rdn_value}'

    @classmethod
    def build_dn(cls, rdn_value):
        return f'{cls.build_rdn(rdn_value)},{cls.base_dn}'

    def _desired_dn(self):
        pk_field = self._meta.pk
        rdn_val = getattr(self, pk_field.attname)
        return self.build_dn(rdn_val)
