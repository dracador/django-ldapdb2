from io import StringIO
from typing import cast

from django.core.management import CommandError, call_command
from django.db import connections
from django.db.utils import ConnectionHandler
from django.test import SimpleTestCase
from django.test.utils import isolate_apps
from ldapdb.backends.ldap.introspection import ContainerSample, DatabaseIntrospection
from ldapdb.management.commands.inspectldap import (
    model_name_from_dn,
    normalize_attribute_name,
    resolve_ldap_connection,
)

from example.tests.base import LDAPTestCase

USERS_DN = 'ou=Users,dc=example,dc=org'
GROUPS_DN = 'ou=Groups,dc=example,dc=org'
INSPECTION_DN = 'ou=Inspection,dc=example,dc=org'
INSPECTION_USERS_DN = f'ou=Users,{INSPECTION_DN}'
MIXED_DN = f'ou=MixedRDN,{INSPECTION_DN}'
ENTRY_1_DN = f'uid=inspect1,{INSPECTION_USERS_DN}'


def _introspection() -> DatabaseIntrospection:
    return cast('DatabaseIntrospection', connections['ldap'].introspection)


def generate(*args, **kwargs) -> str:
    out = StringIO()
    call_command('inspectldap', *args, '--database', 'ldap', stdout=out, **kwargs)
    return out.getvalue()


def build_model(source: str, class_name: str):
    namespace = {}
    patched = source.replace('    class Meta:', "    class Meta:\n        app_label = 'example'")
    exec(compile(patched, '<inspectldap>', 'exec'), namespace)
    return namespace[class_name]


class NormalizeAttributeNameTestCase(SimpleTestCase):
    def test_camel_case(self):
        self.assertEqual(normalize_attribute_name('givenName'), 'given_name')
        self.assertEqual(normalize_attribute_name('userPKCS12'), 'user_pkcs12')
        self.assertEqual(normalize_attribute_name('entryDN'), 'entry_dn')

    def test_hyphens(self):
        self.assertEqual(normalize_attribute_name('x-user-isActive'), 'x_user_is_active')

    def test_keywords(self):
        self.assertEqual(normalize_attribute_name('class'), 'class_field')

    def test_digits(self):
        self.assertEqual(normalize_attribute_name('2fa'), 'attr_2fa')


class ModelNameFromDnTestCase(SimpleTestCase):
    def test_uses_the_containers_own_rdn_value(self):
        self.assertEqual(model_name_from_dn(USERS_DN), 'Users')
        self.assertEqual(model_name_from_dn('ou=Service Accounts,dc=example,dc=org'), 'ServiceAccounts')


class ContainerSampleTestCase(SimpleTestCase):
    def test_rdn_attribute_picks_the_most_common(self):
        sample = ContainerSample(dn=USERS_DN, entry_count=3)
        sample.rdn_attributes.update(['uid', 'uid', 'cn'])
        self.assertEqual(sample.rdn_attribute, 'uid')

    def test_rdn_attribute_is_none_without_a_sample(self):
        self.assertIsNone(ContainerSample(dn=USERS_DN, entry_count=0).rdn_attribute)


class LDAPIntrospectionTestCase(LDAPTestCase):
    def test_subschema_dn_comes_from_the_rootdse(self):
        introspection = _introspection()
        self.assertEqual(introspection.subschema_dn.lower(), 'cn=subschema')

    def test_resolves_a_syntax_inherited_via_sup(self):
        # 'cn' defines no SYNTAX of its own, it falls back to it's SUP name, instead
        info = _introspection().attribute_info('cn')
        self.assertEqual(info.syntax, '1.3.6.1.4.1.1466.115.121.1.15')
        self.assertEqual(info.field_class, 'CharField')

    def test_operational_attributes_are_flagged_read_only(self):
        info = _introspection().attribute_info('entryDN')
        self.assertTrue(info.read_only)
        self.assertEqual(info.field_class, 'DistinguishedNameField')

    def test_minimal_object_classes_drops_implied_and_abstract_classes(self):
        introspection = _introspection()
        minimal = introspection.get_minimal_object_classes(
            ['inetOrgPerson', 'organizationalPerson', 'person', 'top', 'x-extendedUser']
        )
        self.assertEqual(minimal, ['inetOrgPerson', 'x-extendedUser'])

    def test_sample_container_respects_the_limit(self):
        sample = _introspection().sample_container(INSPECTION_USERS_DN, limit=3)
        self.assertEqual(sample.entry_count, 3)
        self.assertEqual(sample.rdn_attribute, 'uid')


