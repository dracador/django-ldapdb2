import logging
from typing import TYPE_CHECKING

import ldap
from ldap.controls.sss import SSSRequestControl
from ldap.controls.vlv import VLVRequestControl, VLVResponseControl

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
                return self._execute_with_sssvlv()
            case LDAPSearchControlType.PAGED_RESULTS:
                return self._execute_with_paging()
            case LDAPSearchControlType.NO_CONTROL:
                return []
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
            print(self.results)
            logger.debug('DatabaseCursor.execute: Results: %s', self.results)
            self._set_description()
            self._format_results()
            self.rowcount = len(self.results)
            self._result_iter = iter(self.results)
        except ldap.LDAPError as e:
            raise e

    def _execute_with_paging(self, timeout: int = -1):
        raise NotImplementedError()

    """
        page_size = 1000  # Adjust page size as needed
        lc = SimplePagedResultsControl(True, size=page_size, cookie='')

        msgid = self.connection.conn.search_ext(
            base_dn, scope, query, attrlist=attributes, serverctrls=[lc]
        )

        results = []
        while True:
            rtype, rdata, rmsgid, serverctrls = self.connection.conn.result3(msgid)
            results.extend(rdata)

            # Look for the SimplePagedResultsControl response control
            pctrls = [
                c for c in serverctrls
                if c.controlType == SimplePagedResultsControl.controlType
            ]
            if pctrls:
                est, cookie = pctrls[0].size, pctrls[0].cookie
                if cookie:
                    # Prepare the next page request
                    lc.cookie = cookie
                    msgid = self.connection.conn.search_ext(
                        base_dn, scope, query, attrlist=attributes, serverctrls=[lc]
                    )
                else:
                    break
            else:
                break

        self.results = results
        self.rowcount = len(self.results)
        self._result_iter = iter(self.results)
        self._set_description()
    """

    def _execute_with_sssvlv(self, timeout: int = -1):
        sss_ctrl = SSSRequestControl(
            ordering_rules=[f'{attr}:{order_rule}' for attr, order_rule in self.ldap_query.order_by]
        )

        # Not sure if we want to keep track of the context_id and offset here, since we could have a more lazy iterator
        # when using this with fetchmany. Otherwise we'll just always do a new search.
        # Using a context_id here would take some load off the LDAP server and probably speed things up.
        vlv_context_id = None

        vlv_ctrl = VLVRequestControl(
            criticality=True,
            before_count=0,
            after_count=self.ldap_query.limit - 1,
            offset=self.ldap_query.ldap_offset,
            content_count=self.ldap_query.limit,
            context_id=vlv_context_id,
        )

        serverctrls = [sss_ctrl, vlv_ctrl]

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

    def _set_description(self):
        if self.results:
            field_names = ['dn'] + self.ldap_query.attrlist
            self.description = [(attr, None, None, None, None, None, None) for attr in field_names]
        else:
            self.description = []

    def _format_results(self):
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
        logger.debug('DatabaseCursor.fetchone: Getting next result of: %s', self.results)
        self._check_closed()
        try:
            return next(self._result_iter)
        except StopIteration:
            return None

    def fetchmany(self, size=None):
        self._check_closed()
        size = size or self.arraysize
        logger.debug('DatabaseCursor.fetchmany: Getting %s results', size)
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
