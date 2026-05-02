"""
Unified LDAP I/O client. Wraps a python-ldap ``ReconnectLDAPObject`` and
exposes both blocking (sync) and awaitable (async) flavors of every operation.

All I/O goes through python-ldap's non-blocking ``*_ext`` request methods plus
``result3``. The two flavors differ only in how they wait for a response:

* **Sync**: ``result3(msgid, timeout=-1)`` blocks the calling thread.
* **Async**: ``loop.add_reader`` drives a drain loop that resolves a
  ``msgid -> asyncio.Future`` map.

Reconnect handling
------------------
``ReconnectLDAPObject``'s built-in transparent reconnect only fires from
``*_s`` synchronous calls. Since we use ``*_ext`` exclusively, we replicate
``_apply_method_s``'s retry semantics ourselves:

* **Sync**: on ``SERVER_DOWN``, force-unbind, call ``conn.reconnect(...)``
  (which re-binds with the original credentials), and retry the operation
  once. If reconnect itself fails after ``retry_max`` attempts, the original
  ``SERVER_DOWN`` propagates.
* **Async**: detect reconnects observationally via ``_reconnects_done`` and
  fail in-flight futures with ``ConnectionResetError`` so the caller can
  decide whether to retry. Transparent retry on the loop would require
  blocking reconnect off the loop via an executor; we don't do that yet.

Connections are not shared across modes — sync and async clients each wrap
their own ``ReconnectLDAPObject``. Sync clients are per-thread (matching
Django's connection model); async clients are per-event-loop (because
``add_reader`` registrations are loop-local).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import TYPE_CHECKING, Any

import ldap

if TYPE_CHECKING:
    from collections.abc import Callable

    from ldap.controls import RequestControl
    from ldap.ldapobject import ReconnectLDAPObject

logger = logging.getLogger(__name__)


_RES_ANY = ldap.RES_ANY


class LDAPClient:
    """One-class LDAP I/O wrapper supporting both sync and async usage.

    Construction:
        - For sync usage: ``LDAPClient(conn)``. Async methods will raise.
        - For async usage: ``LDAPClient(conn, loop=loop)``. Sync methods are
          still callable but should not be invoked from the same event loop
          (they will block the loop). Use them only outside any running loop
          (e.g. during connection setup).

    The same instance must not be used to drive both modes concurrently on
    the same connection — pick one mode per ``LDAPClient`` instance.
    """

    def __init__(
        self,
        conn: ReconnectLDAPObject,
        *,
        loop: asyncio.AbstractEventLoop | None = None,
    ) -> None:
        self._conn = conn
        self._loop = loop
        # Async dispatch state. Lazy: the reader is only registered the
        # first time an async method is called.
        self._waiters: dict[int, asyncio.Future] = {}
        self._registered_fd: int | None = None
        self._reconnects_seen = getattr(conn, '_reconnects_done', 0)
        self._closed = False

    # ------------------------------------------------------------------ #
    # Connection access                                                  #
    # ------------------------------------------------------------------ #

    @property
    def connection(self) -> ReconnectLDAPObject:
        """The underlying ``ReconnectLDAPObject``.

        Provided for tests and for code paths that legitimately need the raw
        python-ldap object (e.g. ``read_rootdse_s`` on first feature lookup).
        Prefer the client's own methods for ordinary I/O.
        """
        return self._conn

    # ================================================================== #
    # Sync API                                                           #
    # ================================================================== #

    def search(
        self,
        base: str,
        scope: int,
        filterstr: str = '(objectClass=*)',
        attrlist: list[str] | None = None,
        serverctrls: list[RequestControl] | None = None,
        clientctrls: list[RequestControl] | None = None,
        timeout: int = -1,
        sizelimit: int = 0,
    ) -> tuple[int, list[tuple[str, dict]], list[RequestControl]]:
        return self._sync_call(
            lambda: self._conn.search_ext(
                base,
                scope,
                filterstr,
                attrlist=attrlist,
                serverctrls=serverctrls,
                clientctrls=clientctrls,
                timeout=timeout,
                sizelimit=sizelimit,
            )
        )

    def add(
        self,
        dn: str,
        modlist: list[tuple[str, Any]],
        serverctrls: list[RequestControl] | None = None,
        clientctrls: list[RequestControl] | None = None,
    ) -> tuple[int, list, list[RequestControl]]:
        return self._sync_call(
            lambda: self._conn.add_ext(
                dn, modlist, serverctrls=serverctrls, clientctrls=clientctrls
            )
        )

    def modify(
        self,
        dn: str,
        modlist: list[tuple[int, str, Any]],
        serverctrls: list[RequestControl] | None = None,
        clientctrls: list[RequestControl] | None = None,
    ) -> tuple[int, list, list[RequestControl]]:
        return self._sync_call(
            lambda: self._conn.modify_ext(
                dn, modlist, serverctrls=serverctrls, clientctrls=clientctrls
            )
        )

    def delete(
        self,
        dn: str,
        serverctrls: list[RequestControl] | None = None,
        clientctrls: list[RequestControl] | None = None,
    ) -> tuple[int, list, list[RequestControl]]:
        return self._sync_call(
            lambda: self._conn.delete_ext(
                dn, serverctrls=serverctrls, clientctrls=clientctrls
            )
        )

    def rename(
        self,
        dn: str,
        newrdn: str,
        newsuperior: str | None = None,
        delold: int = 1,
        serverctrls: list[RequestControl] | None = None,
        clientctrls: list[RequestControl] | None = None,
    ) -> tuple[int, list, list[RequestControl]]:
        # NB: python-ldap names the non-blocking variant ``rename`` (not
        # ``rename_ext`` like the others). The signature still matches the
        # rest of the *_ext family.
        return self._sync_call(
            lambda: self._conn.rename(
                dn, newrdn, newsuperior, delold,
                serverctrls=serverctrls, clientctrls=clientctrls,
            )
        )

    def bind(
        self,
        bind_dn: str,
        bind_pw: str,
    ) -> tuple[int, list, list[RequestControl]]:
        """Async-style simple bind via ``simple_bind`` (non-_s) + result.

        For the *initial* bind during connection setup, prefer the underlying
        ``ReconnectLDAPObject``'s ``simple_bind_s`` directly — that path is
        what triggers ``_apply_method_s``'s retry logic for the
        connection-establishment phase.
        """
        return self._sync_call(lambda: self._conn.simple_bind(bind_dn, bind_pw))

    def close(self) -> None:
        """Sync close: unbind. Idempotent."""
        if self._closed:
            return
        self._closed = True
        with contextlib.suppress(ldap.LDAPError):
            self._conn.unbind_s()

    # ------------------------------------------------------------------ #
    # Sync internals                                                     #
    # ------------------------------------------------------------------ #

    def _sync_call(
        self, request_fn: Callable[[], int]
    ) -> tuple[int, list, list[RequestControl]]:
        """Send a request via ``*_ext``, block on result, retry once on SERVER_DOWN.

        Replicates ``ReconnectLDAPObject._apply_method_s`` semantics for the
        non-blocking request path the client uses exclusively.
        """
        try:
            return self._send_and_wait_sync(request_fn)
        except ldap.SERVER_DOWN:
            self._force_reconnect()
            return self._send_and_wait_sync(request_fn)

    def _send_and_wait_sync(
        self, request_fn: Callable[[], int]
    ) -> tuple[int, list, list[RequestControl]]:
        msgid = request_fn()
        rtype, rdata, _rmsgid, ctrls = self._conn.result3(msgid, timeout=-1)
        return rtype, rdata, ctrls

    def _force_reconnect(self) -> None:
        """Drop the current socket and have ``ReconnectLDAPObject`` rebind."""
        with contextlib.suppress(Exception):
            self._conn.unbind_s()
        self._conn.reconnect(
            self._conn._uri,
            retry_max=getattr(self._conn, '_retry_max', 1),
            retry_delay=getattr(self._conn, '_retry_delay', 60.0),
        )

    # ================================================================== #
    # Async API                                                          #
    # ================================================================== #

    async def asearch(
        self,
        base: str,
        scope: int,
        filterstr: str = '(objectClass=*)',
        attrlist: list[str] | None = None,
        serverctrls: list[RequestControl] | None = None,
        clientctrls: list[RequestControl] | None = None,
        timeout: int = -1,
        sizelimit: int = 0,
    ) -> tuple[int, list[tuple[str, dict]], list[RequestControl]]:
        self._before_async_request()
        msgid = self._conn.search_ext(
            base, scope, filterstr,
            attrlist=attrlist,
            serverctrls=serverctrls,
            clientctrls=clientctrls,
            timeout=timeout,
            sizelimit=sizelimit,
        )
        return await self._await_msgid(msgid)

    async def aadd(
        self,
        dn: str,
        modlist: list[tuple[str, Any]],
        serverctrls: list[RequestControl] | None = None,
        clientctrls: list[RequestControl] | None = None,
    ) -> tuple[int, list, list[RequestControl]]:
        self._before_async_request()
        msgid = self._conn.add_ext(
            dn, modlist, serverctrls=serverctrls, clientctrls=clientctrls
        )
        return await self._await_msgid(msgid)

    async def amodify(
        self,
        dn: str,
        modlist: list[tuple[int, str, Any]],
        serverctrls: list[RequestControl] | None = None,
        clientctrls: list[RequestControl] | None = None,
    ) -> tuple[int, list, list[RequestControl]]:
        self._before_async_request()
        msgid = self._conn.modify_ext(
            dn, modlist, serverctrls=serverctrls, clientctrls=clientctrls
        )
        return await self._await_msgid(msgid)

    async def adelete(
        self,
        dn: str,
        serverctrls: list[RequestControl] | None = None,
        clientctrls: list[RequestControl] | None = None,
    ) -> tuple[int, list, list[RequestControl]]:
        self._before_async_request()
        msgid = self._conn.delete_ext(
            dn, serverctrls=serverctrls, clientctrls=clientctrls
        )
        return await self._await_msgid(msgid)

    async def arename(
        self,
        dn: str,
        newrdn: str,
        newsuperior: str | None = None,
        delold: int = 1,
        serverctrls: list[RequestControl] | None = None,
        clientctrls: list[RequestControl] | None = None,
    ) -> tuple[int, list, list[RequestControl]]:
        self._before_async_request()
        msgid = self._conn.rename(
            dn, newrdn, newsuperior, delold,
            serverctrls=serverctrls, clientctrls=clientctrls,
        )
        return await self._await_msgid(msgid)

    async def abind(
        self,
        bind_dn: str,
        bind_pw: str,
    ) -> tuple[int, list, list[RequestControl]]:
        self._before_async_request()
        msgid = self._conn.simple_bind(bind_dn, bind_pw)
        return await self._await_msgid(msgid)

    async def aclose(self) -> None:
        """Async close: unregister reader, fail outstanding waiters, unbind. Idempotent."""
        if self._closed:
            return
        self._closed = True
        self._unregister_reader()
        for fut in list(self._waiters.values()):
            if not fut.done():
                fut.cancel()
        self._waiters.clear()
        with contextlib.suppress(ldap.LDAPError):
            self._conn.unbind_s()

    # ------------------------------------------------------------------ #
    # Async internals                                                    #
    # ------------------------------------------------------------------ #

    def _before_async_request(self) -> None:
        if self._closed:
            raise ldap.LDAPError('LDAPClient is closed')
        if self._loop is None:
            raise RuntimeError(
                'LDAPClient was constructed without a loop; async methods unavailable'
            )

        # ReconnectLDAPObject may have reconnected behind our back (e.g. from
        # a sync ``*_s`` call elsewhere). Detect that and invalidate state.
        current_reconnects = getattr(self._conn, '_reconnects_done', self._reconnects_seen)
        if current_reconnects != self._reconnects_seen:
            self._handle_async_reconnect_detected(current_reconnects)

        self._ensure_reader_registered()

    def _handle_async_reconnect_detected(self, new_reconnects: int) -> None:
        delta = new_reconnects - self._reconnects_seen
        logger.info(
            'LDAPClient: detected %d reconnect(s); failing %d in-flight async waiter(s).',
            delta,
            len(self._waiters),
        )
        err = ConnectionResetError(
            f'LDAP connection reconnected ({delta} time(s)); '
            'in-flight async requests are invalid'
        )
        for fut in list(self._waiters.values()):
            if not fut.done():
                fut.set_exception(err)
        self._waiters.clear()
        self._reconnects_seen = new_reconnects
        # fd may have been replaced (even at the same number); force re-register.
        self._unregister_reader()

    def _ensure_reader_registered(self) -> None:
        try:
            fd = self._conn.fileno()
        except ldap.LDAPError as exc:
            logger.debug('LDAPClient: fileno() raised %r', exc)
            return
        if fd is None or fd < 0:
            return
        if self._registered_fd == fd:
            return
        if self._registered_fd is not None:
            self._unregister_reader()
        assert self._loop is not None  # checked in _before_async_request
        self._loop.add_reader(fd, self._on_readable)
        self._registered_fd = fd
        logger.debug('LDAPClient: registered async reader on fd=%d', fd)

    def _unregister_reader(self) -> None:
        if self._registered_fd is None or self._loop is None:
            return
        try:
            self._loop.remove_reader(self._registered_fd)
        except (ValueError, OSError) as exc:
            logger.debug(
                'LDAPClient: remove_reader(%d) raised %r', self._registered_fd, exc,
            )
        self._registered_fd = None

    def _on_readable(self) -> None:
        """Drain libldap's queue. Loops until ``result3`` reports nothing left."""
        while True:
            try:
                rtype, rdata, rmsgid, ctrls = self._conn.result3(
                    msgid=_RES_ANY, timeout=0
                )
            except ldap.LDAPError as exc:
                self._fail_all_waiters(exc)
                return
            if rtype is None:
                return
            fut = self._waiters.pop(rmsgid, None)
            if fut is None:
                logger.debug(
                    'LDAPClient: dropping result for unknown msgid=%s (rtype=%s)',
                    rmsgid, rtype,
                )
                continue
            if fut.done():
                continue
            fut.set_result((rtype, rdata, ctrls))

    def _fail_all_waiters(self, exc: BaseException) -> None:
        if not self._waiters:
            return
        logger.warning(
            'LDAPClient: failing %d async waiter(s) due to %s',
            len(self._waiters),
            type(exc).__name__,
        )
        for fut in list(self._waiters.values()):
            if not fut.done():
                fut.set_exception(exc)
        self._waiters.clear()

    async def _await_msgid(
        self, msgid: int
    ) -> tuple[int, list, list[RequestControl]]:
        assert self._loop is not None
        fut: asyncio.Future = self._loop.create_future()
        self._waiters[msgid] = fut
        try:
            return await fut
        except asyncio.CancelledError:
            with contextlib.suppress(ldap.LDAPError):
                self._conn.abandon(msgid)
            self._waiters.pop(msgid, None)
            raise
        except BaseException:
            self._waiters.pop(msgid, None)
            raise