@isolate_apps('example')
class InspectLdapCommandTestCase(LDAPTestCase):
    def test_rejects_a_non_ldap_database(self):
        with self.assertRaises(CommandError):
            call_command('inspectldap', USERS_DN, '--database', 'default', stdout=StringIO())

    def test_rejects_a_model_name_count_mismatch(self):
        with self.assertRaisesMessage(CommandError, 'Got 1 --model-name values for 2 DNs'):
            call_command(
                'inspectldap',
                USERS_DN,
                GROUPS_DN,
                '--database',
                'ldap',
                '--model-name',
                'OnlyOne',
                stdout=StringIO(),
            )

    def test_generated_user_model_matches_the_directory(self):
        source = generate(INSPECTION_USERS_DN)
        model = build_model(source, 'Users')

        self.assertEqual(model.base_dn, INSPECTION_USERS_DN)
        self.assertEqual(model.object_classes, ['inetOrgPerson', 'x-extendedUser'])
        self.assertEqual(model._meta.pk.db_column, 'uid')

        columns = {field.name: field.db_column for field in model._meta.fields}

        self.assertEqual(columns['cn'], 'cn')
        self.assertEqual(columns['sn'], 'sn')
        self.assertEqual(columns['given_name'], 'givenName')
        self.assertEqual(columns['x_user_is_active'], 'x-user-isActive')

    def test_generated_user_model_can_query_the_server(self):
        model = build_model(generate(INSPECTION_USERS_DN), 'Users')
        user = model.objects.using('ldap').get(pk='inspect1')
        self.assertEqual(user.mail, 'inspect.one@example.org')

    def test_required_attributes_are_not_nullable(self):
        model = build_model(generate(INSPECTION_USERS_DN), 'Users')
        fields = {field.name: field for field in model._meta.fields}

        # MUST
        self.assertFalse(fields['cn'].null)
        self.assertFalse(fields['sn'].null)

        # MAY
        self.assertTrue(fields['given_name'].null)

    def test_field_classes_follow_the_schema_syntax(self):
        model = build_model(generate(INSPECTION_USERS_DN), 'Users')
        classes = {field.name: type(field).__name__ for field in model._meta.fields}
        self.assertEqual(classes['x_user_is_active'], 'BooleanField')
        self.assertEqual(classes['x_user_date_time'], 'DateTimeField')
        self.assertEqual(classes['mail'], 'EmailField')
        self.assertEqual(classes['user_password'], 'PasswordField')

    def test_password_field_uses_the_configured_algorithm(self):
        source = generate(INSPECTION_USERS_DN)
        self.assertIn('algorithm=LDAPPasswordAlgorithm.SSHA512', source)
        model = build_model(source, 'Users')
        self.assertEqual(model._meta.get_field('user_password').algorithm.value, 'SSHA512')

    def test_group_model_uses_the_rdn_attribute_as_primary_key(self):
        model = build_model(generate(GROUPS_DN), 'Groups')
        self.assertEqual(model._meta.pk.name, 'cn')
        self.assertEqual(model._meta.pk.db_column, 'cn')
        self.assertEqual(tuple(model._meta.ordering), ('cn',))

    def test_multi_valued_is_inferred_from_the_sampled_data(self):
        model = build_model(generate(GROUPS_DN), 'Groups')
        self.assertTrue(model._meta.get_field('member').multi_valued_field)
        # Schema defines 'ou' as multi-valued but in our directory it should be single-value
        self.assertFalse(model._meta.get_field('ou').multi_valued_field)

    def test_unset_optional_attributes_are_omitted_by_default(self):
        source = generate(GROUPS_DN)
        self.assertNotIn('owner', source)
        self.assertNotIn('entryDN', source)

    def test_fields_carry_no_schema_comments(self):
        source = generate(INSPECTION_USERS_DN, '--all')
        self.assertNotIn('RFC', source)
        for line in source.splitlines():
            if '= CharField(' in line or '= EmailField(' in line:
                self.assertNotIn('#', line, f'field line carries a comment: {line!r}')

    def test_all_promotes_optional_and_operational_attributes(self):
        source = generate(GROUPS_DN, '--all')
        model = build_model(source, 'Groups')
        fields = {field.name: field for field in model._meta.fields}
        self.assertIn('owner', fields)
        self.assertIn('entry_dn', fields)
        self.assertTrue(fields['entry_dn'].read_only)

    def test_custom_model_names_and_multiple_dns(self):
        names = ('--model-name', 'Person', '--model-name', 'Team')
        source = generate(INSPECTION_USERS_DN, GROUPS_DN, *names)
        self.assertIn('class Person(LDAPModel):', source)
        self.assertIn('class Team(LDAPModel):', source)
        self.assertEqual(build_model(source, 'Person').base_dn, INSPECTION_USERS_DN)

    def test_non_default_scope_emits_the_ldap_import(self):
        source = generate(INSPECTION_USERS_DN, '--scope', 'onelevel')
        self.assertIn('import ldap', source)
        self.assertIn('search_scope = ldap.SCOPE_ONELEVEL', source)

    def test_generated_lines_stay_within_the_line_limit(self):
        for source in (generate(INSPECTION_USERS_DN), generate(GROUPS_DN, '--all')):
            for line in source.splitlines():
                self.assertLessEqual(len(line), 120, f'generated line too long: {line!r}')


