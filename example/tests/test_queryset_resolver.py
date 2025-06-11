import ldap
from django.db.models import QuerySet
from django.test import TestCase
from ldapdb.backends.ldap import LDAPSearch

from example.models import LDAPUser


def queryset_to_ldap_search(queryset: QuerySet):
    sql_compiler = queryset.query.get_compiler(using=queryset.db)
    return sql_compiler.as_sql()[0]


def get_new_ldap_search(base=None, filterstr=None, attrlist=None, scope=None, order_by=None, ignore_base_filter=False):
    base_filter = LDAPUser.base_filter
    if base_filter and not ignore_base_filter:
        filterstr = f'(&{base_filter}{filterstr})' if filterstr else base_filter

    return LDAPSearch(
        base=base or 'ou=Users,dc=example,dc=org',
        filterstr=filterstr or LDAPUser.base_filter,
        attrlist=attrlist or [field.column for field in LDAPUser._meta.get_fields() if field.column != 'dn'],
        scope=scope or ldap.SCOPE_SUBTREE,
        order_by=order_by or [],
    )


class QueryResolverTestCase(TestCase):
    """
    TODO: Implement the following test cases:
    --- Basic ---
    LDAPUser.objects.all()
    LDAPGroup.objects.all()
    LDAPUser.objects.all().exists()
    LDAPUser.objects.filter(uid='test')
    LDAPUser.objects.filter(uid__lookup='test')
    LDAPUser.objects.filter(uid__in=['test1', 'test2'])
    LDAPUser.objects.filter(uid__datetimelookup__transform='test') - optional (see comment in features.py)
    LDAPUser.objects.filter(cn__contains='test').exclude(uid='specific_user')

    --- Hidden DN Field handling ---
    LDAPUser.objects.get(dn='uid=admin,dc=example,dc=com').dn

    --- Ordering ---
    LDAPUser.objects.all().order_by('uid')

    --- Values ---
    LDAPUser.objects.all().values('uid', 'cn')

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

    databases = ['ldap']

    def assertLDAPSearchIsEqual(self, queryset: QuerySet, expected_ldap_search: LDAPSearch):
        generated_ldap_search = queryset_to_ldap_search(queryset)
        self.assertIsNotNone(generated_ldap_search)
        self.assertIsInstance(generated_ldap_search, LDAPSearch)

        # Using .serialize() here allows assertEqual to provide a more detailed error message
        self.assertEqual(expected_ldap_search.serialize(), generated_ldap_search.serialize())

    def test_ldapuser_all(self):
        queryset = LDAPUser.objects.all().order_by()
        expected_ldap_search = get_new_ldap_search()
        self.assertLDAPSearchIsEqual(queryset, expected_ldap_search)

    def test_ldapuser_filter_exclude(self):
        queryset = LDAPUser.objects.filter(name='User').exclude(username='admin', name='OtherUser').order_by()
        expected_ldap_search = get_new_ldap_search(
            filterstr='(&(cn=User)(!(&(cn=OtherUser)(uid=admin))))'
        )
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
        expected_ldap_search = get_new_ldap_search(order_by=[('cn', 'caseIgnoreOrderingMatch')])
        self.assertLDAPSearchIsEqual(queryset, expected_ldap_search)

    def test_ldapuser_order_by_reverse(self):
        queryset = LDAPUser.objects.all().order_by('-name')
        expected_ldap_search = get_new_ldap_search(order_by=[('-cn', 'caseIgnoreOrderingMatch')])
        self.assertLDAPSearchIsEqual(queryset, expected_ldap_search)
