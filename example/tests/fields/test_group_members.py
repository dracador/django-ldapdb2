from collections.abc import Sequence

import ldap
from django.core.exceptions import ValidationError
from django.db import connections
from ldapdb.models.fields import MemberField, UpdateStrategy

from example.models import BaseLDAPGroup, LDAPGroup, LDAPUser
from example.tests.base import LDAPTestCase
from example.tests.constants import TEST_LDAP_GROUP_1
from example.tests.generator import create_random_ldap_group, generate_random_group_name

# TODO: Model with MemberField(null=True)


class LDAPRequest:
    charset: str = 'utf-8'  # default

    def get_encoded_values(self, values: Sequence[bytes | str]) -> list[bytes]:
        return [v.encode(self.charset) if isinstance(v, str) else v for v in values]


class AddRequest(LDAPRequest):
    def __init__(self):
        self._items: list[tuple[str, list[bytes]]] = []

    def add(self, name: str, raw_values: Sequence[bytes | str]):
        vals: list[bytes] = self.get_encoded_values(raw_values)
        if vals:
            self._items.append((name, vals))

    def as_modlist(self):
        return list(self._items)

    def __bool__(self):
        return bool(self._items)

    def __iter__(self):
        return iter(self._items)

    def items(self):
        return list(self._items)

    def __str__(self):
        lines = []
        for attr, vals in self._items:
            for v in vals:
                lines.append(f'{attr}: {v!r}')
        return '\n'.join(lines)


class ModifyRequest(LDAPRequest):
    def __init__(self):
        self._ops: list[tuple[int, str, list[bytes]]] = []

    def add(self, attr: str, values: Sequence[bytes | str]):
        vals = self.get_encoded_values(values)
        if not vals:
            return
        self._ops.append((ldap.MOD_ADD, attr, vals))

    def replace(self, attr: str, values: Sequence[bytes | str]):
        vals = self.get_encoded_values(values)
        self._ops.append((ldap.MOD_REPLACE, attr, vals))

    def delete(self, attr: str, values: Sequence[bytes | str] | None = None):
        vals = [] if values is None else self.get_encoded_values(values)
        self._ops.append((ldap.MOD_DELETE, attr, vals))

    def as_modlist(self):
        return list(self._ops)

    def __bool__(self):
        return bool(self._ops)

    def __str__(self):
        lines = []
        for op, attr, vals in self._ops:
            op_name = {
                ldap.MOD_ADD: 'ADD',
                ldap.MOD_DELETE: 'DELETE',
                ldap.MOD_REPLACE: 'REPLACE',
            }.get(op, str(op))
            if not vals:
                lines.append(f'{op_name} {attr}')
            else:
                for v in vals:
                    lines.append(f'{op_name} {attr}: {v!r}')
        return '\n'.join(lines)


class LDAPGroupWithAddDeleteStrategyMemberField(BaseLDAPGroup):
    members = MemberField(db_column='member', default='dc=example,dc=org', update_strategy=UpdateStrategy.ADD_DELETE)


class LDAPGroupWithReplaceStrategyMemberField(BaseLDAPGroup):
    members = MemberField(db_column='member', default='dc=example,dc=org', update_strategy=UpdateStrategy.REPLACE)


class MemberFieldTestCase(LDAPTestCase):
    def setUp(self):
        self.user_1 = LDAPUser.objects.get(username='admin')
        self.existing_test_group = LDAPGroup.objects.get(name=TEST_LDAP_GROUP_1.name)

    def test_members_values(self):
        """Test that the MemberField can be retrieved from the LDAPGroup model."""
        self.assertEqual(
            self.existing_test_group.members,
            [
                'uid=admin,ou=Users,dc=example,dc=org',
                'uid=user1,ou=Users,dc=example,dc=org',
            ],
        )

    def test_create_group(self):
        name = generate_random_group_name()
        instance = create_random_ldap_group(
            name=name,
            do_not_create=True,
            members=[
                self.user_1.dn,
            ],
        )
        instance.full_clean()
        instance.save()
        instance.refresh_from_db()
        self.assertEqual(name, instance.name)

    def test_create_group_with_default_member(self):
        instance = create_random_ldap_group(
            do_not_create=True,
            members=[],
        )
        instance.full_clean()
        instance.save()
        instance.refresh_from_db()  # TODO: Currently need to run refresh_from_db() to get the dn attribute
        with connections[instance._state.db].cursor() as cursor:
            result = cursor.connection.search_s(
                base=instance.dn,
                scope=ldap.SCOPE_BASE,
                filterstr='(objectClass=*)',
                attrlist=['member'],
            )

        _dn, attrs = result[0]
        raw_members = [m.decode() for m in attrs['member']]
        self.assertEqual(raw_members, ['dc=example,dc=org'])

    def test_members_none(self):
        # TODO: Currently broken, members=None should be handled the same way as members=[]
        #
        # with self.assertRaises(ValidationError):
        #    instance = create_random_ldap_group(
        #        do_not_create=True,
        #        members=None,
        #    )
        #    instance.full_clean()
        #    instance.save()
        pass

    def test_invalid_member_dn(self):
        with self.assertRaises(ValidationError) as e:
            instance = create_random_ldap_group(do_not_create=True, members=['invalid-dn'])
            instance.full_clean()
            instance.save()
        self.assertIn('Invalid distinguished name', str(e.exception))

    def test_update_group_members_add_update_strategy(self):
        # TODO: Fix ADD_DELETE strategy with lists

        """
        new_members = ['uid=user2,ou=Users,dc=example,dc=org']
        instance = create_random_ldap_group(
            model_cls=LDAPGroupWithAddDeleteStrategyMemberField,
            members=[
                self.user_1.dn,
            ],
        )
        instance.members = new_members
        instance.save()
        instance.refresh_from_db()
        self.assertEqual(instance.members, new_members)
        """

    def test_update_group_members_replace_strategy(self):
        new_members = ['uid=user2,ou=Users,dc=example,dc=org']
        instance = create_random_ldap_group(
            model_cls=LDAPGroupWithReplaceStrategyMemberField,
            members=[
                self.user_1.dn,
            ],
        )
        instance.members = new_members
        instance.save()
        instance.refresh_from_db()
        self.assertEqual(instance.members, new_members)
