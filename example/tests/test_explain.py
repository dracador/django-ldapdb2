from unittest import mock

from django.db import connections
from django.test import SimpleTestCase
from ldapdb.backends.ldap import LDAPSearch, LDAPSearchControlType
from ldapdb.backends.ldap.explain import render_ldapsearch

from example.models import LDAPUser
from .base import LDAPTestCase
from .constants import TEST_LDAP_USER_1


def _get_sliced_qs():
    return LDAPUser.objects.filter(username__startswith='user').order_by('username').values('username', 'mail')[:3]


def _disable_features(*feature_names):
    features = connections['ldap'].features
    return mock.patch.multiple(features, **dict.fromkeys(feature_names, False))


class ExplainTextTestCase(LDAPTestCase):
    def test_ctrls_in_qs(self):
        self.assertEqual(
            _get_sliced_qs().explain(),
            'SEARCH ou=Users,dc=example,dc=org\n'
            '  scope:      subtree\n'
            '  filter:     (&(objectClass=inetOrgPerson)(uid=user*))\n'
            '  attributes: uid, mail\n'
            '  controls:   server-side sort (uid:caseIgnoreOrderingMatch), VLV offset=1 count=3\n'
            '  in Python:  nothing',
        )

    def test_missing_vlv_control_on_unsliced_qs(self):
        explanation = LDAPUser.objects.order_by('-username').values('username').explain()
        self.assertIn('  controls:   server-side sort (-uid:caseIgnoreOrderingMatch)\n', explanation)

    def test_filtered_dn_as_base_scope(self):
        explanation = LDAPUser.objects.filter(dn=TEST_LDAP_USER_1.dn).values('username').explain()
        self.assertTrue(
            explanation.startswith('SEARCH uid=user1,ou=Users,dc=example,dc=org\n  scope:      base\n'),
            explanation,
        )

    def test_disabled_sssvlv_uses_python_explain(self):
        with _disable_features('supports_sssvlv'):
            explanation = _get_sliced_qs().explain()
        self.assertTrue(
            explanation.endswith(
                '  controls:   simple paged results (page size 999)\n'
                '  in Python:  sort by uid (byte order), slice [0:3]'
            ),
            explanation,
        )

    def test_empty_ctrls(self):
        with _disable_features('supports_sssvlv', 'supports_simple_paged_results'):
            explanation = LDAPUser.objects.values('username').explain()
        self.assertTrue(
            explanation.endswith('  controls:   none\n  in Python:  sort by uid (byte order)'),
            explanation,
        )

    def test_reject_unknown_formatting(self):
        with self.assertRaises(ValueError):
            _get_sliced_qs().explain(format='xml')

    def test_disallow_analyze(self):
        with self.assertRaises(ValueError):
            _get_sliced_qs().explain(analyze=True)


class ExplainLDAPSearchTestCase(LDAPTestCase):
    def test_ldapsearch_formatting(self):
        self.assertEqual(
            _get_sliced_qs().explain(format='ldapsearch'),
            'ldapsearch -H ldap://localhost -x -D uid=admin,ou=Users,dc=example,dc=org -W \\\n'
            '  -b ou=Users,dc=example,dc=org -s sub \\\n'
            "  -E '!sss=uid:caseIgnoreOrderingMatch' -E '!vlv=0/2/1/0' \\\n"
            "  '(&(objectClass=inetOrgPerson)(uid=user*))' uid mail",
        )

    def test_non_sssvlv_python_comment(self):
        with _disable_features('supports_sssvlv'):
            explanation = _get_sliced_qs().explain(format='ldapsearch')
        self.assertEqual(
            explanation,
            'ldapsearch -H ldap://localhost -x -D uid=admin,ou=Users,dc=example,dc=org -W \\\n'
            '  -b ou=Users,dc=example,dc=org -s sub \\\n'
            "  -E '!pr=999/noprompt' \\\n"
            "  '(&(objectClass=inetOrgPerson)(uid=user*))' uid mail\n"
            '# in Python afterwards: sort by uid (byte order), slice [0:3]',
        )


class RenderLDAPSearchTestCase(SimpleTestCase):
    def test_anon_binds(self):
        search = LDAPSearch(
            base='dc=example,dc=org',
            attrlist=['cn'],
            control_type=LDAPSearchControlType.NO_CONTROL,
        )
        lines = render_ldapsearch(search, page_size=1000, uri='ldap://localhost', bind_dn='')
        self.assertEqual(
            lines,
            ["ldapsearch -H ldap://localhost -x \\\n  -b dc=example,dc=org -s sub \\\n  '(objectClass=*)' cn"],
        )
