import asyncio
import contextlib
from functools import cached_property
from typing import TYPE_CHECKING

import ldap
from asgiref.sync import sync_to_async
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

if TYPE_CHECKING:
    from .connection import LDAPClient


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
        # Sync LDAPClient wrapping ``self.connection``. Lazily built; rebuilt
        # if ``self.connection`` is replaced (Django's ``connect()`` /
        # ``close()`` lifecycle).
        self._ldap_client: LDAPClient | None = None
        # Per-event-loop async LDAPClient cache. Each event loop that runs
        # async ORM calls gets its own dedicated client wrapping its own
        # python-ldap connection. ``add_reader`` registrations are loop-local,
        # so clients cannot be shared across loops.
        self._async_clients: dict[asyncio.AbstractEventLoop, LDAPClient] = {}

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
        # Local import to keep the cursor module decoupled from base.
        from .cursor import get_prefetched_cursor

        prefetched = get_prefetched_cursor()
        if prefetched is not None:
            # The async manager methods pre-fetched results via the async
            # client; hand those rows to the sync ORM so it can build models
            # with its existing machinery.
            return CursorWrapper(prefetched, self)
        return CursorWrapper(DatabaseCursor(self.ldap_client, self.settings_dict), self)

    @async_unsafe
    def close(self):
        self.validate_thread_sharing()

        if self.connection is not None:
            if hasattr(self.connection, '_l'):
                self.connection.unbind_s()
            self.connection = None
        # Drop the cached sync client; a fresh one is built next time
        # ``ensure_connection`` produces a new ReconnectLDAPObject.
        self._ldap_client = None

    # ------------------------------------------------------------------ #
    # LDAP I/O client (sync)                                             #
    # ------------------------------------------------------------------ #

    @property
    def ldap_client(self) -> 'LDAPClient':
        """Sync LDAP I/O client wrapping ``self.connection``.

        Lazy: built on first access after a connection exists; rebuilt if
        ``self.connection`` is replaced (e.g. after a ``close()`` /
        re-``connect()``). Used by :class:`DatabaseCursor` and the
        update/insert/delete compilers.
        """
        # Local import to avoid a circular dependency at module load time
        # (``connection`` imports nothing from this module, but base.py is
        # already mid-init when its decorators run on first import).
        from .connection import LDAPClient

        self.ensure_connection()
        if self._ldap_client is None or self._ldap_client.connection is not self.connection:
            self._ldap_client = LDAPClient(self.connection)
        return self._ldap_client

    # ------------------------------------------------------------------ #
    # LDAP I/O client (async)                                            #
    # ------------------------------------------------------------------ #

    async def aget_async_client(self) -> 'LDAPClient':
        """Return (creating if needed) an async :class:`LDAPClient` bound to
        the current event loop.

        ``add_reader`` registrations are loop-local, so each event loop needs
        its own client wrapping its own ``ReconnectLDAPObject``. Within one
        loop the client is reused across coroutines — multiple in-flight
        requests are multiplexed by msgid on a single LDAP socket.
        """
        from .connection import LDAPClient

        loop = asyncio.get_running_loop()
        existing = self._async_clients.get(loop)
        if existing is not None and not existing._closed:
            return existing

        # Build a fresh ``ReconnectLDAPObject`` off-loop (the bind is
        # blocking I/O). ``get_new_connection`` is ``@async_unsafe``-decorated,
        # so we go through ``sync_to_async``.
        conn_params = self.get_connection_params()
        sync_conn = await sync_to_async(self.get_new_connection)(conn_params)
        client = LDAPClient(sync_conn, loop=loop)
        self._async_clients[loop] = client
        return client

    async def aclose_async_clients(self) -> None:
        """Close all per-loop async clients owned by this wrapper.

        Intended for shutdown / teardown. Safe to call from any loop.
        """
        for client in list(self._async_clients.values()):
            with contextlib.suppress(Exception):
                await client.aclose()
        self._async_clients.clear()
