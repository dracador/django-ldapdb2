import logging
from typing import TYPE_CHECKING

import ldap
from ldap.controls.sss import SSSRequestControl
from ldap.controls.vlv import VLVRequestControl

from ldapdb.backends.ldap import LDAPSearch
from .lib import LDAPDatabase, LDAPSearchControlType

if TYPE_CHECKING:
    from ldap.ldapobject import ReconnectLDAPObject

logger = logging.getLogger(__name__)


class DatabaseCursor:
    """DatabaseCursor for LDAP according to PEP 249 (DB-API 2.0)"""

    def __init__(self, connection):
        self.connection: ReconnectLDAPObject = connection
        self.ldap_query: LDAPSearch | None = None
        self.description = None
        self.rowcount = -1
        self.arraysize = 1
        self.closed = False
        self.lastrowid = None
        self.results: list[tuple[str, dict]] = []
        self._result_iter = iter([])

    def search(self):
        match self.ldap_query.control_type:
            case LDAPSearchControlType.SSSVLV:
                logger.debug('DatabaseCursor.search: Using SSSVLV control')
                return self._execute_with_sssvlv()
            case LDAPSearchControlType.PAGED_RESULTS:
                logger.debug('DatabaseCursor.search: Using Paged Results control')
                return self._execute_with_paging()
            case LDAPSearchControlType.NO_CONTROL:
                logger.debug('DatabaseCursor.search: Using no control - Returning empty list for now!')
                return self._execute_without_control()
            case _:
                raise NotImplementedError(f'Control type {self.ldap_query.control_type} not yet implemented')

    def execute(self, query, *_args, **_params):
        logger.debug('DatabaseCursor.execute: query: %s (%s), params: %s', query, type(query), _params)
        self._check_closed()

        if not isinstance(query, LDAPSearch):
            raise ValueError('Query object must be an instance of LDAPSearch')

        self.ldap_query = query
        self.description = None
        self.rowcount = -1
        self.lastrowid = None

        try:
            self.results = self.search()
            self.set_description()
            self.format_results()
            self.rowcount = len(self.results)
            self._result_iter = iter(self.results)
        except ldap.LDAPError as e:
            raise e

    def _execute_without_control(self):
        raise NotImplementedError()

    def _execute_with_paging(self, timeout: int = -1):
        raise NotImplementedError()

    def _execute_with_sssvlv(self, timeout: int = -1):
        assert self.ldap_query.order_by, 'SSSVLV control requires order_by fields to be set'

        sss_ordering_rules = [f'{attr}:{order_rule}' for attr, order_rule in self.ldap_query.order_by]
        logger.debug('DatabaseCursor._execute_with_sssvlv: Ordering rules: %s', sss_ordering_rules)
        sss_ctrl = SSSRequestControl(ordering_rules=sss_ordering_rules)

        # Not sure if we want to keep track of the context_id and offset/content_count here,
        # since we could have a more lazy iterator when using this with fetchmany.
        # Otherwise we'll just always do a new search.
        # Using a context_id here would take some load off the LDAP server and probably speed things up.
        vlv_context_id = None
        vlv_offset = None
        vlv_content_count = None

        if vlv_offset is None and self.ldap_query.offset:
            vlv_offset = self.ldap_query.offset + 1  # VLV uses 1-based indexing

        if self.ldap_query.limit:
            vlv_content_count = self.ldap_query.limit

        vlv_ctrl = VLVRequestControl(
            criticality=True,
            before_count=0,
            after_count=self.ldap_query.limit - 1 if self.ldap_query.limit else 0,
            offset=vlv_offset,
            content_count=vlv_content_count,
            greater_than_or_equal=None if vlv_offset and vlv_content_count else 10000,  # just a basic fallback value
            context_id=vlv_context_id,
        )

        serverctrls = [sss_ctrl, vlv_ctrl]

        logger.debug('DatabaseCursor._execute_with_sssvlv: Serialized Search: %s', self.ldap_query.serialize())

        msgid = self.connection.search_ext(
            base=self.ldap_query.base,
            scope=self.ldap_query.scope,
            filterstr=self.ldap_query.filterstr,
            attrlist=self.ldap_query.attrlist,
            serverctrls=serverctrls,
            timeout=timeout,
        )

        rtype, rdata, rmsgid, serverctrls = self.connection.result3(msgid)
        return rdata

    def set_description(self):
        if self.results:
            field_names = self.ldap_query.attrlist
            self.description = [(attr, None, None, None, None, None, None) for attr in field_names]
        else:
            self.description = []

    def format_results(self):
        results = []
        column_names = [col[0] for col in self.description]

        for dn, attributes in self.results:
            row_data = {}
            for attr_name in column_names:
                if attr_name == 'dn':
                    row_data['dn'] = [dn]
                else:
                    row_data[attr_name] = attributes.get(attr_name, [None])

            # sort rows in the correct order that is defined by the column names in description<
            row = tuple(row_data[col] for col in column_names)
            results.append(row)
        self.results = results

    def executemany(self, query, param_list):
        logger.debug('DatabaseCursor.executemany: query: %s, param_list: %s', query, param_list)
        self._check_closed()
        raise NotImplementedError()

    def fetchone(self):
        self._check_closed()
        try:
            logger.debug('DatabaseCursor.fetchone: Getting next result...')
            return next(self._result_iter)
        except StopIteration:
            logger.debug('DatabaseCursor.fetchone: No more results')
            return None

    def fetchmany(self, size=None):
        self._check_closed()
        size = size or self.arraysize
        logger.debug('DatabaseCursor.fetchmany: Getting the next %s results', size)
        results = []
        for _ in range(size):
            row = self.fetchone()
            if row is None:
                break
            results.append(row)
        return results

    def fetchall(self):
        logger.debug('DatabaseCursor.fetchall: Getting all results')
        self._check_closed()
        return list(self._result_iter)

    def _check_closed(self):
        if self.closed:
            raise LDAPDatabase.ProgrammingError('Cursor is closed')

    def close(self):
        logger.debug('DatabaseCursor.close: Closing cursor')
        self.connection = None
        self.closed = True
        self.ldap_query = None
        self.results = []
        self._result_iter = iter([])
