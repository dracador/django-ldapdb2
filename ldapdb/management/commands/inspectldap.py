import keyword
import re
from collections.abc import Iterator
from dataclasses import dataclass, field

import ldap
from django.core.management.base import BaseCommand, CommandError
from django.db import Error as DatabaseError, connections

from ldapdb.backends.ldap.introspection import EXCLUDED_ATTRIBUTES, AttributeInfo, ContainerSample
from ldapdb.models.fields import LDAPPasswordAlgorithm

SCOPES = {
    'base': ldap.SCOPE_BASE,
    'onelevel': ldap.SCOPE_ONELEVEL,
    'subtree': ldap.SCOPE_SUBTREE,
}
DEFAULT_SCOPE = 'subtree'

DEFAULT_PASSWORD_ALGORITHM = 'SSHA512'  # TODO: is there a way we can find out by sampling?
FIELD_INDENT = 4
MAX_LINE_LENGTH = 120  # TODO: make configurable
SIZED_FIELD_CLASSES = {'CharField', 'TextField', 'EmailField', 'DistinguishedNameField', 'MemberField'}

HEADER = [
    '# This is an auto-generated django-ldapdb model module.',
    "# It was built from the schema of the DN's objectClasses plus a sample of its entries,",
    '# so treat it as a starting point rather than a finished model:',
    '#   * Check that the primary key is the attribute the entries are really named by.',
    '#   * Drop the fields you do not need and add any additional ones.',
    '#   * Review max_length values. The ones provided by the the schema are often very generous.',
    '#   * Rename the model and its fields as you see fit, but do not change any db_column.',
    '#   * Set `multi_valued_field=True` attributes manually for fields that can be multi-valued.',
]


def normalize_attribute_name(attribute: str) -> str:
    name = re.sub(r'\W', '_', attribute)
    name = re.sub(r'(?<=[a-z0-9])(?=[A-Z])', '_', name)
    name = re.sub(r'(?<=[A-Z])(?=[A-Z][a-z])', '_', name)
    name = re.sub(r'_+', '_', name).strip('_').lower()

    if not name:
        name = 'field'
    if name[0].isdigit():
        name = f'attr_{name}'
    if keyword.iskeyword(name) or keyword.issoftkeyword(name):
        name = f'{name}_field'
    return name


def model_name_from_dn(dn: str) -> str:
    rdn = ldap.dn.explode_dn(dn, notypes=True)[0]
    name = re.sub(r'[^a-zA-Z0-9]', '', rdn.title())
    if not name or name[0].isdigit():
        name = f'Model{name}'
    return name


def resolve_ldap_connection(databases, alias: str | None):
    if alias is None:
        alias = next((name for name in databases if databases[name].vendor == 'ldap'), None)
        if alias is None:
            raise CommandError(
                'No database in settings.DATABASES uses the ldap backend. Add one, or use --database.'
            )
        return databases[alias]

    connection = databases[alias]
    if connection.vendor != 'ldap':
        raise CommandError(
            f'Database {alias!r} uses the {connection.vendor} backend. '
            f'inspectldap only works on an ldap database.'
        )
    return connection


def parent_dn(dn: str) -> str:
    return ldap.dn.dn2str(ldap.dn.str2dn(dn)[1:])


@dataclass
class FieldSpec:
    name: str
    field_class: str
    kwargs: list[str]

    @property
    def imports(self) -> set[str]:
        if self.field_class == 'PasswordField':
            return {self.field_class, 'LDAPPasswordAlgorithm'}
        return {self.field_class}


@dataclass
class FieldSection:
    heading: str
    fields: list[FieldSpec]


@dataclass
class ModelSpec:
    name: str
    base_dn: str
    object_classes: dict[str, int]  # objectClass + the sample count
    entry_count: int
    search_scope: str | None
    notes: list[str]
    sections: list[FieldSection]
    primary_key_name: str | None

    @property
    def imports(self) -> set[str]:
        return set().union(*(spec.imports for section in self.sections for spec in section.fields))


@dataclass
class EmptyContainer:
    dn: str


@dataclass
class BuildContext:
    sample: ContainerSample
    must: set[str]
    password_algorithm: str
    used_names: set[str] = field(default_factory=set)
    primary_key_name: str | None = None


def render_module(models: list[ModelSpec | EmptyContainer]) -> Iterator[str]:
    specs = [model for model in models if isinstance(model, ModelSpec)]

    yield from HEADER
    yield ''
    if any(spec.search_scope for spec in specs):
        yield 'import ldap'
        yield ''
    yield 'from ldapdb.models import LDAPModel'
    imports = set().union(*(spec.imports for spec in specs))
    if imports:
        yield from _render_field_import(sorted(imports))

    for model in models:
        yield ''
        yield ''
        if isinstance(model, EmptyContainer):
            yield f'# No entries found directly below {model.dn!r} -- nothing to introspect.'
        else:
            yield from render_model(model)


