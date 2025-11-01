from typing import TYPE_CHECKING, cast

import ldap
from django.db import transaction
from django.db.transaction import get_connection
from django.test import TransactionTestCase
from ldap import modlist
from ldapdb.backends.ldap.transaction import TxnRequestControl, as_ldap_transaction, end_ldap_txn, start_ldap_txn

from .generator import create_random_ldap_user, generate_random_name, generate_random_username

if TYPE_CHECKING:
    from ldapdb.backends.ldap.base import DatabaseWrapper


class LDAPTransactionTests(TransactionTestCase):
    """
    TODO:
    - Savepoints/inner atomic blocks?
    - rollback via IntegrityError
    - too many binds?
    """

    databases = ['ldap']

    def assertIsTransaction(self):
        conn = get_connection('ldap')
        if conn.get_autocommit():
            self.fail(f'Connection is not in transaction but should be - {conn._txn_id=}, {conn._in_txn=}')

    def assertIsNotTransaction(self):
        conn = get_connection('ldap')
        if not conn.get_autocommit():
            self.fail(f'Connection is in transaction but should not be - {conn._txn_id=}, {conn._in_txn=}')

    @staticmethod
    def _get_new_connection():
        from django.db import connections

        db_wrapper: DatabaseWrapper = cast('DatabaseWrapper', connections['ldap'])
        return db_wrapper.get_new_connection()

    @staticmethod
    def _build_user_attrs(name=None):
        if name is None:
            name = generate_random_name()
        username = generate_random_username()
        dn = f'uid={username},ou=Users,dc=example,dc=org'
        attrs = {
            'objectclass': [b'top', b'inetOrgPerson', b'organizationalPerson'],
            'uid': username.encode(),
            'cn': name.encode(),
            'sn': b'Surname',
        }
        return dn, attrs

    def test_without_atomic_transaction(self):
        name = generate_random_name()
        dn, attrs = self._build_user_attrs(name)
        ldif_add = modlist.addModlist(attrs)
        changed_name = f'{name}-changed'

        conn = self._get_new_connection()
        conn.add_ext_s(dn, ldif_add)
        conn.modify_ext_s(dn, [(ldap.MOD_REPLACE, 'cn', changed_name.encode())])

        ldap_search = conn.search_s(dn, ldap.SCOPE_BASE)
        self.assertEqual(ldap_search[0][1]['cn'], [changed_name.encode()])

    def test_add_modify_with_manual_transaction_commit(self):
        name = generate_random_name()
        dn, attrs = self._build_user_attrs(name)
        ldif_add = modlist.addModlist(attrs)
        changed_name = f'{name}-changed'

        # force new connection to avoid potential re-bindings that destroy the transaction
        conn = self._get_new_connection()
        with as_ldap_transaction(conn) as ctrl:
            conn.add_ext_s(dn, ldif_add, serverctrls=[ctrl])
            conn.modify_ext_s(dn, [(ldap.MOD_REPLACE, 'cn', changed_name.encode())], serverctrls=[ctrl])

        # use same connection after transaction end
        ldap_search = conn.search_s(dn, ldap.SCOPE_BASE)
        self.assertEqual(ldap_search[0][1]['cn'], [changed_name.encode()])

    def test_modify_with_manual_transaction_rollback(self):
        name = generate_random_name()
        dn, attrs = self._build_user_attrs(name)
        ldif_add = modlist.addModlist(attrs)
        changed_name = f'{name}-changed'

        # force new connection to avoid potential re-bindings that destroy the transaction
        conn = self._get_new_connection()

        # do it without transaction first
        conn.add_ext_s(dn, ldif_add)

        # start transaction and rollback
        txn_id = start_ldap_txn(conn)
        ctrl = TxnRequestControl(txn_id)
        conn.modify_ext_s(dn, [(ldap.MOD_REPLACE, 'cn', changed_name.encode())], serverctrls=[ctrl])
        end_ldap_txn(conn, txn_id, commit=False)

        ldap_search = conn.search_s(dn, ldap.SCOPE_BASE)
        self.assertEqual(ldap_search[0][1]['cn'], [attrs['cn']])

    # ----- Tests below use django transaction management, which might have broken connection handling -----
    def test_modify_with_django_transaction_commit(self):
        self.assertIsNotTransaction()

        name = generate_random_name()
        changed_name = f'{name}-changed'
        user = create_random_ldap_user(name=name)

        with transaction.atomic(using='ldap'):
            self.assertIsTransaction()
            user.name = changed_name
            user.save()

        user.refresh_from_db()
        self.assertEqual(user.name, changed_name)

    def test_modify_with_django_transaction_rollback(self):
        name = generate_random_name()
        changed_name = f'{name}-changed'
        user = create_random_ldap_user(name=name)

        self.assertIsNotTransaction()
        with self.assertRaises(RuntimeError), transaction.atomic(using='ldap'):
            self.assertIsTransaction()
            user.name = changed_name
            user.save()
            raise RuntimeError  # force rollback

        user.refresh_from_db()
        self.assertEqual(user.name, name)
