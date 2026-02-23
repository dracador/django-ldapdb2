import functools
import json
import logging
from typing import TYPE_CHECKING

import ldap
from django.db.models import Count
from ldap.controls import SimplePagedResultsControl
from ldap.controls.sss import SSSRequestControl
from ldap.controls.vlv import VLVRequestControl

from ldapdb.exceptions import LDAPQueryTypeError
from ldapdb.models import LDAPQuery
from .lib import LDAPDatabase, LDAPSearchControlType, unescape_ldap_dn_chars

if TYPE_CHECKING:
    from ldap.controls import RequestControl
    from ldap.ldapobject import ReconnectLDAPObject

logger = logging.getLogger(__name__)


def _sort_and_slice_ldap_results(
    results: list[tuple[str, dict]],
    ordering_rules: list[tuple[str, str]],
    offset: int,
    limit: int,
) -> list[tuple[str, dict]]:
    """
    Sort and slice a list of raw LDAP results in Python.

    Used as a fallback when the server does not support SSSVLV. Ordering rule OIDs
    are ignored — sorting is lexicographic on the raw bytes value, which is correct
    for string attributes but not for numeric or language-specific ordering rules.
    """
    if ordering_rules:
        def _compare(a: tuple[str, dict], b: tuple[str, dict]) -> int:
            dn_a, attrs_a = a
            dn_b, attrs_b = b
            for attrname, _ in ordering_rules:
                descending = attrname.startswith('-')
                attr = attrname.lstrip('-')
                if attr == 'dn':
                    val_a = dn_a.encode() if isinstance(dn_a, str) else dn_a
                    val_b = dn_b.encode() if isinstance(dn_b, str) else dn_b
                else:
                    val_a = attrs_a.get(attr, [b''])[0] if attrs_a.get(attr) else b''
                    val_b = attrs_b.get(attr, [b''])[0] if attrs_b.get(attr) else b''
                if val_a < val_b:
                    result = -1
                elif val_a > val_b:
                    result = 1
                else:
                    continue
                return -result if descending else result
            return 0

        results = sorted(results, key=functools.cmp_to_key(_compare))

    if offset or limit:
        end = offset + limit if limit else None
        results = results[offset:end]

    return results


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

    def __init__(self, connection, settings_dict: dict | None = None):
        self.connection: ReconnectLDAPObject | None = connection
        self.settings_dict: dict = settings_dict or {}
        self.query: LDAPQuery | None = None
        self.description = None
        self.rowcount = -1
        self.arraysize = 1
        self.closed = False
        self.lastrowid = None

        # results can be either a list of tuples (dn, attributes) or a list of integers (count)
        self.results: list[tuple[str, dict]] | list[tuple[int]] = []
        self._result_iter = iter([])

    @property
    def search_obj(self):
        return self.query.ldap_search

    def search(self):
        # noinspection PyUnreachableCode
        # Fixed with PyCharm 2025.2 but EAP is unusable right now
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

        if self.search_obj.control_type != LDAPSearchControlType.SSSVLV:
            self.results = _sort_and_slice_ldap_results(
                self.results,
                self.search_obj.ordering_rules,
                self.search_obj.offset,
                self.search_obj.limit,
            )

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
        page_size = self.settings_dict.get('PAGE_SIZE', 1000)
        cookie = b''
        results = []
        while True:
            ctrl = SimplePagedResultsControl(criticality=True, size=page_size, cookie=cookie)
            msgid = self.connection.search_ext(
                base=self.search_obj.base,
                scope=self.search_obj.scope,
                filterstr=self.search_obj.filterstr,
                attrlist=self.search_obj.attrlist_without_dn,
                serverctrls=[ctrl],
                timeout=timeout,
            )
            _rtype, rdata, _rmsgid, serverctrls = self.connection.result3(msgid)
            results.extend(rdata)
            paged_ctrl = next(
                (c for c in serverctrls if c.controlType == SimplePagedResultsControl.controlType),
                None,
            )
            if not paged_ctrl or not paged_ctrl.cookie:
                break
            cookie = paged_ctrl.cookie
        return results

    def _execute_with_sssvlv(self, timeout: int = -1):
        serverctrls: list[RequestControl] = []

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
            # dn might contain hexadecimal characters, so decode it first
            dn = unescape_ldap_dn_chars(dn)

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
