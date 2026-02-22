from django.core.exceptions import ImproperlyConfigured
from django.test import TestCase, override_settings
from ldapdb.router import Router


class RouterTests(TestCase):
    @override_settings(DATABASES={'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': ':memory:'}})
    def test_default_database_raises_improperly_configured_when_no_ldap_db(self):
        router = Router()
        with self.assertRaises(ImproperlyConfigured):
            _ = router.default_database
