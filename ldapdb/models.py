import ldap
from django.db import models as django_models

from .fields import DistinguishedNameField


class LDAPModel(django_models.Model):
    # TODO: Check for existing base_dn and object_classes fields and raise an error if they are not present
    base_dn = None
    scope = ldap.SCOPE_SUBTREE

    dn = DistinguishedNameField(db_column='dn', unique=True, editable=False, hidden=True)

    class Meta:
        abstract = True
        managed = False

    def __init_subclass__(cls, **kwargs):
        # We want to set managed to False for all LDAP models but don't want to force the user to do it themselves
        if not hasattr(cls, 'Meta'):
            cls.Meta = type('Meta', (), {'managed': False})

        if getattr(cls.Meta, 'managed', False):
            raise ValueError(f'{cls.__name__} has Meta.managed set to True. This is not allowed for LDAP models.')
        else:
            cls.Meta.managed = False
