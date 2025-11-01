import json
import logging
from typing import TYPE_CHECKING

import ldap
from django.db.models import Count
from ldap.controls.sss import SSSRequestControl
from ldap.controls.vlv import VLVRequestControl

from ldapdb.exceptions import LDAPQueryTypeError
from ldapdb.models import LDAPQuery
from .ldif_helpers import AddRequest, ModifyRequest
from .lib import LDAPDatabase, LDAPSearchControlType

if TYPE_CHECKING:
    from ldap.controls import RequestControl
    from ldap.ldapobject import ReconnectLDAPObject

    from .base import DatabaseWrapper

logger = logging.getLogger(__name__)


class DatabaseCursor:
    """
    DatabaseCursor for LDAP according to PEP 249 (DB-API 2.0)

    This class is used to execute LDAP queries and fetch results.
    It is designed to work with the LDAPDatabase backend and the LDAPQuery class.

    It supports the following LDAP search types:
    * Server Side Sorting (+ Virtual List View) (SSSVLV)
    * Simple Paged Results
    * No Control (simple search)

    Notes on Virtual List View (VLV) and Simple Paged Results:
    Theoretically, this cursor could support a more lazy iterator for paginated requests, where it would only fetch
    the next page and not all results at once. However, this would require keeping track of the context ID and offset,
    which is not currently implemented. Instead, it fetches all results at once and formats them accordingly.
    For 99% of use cases, this is sufficient and simplifies the implementation.

    Notes on Ordering:
    Without Server Side Sorting (SSS), the results will not be ordered by the LDAP server directly.
    TODO: Implement a way to sort results in Python if SSS is not used.
    """

    def __init__(self, connection, db_wrapper: 'DatabaseWrapper'):
        self.connection: ReconnectLDAPObject = connection
        self.db_wrapper = db_wrapper
        self.query: LDAPQuery | None = None
        self.description = None
        self.rowcount = -1
        self.arraysize = 1
        self.closed = False
        self.lastrowid = None
        self.results: list[tuple[str, dict]] = []
        self._result_iter = iter([])

    @property
    def search_obj(self):
        return self.query.ldap_search

    def search(self):
        match self.search_obj.control_type:
            case LDAPSearchControlType.SSSVLV:
                logger.debug('DatabaseCursor.search: Using SSSVLV control')
                return self._execute_with_sssvlv()
            case LDAPSearchControlType.SIMPLE_PAGED_RESULTS:
                logger.debug('DatabaseCursor.search: Using Paged Results control')
                return self._execute_with_simple_paging()
            case LDAPSearchControlType.NO_CONTROL:
                logger.debug('DatabaseCursor.search: Using no controls')
                return self._execute_without_ctrls()
            case _:
                raise NotImplementedError(f'Unknown control type {self.search_obj.control_type}')

    def execute(self, query: LDAPQuery, *_args, **_params):
        logger.debug('DatabaseCursor.execute: query: %s (%s), params: %s', query, type(query), _params)
        self._check_closed()

        if not isinstance(query, LDAPQuery):
            raise LDAPQueryTypeError(query)

        self.query = query
        self.description = None
        self.rowcount = -1
        self.lastrowid = None

        self.results = self.search()

        if (
            not self.query.group_by
            and len(self.query.annotations) == 1
            and all(isinstance(v, Count) for v in self.query.annotations.values())
        ):
            # TODO: Use NumSubordinates/ldapentrycount?#
            #  https://ldapwiki.com/wiki/Wiki.jsp?page=NumSubordinates
            # This is a special case for count queries like LDAPUser.objects.count(),
            # where we only return the count of results.
            alias = next(iter(self.query.annotations))
            self.results = [(len(self.results),)]
            self.description = [(alias, None, None, None, None, None, None)]
            self.rowcount = 1
            self._result_iter = iter(self.results)
            return

        self.set_description()
        self.format_results()
        self.rowcount = len(self.results)
        self._result_iter = iter(self.results)

    def _execute_without_ctrls(self, timeout: int = -1):
        logger.debug('DatabaseCursor._execute_without_ctrls')
        return self.connection.search_st(
            base=self.search_obj.base,
            scope=self.search_obj.scope,
            filterstr=self.search_obj.filterstr,
            attrlist=self.search_obj.attrlist_without_dn,
            timeout=timeout,
        )

    def _execute_with_simple_paging(self, timeout: int = -1):
        raise NotImplementedError()

    def _execute_with_sssvlv(self, timeout: int = -1):
        serverctrls: list[RequestControl] = []

        # serverctrls.extend(self.txn_ctrls)

        sss_ordering_rules = [f'{attr}:{order_rule}' for attr, order_rule in self.search_obj.ordering_rules]
        logger.debug('DatabaseCursor._execute_with_sssvlv: Ordering rules: %s', sss_ordering_rules)
        sss_ctrl = SSSRequestControl(criticality=True, ordering_rules=sss_ordering_rules)
        serverctrls.append(sss_ctrl)

        vlv_ctrl = None
        use_vlv = self.search_obj.limit or self.search_obj.offset
        if use_vlv:
            # Not sure if we want to keep track of the context_id and offset here, since we could have a more lazy
            # iterator when using this with fetchmany. Otherwise we'll just always do a new search.
            vlv_context_id = None

            vlv_ctrl = VLVRequestControl(
                criticality=True,
                before_count=0,
                after_count=max(0, self.search_obj.limit - 1),
                offset=self.search_obj.ldap_offset,
                content_count=0,
                context_id=vlv_context_id,
            )

            serverctrls.append(vlv_ctrl)

        logger.debug(
            'DatabaseCursor._execute_with_sssvlv:\nLDAPSearch: %s\nSSSConfig: %s\nVLVConfig: %s\n',
            self.search_obj.as_json(),
            json.dumps(sss_ctrl.__dict__, indent=4, sort_keys=True),
            json.dumps(vlv_ctrl.__dict__, indent=4, sort_keys=True) if vlv_ctrl else None,
        )

        try:
            msgid = self.connection.search_ext(
                base=self.search_obj.base,
                scope=self.search_obj.scope,
                filterstr=self.search_obj.filterstr,
                attrlist=self.search_obj.attrlist_without_dn,
                serverctrls=serverctrls,
                timeout=timeout,
            )

            rtype, rdata, rmsgid, serverctrls = self.connection.result3(msgid)
            logger.debug('DatabaseCursor._execute_with_sssvlv - Result: length: %s, results: %s', len(rdata), rdata)
        except ldap.LDAPError as exc:
            # VLV error 76 -> Index out of range
            if exc.args and isinstance(exc.args[0], dict) and exc.args[0].get('result') == ldap.VLV_ERROR.errnum:
                # To not break the behavior django expects, we return an empty list and let django raise the IndexError
                return []
            raise
        return rdata

    def set_description(self):
        field_names = []
        if self.results:
            if self.search_obj.attrlist:
                field_names.extend(self.search_obj.attrlist)
            elif not self.query.annotation_aliases:
                # Only prepend DN when the row would otherwise be empty
                # *and* the query has no annotations.
                field_names.append('dn')

        if self.query.annotation_aliases:
            field_names.extend(self.query.annotation_aliases)

        self.description = [(attr, None, None, None, None, None, None) for attr in field_names]

    def format_results(self):
        column_names = [col[0] for col in self.description]

        results = []
        for dn, attributes in self.results:
            row_data = {}
            for attr_name in column_names:
                if attr_name == 'dn':
                    row_data['dn'] = [dn]
                else:
                    row_data[attr_name] = attributes.get(attr_name, None)

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
        self.query = None
        self.results = []
        self._result_iter = iter([])

    @property
    def txn_ctrls(self):
        return self.db_wrapper.ops.get_txn_serverctrls(self.db_wrapper)

    def add(self, dn: str, mods: AddRequest):
        serverctrls = self.txn_ctrls
        logger.debug('DatabaseCursor.add: dn: %s, mods: %s, serverctrls: %s', dn, mods.as_modlist(), serverctrls)
        resp_type, resp_data, resp_msgid, resp_ctrls = self.connection.add_ext_s(dn, mods.as_modlist(), serverctrls=serverctrls)
        print(f'add_ext_s results: {resp_type=}, {resp_data=}, {resp_msgid=}, {resp_ctrls=}')
        return resp_type, resp_data, resp_msgid, resp_ctrls

    def add_s(self, dn: str, mods: AddRequest):
        logger.debug('DatabaseCursor.add: dn: %s, mods: %s', dn, mods.as_modlist())
        return self.connection.add_s(dn, mods.as_modlist())

    def modify(self, dn: str, mods: ModifyRequest):
        serverctrls = self.txn_ctrls
        logger.debug('DatabaseCursor.modify: dn: %s, mods: %s, serverctrls: %s', dn, mods.as_modlist(), serverctrls)
        return self.connection.modify_ext_s(dn, mods.as_modlist(), serverctrls=serverctrls)

    def delete(self, dn):
        serverctrls = self.txn_ctrls
        logger.debug('DatabaseCursor.delete: dn: %s', dn)
        return self.connection.delete_ext_s(dn, serverctrls=serverctrls)
