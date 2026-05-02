"""
Smoke tests for the demo views in ``example/views.py``.

Each test fires the view via Django's test client and confirms the response
shape. The sync and async views should return the *same* set of users
(modulo iteration order, which they don't guarantee).
"""

from __future__ import annotations

import json

from django.test import Client, override_settings

from .base import LDAPTestCase
from .constants import TEST_LDAP_AVAILABLE_USERS


@override_settings(ALLOWED_HOSTS=['*'])
class ExampleViewTests(LDAPTestCase):
    """Sync test class — exercises both the sync and async views via the test
    client. Django's test client handles the async view by running it on its
    own loop internally."""

    def setUp(self) -> None:
        super().setUp()
        self.client = Client()

    def _expected_usernames(self) -> set[str]:
        return {u.username for u in TEST_LDAP_AVAILABLE_USERS}

    def test_users_sync(self) -> None:
        response = self.client.get('/users/sync/')
        self.assertEqual(response.status_code, 200)
        body = json.loads(response.content)
        self.assertEqual(body['mode'], 'sync')
        self.assertEqual(body['count'], 3)
        usernames = {u['username'] for u in body['users']}
        self.assertEqual(usernames, self._expected_usernames())
        self.assertGreaterEqual(body['elapsed_ms'], 0)

    def test_users_async(self) -> None:
        response = self.client.get('/users/async/')
        self.assertEqual(response.status_code, 200)
        body = json.loads(response.content)
        self.assertEqual(body['mode'], 'async')
        self.assertEqual(body['count'], 3)
        usernames = {u['username'] for u in body['users']}
        self.assertEqual(usernames, self._expected_usernames())
        self.assertGreaterEqual(body['elapsed_ms'], 0)

    def test_sync_and_async_return_same_user_set(self) -> None:
        sync_body = json.loads(self.client.get('/users/sync/').content)
        async_body = json.loads(self.client.get('/users/async/').content)
        sync_users = {u['username']: u for u in sync_body['users']}
        async_users = {u['username']: u for u in async_body['users']}
        self.assertEqual(sync_users.keys(), async_users.keys())
        for username, sync_user in sync_users.items():
            self.assertEqual(sync_user, async_users[username])
