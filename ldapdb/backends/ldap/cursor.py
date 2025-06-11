import logging
from typing import TYPE_CHECKING

import ldap
from django.db import NotSupportedError
from ldap.controls.sss import SSSRequestControl
from ldap.controls.vlv import VLVRequestControl

from ldapdb.backends.ldap import LDAPSearch
from .lib import LDAPDatabase, LDAPSearchControlType

if TYPE_CHECKING:
    from ldap.controls import RequestControl
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
        # noinspection PyUnreachableCode
        # Fixed with PyCharm 2025.2 but EAP is unusable right now
        match self.ldap_query.control_type:
            case LDAPSearchControlType.SSSVLV:
                if (self.ldap_query.limit or self.ldap_query.offset) and not self.ldap_query.order_by:
                    raise AttributeError(
                        'Cannot use limit/offset without order_by. '
                        'Either use order_by() in your filter or set a default ordering in your model.'
                    )
                elif self.ldap_query.order_by:
                    return self._execute_with_sssvlv()
                else:
                    # TODO: Make LDAPSearchControlType.PAGED_RESULTS the fallback instead of a simple search_st() call.
                    #  - Should probably be decided before this function gets called.
                    return self._execute_without_ctrls()
            case LDAPSearchControlType.PAGED_RESULTS:
                return self._execute_with_paging()
            case LDAPSearchControlType.NO_CONTROL:
                raise NotImplementedError
            case _:
                raise NotImplementedError(f'Unknown control type {self.ldap_query.control_type}')

    def execute(self, query, *_args, **_params):
        logger.debug('DatabaseCursor.execute: query: %s (%s), params: %s', query, type(query), _params)
        self._check_closed()

        if not isinstance(query, LDAPSearch):
            raise NotSupportedError('Query object must be an instance of LDAPSearch')

        self.ldap_query = query
        self.description = None
        self.rowcount = -1
        self.lastrowid = None

        try:
            self.results = self.search()
            logger.debug('DatabaseCursor.execute: Results: %s', self.results)
            self._set_description()
            self._format_results()
            self.rowcount = len(self.results)
            self._result_iter = iter(self.results)
        except ldap.LDAPError as e:
            raise e

    def _execute_without_ctrls(self, timeout: int = -1):
        return self.connection.search_st(
            base=self.ldap_query.base,
            scope=self.ldap_query.scope,
            filterstr=self.ldap_query.filterstr,
            attrlist=self.ldap_query.attrlist,
            timeout=timeout,
        )

    def _execute_with_paging(self, timeout: int = -1):
        raise NotImplementedError()

    def _execute_with_sssvlv(self, timeout: int = -1):
        serverctrls: list[RequestControl] = []

        sss_ctrl = SSSRequestControl(
            ordering_rules=[f'{attr}:{order_rule}' for attr, order_rule in self.ldap_query.order_by]
        )
        serverctrls.append(sss_ctrl)

        use_vlv = self.ldap_query.limit or self.ldap_query.offset
        if use_vlv:
            # Not sure if we want to keep track of the context_id and offset here, since we could have a more lazy
            # iterator when using this with fetchmany. Otherwise we'll just always do a new search.
            # Using a context_id here would take some load off the LDAP server and probably speed things up.
            vlv_context_id = None

            vlv_ctrl = VLVRequestControl(
                criticality=True,
                before_count=0,
                after_count=max(0, self.ldap_query.limit - 1),
                offset=self.ldap_query.ldap_offset,
                content_count=self.ldap_query.limit,
                context_id=vlv_context_id,
            )

            serverctrls.append(vlv_ctrl)

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
