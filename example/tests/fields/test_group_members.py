import ldap
from django.core.exceptions import ValidationError
from django.db import connections
from ldapdb.models.fields import DistinguishedNameField, MemberField, UpdateStrategy

from example.models import BaseLDAPGroup, LDAPGroup, LDAPUser
from example.tests.base import LDAPTestCase
from example.tests.constants import TEST_LDAP_GROUP_1
from example.tests.generator import (
    create_random_ldap_group,
    create_random_ldap_user,
    generate_random_group_name,
    generate_random_username,
)


class LDAPGroupWithAddDeleteStrategyMemberField(BaseLDAPGroup):
    members = MemberField(db_column='member', default='dc=example,dc=org', update_strategy=UpdateStrategy.ADD_DELETE)


class LDAPGroupWithReplaceStrategyMemberField(BaseLDAPGroup):
    members = MemberField(db_column='member', default='dc=example,dc=org', update_strategy=UpdateStrategy.REPLACE)


class LDAPGroupWithCustomMembersFieldAddDelete(BaseLDAPGroup):
    object_classes = ['groupOfNames', 'x-extendedGroup']
    custom_members = DistinguishedNameField(
        db_column='x-group-customMember', update_strategy=UpdateStrategy.ADD_DELETE, multi_valued_field=True
    )


class LDAPGroupWithCustomMembersFieldReplace(BaseLDAPGroup):
    object_classes = ['groupOfNames', 'x-extendedGroup']
    custom_members = DistinguishedNameField(
        db_column='x-group-customMember', update_strategy=UpdateStrategy.REPLACE, multi_valued_field=True
    )


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
        instance = create_random_ldap_group(
            model_cls=LDAPGroupWithAddDeleteStrategyMemberField,
            members=[
                self.user_1.dn,
            ],
        )
        new_members = ['uid=user2,ou=Users,dc=example,dc=org']
        instance.members = new_members
        instance.save()
        instance.refresh_from_db()
        self.assertEqual(instance.members, new_members)

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

    def test_remove_custom_member_from_groups_add_delete(self):
        # noinspection PyTypeChecker
        instance: LDAPGroupWithCustomMembersFieldAddDelete = create_random_ldap_group(
            model_cls=LDAPGroupWithCustomMembersFieldAddDelete,
            do_not_create=True,
            custom_members=[
                self.user_1.dn,
            ],
        )
        instance.full_clean()
        instance.save()
        instance.refresh_from_db()
        instance.custom_members.remove(self.user_1.dn)
        instance.save(update_fields=['custom_members'])
        instance.refresh_from_db()
        self.assertEqual(
            instance.custom_members,
            [],
        )

    def test_remove_custom_member_from_groups_replace(self):
        # noinspection PyTypeChecker
        instance: LDAPGroupWithCustomMembersFieldReplace = create_random_ldap_group(
            model_cls=LDAPGroupWithCustomMembersFieldReplace,
            do_not_create=True,
            custom_members=[
                self.user_1.dn,
            ],
        )
        instance.full_clean()
        instance.save()
        instance.refresh_from_db()
        instance.custom_members.remove(self.user_1.dn)
        instance.save(update_fields=['custom_members'])
        instance.refresh_from_db()
        self.assertEqual(
            instance.custom_members,
            [],
        )

    def test_group_member_with_special_char_dn(self):
        """
        Test that a DN containing special characters (which requires escaping on the wire)
        can be added to a MemberField and retrieved correctly.
        """
        user = create_random_ldap_user(username=f'{generate_random_username()}+membertest')
        user.refresh_from_db()

        name = generate_random_group_name()
        group = create_random_ldap_group(
            name=name,
            do_not_create=True,
            members=[
                user.dn,
            ],
        )
        group.full_clean()
        group.save()
        group.refresh_from_db()

        self.assertIn('+', user.dn)  # user.dn should contain the unescaped character
        self.assertIn(user.dn, group.members)
