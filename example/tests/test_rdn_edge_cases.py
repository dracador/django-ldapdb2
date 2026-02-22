from django.core.exceptions import ValidationError
from ldapdb.models.fields import CharField

from example.models import BaseLDAPUser, LDAPUser
from example.tests.base import LDAPTestCase
from example.tests.generator import create_random_ldap_user, randomize_string


class LDAPUserWithCNAsPK(BaseLDAPUser):
    username = CharField(db_column='uid', primary_key=False)
    name = CharField(db_column='cn', primary_key=True)


class FunkyRDNTestCase(LDAPTestCase):
    def test_escaped_characters_in_dn(self):
        # See ldapdb.lib.escape_ldap_dn_chars()
        # Note: "#" is a special case, in that it only needs to be escaped at the start of an RDN
        dn_special_chars = ['\\', ',', '#', '+', '<', '>', ';', '"', '=']

        username = randomize_string('#kläüßgonzález' + ''.join(dn_special_chars))
        user = create_random_ldap_user(username=username)
        self.assertEqual(user.username, username)
        self.assertEqual(f'uid={username},ou=Users,dc=example,dc=org', user.dn)

        dn_before_refresh = user.dn
        user.refresh_from_db()
        dn_after_refresh = user.dn
        self.assertEqual(dn_before_refresh, dn_after_refresh)

        user.last_name = 'New Last Name'
        user.save()

    def test_cn_rdn(self):
        user = create_random_ldap_user(model_cls=LDAPUserWithCNAsPK, do_not_create=True)
        user.save()
        expected_dn = f'cn={user.name},ou=Users,dc=example,dc=org'
        self.assertEqual(expected_dn, user.dn)

        # test renaming/escaping
        new_name = f'{user.name}; Renamed'
        user.name = new_name
        user.save()

        # When creating objects, SQLInsertCompiler will set the
        expected_dn = f'cn={new_name},ou=Users,dc=example,dc=org'
        self.assertEqual(expected_dn, user.dn)

        # check again after DN has been set by the cursor
        user.refresh_from_db()
        self.assertEqual(expected_dn, user.dn)

    def test_uid_whitespace_rdn(self):
        user = create_random_ldap_user(do_not_create=True)
        user.username = whitespaced_username = f' {user.username} '
        user.save()
        expected_dn = f'uid={whitespaced_username},ou=Users,dc=example,dc=org'
        self.assertEqual(expected_dn, user.dn)

        # test renaming/escaping
        new_username = f' {user.username}-renamed '
        user.username = new_username
        user.save()
        self.assertEqual(user.dn, f'uid={new_username},ou=Users,dc=example,dc=org')

    def test_nul_byte_rdn(self):
        with self.assertRaises(ValidationError):
            user = create_random_ldap_user(do_not_create=True)
            user.username = user.username + '\x00'
            user.save()

    def test_escaped_dn_raises_for_mismatched_base_dn(self):
        user = LDAPUser.__new__(LDAPUser)
        user.dn = 'uid=foo,ou=OtherOU,dc=example,dc=org'
        with self.assertRaises(ValueError):
            _ = user.escaped_dn

    def test_escaped_dn_works_for_matching_base_dn(self):
        user = LDAPUser.__new__(LDAPUser)
        user.dn = 'uid=foo,ou=Users,dc=example,dc=org'
        escaped = user.escaped_dn
        self.assertIn('foo', escaped)
        self.assertIn(LDAPUser.base_dn, escaped)
