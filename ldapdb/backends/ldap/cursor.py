import logging

import ldap

from ldapdb.backends.ldap.compiler import LDAPSearchObject

logger = logging.getLogger(__name__)


class DatabaseCursor:
    def __init__(self, connection):
        self.connection = connection
        self.description = None
        self.rowcount = -1
        self.arraysize = 1
        self.lastrowid = None

    def execute(self, query, params=None):
        logger.debug('DatabaseCursor.execute: query: %s, params: %s', query, params)
        if params is None:
            params = {}
        self.description = None
        self.rowcount = -1
        self.lastrowid = None

        if not isinstance(query, LDAPSearchObject):
            raise ValueError('Query object must be an instance of LDAPSearchObject')

        try:
            self.connection.search_s(query, ldap.SCOPE_SUBTREE, **params)
            self.rowcount = len(self.connection.result)
        except ldap.LDAPError as e:
            raise e

    def executemany(self, query, param_list):
        logger.debug('DatabaseCursor.executemany: query: %s, param_list: %s', query, param_list)
        for params in param_list:
            self.execute(query, params)

    def fetchone(self):
        logger.debug('DatabaseCursor.fetchone: Popping first result of: %s', self.connection.result)
        if self.connection.result:
            return self.connection.result.pop(0)
        return None

    def fetchall(self):
        logger.debug('DatabaseCursor.fetchall: Results: %s', self.connection.result)
        results = self.connection.result
        self.connection.result = []
        return results

    def fetchmany(self, size=None):
        if size is None:
            size = self.arraysize
        results = self.connection.result[:size]
        logger.debug('DatabaseCursor.fetchmany: size: %s - Results: %s', size, results)
        self.connection.result = self.connection.result[size:]
        return results

    def close(self):
        logger.debug('DatabaseCursor.close: Closing cursor')
        self.connection = None
