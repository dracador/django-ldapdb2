"""
Example views demonstrating ``django-ldapdb2``'s sync and async ORM paths.

Run the example app under an ASGI server (e.g. ``uvicorn example.asgi:application``)
to see the async views in action; under ``runserver`` async views still work,
but ``runserver`` won't run them on the event loop the same way an ASGI
server would.

The two views ``users_sync`` and ``users_async`` issue the *same* LDAP queries
against the test directory and return the *same* response shape — the only
difference is the I/O dispatch. Compare the ``elapsed_ms`` field to see the
``asyncio.gather`` benefit when the LDAP server has any non-zero latency.
"""

from __future__ import annotations

import asyncio
import time

from django.http import JsonResponse

from example.models import LDAPUser

USERNAMES_TO_FETCH = ['admin', 'user1', 'user2']


def _serialize(user: LDAPUser) -> dict:
    return {
        'dn': user.dn,
        'username': user.username,
        'name': user.name,
        'last_name': user.last_name,
        'mail': user.mail,
    }


def users_sync(_request):
    """Sync fan-out: N sequential ``LDAPUser.objects.get(...)`` calls.

    Wall time = sum of N round-trips (plus per-call Python overhead).
    """
    t0 = time.perf_counter()
    users = []
    for username in USERNAMES_TO_FETCH:
        try:
            users.append(_serialize(LDAPUser.objects.get(username=username)))
        except LDAPUser.DoesNotExist:
            users.append({'username': username, 'error': 'not_found'})
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    return JsonResponse({
        'mode': 'sync',
        'count': len(users),
        'elapsed_ms': round(elapsed_ms, 3),
        'users': users,
    })


async def users_async(_request):
    """Async fan-out: ``asyncio.gather`` over ``LDAPUser.objects.aget(...)``.

    All N searches dispatch on one LDAP connection, multiplexed by msgid.
    Wall time ≈ max of N round-trips, not sum. The benefit grows with the
    server's latency; on a localhost test server the difference is small
    because per-call Python overhead dominates.
    """
    t0 = time.perf_counter()

    async def fetch_one(username: str) -> dict:
        try:
            return _serialize(await LDAPUser.objects.aget(username=username))
        except LDAPUser.DoesNotExist:
            return {'username': username, 'error': 'not_found'}

    users = await asyncio.gather(*[fetch_one(u) for u in USERNAMES_TO_FETCH])
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    return JsonResponse({
        'mode': 'async',
        'count': len(users),
        'elapsed_ms': round(elapsed_ms, 3),
        'users': list(users),
    })
