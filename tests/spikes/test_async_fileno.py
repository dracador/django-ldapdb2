"""
Phase 0.1 spike: Verify LDAPObject.fileno() returns a usable socket fd.

Runnable script (not a pytest/unittest test). Prints findings.

Tasks covered:
    1. fileno() returns an int.
    2. Cross-check against ldap.OPT_DESC.
    3. os.read() on the fd should not be safe / not yield application data
       (libldap owns the buffered read; we only want it for select/epoll).
    4. fileno after start_tls_s() — skipped if test server has no TLS configured.
    5. fileno across ReconnectLDAPObject reconnect — kills/restarts the docker
       container to force libldap to reopen the socket.

Run from project root with the venv activated:
    .venv/bin/python tests/spikes/test_async_fileno.py
"""

from __future__ import annotations

import select
import socket
import subprocess
import sys
import time

import ldap
from ldap.ldapobject import ReconnectLDAPObject

URI = 'ldap://localhost'
BIND_DN = 'uid=admin,ou=Users,dc=example,dc=org'
BIND_PW = 'adminpassword'
DOCKER_CONTAINER = 'django-ldapdb2-openldap'
DOCKER_COMPOSE_FILE = 'tests/openldap-server/docker-compose.yaml'


def _new_conn() -> ReconnectLDAPObject:
    conn = ReconnectLDAPObject(uri=URI, retry_max=3, retry_delay=0.5, bytes_mode=False)
    # Order matters: REQUIRE_CERT first, NEWCTX=0 last to apply.
    conn.set_option(ldap.OPT_X_TLS_REQUIRE_CERT, ldap.OPT_X_TLS_NEVER)
    conn.set_option(ldap.OPT_X_TLS_NEWCTX, 0)
    conn.simple_bind_s(BIND_DN, BIND_PW)
    return conn


def _run(cmd: list[str]) -> None:
    print(f'    $ {" ".join(cmd)}')
    subprocess.run(cmd, check=True, capture_output=True)


def step_1_fileno_returns_int(conn: ReconnectLDAPObject) -> int:
    fd = conn.fileno()
    print(f'  fileno() -> {fd} (type {type(fd).__name__})')
    assert isinstance(fd, int) and fd >= 0, 'fileno() must return a non-negative int'
    return fd


def step_2_cross_check_opt_desc(conn: ReconnectLDAPObject, fd: int) -> None:
    try:
        opt_desc = conn.get_option(ldap.OPT_DESC)
        print(f'  OPT_DESC -> {opt_desc}')
        if opt_desc != fd:
            print(f'  NOTE: OPT_DESC ({opt_desc}) != fileno() ({fd}) — informational only')
        else:
            print('  OPT_DESC matches fileno()')
    except (ldap.LDAPError, ValueError) as exc:
        print(f'  OPT_DESC not exposed / unsupported: {exc!r} — skip cross-check')


