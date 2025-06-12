import ldap
from django.db import models as django_models
from django.db.models import QuerySet
from django.db.models.sql import Query

from .fields import PrimaryDistinguishedNameField


class LDAPQuery(Query):
    def __init__(self, model, **kwargs):
        super().__init__(model, **kwargs)


class LDAPQuerySet(QuerySet):
    def __init__(self, model=None, query=None, using=None, hints=None):
        if query is None:
            query = LDAPQuery(model)
        super().__init__(model=model, query=query, using=using, hints=hints)


class LDAPModel(django_models.Model):
    base_dn: str = None
    base_filter: str = '(objectClass=*)'
    search_scope: int = ldap.SCOPE_SUBTREE
    object_classes: list[str] = ['top']

    # objects = LDAPQuerySet.as_manager()

    dn = PrimaryDistinguishedNameField(db_column='dn', unique=True, editable=False, hidden=True)

    class Meta:
        abstract = True
        managed = False
        ordering = ('dn',)

    def __init_subclass__(cls, **kwargs):
        cls._check_required_attrs()

        # We want to set managed to False for all LDAP models but don't want to force the user to do it themselves
        if not hasattr(cls, 'Meta'):
            cls.Meta = type('Meta', (), {'managed': False})

        if getattr(cls.Meta, 'managed', False):
            raise ValueError(f'{cls.__name__} has Meta.managed set to True. This is not allowed for LDAP models.')
        else:
            cls.Meta.managed = False

    @classmethod
    def _check_required_attrs(cls):
        for required_attribute in ['base_dn', 'object_classes']:
            if not getattr(cls, required_attribute, None):
                raise ValueError(f'{cls.__name__} is missing the required attribute {required_attribute}')
