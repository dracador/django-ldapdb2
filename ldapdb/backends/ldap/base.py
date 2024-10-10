from functools import cached_property

import ldap
from django.db.backends.base.base import BaseDatabaseWrapper
from django.db.backends.base.validation import BaseDatabaseValidation
from django.db.backends.utils import CursorWrapper
from django.utils.asyncio import async_unsafe

from .client import DatabaseClient
from .creation import DatabaseCreation
from .cursor import DatabaseCursor
from .features import DatabaseFeatures
from .introspection import DatabaseIntrospection
from .operations import DatabaseOperations


class LdapDatabase:
    # Base class for all exceptions as defined in PEP-249
    Error = ldap.LDAPError

    class DatabaseError(Error):
        """Database-side errors."""

    class OperationalError(
        DatabaseError,
        ldap.ADMINLIMIT_EXCEEDED,
        ldap.AUTH_METHOD_NOT_SUPPORTED,
        ldap.AUTH_UNKNOWN,
        ldap.BUSY,
        ldap.CONFIDENTIALITY_REQUIRED,
        ldap.CONNECT_ERROR,
        ldap.INAPPROPRIATE_AUTH,
        ldap.INVALID_CREDENTIALS,
        ldap.OPERATIONS_ERROR,
        ldap.RESULTS_TOO_LARGE,
        ldap.SASL_BIND_IN_PROGRESS,
        ldap.SERVER_DOWN,
        ldap.SIZELIMIT_EXCEEDED,
        ldap.STRONG_AUTH_NOT_SUPPORTED,
        ldap.STRONG_AUTH_REQUIRED,
        ldap.TIMELIMIT_EXCEEDED,
        ldap.TIMEOUT,
        ldap.UNAVAILABLE,
        ldap.UNAVAILABLE_CRITICAL_EXTENSION,
        ldap.UNWILLING_TO_PERFORM,
    ):
        """Exceptions related to the database operations, out of the programmer control."""

    class IntegrityError(
        DatabaseError,
        ldap.AFFECTS_MULTIPLE_DSAS,
        ldap.ALREADY_EXISTS,
        ldap.CONSTRAINT_VIOLATION,
        ldap.TYPE_OR_VALUE_EXISTS,
    ):
        """Exceptions related to database Integrity."""

    class DataError(
        DatabaseError,
        ldap.INVALID_DN_SYNTAX,
        ldap.INVALID_SYNTAX,
        ldap.NOT_ALLOWED_ON_NONLEAF,
        ldap.NOT_ALLOWED_ON_RDN,
        ldap.OBJECT_CLASS_VIOLATION,
        ldap.UNDEFINED_TYPE,
    ):
        """Exceptions related to invalid data"""

    class InterfaceError(
        ldap.CLIENT_LOOP,
        ldap.DECODING_ERROR,
        ldap.ENCODING_ERROR,
        ldap.LOCAL_ERROR,
        ldap.LOOP_DETECT,
        ldap.NO_MEMORY,
        ldap.PROTOCOL_ERROR,
        ldap.REFERRAL_LIMIT_EXCEEDED,
        ldap.USER_CANCELLED,
        Error,
    ):
        """Exceptions related to the pyldap interface."""

    class InternalError(
        DatabaseError,
        ldap.ALIAS_DEREF_PROBLEM,
        ldap.ALIAS_PROBLEM,
    ):
        """Exceptions encountered within the database."""

    class ProgrammingError(
        DatabaseError,
        ldap.CONTROL_NOT_FOUND,
        ldap.FILTER_ERROR,
        ldap.INAPPROPRIATE_MATCHING,
        ldap.NAMING_VIOLATION,
        ldap.NO_SUCH_ATTRIBUTE,
        ldap.NO_SUCH_OBJECT,
        ldap.PARAM_ERROR,
    ):
        """Invalid data send by the programmer."""

    class NotSupportedError(
        DatabaseError,
        ldap.NOT_SUPPORTED,
    ):
        """Exception for unsupported actions."""


class DatabaseWrapper(BaseDatabaseWrapper):
    display_name = 'ldapdb'
    vendor = 'ldap'

    Database = LdapDatabase

    client_class = DatabaseClient
    creation_class = DatabaseCreation
    features_class = DatabaseFeatures
    ops_class = DatabaseOperations
    introspection_class = DatabaseIntrospection
    validation_class = BaseDatabaseValidation

    operators = {
        'exact': '=%s',
        'contains': '=*%s*',
        'in': '=*%s*',  # has to be overridden in ListFields to use =%s
        'gt': '>%s',
        'gte': '>=%s',
        'lt': '<%s',
        'lte': '<=%s',
        'startswith': '=%s*',
        'endswith': '=*%s',
        # Most LDAP servers use case-insensitive lookups, anyway, so these are the same as their non-i counterparts
        'iexact': '=%s',
        'icontains': '=*%s*',
        'istartswith': '=%s*',
        'iendswith': '=*%s',
        # isnull is handled by the Lookup, since it's based on the filter value
    }

    def _commit(self):
        pass

    def _rollback(self):
        pass

    def _set_autocommit(self, autocommit):
        pass

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
    def get_new_connection(self, conn_params=None):
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
        return CursorWrapper(DatabaseCursor(self.connection), self)

    @async_unsafe
    def close(self):
        self.validate_thread_sharing()

        if self.connection is not None:
            if hasattr(self.connection, '_l'):
                self.connection.unbind_s()
            self.connection = None
