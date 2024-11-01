from typing import TYPE_CHECKING

import ldap
from django.db import models as django_models
from django.db.models import QuerySet
from django.db.models.sql import Query

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


class LDAPQuerySet(QuerySet):
    def __init__(self, model=None, query=None, using=None, hints=None):
        if query is None:
            query = LDAPQuery(model)
        super().__init__(model=model, query=query, using=using, hints=hints)

    def raw(self, *_args, **_kwargs):
        # Maybe allow raw to take an LDIF input or an LDAPSearch instance?
        raise AssertionError('Raw queries not supported with LDAP backend')


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
