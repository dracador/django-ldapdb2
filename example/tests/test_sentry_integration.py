import unittest

from example.models import LDAPUser
from example.tests.base import LDAPTestCase

try:
    import sentry_sdk
    from sentry_sdk.integrations.django import DjangoIntegration

    SENTRY_AVAILABLE = True
except ImportError:
    SENTRY_AVAILABLE = False


class TestSentryIntegration(LDAPTestCase):
    @unittest.skipUnless(SENTRY_AVAILABLE, 'sentry-sdk is not installed for this env')
    def test_query_with_sentry_enabled(self):
        sentry_sdk.init(
            dsn='http://public@example.com/1',
            integrations=[DjangoIntegration()],
            traces_sample_rate=1.0,
            enable_tracing=True,
            debug=True,
        )

        # This query would raise a EmptyResultSet exception if LDAPQuery.sql_with_params() is called somewhere in sentry
        list(LDAPUser.objects.filter(entry_dn__in=[]))
