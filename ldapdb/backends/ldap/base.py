from collections import deque
from functools import cached_property

import ldap
from django.db.backends.base.base import BaseDatabaseWrapper
from django.db.backends.base.validation import BaseDatabaseValidation
from django.db.backends.utils import CursorWrapper
from django.utils.asyncio import async_unsafe
from ldap.ldapobject import ReconnectLDAPObject

from .client import DatabaseClient
from .creation import DatabaseCreation
from .cursor import DatabaseCursor
from .features import DatabaseFeatures
from .introspection import DatabaseIntrospection
from .lib import LDAPDatabase
from .lookups import LDAP_OPERATORS
from .operations import DatabaseOperations


class DatabaseWrapper(BaseDatabaseWrapper):
    display_name = 'ldapdb'
    vendor = 'ldap'

    Database = LDAPDatabase

    client: DatabaseClient
    client_class = DatabaseClient
    creation: DatabaseCreation
    creation_class = DatabaseCreation
    features: DatabaseFeatures
    features_class = DatabaseFeatures
    ops: DatabaseOperations
    ops_class = DatabaseOperations
    introspection: DatabaseIntrospection
    introspection_class = DatabaseIntrospection
    validation: BaseDatabaseValidation
    validation_class = BaseDatabaseValidation

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.operators = {name: fmt for name, (fmt, _) in LDAP_OPERATORS.items()}

    def _commit(self):
        pass

    def _rollback(self):
        pass

    def _set_autocommit(self, autocommit):
        pass

    def set_autocommit(self, autocommit, force_begin_transaction_with_broken_autocommit=False):
        """
        Toggle autocommit without logging a phantom BEGIN.

        This backend has no wire-level transactions (_commit/_rollback/_set_autocommit are
        no-ops), so the "BEGIN" that the default set_autocommit() logs via
        debug_transaction() corresponds to zero LDAP round-trips. That marker is appended
        straight to connection.queries_log while never passing through the cursor so it corrupts
        query counting for stuff like assertNumQueries or django-debug-toolbar.
        COMMIT/ROLLBACK don't have this problem as Django logs those from inside _commit()/_rollback(),
        which we just no-op above.

        The phantom BEGIN only surfaces on Django < 5.1, where supports_transactions is False,
        so TestCase doesn't hold an outer atomic block and operations like QuerySet.delete()
        (which wrap their work in transaction.atomic()) flip autocommit themselves.

        We can route that one log entry to a throwaway buffer for the duration of the call instead of
        reimplementing the base method, so we don't drift if Django changes its internals.
        Real LDAP operations are logged via the Cursor/CursorWrapper.
        """
        saved_log = self.queries_log
        self.queries_log = deque(maxlen=0)
        try:
            super().set_autocommit(autocommit, force_begin_transaction_with_broken_autocommit)
        finally:
            self.queries_log = saved_log

    @cached_property
    def charset(self):
        return self.settings_dict.get('CHARSET', 'utf-8')

    def get_connection_params(self):
        """
        Compute appropriate parameters for establishing a new connection.
        Computed at system startup.
        """
        return {
            'uri': self.settings_dict['NAME'],
            'tls': self.settings_dict.get('TLS', False),
            'bind_dn': self.settings_dict['BIND_DN'],
            'bind_pw': self.settings_dict['BIND_PASSWORD'],
            'retry_max': self.settings_dict.get('RETRY_MAX', 1),
            'retry_delay': self.settings_dict.get('RETRY_DELAY', 60.0),
            'query_timeout': int(self.settings_dict.get('QUERY_TIMEOUT', -1)),
            'charset': self.settings_dict.get('CHARSET', 'utf-8'),
            'page_size': int(self.settings_dict.get('PAGE_SIZE', 1000)),
            'password_hashing_algorithm': self.settings_dict.get('PASSWORD_HASHING_ALGORITHM', 'SSHA'),
            'connection_options': {
                k if isinstance(k, int) else k.lower(): v
                for k, v in self.settings_dict.get('CONNECTION_OPTIONS', {}).items()
            },
        }

    def ensure_connection(self):
        super().ensure_connection()

        # Do a test bind, which will revive the connection if interrupted, or reconnect
        conn_params = self.get_connection_params()
        try:
            self.connection.simple_bind_s(
                conn_params['bind_dn'],
                conn_params['bind_pw'],
            )
        except ldap.SERVER_DOWN:
            self.connect()

    @async_unsafe
    def get_new_connection(self, conn_params=None) -> ReconnectLDAPObject:
        """Build a connection from its parameters."""
        if conn_params is None:
            conn_params = self.get_connection_params()

        connection = ldap.ldapobject.ReconnectLDAPObject(
            uri=conn_params['uri'],
            retry_max=conn_params['retry_max'],
            retry_delay=conn_params['retry_delay'],
            bytes_mode=False,
        )

        options = conn_params['connection_options']
        for opt, value in options.items():
            connection.set_option(opt, value)

        if conn_params['tls']:
            connection.start_tls_s()

        connection.simple_bind_s(
            conn_params['bind_dn'],
            conn_params['bind_pw'],
        )
        return connection

    @async_unsafe
    def create_cursor(self, *_args, **_kwargs):
        return CursorWrapper(DatabaseCursor(self.connection, self.settings_dict), self)

    @async_unsafe
    def close(self):
        self.validate_thread_sharing()

        if self.connection is not None:
            if hasattr(self.connection, '_l'):
                self.connection.unbind_s()
            self.connection = None
