from collections import namedtuple

from example.models import LDAPUser
from .base import LDAPTestCase, get_new_ldap_search
from .constants import TEST_LDAP_ADMIN_USER_1, TEST_LDAP_AVAILABLE_USERS, TEST_LDAP_GROUP_1, TEST_LDAP_USER_1


class SQLCompilerTestCase(LDAPTestCase):
    def test_ldapgroup_get(self):
        obj = self._get_group_1_object()
        self.assertLDAPModelObjectsAreEqual(TEST_LDAP_GROUP_1, obj)

    def test_ldapuser_all(self):
        queryset = LDAPUser.objects.all()
        expected_ldap_search = get_new_ldap_search()
        self.assertLDAPSearchIsEqual(queryset, expected_ldap_search)

    def test_queryset_none(self):
        obj = self._get_user_1_object()
        self.assertFalse(obj in LDAPUser.objects.none())
        self.assertFalse(bool(LDAPUser.objects.none().values()))

    def test_ldapuser_get(self):
        obj = self._get_user_1_object()
        self.assertLDAPModelObjectsAreEqual(TEST_LDAP_USER_1, obj)

    def test_ldapuser_exists(self):
        self.assertTrue(LDAPUser.objects.all().exists())

    def test_ldapuser_count(self):
        # Use assertGreaterEqual because other tests might add more users
        self.assertGreaterEqual(LDAPUser.objects.all().count(), len(TEST_LDAP_AVAILABLE_USERS))

    def test_ldapuser_filter_count(self):
        self.assertEqual(LDAPUser.objects.filter(username__contains='admin').count(), 1)

    def test_ldapuser_len_all_equals_count(self):
        self.assertEqual(LDAPUser.objects.all().count(), len(LDAPUser.objects.all()))

    def test_exists_after_filter(self):
        self.assertTrue(LDAPUser.objects.filter(username=TEST_LDAP_USER_1.username).exists())
        self.assertFalse(LDAPUser.objects.filter(username='doesnotexist').exists())

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

    def test_ldapuser_filter_lookup_isnull(self):
        queryset = LDAPUser.objects.filter(is_active__isnull=True)
        expected_ldap_search = get_new_ldap_search(filterstr='(!(x-user-isActive=*))')
        self.assertLDAPSearchIsEqual(queryset, expected_ldap_search)

    def test_ldapuser_filter_injection(self):
        queryset = LDAPUser.objects.filter(username='*)(uid=*')
        expected_ldap_search = get_new_ldap_search(filterstr=r'(uid=\2a\29\28uid=\2a)')
        self.assertLDAPSearchIsEqual(queryset, expected_ldap_search)

    def test_ldapuser_filter_only(self):
        objs = LDAPUser.objects.filter(username=TEST_LDAP_USER_1.username).only('name')
        obj = objs.first()
        self.assertEqual(TEST_LDAP_USER_1.name, obj.name)
        self.assertEqual(TEST_LDAP_USER_1.last_name, obj.last_name)

    def test_ldapuser_filter_only_values(self):
        objs = LDAPUser.objects.filter(username=TEST_LDAP_USER_1.username).only('username').values('name')
        self.assertEqual([{'name': TEST_LDAP_USER_1.name}], list(objs))

    def test_ldapuser_filter_only_values_list(self):
        objs = LDAPUser.objects.filter(username=TEST_LDAP_USER_1.username).only('username').values_list('name')
        self.assertEqual([(TEST_LDAP_USER_1.name,)], list(objs))

    def test_ldapuser_filter_only_values_list_flat(self):
        objs = (
            LDAPUser.objects.filter(username=TEST_LDAP_USER_1.username).only('username').values_list('name', flat=True)
        )
        self.assertEqual([TEST_LDAP_USER_1.name], list(objs))

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
        queryset = self.get_testuser_objects().values('username')
        expected_ldap_search = get_new_ldap_search(attrlist=['uid'], filterstr='(|(uid=admin)(uid=user1)(uid=user2))')
        self.assertLDAPSearchIsEqual(queryset, expected_ldap_search)
        self.assertQuerySetEqual(
            queryset,
            [{'username': u.username} for u in TEST_LDAP_AVAILABLE_USERS],
        )

    def test_ldapuser_values_list(self):
        queryset = self.get_testuser_objects().values_list('name')
        expected_ldap_search = get_new_ldap_search(attrlist=['cn'], filterstr='(|(uid=admin)(uid=user1)(uid=user2))')
        self.assertLDAPSearchIsEqual(queryset, expected_ldap_search)
        self.assertQuerySetEqual(
            queryset,
            [(u.name,) for u in TEST_LDAP_AVAILABLE_USERS],
        )

    def test_ldapuser_values_list_flat(self):
        queryset = self.get_testuser_objects().values_list('name', flat=True)
        expected_ldap_search = get_new_ldap_search(attrlist=['cn'], filterstr='(|(uid=admin)(uid=user1)(uid=user2))')
        self.assertLDAPSearchIsEqual(queryset, expected_ldap_search)
        self.assertQuerySetEqual(
            queryset,
            [u.name for u in TEST_LDAP_AVAILABLE_USERS],
        )

    def test_ldapuser_values_list_named(self):
        values = ['name']
        queryset = self.get_testuser_objects().values_list(*values, named=True)
        expected_ldap_search = get_new_ldap_search(attrlist=['cn'], filterstr='(|(uid=admin)(uid=user1)(uid=user2))')
        self.assertLDAPSearchIsEqual(queryset, expected_ldap_search)
        row_tuple = namedtuple('Row', values)
        self.assertQuerySetEqual(
            queryset,
            [row_tuple(u.name) for u in TEST_LDAP_AVAILABLE_USERS],
        )

    def test_ldapuser_order_first(self):
        obj = self.get_testuser_objects().order_by('username').first()
        self.assertLDAPModelObjectsAreEqual(TEST_LDAP_ADMIN_USER_1, obj)

    def test_ldapuser_order_last(self):
        obj = self.get_testuser_objects().order_by('username').last()
        self.assertLDAPModelObjectsAreEqual(TEST_LDAP_AVAILABLE_USERS[-1], obj)

    def test_ldapuser_index_access(self):
        testuser_usernames = [u.username for u in TEST_LDAP_AVAILABLE_USERS]
        obj = LDAPUser.objects.filter(username__in=testuser_usernames).order_by('username')[1]
        self.assertLDAPModelObjectsAreEqual(TEST_LDAP_USER_1, obj)

    def test_ldapuser_index_access_oob(self):
        with self.assertRaises(IndexError):
            _ = LDAPUser.objects.all().order_by('username')[9999999]

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
            obj = LDAPUser.objects.filter(username=TEST_LDAP_USER_1.username).values(*unordered_fields_subset).first()
            self.assertLDAPModelObjectsAreEqual(TEST_LDAP_USER_1, obj, fields=unordered_fields_subset)

    def test_refresh_from_db(self):
        obj = self._get_user_1_object()
        obj.name = 'New name'  # Note: Setting the primary key to something else will result in a DoesNotExist error
        obj.refresh_from_db()
        self.assertLDAPModelObjectsAreEqual(TEST_LDAP_USER_1, obj)

    def test_integer_field_in_lookup_with_integer_values(self):
        results = list(LDAPUser.objects.filter(department_number__in=[1]))
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].username, TEST_LDAP_USER_1.username)

    def test_integer_field_in_lookup_empty_list(self):
        results = list(LDAPUser.objects.filter(department_number__in=[]))
        self.assertEqual(results, [])

    def test_integer_field_scalar_lookup(self):
        results = list(LDAPUser.objects.filter(department_number=1))
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].username, TEST_LDAP_USER_1.username)
