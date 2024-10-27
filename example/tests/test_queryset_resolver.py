from example.models import LDAPUser
from .base import LDAPTestCase, get_new_ldap_search


class QueryResolverTestCase(LDAPTestCase):
    """
    TODO: Implement the following test cases:
    --- Basic ---
    X LDAPUser.objects.all()
    LDAPUser.objects.all().exists()
    X LDAPUser.objects.filter(uid='test')
    X LDAPUser.objects.filter(uid__lookup='test')
    X LDAPUser.objects.filter(uid__in=['test1', 'test2'])
    LDAPUser.objects.filter(uid__datetimelookup__transform='test') - optional (see comment in features.py)
    X LDAPUser.objects.filter(cn__contains='test').exclude(uid='specific_user')

    --- Hidden DN Field handling ---
    LDAPUser.objects.get(dn='uid=admin,dc=example,dc=com').dn

    --- Ordering ---
    X LDAPUser.objects.all().order_by('uid')

    --- Values ---
    X LDAPUser.objects.all().values('uid', 'cn')

    --- Aggregation ---
    LDAPUser.objects.all().count()
    LDAPUser.objects.aggregate(Count('uid'))

    --- Annotation ---
    LDAPUser.objects.annotate(num_uids=Count('uid'))

    --- Q queries ---
    LDAPUser.objects.filter(Q(uid='test') & Q(uid='test2'))
    LDAPUser.objects.filter(Q(uid='test') | Q(uid='test2'))
    LDAPUser.objects.filter(~Q(uid='test'))
    LDAPUser.objects.filter(Q(uid='test') & ~Q(uid='test2'))
    LDAPUser.objects.filter(Q(uid='test') | ~Q(uid='test2'))

    --- Deferred fields ---
    LDAPUser.objects.defer('cn').get(uid='test').cn

    --- Renaming ---
    u = LDAPUser.objects.get(uid='test'); u.uid = 'test_renamed'; u.save()
    """

    def test_ldapuser_all(self):
        queryset = LDAPUser.objects.all().order_by()
        expected_ldap_search = get_new_ldap_search()
        self.assertLDAPSearchIsEqual(queryset, expected_ldap_search)

    def test_ldapuser_filter_exclude(self):
        queryset = LDAPUser.objects.filter(name='User').exclude(username='admin', name='OtherUser').order_by()
        expected_ldap_search = get_new_ldap_search(filterstr='(&(cn=User)(!(&(cn=OtherUser)(uid=admin))))')
        self.assertLDAPSearchIsEqual(queryset, expected_ldap_search)

    def test_ldapuser_filter_lookup_contains(self):
        queryset = LDAPUser.objects.filter(name__contains='User').order_by()
        expected_ldap_search = get_new_ldap_search(filterstr='(cn=*User*)')
        self.assertLDAPSearchIsEqual(queryset, expected_ldap_search)

    def test_ldapuser_filter_lookup_in(self):
        queryset = LDAPUser.objects.filter(name__in=['User1', 'User2']).order_by()
        expected_ldap_search = get_new_ldap_search(filterstr='(|(cn=User1)(cn=User2))')
        self.assertLDAPSearchIsEqual(queryset, expected_ldap_search)

    def test_ldapuser_order_by(self):
        queryset = LDAPUser.objects.all().order_by('name')
        expected_ldap_search = get_new_ldap_search(ordering_rules=[('cn', 'caseIgnoreOrderingMatch')])
        self.assertLDAPSearchIsEqual(queryset, expected_ldap_search)

    def test_ldapuser_order_by_reverse(self):
        queryset = LDAPUser.objects.all().order_by('-name')
        expected_ldap_search = get_new_ldap_search(ordering_rules=[('-cn', 'caseIgnoreOrderingMatch')])
        self.assertLDAPSearchIsEqual(queryset, expected_ldap_search)

    def test_ldapuser_slicing_from(self):
        queryset = LDAPUser.objects.all().order_by()[10:]
        expected_ldap_search = get_new_ldap_search(offset=10)
        self.assertLDAPSearchIsEqual(queryset, expected_ldap_search)

    def test_ldapuser_slicing_to(self):
        queryset = LDAPUser.objects.all().order_by()[:10]
        expected_ldap_search = get_new_ldap_search(limit=10)
        self.assertLDAPSearchIsEqual(queryset, expected_ldap_search)

    def test_ldapuser_slicing_from_to(self):
        queryset = LDAPUser.objects.all().order_by()[10:20]
        expected_ldap_search = get_new_ldap_search(limit=10, offset=10)
        self.assertLDAPSearchIsEqual(queryset, expected_ldap_search)

    def test_ldapuser_values(self):
        queryset = LDAPUser.objects.all().order_by().values('username')
        expected_ldap_search = get_new_ldap_search(attrlist=['uid'])
        self.assertLDAPSearchIsEqual(queryset, expected_ldap_search)
        self.assertTrue(queryset)
