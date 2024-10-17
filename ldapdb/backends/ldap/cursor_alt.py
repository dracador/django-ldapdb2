import logging
from typing import TYPE_CHECKING

import ldap
from ldap.controls import SimplePagedResultsControl
from ldap.controls.sss import SSSRequestControl
from ldap.controls.vlv import VLVRequestControl

from ldapdb.backends.ldap import LDAPSearch
from .lib import LDAPSearchControlType

if TYPE_CHECKING:
    from ldap.ldapobject import ReconnectLDAPObject

logger = logging.getLogger(__name__)


class DatabaseCursor:
    def __init__(self, connection):
        self.connection: ReconnectLDAPObject = connection
        self.description = None
        self.rowcount = -1
        self.arraysize = 1000  # where does this or the size parameter come from?
        self.lastrowid = None
        self.results: list[tuple[str, dict]] = []

    @staticmethod
    def _get_server_controls(ldap_query: LDAPSearch, next_page_obj: str = None):
        if ldap_query.control_type == LDAPSearchControlType.SSSVLV:
            sss = SSSRequestControl(ordering_rules=[f'{attr}:{order_rule}' for attr, order_rule in ldap_query.order_by])

            vlv = VLVRequestControl(
                after_count=ldap_query.limit - 1 if ldap_query.limit else 100000000,
                before_count=0,
                content_count=0,
                criticality=False,
                offset=ldap_query.offset + 1,  # offset specifies the index of the first result
            )
            return [sss, vlv]

        elif ldap_query.control_type == LDAPSearchControlType.PAGED_RESULTS:
            simple_page_ctrl = SimplePagedResultsControl(
                criticality=False,
                size=ldap_query.limit,
                cookie='',
            )

            # TODO: Check type of next_page_obj
            print(type(next_page_obj))

            if next_page_obj:
                simple_page_ctrl.cookie = next_page_obj
            return [simple_page_ctrl]
        return []

    def _search(self, ldap_search: LDAPSearch, timeout: int = -1, limit: int = 0):
        logger.debug(
            'DatabaseCursor._search: search: %s, timeout: %s, limit: %s', ldap_search.serialize(), timeout, limit
        )
        return self.connection.search_ext_s(  # TODO: SHOULD NOT BE SYNCHRONEOUS
            base=ldap_search.base,
            scope=ldap_search.scope,
            filterstr=ldap_search.filterstr,
            attrlist=ldap_search.attrlist,
            serverctrls=self._get_server_controls(ldap_search),
            clientctrls=None,
            timeout=timeout,
            sizelimit=limit,
        )

    def execute(self, query, *_args, **_params):
        logger.debug('DatabaseCursor.execute: query: %s (%s), params: %s', query, type(query), _params)
        if self.results:
            raise AssertionError('Cursor already has cached results. This should not happen.')

        self.description = None
        self.rowcount = -1
        self.lastrowid = None
        print(query, type(query), self.connection, type(self.connection))

        if not isinstance(query, LDAPSearch):
            raise ValueError('Query object must be an instance of LDAPSearch')

        try:
            results = self._search(query)
            print(results)
            self.rowcount = len(results)
        except ldap.LDAPError as e:
            raise e

    def executemany(self, query, param_list):
        logger.debug('DatabaseCursor.executemany: query: %s, param_list: %s', query, param_list)
        raise NotImplementedError()

    def fetchone(self):
        logger.debug('DatabaseCursor.fetchone: Popping first result of: %s', self.connection.result)
        raise NotImplementedError()
        if self.connection.result:
            return self.connection.result.pop(0)
        return None

    def fetchall(self):
        raise NotImplementedError()
        logger.debug('DatabaseCursor.fetchall: Results: %s', self.connection.result)
        results = self.connection.result
        self.connection.result = []
        return results

    def fetchmany(self, size=None):
        print(size)
        if size is None:
            size = self.arraysize
        results = self._search()[:size]
        logger.debug('DatabaseCursor.fetchmany: size: %s - Results: %s', size, results)
        self.connection.result = self.connection.result[size:]
        return results

    def close(self):
        logger.debug('DatabaseCursor.close: Closing cursor')
        self.connection = None
