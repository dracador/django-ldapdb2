from example.models import LDAPUser
from .base import LDAPTestCase, get_new_ldap_search
from .constants import TEST_LDAP_USER_1


class QueryResolverTestCase(LDAPTestCase):
    """
    TODO: Implement the following test cases:
    --- Basic ---
    X LDAPUser.objects.all()
    X LDAPUser.objects.get(username='user1')
    X LDAPUser.objects.all().exists()
    X LDAPUser.objects.filter(uid='test')
    X LDAPUser.objects.filter(uid__lookup='test')
    X LDAPUser.objects.filter(uid__in=['test1', 'test2'])
    LDAPUser.objects.filter(uid__datetimelookup__transform='test') - optional (see comment in features.py)
    X LDAPUser.objects.filter(cn__contains='test').exclude(uid='specific_user')

    --- Hidden DN Field handling ---
    LDAPUser.objects.get(dn='uid=admin,dc=example,dc=com').dn

    --- Ordering ---
    X LDAPUser.objects.all().order_by('uid')
    LDAPUser.objects.all().order_by('dn') - optional, since we'd have to implement custom sorting for this

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

    @staticmethod
    def _get_user_1_object():
        return LDAPUser.objects.get(username=TEST_LDAP_USER_1.username)

    def test_ldapuser_all(self):
        queryset = LDAPUser.objects.all()
        expected_ldap_search = get_new_ldap_search()
        self.assertLDAPSearchIsEqual(queryset, expected_ldap_search)

    def test_ldapuser_get(self):
        obj = self._get_user_1_object()
        self.assertLDAPModelObjectsAreEqual(TEST_LDAP_USER_1, obj)

    def test_ldapuser_exists(self):
        self.assertTrue(LDAPUser.objects.all().exists())

    def test_ldapuser_filter_exclude(self):
        queryset = LDAPUser.objects.filter(name='User').exclude(username='admin', name='OtherUser')
        expected_ldap_search = get_new_ldap_search(filterstr='(&(cn=User)(!(&(cn=OtherUser)(uid=admin))))')
        self.assertLDAPSearchIsEqual(queryset, expected_ldap_search)

    def test_ldapuser_filter_lookup_contains(self):
        queryset = LDAPUser.objects.filter(name__contains='User')
        expected_ldap_search = get_new_ldap_search(filterstr='(cn=*User*)')
        self.assertLDAPSearchIsEqual(queryset, expected_ldap_search)

    def test_ldapuser_filter_lookup_in(self):
        queryset = LDAPUser.objects.filter(name__in=['User1', 'User2'])
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
        queryset = LDAPUser.objects.all()[10:]
        expected_ldap_search = get_new_ldap_search(offset=10)
        self.assertLDAPSearchIsEqual(queryset, expected_ldap_search)

    def test_ldapuser_slicing_to(self):
        queryset = LDAPUser.objects.all()[:10]
        expected_ldap_search = get_new_ldap_search(limit=10)
        self.assertLDAPSearchIsEqual(queryset, expected_ldap_search)

    def test_ldapuser_slicing_from_to(self):
        queryset = LDAPUser.objects.all()[10:20]
        expected_ldap_search = get_new_ldap_search(limit=10, offset=10)
        self.assertLDAPSearchIsEqual(queryset, expected_ldap_search)

    def test_ldapuser_values(self):
        queryset = LDAPUser.objects.all().values('username')
        expected_ldap_search = get_new_ldap_search(attrlist=['uid'])
        self.assertLDAPSearchIsEqual(queryset, expected_ldap_search)
        self.assertTrue(queryset)

    def test_model_field_order(self):
        """
        This test is supposed to be run a lot of times to ensure the order of fields is correct

        Why this might even be an issue:
        Normally, Django requires the attributes returned by the Cursor via Cursor.description to be in the same order
        as the fields in the model as returned by model._meta.get_fields().
        This is not the case with LDAP, since we can't guarantee the order of attributes in the search results,
        especially since "dn" behaves differently than other attributes.

        We'll have to run this a lot of times, since the field order might be correct by chance,
        even if the implementation is faulty.
        """

        for _ in range(200):
            self.test_ldapuser_get()

    def test_model_field_order_with_specific_fields(self):
        """See test_model_field_order()"""

        # The order of these fields should *not* be the one from model._meta.get_fields()
        unordered_fields_subset = ['mail', 'name', 'username', 'dn']

        for _ in range(200):
            # FIXME: This test currently fails!
            #  {
            #      "mail": "uid=user1,ou=Users,dc=example,dc=org",
            #      "name": "user1",
            #      "username": "User One",
            #      "dn": "user.one@example.org"
            #  }
            obj = LDAPUser.objects.filter(username=TEST_LDAP_USER_1.username).values(*unordered_fields_subset).first()
            self.assertLDAPModelObjectsAreEqual(TEST_LDAP_USER_1, obj, fields=unordered_fields_subset)