@isolate_apps('example')
class ChildlessDNTestCase(LDAPTestCase):
    def test_sample_direct_dn_when_it_has_no_children(self):
        sample = _introspection().sample_container(ENTRY_1_DN, limit=20)
        self.assertTrue(sample.direct_entry)
        self.assertEqual(sample.entry_count, 1)
        self.assertEqual(sample.rdn_attribute, 'uid')

    def test_model_is_based_at_the_parent_of_a_childless_dn(self):
        model = build_model(generate(ENTRY_1_DN), 'Inspect1')
        self.assertEqual(model.base_dn, INSPECTION_USERS_DN)
        self.assertEqual(model._meta.pk.db_column, 'uid')

    def test_childless_dn_is_called_out_in_the_generated_source(self):
        source = generate(ENTRY_1_DN)
        self.assertIn('has no children', source)
        self.assertIn(ENTRY_1_DN, source)

    def test_generated_model_for_a_childless_dn_can_query_the_server(self):
        model = build_model(generate(ENTRY_1_DN), 'Inspect1')
        self.assertEqual(model.objects.using('ldap').get(pk='inspect1').mail, 'inspect.one@example.org')


class MissingDNTestCase(LDAPTestCase):
    def test_a_dn_that_does_not_exist_is_reported_as_a_command_error(self):
        with self.assertRaisesMessage(CommandError, "Could not read 'ou=NoSuchThing,dc=example,dc=org'"):
            generate('ou=NoSuchThing,dc=example,dc=org')


class PositionalDNTestCase(LDAPTestCase):
    def test_dns_are_taken_as_positional_arguments(self):
        out = StringIO()
        call_command('inspectldap', INSPECTION_USERS_DN, GROUPS_DN, '--database', 'ldap', stdout=out)
        source = out.getvalue()
        self.assertIn('class Users(LDAPModel):', source)
        self.assertIn('class Groups(LDAPModel):', source)

    def test_at_least_one_dn_is_required(self):
        with self.assertRaises(CommandError):
            call_command('inspectldap', '--database', 'ldap', stdout=StringIO())


@isolate_apps('example')
class DatabaseSelectionTestCase(LDAPTestCase):
    def test_picks_the_first_ldap_database_when_none_is_named(self):
        out = StringIO()
        call_command('inspectldap', INSPECTION_USERS_DN, stdout=out)
        self.assertIn('class Users(LDAPModel):', out.getvalue())

    def test_reports_when_no_database_uses_the_backend(self):
        handler = ConnectionHandler({'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': ':memory:'}})
        with self.assertRaisesMessage(CommandError, 'No database in settings.DATABASES uses the ldap backend'):
            resolve_ldap_connection(handler, None)

    def test_a_named_non_ldap_database_is_rejected(self):
        with self.assertRaisesMessage(CommandError, 'only works on an ldap database'):
            resolve_ldap_connection(connections, 'default')

    def test_skips_a_non_ldap_database_that_comes_first(self):
        self.assertEqual(resolve_ldap_connection(connections, None).alias, 'ldap')
