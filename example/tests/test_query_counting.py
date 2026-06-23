"""
Every logical LDAP operation must produce exactly one entry in the query log,
so that assertNumQueries / django-debug-toolbar report real round-trip counts.

Django stores the query count *only* when the actual cursor is called.
In the past, we've used LDAP operations (search_s/add_s/modify_s/del_s)
in the compilers directly, so they were never actually counted.

So nowadays, when introducing any other LDAP operation,
we have to make sure we route it through the cursor.
"""

from example.models import LDAPUser
from example.tests.base import LDAPTestCase
from example.tests.constants import TEST_LDAP_USER_1
from example.tests.generator import create_random_ldap_user, generate_random_username


class QueryCountingTestCase(LDAPTestCase):
    def test_read_filter_is_one_query(self):
        with self.assertNumQueries(1):
            list(LDAPUser.objects.filter(username=TEST_LDAP_USER_1.username))

    def test_count_is_one_query(self):
        with self.assertNumQueries(1):
            LDAPUser.objects.count()

    def test_create_is_one_query(self):
        username = generate_random_username()
        with self.assertNumQueries(1):
            LDAPUser.objects.create(
                username=username,
                first_name='Count',
                last_name='Create',
                name='Count Create',
                mail=f'{username}@example.com',
            )

    def test_delete_existing_is_one_query(self):
        user = create_random_ldap_user()
        with self.assertNumQueries(1):
            LDAPUser.objects.filter(username=user.username).delete()

    def test_delete_missing_is_one_query(self):
        with self.assertNumQueries(1):
            LDAPUser.objects.filter(username='does_not_exist').delete()

    def test_update_existing_field_is_two_queries(self):
        user = create_random_ldap_user(mail='before@example.com')
        user = LDAPUser.objects.get(username=user.username)
        user.mail = 'after@example.com'
        # search (read-before-write diff) + modify
        with self.assertNumQueries(2):
            user.save()

    def test_rename_with_field_change_is_three_queries(self):
        old_username = generate_random_username()
        new_username = generate_random_username()
        create_random_ldap_user(username=old_username, mail='before@example.com')
        user = LDAPUser.objects.get(username=old_username)
        user.username = new_username
        user.mail = 'after@example.com'
        # rename + search (read-before-write diff) + modify
        with self.assertNumQueries(3):
            user.save()
