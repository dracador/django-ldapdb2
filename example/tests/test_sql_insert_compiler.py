from random import choice

from django.db import DatabaseError, IntegrityError

from example.models import LDAPUser
from example.tests.base import LDAPTestCase
from example.tests.constants import TEST_LDAP_USER_1, THUMBNAIL_PHOTO_BYTES
from example.tests.generator import create_random_ldap_user, generate_random_username


class SQLInsertUpdateCompilerTestCase(LDAPTestCase):
    @staticmethod
    def _get_user_1_object():
        return LDAPUser.objects.get(username=TEST_LDAP_USER_1.username)

    def test_create_user_fail_on_object_schema_error(self):
        """
        The objectClass inetOrgPerson requires the sn attribute to be set.
        Check that the ldap.OBJECT_CLASS_VIOLATION is propagated up to an IntegrityError
        """
        with self.assertRaises(IntegrityError):
            _ = LDAPUser.objects.create(username='user98', name='User 98', mail='user98@example.com')

    def test_create_user(self):
        created_user = create_random_ldap_user(is_active=True, thumbnail_photo=THUMBNAIL_PHOTO_BYTES)
        self.assertIsNotNone(created_user, 'User should be created successfully.')
        user = LDAPUser.objects.get(username=created_user.username)
        self.assertEqual(user.username, created_user.username, "User's username should match the created value.")

    def test_early_dn_after_creation(self):
        user = create_random_ldap_user(do_not_create=True)
        user.full_clean()
        user.save()
        self.assertIsNotNone(user.dn, "User's DN should be set after creation.")

    def test_create_user_via_save(self):
        # Creating via .save() will use the SQLUpdateCompiler instead of SQLInsertCompiler initially.
        # Letting the SQLUpdateCompiler return 0 will move the handling over to the SQLInsertCompiler.
        non_created_user = create_random_ldap_user(do_not_create=True)
        non_created_user.save()
        user = LDAPUser.objects.get(username=non_created_user.username)
        self.assertEqual(user.username, non_created_user.username, "User's username should match the created value.")

    def test_create_user_save_after_creation(self):
        non_created_user = create_random_ldap_user()
        non_created_user.save()
        user = LDAPUser.objects.get(username=non_created_user.username)
        self.assertEqual(user.username, non_created_user.username, "User's username should match the created value.")

    def test_create_user_via_save_with_force_insert(self):
        non_created_user = create_random_ldap_user(do_not_create=True)
        non_created_user.save(force_insert=True)
        user = LDAPUser.objects.get(username=non_created_user.username)
        self.assertEqual(user.username, non_created_user.username, "User's username should match the created value.")

    def test_create_user_via_save_with_force_update(self):
        non_created_user = create_random_ldap_user(do_not_create=True)
        with self.assertRaises(DatabaseError):
            non_created_user.save(force_update=True)

    def test_update_user_primary_field(self):
        old_username = generate_random_username()
        new_username = generate_random_username()
        obj = create_random_ldap_user(username=old_username)
        obj.username = new_username
        obj.save()
        obj.refresh_from_db()
        self.assertFalse(LDAPUser.objects.filter(username=old_username).exists())
        self.assertEqual(obj.dn, f'uid={new_username},{LDAPUser.base_dn}')

    def test_update_user_non_primary_field(self):
        new_mail = 'aftervaluechange@example.com'
        user = create_random_ldap_user(mail='beforevaluechange@example.com')
        user.mail = new_mail
        user.save()
        user.refresh_from_db()
        self.assertEqual(user.mail, new_mail)

    def test_readonly_attributes_create_success(self):
        # Not setting any of the operational fields should allow saving
        instance = create_random_ldap_user(do_not_create=True)
        instance.full_clean()
        instance.save()
        instance.refresh_from_db()
        self.assertEqual(instance.dn, instance.entry_dn)

    def test_readonly_attributes_changed_after_create(self):
        # Read-only fields should be ignored on create
        instance = create_random_ldap_user()
        new_dn = 'uid=new_username,ou=Users,dc=example,dc=org'
        instance.entry_dn = new_dn
        instance.full_clean()
        instance.save()
        instance.refresh_from_db()
        self.assertNotEqual(instance.entry_dn, new_dn)

    def test_escaped_characters_in_dn(self):
        # See ldapdb.lib.escape_ldap_dn_chars()
        # Note: "#" is a special case, in that it only needs to be escaped at the start of an RDN
        dn_special_chars = ['\\', ',', '#', '+', '<', '>', ';', '"', '=']

        username = '#kläüßgonzález' + ''.join(dn_special_chars) + str(choice(range(1000)))
        user = create_random_ldap_user(username=username)
        self.assertEqual(user.username, username)
        self.assertEqual(user.dn, f'uid={username},ou=Users,dc=example,dc=org')

        dn_before_refresh = user.dn
        user.refresh_from_db()
        dn_after_refresh = user.dn
        self.assertEqual(dn_before_refresh, dn_after_refresh)
