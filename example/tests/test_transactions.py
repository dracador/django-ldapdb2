from __future__ import annotations

import unittest
from typing import Optional

from django.db import connections, transaction

from example.models import LDAPUser
from .base import LDAPTestCase


class LDAPTransactionTests(LDAPTestCase):
    """
    Transactional behavior tests for the LDAP backend using your LDAPTestCase helpers.
    Assumptions:
      - LDAPTestCase._get_user_1_object() returns a valid LDAPUser instance we can modify.
      - Your backend sets `connection.features.supports_transactions`.
      - Savepoints are NOT supported; nested atomic sets rollback-only on outer block.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        db = connections['ldap']
        print(db.features.supports_transactions)
        if not db.features.supports_transactions:
            raise unittest.SkipTest('LDAP server/driver does not support RFC 5805 transactions')

        cls.UserModel = LDAPUser
        cls.mutable_field_name = cls._pick_mutable_string_field()
        if not cls.mutable_field_name:
            raise unittest.SkipTest('Could not find a safe, editable, non-unique string field to mutate.')

    @classmethod
    def _pick_mutable_string_field(cls) -> str | None:
        """
        Pick a safe, editable, non-unique string-like field to change for tests.
        Preference: non-unique Char/Text/Email fields that are not PK and editable.
        Fallbacks: 'mail' or 'cn' if present and editable.
        """
        string_types = {'CharField', 'TextField', 'EmailField'}
        for f in cls.UserModel._meta.get_fields():
            # Only concrete model fields
            if not hasattr(f, 'attname'):
                continue
            if getattr(f, 'primary_key', False):
                continue
            if getattr(f, 'unique', False):
                continue
            if getattr(f, 'editable', True) is False:
                continue
            internal = getattr(f, 'get_internal_type', lambda: '')()
            if internal in string_types:
                return f.attname

        # Fallbacks if above didn't find any
        for name in ('mail', 'cn', 'description'):
            try:
                f = cls.UserModel._meta.get_field(name)
                if getattr(f, 'editable', True) and not getattr(f, 'primary_key', False):
                    return name
            except Exception:
                pass
        return None

    def _fresh_user1(self):
        return self._get_user_1_object()

    def test_commit_persists_changes(self):
        user = self._fresh_user1()
        field = self.mutable_field_name
        before = getattr(user, field, None)

        new_val = self._uniqueize(before, suffix='+tx_commit')

        with transaction.atomic(using='ldap'):
            setattr(user, field, new_val)
            user.save()

        # After commit, the value must persist
        refreshed = self._fresh_user1()
        self.assertEqual(getattr(refreshed, field), new_val)

        # Also demonstrate with your dict-based equality helper (field-focused)
        self.assertLDAPModelObjectsAreEqual(
            left_model_instance={field: new_val},
            right_model_instance=refreshed,
            fields=[field],
        )

    def test_rollback_discards_changes(self):
        user = self._fresh_user1()
        field = self.mutable_field_name
        committed_val = getattr(user, field, None)  # current committed state

        try:
            with transaction.atomic(using='ldap'):
                setattr(user, field, self._uniqueize(committed_val, suffix='+tx_rollback'))
                user.save()
                # Force rollback
                raise RuntimeError('boom')
        except RuntimeError:
            pass

        # After rollback, the value should equal the original committed value
        refreshed = self._fresh_user1()
        self.assertLDAPModelObjectsAreEqual(
            left_model_instance=refreshed,
            right_model_instance=refreshed,
            fields=[field],
        )

    def test_nested_atomic_without_savepoints_marks_outer_as_rollback_only(self):
        """
        We assume savepoints are not implemented. Django should mark the outer
        transaction as rollback-only when an inner atomic() errors and is caught.
        Exiting the outer block then raises TransactionManagementError.
        """
        from django.db import TransactionManagementError

        user = self._fresh_user1()
        field = self.mutable_field_name
        committed_val = getattr(user, field, None)

        with self.assertRaises(TransactionManagementError), transaction.atomic(using='ldap'):
            # Change some value inside the outer block
            setattr(user, field, self._uniqueize(committed_val, suffix='+outer'))
            user.save()

            try:
                with transaction.atomic(using='ldap'):
                    # Inner failure => no savepoint => mark outer as rollback-only
                    raise ValueError('inner failure')
            except ValueError:
                # Outer is now rollback-only; leaving it must raise
                pass

                # Exiting the outer block should raise TransactionManagementError

        # Ensure nothing was committed
        refreshed = self._fresh_user1()
        self.assertEqual(getattr(refreshed, field), committed_val)

    # ---------- helpers ----------

    @staticmethod
    def _uniqueize(value: Optional[str], suffix: str) -> str:
        base = (value or '').split('+tx', 1)[0]  # strip any previous test suffix
        if not base:
            base = 'x'
        return f'{base}{suffix}'
