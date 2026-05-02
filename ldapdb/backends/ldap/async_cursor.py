"""
Asyncio-native cursor mirroring :class:`DatabaseCursor`.

Same compiler output (``LDAPSearch``), same Python-side result formatting —
only the I/O methods are awaitable. The caller is expected to run the cursor
on the same event loop that owns its :class:`LDAPClient`.

The paging loop inside one search remains a plain ``while True``: paging is
inherently sequential (next cookie depends on the previous response). Async
helps **across** searches (``asyncio.gather`` over multiple cursors), not
within one cursor's request stream.
"""

from __future__ import annotations

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
from .cursor import DatabaseCursor, _sort_and_slice_ldap_results
from .lib import LDAPDatabase, LDAPSearchControlType

if TYPE_CHECKING:
    from ldap.controls import RequestControl

    from .connection import LDAPClient

logger = logging.getLogger(__name__)


class AsyncDatabaseCursor(DatabaseCursor):
    """Async counterpart to :class:`DatabaseCursor`.

    Reuses the sync class's pure-Python helpers (description building, result
    formatting, sort/slice fallback) and overrides the I/O entry points
    (:meth:`aexecute` and the three control-mode dispatch methods) to run on
    an asyncio event loop via :class:`LDAPClient`'s async methods.

    Fetching is sync because :meth:`aexecute` already loaded all rows into the
    cursor — there's nothing left to await. The ``afetch*`` methods are thin
    awaitable wrappers provided for API symmetry.
    """

    def __init__(
        self,
        client: LDAPClient,
        settings_dict: dict | None = None,
    ) -> None:
        super().__init__(client, settings_dict)

    # ------------------------------------------------------------------ #
    # Async dispatch                                                     #
    # ------------------------------------------------------------------ #

    async def asearch(self) -> list[tuple[str, dict]]:
        """Async dispatch by control type — mirror of :meth:`DatabaseCursor.search`."""
        match self.search_obj.control_type:
            case LDAPSearchControlType.SSSVLV:
                logger.debug('AsyncDatabaseCursor.asearch: Using SSSVLV control')
                return await self._aexecute_with_sssvlv()
            case LDAPSearchControlType.SIMPLE_PAGED_RESULTS:
                logger.debug('AsyncDatabaseCursor.asearch: Using Paged Results control')
                return await self._aexecute_with_simple_paging()
            case LDAPSearchControlType.NO_CONTROL:
                logger.debug('AsyncDatabaseCursor.asearch: Using no controls')
                return await self._aexecute_without_ctrls()
            case _:
                raise NotImplementedError(f'Unknown control type {self.search_obj.control_type}')

    async def aexecute(self, query: LDAPQuery, *_args, **_params) -> None:
        """Async counterpart to :meth:`DatabaseCursor.execute`.

        Loads results into ``self.results`` exactly like the sync path, then
        applies the same Python-side description/format/sort/slice steps.
        """
        logger.debug('AsyncDatabaseCursor.aexecute: query: %s, params: %s', query, _params)
        self._check_closed()

        if not isinstance(query, LDAPQuery):
            raise LDAPQueryTypeError(query)

        self.query = query
        self.description = None
        self.rowcount = -1
        self.lastrowid = None

        self.results = await self.asearch()

        if (
            not self.query.group_by
            and len(self.query.annotations) == 1
            and all(isinstance(v, Count) for v in self.query.annotations.values())
        ):
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

    # ------------------------------------------------------------------ #
    # Awaitable fetch wrappers                                           #
    # ------------------------------------------------------------------ #

    async def afetchone(self):
        return self.fetchone()

    async def afetchmany(self, size=None):
        return self.fetchmany(size)

    async def afetchall(self):
        return self.fetchall()

    # ------------------------------------------------------------------ #
    # Per-control-type async I/O                                         #
    # ------------------------------------------------------------------ #

    async def _aexecute_without_ctrls(self, timeout: int = -1) -> list[tuple[str, dict]]:
        logger.debug('AsyncDatabaseCursor._aexecute_without_ctrls')
        _rtype, rdata, _ctrls = await self.client.asearch(
            base=self.search_obj.base,
            scope=self.search_obj.scope,
            filterstr=self.search_obj.filterstr,
            attrlist=self.search_obj.attrlist_without_dn,
            timeout=timeout,
        )
        return rdata

    async def _aexecute_with_simple_paging(self, timeout: int = -1) -> list[tuple[str, dict]]:
        page_size = self.settings_dict.get('PAGE_SIZE', 1000)
        cookie = b''
        results: list[tuple[str, dict]] = []
        while True:
            ctrl = SimplePagedResultsControl(criticality=True, size=page_size, cookie=cookie)
            _rtype, rdata, serverctrls = await self.client.asearch(
                base=self.search_obj.base,
                scope=self.search_obj.scope,
                filterstr=self.search_obj.filterstr,
                attrlist=self.search_obj.attrlist_without_dn,
                serverctrls=[ctrl],
                timeout=timeout,
            )
            results.extend(rdata)
            paged_ctrl = next(
                (c for c in serverctrls if c.controlType == SimplePagedResultsControl.controlType),
                None,
            )
            if not paged_ctrl or not paged_ctrl.cookie:
                break
            cookie = paged_ctrl.cookie
        return results

    async def _aexecute_with_sssvlv(self, timeout: int = -1) -> list[tuple[str, dict]]:
        serverctrls: list[RequestControl] = []

        sss_ordering_rules = [f'{attr}:{order_rule}' for attr, order_rule in self.search_obj.ordering_rules]
        logger.debug('AsyncDatabaseCursor._aexecute_with_sssvlv: Ordering rules: %s', sss_ordering_rules)
        sss_ctrl = SSSRequestControl(criticality=True, ordering_rules=sss_ordering_rules)
        serverctrls.append(sss_ctrl)

        vlv_ctrl = None
        use_vlv = self.search_obj.limit or self.search_obj.offset
        if use_vlv:
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
            'AsyncDatabaseCursor._aexecute_with_sssvlv:\nLDAPSearch: %s\nSSSConfig: %s\nVLVConfig: %s\n',
            self.search_obj.as_json(),
            json.dumps(sss_ctrl.__dict__, indent=4, sort_keys=True),
            json.dumps(vlv_ctrl.__dict__, indent=4, sort_keys=True) if vlv_ctrl else None,
        )

        try:
            _rtype, rdata, _ctrls = await self.client.asearch(
                base=self.search_obj.base,
                scope=self.search_obj.scope,
                filterstr=self.search_obj.filterstr,
                attrlist=self.search_obj.attrlist_without_dn,
                serverctrls=serverctrls,
                timeout=timeout,
            )
        except ldap.LDAPError as exc:
            # VLV error 76 -> Index out of range
            if exc.args and isinstance(exc.args[0], dict) and exc.args[0].get('result') == ldap.VLV_ERROR.errnum:
                # Match sync behavior: return empty list and let Django raise IndexError.
                return []
            raise
        return rdata

    # ------------------------------------------------------------------ #
    # Lifecycle                                                          #
    # ------------------------------------------------------------------ #

    async def aclose(self) -> None:
        """Async cursor close. Does not close the underlying client."""
        logger.debug('AsyncDatabaseCursor.aclose: Closing cursor')
        # Drop references so subsequent calls fail fast. The underlying
        # ``LDAPClient`` is owned by ``DatabaseWrapper`` (per-event-loop)
        # and is not closed by the cursor.
        self.client = None  # type: ignore[assignment]
        self.connection = None
        self.closed = True
        self.query = None
        self.results = []
        self._result_iter = iter([])

    # The sync ``execute`` and the three sync ``_execute_*`` helpers from the
    # base class would attempt blocking I/O. Block them with a clear error so
    # misuse is loud.
    def execute(self, query, *_args, **_params):  # type: ignore[override]  # noqa: ARG002
        raise LDAPDatabase.DatabaseError(
            'AsyncDatabaseCursor: use aexecute() from an async context, not execute()'
        )
