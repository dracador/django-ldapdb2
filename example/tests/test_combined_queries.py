from django.db import NotSupportedError

from example.models import LDAPAdminUser, LDAPUser
from .base import LDAPTestCase, get_new_ldap_search
from .constants import TEST_LDAP_USER_1, TEST_LDAP_USER_2

BASE_FILTER = LDAPUser.base_filter
USER_1 = f'(&{BASE_FILTER}(uid={TEST_LDAP_USER_1.username}))'
USER_2 = f'(&{BASE_FILTER}(uid={TEST_LDAP_USER_2.username}))'
BOTH_USERS = f'(&{BASE_FILTER}(|(uid={TEST_LDAP_USER_1.username})(uid={TEST_LDAP_USER_2.username})))'


class CombinedQueryFilterTestCase(LDAPTestCase):
    @staticmethod
    def _user_1_queryset():
        return LDAPUser.objects.filter(username=TEST_LDAP_USER_1.username)

    @staticmethod
    def _user_2_queryset():
        return LDAPUser.objects.filter(username=TEST_LDAP_USER_2.username)

    @staticmethod
    def _both_users_queryset():
        return LDAPUser.objects.filter(username__in=[TEST_LDAP_USER_1.username, TEST_LDAP_USER_2.username])

    def test_union_compiles_to_or_filter(self):
        queryset = self._user_1_queryset().union(self._user_2_queryset())
        expected = get_new_ldap_search(filterstr=f'(|{USER_1}{USER_2})', ignore_base_filter=True)
        self.assertLDAPSearchIsEqual(queryset, expected)

    def test_intersection_compiles_to_and_filter(self):
        queryset = self._both_users_queryset().intersection(self._user_1_queryset())
        expected = get_new_ldap_search(filterstr=f'(&{BOTH_USERS}{USER_1})', ignore_base_filter=True)
        self.assertLDAPSearchIsEqual(queryset, expected)

    def test_difference_compiles_to_and_not_filter(self):
        queryset = self._both_users_queryset().difference(self._user_2_queryset())
        expected = get_new_ldap_search(filterstr=f'(&{BOTH_USERS}(!{USER_2}))', ignore_base_filter=True)
        self.assertLDAPSearchIsEqual(queryset, expected)

    def test_union_of_three_branches(self):
        queryset = self._user_1_queryset().union(self._user_2_queryset(), self._user_1_queryset())
        expected = get_new_ldap_search(filterstr=f'(|{USER_1}{USER_2}{USER_1})', ignore_base_filter=True)
        self.assertLDAPSearchIsEqual(queryset, expected)

    def test_nested_union_recurses(self):
        queryset = self._user_1_queryset().union(self._user_2_queryset()).union(self._user_1_queryset())
        expected = get_new_ldap_search(filterstr=f'(|(|{USER_1}{USER_2}){USER_1})', ignore_base_filter=True)
        self.assertLDAPSearchIsEqual(queryset, expected)

    def test_outer_order_by_is_applied(self):
        # combined querysets order by a Ref to the select alias, not by the column itself
        queryset = self._user_1_queryset().union(self._user_2_queryset()).order_by('name')
        expected = get_new_ldap_search(
            filterstr=f'(|{USER_1}{USER_2})',
            ignore_base_filter=True,
            ordering_rules=[('cn', 'caseIgnoreOrderingMatch')],
        )
        self.assertLDAPSearchIsEqual(queryset, expected)

    def test_combined_queryset_is_a_single_search(self):
        queryset = self._user_1_queryset().union(self._user_2_queryset())
        with self.assertNumQueries(1):
            list(queryset)


class CombinedQueryResultTestCase(LDAPTestCase):
    @staticmethod
    def _usernames(queryset):
        return sorted(user.username for user in queryset)

    def test_union_returns_both_branches(self):
        queryset = LDAPUser.objects.filter(username=TEST_LDAP_USER_1.username).union(
            LDAPUser.objects.filter(username=TEST_LDAP_USER_2.username)
        )
        self.assertEqual(
            self._usernames(queryset),
            sorted([TEST_LDAP_USER_1.username, TEST_LDAP_USER_2.username]),
        )

    def test_intersection_returns_the_overlap(self):
        queryset = LDAPUser.objects.filter(
            username__in=[TEST_LDAP_USER_1.username, TEST_LDAP_USER_2.username]
        ).intersection(LDAPUser.objects.filter(username=TEST_LDAP_USER_1.username))
        self.assertEqual(self._usernames(queryset), [TEST_LDAP_USER_1.username])

    def test_difference_removes_the_right_branch(self):
        queryset = LDAPUser.objects.filter(
            username__in=[TEST_LDAP_USER_1.username, TEST_LDAP_USER_2.username]
        ).difference(LDAPUser.objects.filter(username=TEST_LDAP_USER_2.username))
        self.assertEqual(self._usernames(queryset), [TEST_LDAP_USER_1.username])

    def test_union_of_disjoint_branches_counts_both(self):
        queryset = LDAPUser.objects.filter(username=TEST_LDAP_USER_1.username).union(
            LDAPUser.objects.filter(username=TEST_LDAP_USER_2.username)
        )
        self.assertEqual(queryset.count(), 2)


class CombinedQueryUnsupportedTestCase(LDAPTestCase):
    def test_union_all_raises(self):
        queryset = LDAPUser.objects.filter(username=TEST_LDAP_USER_1.username).union(
            LDAPUser.objects.filter(username=TEST_LDAP_USER_2.username), all=True
        )
        with self.assertRaises(NotSupportedError):
            list(queryset)

    def test_different_models_raise(self):
        queryset = LDAPUser.objects.all().union(LDAPAdminUser.objects.all())
        with self.assertRaises(NotSupportedError):
            list(queryset)

    def test_sliced_branch_raises(self):
        queryset = LDAPUser.objects.all()[:1].union(LDAPUser.objects.filter(username=TEST_LDAP_USER_2.username))
        with self.assertRaises(NotSupportedError):
            list(queryset)

    def test_branch_filtering_on_dn_raises(self):
        queryset = LDAPUser.objects.filter(dn=TEST_LDAP_USER_1.dn).union(
            LDAPUser.objects.filter(username=TEST_LDAP_USER_2.username)
        )
        with self.assertRaises(NotSupportedError):
            list(queryset)


class TestCombinedQuerySelect(LDAPTestCase):
    def test_branch_without_explicit_select_inherits_the_outer_one(self):
        queryset = LDAPUser.objects.values('username').union(
            LDAPUser.objects.filter(username=TEST_LDAP_USER_2.username)
        )
        expected = get_new_ldap_search(
            filterstr=f'(|{BASE_FILTER}{USER_2})',
            attrlist=['uid'],
            ignore_base_filter=True,
        )
        self.assertLDAPSearchIsEqual(queryset, expected)
        self.assertIn({'username': TEST_LDAP_USER_2.username}, list(queryset))

    def test_conflicting_values_raise(self):
        queryset = LDAPUser.objects.values('username').union(LDAPUser.objects.values('mail'))
        with self.assertRaisesMessage(NotSupportedError, 'must select the same fields'):
            list(queryset)

    def test_explicit_select_on_the_right_branch_only_raises(self):
        queryset = LDAPUser.objects.all().union(LDAPUser.objects.values('username'))
        with self.assertRaisesMessage(NotSupportedError, 'must select the same fields'):
            list(queryset)

    def test_conflicting_only_raises(self):
        queryset = LDAPUser.objects.only('mail').union(LDAPUser.objects.all())
        with self.assertRaisesMessage(NotSupportedError, 'must select the same fields'):
            list(queryset)