def step_3_os_read_unsafe(fd: int) -> None:
    # The fd should be a real socket. We can register it with select; we should
    # NOT try to consume bytes via os.read because libldap owns the read buffer.
    # Demonstrate that:
    #   - select.select returns timely (no events when idle)
    #   - the fd is a SOCK_STREAM
    sock = socket.fromfd(fd, socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock_type = sock.getsockopt(socket.SOL_SOCKET, socket.SO_TYPE)
        print(f'  socket SO_TYPE -> {sock_type} (SOCK_STREAM={socket.SOCK_STREAM})')
    finally:
        sock.detach()  # do not close — libldap owns the underlying socket

    # select with 0 timeout — should not block, no readable data when idle
    rlist, _, _ = select.select([fd], [], [], 0)
    print(f'  select.select(timeout=0) -> readable={rlist}')

    # We deliberately do NOT call os.read(fd, ...) here. Even one byte stolen
    # from the kernel buffer would corrupt libldap's framing. The point of
    # exposing fileno() is for the event loop to learn "data ready", and then
    # call into libldap (via result3) to actually consume.
    print('  (skipped os.read — would corrupt libldap framing)')


def step_4_fileno_after_starttls(conn: ReconnectLDAPObject, fd_before: int) -> None:
    print('  start_tls_s ...')
    try:
        conn.start_tls_s()
    except ldap.LDAPError as exc:
        print(f'  start_tls_s FAILED: {type(exc).__name__}: {exc}')
        print('  -> test LDAP server does not appear to have TLS configured.')
        print('  -> TLS validation must be done separately (see spike report).')
        return
    fd_after = conn.fileno()
    print(f'  fileno before TLS = {fd_before}, after TLS = {fd_after}')
    if fd_after != fd_before:
        print('  NOTE: fd changed after start_tls — async wrapper MUST re-register reader.')
    else:
        print('  fd unchanged after StartTLS — no re-registration needed for the upgrade.')

    # RFC 4513: bind state is reset after StartTLS. Re-bind, then verify search works.
    conn.simple_bind_s(BIND_DN, BIND_PW)
    results = conn.search_s('dc=example,dc=org', ldap.SCOPE_BASE, '(objectClass=*)', attrlist=['dn'])
    print(f'  search over TLS returned {len(results)} entry/entries — TLS plumbing OK')


def step_5_fileno_after_reconnect(conn: ReconnectLDAPObject, fd_before: int) -> None:
    reconnects_before = getattr(conn, '_reconnects_done', None)
    # Force a reconnect by restarting the docker container.
    print('  forcing reconnect by restarting docker container...')
    _run(['docker', 'restart', '-t', '0', DOCKER_CONTAINER])
    # Wait for the LDAP port to be ready again.
    deadline = time.time() + 30
    while time.time() < deadline:
        try:
            with socket.create_connection(('localhost', 389), timeout=1):
                break
        except OSError:
            time.sleep(0.2)
    else:
        print('  ERROR: server did not come back up within 30s')
        return

    # ReconnectLDAPObject reconnects on next operation — issue a search.
    print('  issuing search to trigger reconnect...')
    try:
        conn.search_s('dc=example,dc=org', ldap.SCOPE_BASE, '(objectClass=*)', attrlist=['dn'])
    except ldap.LDAPError as exc:
        print(f'  search after restart raised {type(exc).__name__}: {exc}')

    fd_after = conn.fileno()
    reconnects_after = getattr(conn, '_reconnects_done', None)
    print(f'  fileno before reconnect = {fd_before}, after reconnect = {fd_after}')
    print(f'  _reconnects_done before = {reconnects_before}, after = {reconnects_after}')

    if reconnects_after is not None and reconnects_before is not None and reconnects_after > reconnects_before:
        print('  CONFIRMED: ReconnectLDAPObject performed a reconnect.')
        if fd_after == fd_before:
            print('  fd number happens to be the same (Linux fd-reuse) but the underlying')
            print('  socket has been replaced. The async wrapper MUST still re-register the')
            print('  reader, because kernel epoll bound the registration to the old socket')
            print('  object, and that registration is dropped when the old fd was closed.')
        else:
            print('  fd number changed — async wrapper must obviously re-register.')
    else:
        print('  WARNING: no reconnect counter advance detected; reconnect may not have happened')


def main() -> int:
    print('=== Phase 0.1: fileno() validation spike ===')
    print()
    print('Step 1: fileno() returns an int')
    conn = _new_conn()
    fd_before = step_1_fileno_returns_int(conn)
    print()

    print('Step 2: cross-check OPT_DESC')
    step_2_cross_check_opt_desc(conn, fd_before)
    print()

    print('Step 3: fd is a socket; do not consume via os.read')
    step_3_os_read_unsafe(fd_before)
    print()

    print('Step 4: fileno after start_tls_s()')
    step_4_fileno_after_starttls(conn, fd_before)
    print()

    print('Step 5: fileno across ReconnectLDAPObject reconnect')
    # Use a fresh connection — start_tls may have left the previous one in a
    # state we do not want to perturb with a server restart.
    fresh = _new_conn()
    step_5_fileno_after_reconnect(fresh, fresh.fileno())
    print()

    print('=== spike 0.1 complete ===')
    return 0


if __name__ == '__main__':
    sys.exit(main())