def render_model(spec: ModelSpec) -> list[str]:
    lines = [f'class {spec.name}(LDAPModel):', f'    base_dn = {spec.base_dn!r}']
    lines += _render_object_classes(spec)
    if spec.search_scope:
        lines.append(f'    search_scope = ldap.SCOPE_{spec.search_scope.upper()}')
    lines.append('')
    lines += [f'    # {note}' for note in spec.notes]
    lines.append('')

    for index, section in enumerate(spec.sections):
        if index:
            lines.append('')
        lines.append(f'    # {section.heading}')
        for field_spec in section.fields:
            lines += [f'    {line}' for line in render_field(field_spec, indent=FIELD_INDENT)]

    lines.append('')
    lines.append('    class Meta:')
    pk = spec.primary_key_name
    lines.append(f'        ordering = ({pk!r},)' if pk else '        ordering = ()')
    return lines


def render_field(spec: FieldSpec, indent: int) -> list[str]:
    one_line = f'{spec.name} = {spec.field_class}({", ".join(spec.kwargs)})'
    if indent + len(one_line) <= MAX_LINE_LENGTH:
        return [one_line]
    return [f'{spec.name} = {spec.field_class}(', *[f'    {kwarg},' for kwarg in spec.kwargs], ')']


def _render_object_classes(spec: ModelSpec) -> list[str]:
    if len(spec.object_classes) == 1:
        return [f'    object_classes = {list(spec.object_classes)!r}']

    lines = ['    object_classes = [']
    for name, count in spec.object_classes.items():
        note = '' if count == spec.entry_count else f'  # only on {count}/{spec.entry_count} sampled entries'
        lines.append(f'        {name!r},{note}')
    lines.append('    ]')
    return lines


def _render_field_import(field_classes: list[str]) -> Iterator[str]:
    one_line = f'from ldapdb.models.fields import {", ".join(field_classes)}'
    if len(one_line) <= MAX_LINE_LENGTH:
        yield one_line
        return
    yield 'from ldapdb.models.fields import ('
    for field_class in field_classes:
        yield f'    {field_class},'
    yield ')'


