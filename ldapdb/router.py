from functools import cached_property

from .exceptions import MultipleLDAPDatasesError
from .models import LDAPModel


class Router:
    @cached_property
    def ldap_databases(self):
        from django.conf import settings

        return [db for db, db_settings in settings.DATABASES.items() if db_settings['ENGINE'] == 'ldapdb.backends.ldap']

    @property
    def default_database(self):
        if len(self.ldap_databases) > 1:
            raise MultipleLDAPDatasesError()
        return self.ldap_databases[0]

    def get_db_from_model(self, model):
        return getattr(model._meta, 'ldap_database', self.default_database)

    def db_for_read(self, model, **_hints):
        if issubclass(model, LDAPModel):
            return self.get_db_from_model(model)
        return None

    def db_for_write(self, *args, **kwargs):
        return self.db_for_read(*args, **kwargs)

    def allow_migrate(self, db, *_args, model=None, **_hints):
        if db in self.ldap_databases:
            return False

        # avoid any migration operation on ldap models - *should* never happen, but let's be safe
        if issubclass(model, LDAPModel):
            return False
        return None
