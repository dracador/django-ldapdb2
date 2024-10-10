from django.db import models as django_models

from .fields import DistinguishedNameField


class LDAPModel(django_models.Model):
    dn = DistinguishedNameField('entryDN', unique=True, editable=False)

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