class Command(BaseCommand):
    help = (
        'Introspects the LDAP entries from a provided DN and/or their children '
        'and outputs a django-ldapdb2 model class. '
        'The generated fields come from the schema of the found objectClasses.'
    )
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument(
            'dns',
            nargs='+',
            metavar='DN',
            help='Container DN to introspect. Will be used as the model base_dn. Accepts more than one.',
        )
        parser.add_argument(
            '--database',
            default=None,
            choices=tuple(connections),
            help='Nominates the LDAP database to introspect. Defaults to the first one using this backend.',
        )
        parser.add_argument(
            '--sample',
            type=int,
            default=20,
            help='How many child entries to read per DN when deciding which attributes to emit (default: 20).',
        )
        parser.add_argument(
            '--all',
            action='store_true',
            dest='emit_all',
            help='Add all fields that the objectClasses allow, including the operational ones. '
            'By default only the attributes found on at least one sample will be created as fields.',
        )
        parser.add_argument(
            '--scope',
            default=DEFAULT_SCOPE,
            choices=sorted(SCOPES),
            help=f'search_scope for the generated model. Default: {DEFAULT_SCOPE}).',
        )
        parser.add_argument(
            '--model-name',
            dest='model_names',
            action='append',
            default=[],
            help='Class name for the generated model. Repeat once per DN, in the same order.',
        )

    def handle(self, **options):
        connection = resolve_ldap_connection(connections, options['database'])
        if options['sample'] < 1:
            raise CommandError('--sample must be at least 1.')

        model_names = options['model_names']
        if model_names and len(model_names) != len(options['dns']):
            raise CommandError(f'Got {len(model_names)} --model-name values for {len(options["dns"])} DNs.')

        for line in render_module(self.build_models(connection, options)):
            self.stdout.write(line)

    def build_models(self, connection, options) -> list[ModelSpec | EmptyContainer]:
        introspection = connection.introspection
        password_algorithm = self._password_algorithm(connection)
        models = []
        for index, dn in enumerate(options['dns']):
            model_name = options['model_names'][index] if options['model_names'] else model_name_from_dn(dn)
            models.append(self.build_model(introspection, dn, model_name, options, password_algorithm))
        return models

    @staticmethod
    def _password_algorithm(connection) -> str:
        configured = connection.settings_dict.get('PASSWORD_HASHING_ALGORITHM') or DEFAULT_PASSWORD_ALGORITHM
        try:
            return LDAPPasswordAlgorithm(configured).name
        except ValueError:
            return DEFAULT_PASSWORD_ALGORITHM

    def build_model(
        self, introspection, dn: str, model_name: str, options, password_algorithm: str
    ) -> ModelSpec | EmptyContainer:
        try:
            sample = introspection.sample_container(dn, options['sample'])
        except DatabaseError as exc:
            raise CommandError(f'Could not read {dn!r}: {exc}') from exc

        if not sample.entry_count:
            return EmptyContainer(dn)

        # if the passed DN is itself just a single entry, we'll just check the parent
        base_dn = parent_dn(dn) or dn if sample.direct_entry else dn

        seen_object_classes = sample.structural_object_classes
        object_classes = introspection.get_minimal_object_classes(seen_object_classes)
        must, may = introspection.get_object_class_attributes(seen_object_classes)

        schema_attributes = {name.lower(): name for name in must + may}
        populated = {name.lower(): name for name in sample.populated}
        must_set = {name.lower() for name in must}

        emitted = sorted(
            (must_set | (schema_attributes.keys() & populated.keys())) - EXCLUDED_ATTRIBUTES,
            key=str.lower,
        )
        unused = sorted(schema_attributes.keys() - set(emitted) - EXCLUDED_ATTRIBUTES, key=str.lower)
        operational = sorted(populated.keys() - schema_attributes.keys() - EXCLUDED_ATTRIBUTES, key=str.lower)

        context = BuildContext(sample=sample, must=must_set, password_algorithm=password_algorithm)

        by_requirement: dict[bool, list[FieldSpec]] = {True: [], False: []}
        for key in emitted:
            spec, required = self._build_field(
                introspection, schema_attributes.get(key, populated.get(key, key)), context
            )
            by_requirement[required].append(spec)
        sections = [
            FieldSection(heading, fields)
            for heading, fields in (('Required', by_requirement[True]), ('Optional', by_requirement[False]))
            if fields
        ]

        if options['emit_all']:
            for heading, keys, lookup in (
                ('Allowed by the objectClasses above but unset on every sampled entry:', unused, schema_attributes),
                (
                    'Operational/Read-only attributes:',
                    operational,
                    populated,
                ),
            ):
                if keys:
                    fields = [self._build_field(introspection, lookup[key], context)[0] for key in keys]
                    sections.append(FieldSection(heading, fields))

        return ModelSpec(
            name=model_name,
            base_dn=base_dn,
            object_classes={name: sample.object_classes[name] for name in object_classes},
            entry_count=sample.entry_count,
            search_scope=None if options['scope'] == DEFAULT_SCOPE else options['scope'],
            notes=self._add_notes(sample),
            sections=sections,
            primary_key_name=context.primary_key_name,
        )

    @staticmethod
    def _add_notes(sample: ContainerSample) -> list[str]:
        if sample.direct_entry:
            notes = [
                f'{sample.dn} has no children, so the provided DN itself was sampled ',
                'and base_dn was moved up to its parent. Make sure that the entries you want',
                'really are sibling-DNs',
            ]
        else:
            notes = [f'Built from {sample.entry_count} entries sampled below this DN.']

        notes += [
            'If there are attributes that have multiple values, `multi_valued_field` will be set.',
            'Since LDAP schemas declare almost every attribute multi-valued, we cannot rely on that information.',
            'Check all fields manually for `multi_valued_field`.',
        ]

        if len(sample.rdn_attributes) > 1:
            spread = ', '.join(f'{attr}={count}' for attr, count in sample.rdn_attributes.most_common())
            notes.append(f'The RDN of the sampled entries do not match: {spread}.')
            notes.append('Check that primary_key is on the right field before using this model.')
        return notes

    @staticmethod
    def _get_unique_field_name(attribute: str, used_names: set[str]) -> str:
        name = normalize_attribute_name(attribute)
        candidate = name
        suffix = 0
        while candidate in used_names:
            suffix += 1
            candidate = f'{name}_{suffix}'
        used_names.add(candidate)
        return candidate

    def _build_field(self, introspection, attribute: str, context: BuildContext) -> tuple[FieldSpec, bool]:
        info = introspection.attribute_info(attribute)
        if info is None:
            info = AttributeInfo(
                name=attribute,
                aliases=(attribute,),
                field_class='CharField',
                syntax='',
                max_length=255,
                single_value=True,
                read_only=False,
                obsolete=False,
                description='',
                syntax_known=False,
            )

        sample = context.sample
        field_name = self._get_unique_field_name(info.name, context.used_names)
        kwargs = [f'db_column={info.name!r}']

        if info.field_class == 'PasswordField':
            kwargs.append(f'algorithm=LDAPPasswordAlgorithm.{context.password_algorithm}')

        if info.max_length and info.field_class in SIZED_FIELD_CLASSES:
            kwargs.append(f'max_length={info.max_length}')

        if info.name in sample.multi_valued:
            kwargs.append('multi_valued_field=True')

        is_primary_key = sample.rdn_attribute is not None and info.name.lower() == sample.rdn_attribute.lower()
        required = (
            is_primary_key
            or info.read_only
            or (info.name.lower() in context.must and sample.populated[info.name] == sample.entry_count)
        )
        if is_primary_key:
            kwargs.append('primary_key=True')
            context.primary_key_name = field_name
        elif info.read_only:
            kwargs.append('read_only=True')
        elif not required:
            kwargs.append('blank=True')
            kwargs.append('null=True')

        return FieldSpec(name=field_name, field_class=info.field_class, kwargs=kwargs), required
