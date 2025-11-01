import logging
from functools import cached_property

import ldap
from django.db import OperationalError
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
from .transaction import end_ldap_txn, start_ldap_txn


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

    connection: ReconnectLDAPObject | None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.operators = {name: fmt for name, (fmt, _) in LDAP_OPERATORS.items()}

        # txn state
        self._in_txn: bool = False
        self._needs_rollback: bool = False
        self._txn_id: bytes | None = None
        self._dbg_calls = {'set_ac': [], 'commit': 0, 'rollback': 0}

    def _start_ldap_txn(self):
        try:
            self._txn_id = start_ldap_txn(self.connection)
            self._in_txn = True
        except ldap.LDAPError as exc:
            raise OperationalError(f'Failed to start LDAP transaction: {exc}') from exc

    def _end_ldap_txn(self, txn_id: bytes, commit: bool):
        try:
            end_ldap_txn(self.connection, txn_id, commit)
        except ldap.LDAPError as exc:
            raise OperationalError(f'Failed to {"commit" if commit else "abort"} LDAP transaction: {exc}') from exc
        finally:
            self._txn_tid = None
            self._in_txn = False

    def get_autocommit(self):
        self.ensure_connection()
        # print("get_autocommit: ", self.autocommit, not self._in_txn,)
        return not self._in_txn

    def _set_autocommit(self, autocommit: bool):
        self._dbg_calls['set_ac'].append(autocommit)
        # self.autocommit = autocommit
        if not autocommit and self.features.supports_transactions and not self._in_txn:
            self._start_ldap_txn()

    def _commit(self):
        self._dbg_calls['commit'] += 1
        print('COMMIT CALLED')
        logging.getLogger('ldapdb').debug(
            'DatabaseWrapper._commit: Committing transaction',
        )
        if self._in_txn:
            self._end_ldap_txn(self._txn_id, commit=True)
            self._in_txn = False

    def _rollback(self):
        self._dbg_calls['rollback'] += 1
        if self._in_txn:
            self._end_ldap_txn(self._txn_id, commit=False)
            self._in_txn = False

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
    def create_cursor(self, *_args, **_kwargs) -> CursorWrapper:
        return CursorWrapper(DatabaseCursor(self.connection, db_wrapper=self), self)

    @async_unsafe
    def _close(self):
        self.validate_thread_sharing()

        if self.connection is not None:
            if hasattr(self.connection, '_l'):
                self.connection.unbind_s()
            self.connection = None
