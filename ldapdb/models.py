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
    object_classes: list[str] = ['top']  # TODO: object_classes should be a ListField of some sort

    objects = LDAPQuerySet.as_manager()

    dn = DistinguishedNameField(db_column='dn', unique=True, editable=False, hidden=True)

    class Meta:
        abstract = True
        managed = False
        base_manager_name = 'objects'  # force base manager to use LDAPQuery instances
        #  ordering = ('dn',)  - TODO: Allow ordering by dn, even if it's the same as the pk field?

    @classmethod
    def _check_required_attrs(cls):
        for required_attribute in ['base_dn', 'object_classes']:
            if not getattr(cls, required_attribute, None):
                raise ValueError(f'{cls.__name__} is missing the required attribute {required_attribute}')

    def __init_subclass__(cls, **kwargs):
        cls._check_required_attrs()

        # We want to set managed to False for all LDAP models but don't want to force the user to do it themselves
        if not hasattr(cls, 'Meta'):
            cls.Meta = type('Meta', (), {'managed': False})

        if getattr(cls.Meta, 'managed', False):
            raise ValueError(f'{cls.__name__} has Meta.managed set to True. This is not allowed for LDAP models.')
        else:
            cls.Meta.managed = False
