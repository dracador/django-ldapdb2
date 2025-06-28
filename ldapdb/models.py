from typing import TYPE_CHECKING

import ldap
from django.db import models as django_models
from django.db.models import QuerySet
from django.db.models.sql import Query
from django.db.models.sql.constants import CURSOR
from django.db.models.sql.subqueries import InsertQuery, UpdateQuery

from .exceptions import LDAPModelTypeError
from .fields import DistinguishedNameField

if TYPE_CHECKING:
    from .backends.ldap import LDAPSearch


class LDAPQuery(Query):
    model: 'LDAPModel'

    def __init__(self, model, **kwargs):
        super().__init__(model, **kwargs)

        if not issubclass(model, LDAPModel):
            raise LDAPModelTypeError(model)

        self.ldap_search: LDAPSearch | None = None


class LDAPInsertQuery(InsertQuery, LDAPQuery):
    pass


class LDAPQuerySet(QuerySet):
    def __init__(self, model=None, query=None, using=None, hints=None):
        if query is None:
            query = LDAPQuery(model)
        super().__init__(model=model, query=query, using=using, hints=hints)

    def raw(self, *_args, **_kwargs):
        # Maybe allow raw to take an LDIF input or an LDAPSearch instance?
        raise AssertionError('Raw queries not supported with LDAP backend')

    def _insert(
        self,
        objs,
        fields,
        returning_fields=None,
        raw=False,
        using=None,
        on_conflict=None,
        update_fields=None,
        unique_fields=None,
    ):
        """
        Insert a new record for the given model. This provides an interface to
        the InsertQuery class and is how Model.save() is implemented.
        """
        self._for_write = True
        print('Inserting', objs, fields, returning_fields, raw, using, on_conflict, update_fields, unique_fields)
        if using is None:
            using = self.db
        query = LDAPInsertQuery(
            self.model,
            on_conflict=on_conflict,
            update_fields=update_fields,
            unique_fields=unique_fields,
        )
        query.insert_values(fields, objs, raw=raw)
        return query.get_compiler(using=using).execute_sql(returning_fields)

    def _update(self, values):
        """
        A version of update() that accepts field objects instead of field names.
        Used primarily for model saving and not intended for use by general
        code (it requires too much poking around at model internals to be
        useful at that level).
        """
        print('Updating', values)
        if self.query.is_sliced:
            raise TypeError("Cannot update a query once a slice has been taken.")
        query = self.query.chain(UpdateQuery)
        query.add_update_fields(values)
        # Clear any annotations so that they won't be present in subqueries.
        query.annotations = {}
        self._result_cache = None
        return query.get_compiler(self.db).execute_sql(CURSOR)


class LDAPModel(django_models.Model):
    base_dn: str = None
    base_filter: str = '(objectClass=*)'  # the base filter will be always be applied to all queries
    search_scope: int = ldap.SCOPE_SUBTREE
    object_classes: list[str] = None  # TODO: object_classes should be a ListField of some sort

    objects = LDAPQuerySet.as_manager()

    dn = DistinguishedNameField(db_column='dn', unique=True, editable=False, hidden=True)

    class Meta:
        abstract = True

        # Force base manager to use LDAPQuery instances.
        # Will also trickle down to subclasses without them having it explicitly set in model._meta.
        base_manager_name = 'objects'

    def get_dn(self):
        if self.dn:
            return self.dn
        return f'{self._meta.pk.column}={self.pk},{self.base_dn}'

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
    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)

        cls._check_non_abstract_inheritance()
        cls._check_required_attrs()
