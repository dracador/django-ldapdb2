from collections import Counter
from dataclasses import dataclass, field
from functools import cached_property
from typing import TYPE_CHECKING

import ldap
from django.db.backends.base.introspection import BaseDatabaseIntrospection
from ldap.schema import AttributeType, ObjectClass, SubSchema

from .lib import LDAPRawSearchOp

if TYPE_CHECKING:
    from ldapdb.backends.ldap.base import DatabaseWrapper

DEFAULT_SYNTAX = '1.3.6.1.4.1.1466.115.121.1.15'  # Directory String -> CharField
SYNTAX_FIELD_CLASSES = {
    '1.3.6.1.1.16.1': 'CharField',  # UUID
    '1.3.6.1.4.1.1466.115.121.1.5': 'BinaryField',  # Binary
    '1.3.6.1.4.1.1466.115.121.1.6': 'CharField',  # Bit String
    '1.3.6.1.4.1.1466.115.121.1.7': 'BooleanField',  # Boolean
    '1.3.6.1.4.1.1466.115.121.1.8': 'BinaryField',  # Certificate
    '1.3.6.1.4.1.1466.115.121.1.9': 'BinaryField',  # Certificate List
    '1.3.6.1.4.1.1466.115.121.1.10': 'BinaryField',  # Certificate Pair
    '1.3.6.1.4.1.1466.115.121.1.11': 'CharField',  # Country String
    '1.3.6.1.4.1.1466.115.121.1.12': 'DistinguishedNameField',  # DN
    '1.3.6.1.4.1.1466.115.121.1.14': 'CharField',  # Delivery Method
    '1.3.6.1.4.1.1466.115.121.1.15': 'CharField',  # Directory String
    '1.3.6.1.4.1.1466.115.121.1.22': 'CharField',  # Facsimile Telephone Number
    '1.3.6.1.4.1.1466.115.121.1.23': 'BinaryField',  # Fax
    '1.3.6.1.4.1.1466.115.121.1.24': 'DateTimeField',  # Generalized Time
    '1.3.6.1.4.1.1466.115.121.1.26': 'CharField',  # IA5 String
    '1.3.6.1.4.1.1466.115.121.1.27': 'IntegerField',  # INTEGER
    '1.3.6.1.4.1.1466.115.121.1.28': 'BinaryField',  # JPEG
    '1.3.6.1.4.1.1466.115.121.1.34': 'CharField',  # Name And Optional UID
    '1.3.6.1.4.1.1466.115.121.1.36': 'CharField',  # Numeric String
    '1.3.6.1.4.1.1466.115.121.1.38': 'CharField',  # OID
    '1.3.6.1.4.1.1466.115.121.1.40': 'BinaryField',  # Octet String
    '1.3.6.1.4.1.1466.115.121.1.41': 'TextField',  # Postal Address
    '1.3.6.1.4.1.1466.115.121.1.44': 'CharField',  # Printable String
    '1.3.6.1.4.1.1466.115.121.1.50': 'CharField',  # Telephone Number
    '1.3.6.1.4.1.1466.115.121.1.52': 'CharField',  # Telex Number
    '1.3.6.1.4.1.1466.115.121.1.53': 'DateTimeField',  # UTC Time
}

ATTRIBUTE_NAME_FIELD_CLASSES = {
    'mail': 'EmailField',
    'member': 'MemberField',
    'uniquemember': 'MemberField',
    'userpassword': 'PasswordField',
}

EXCLUDED_ATTRIBUTES = set(
    'objectClass',  # is handled as a non-field (for now)
)


@dataclass(frozen=True)
class AttributeInfo:
    name: str  # will be the db_column later
    aliases: tuple[str, ...]  # NAMEs as decribed in the schema
    field_class: str
    syntax: str
    max_length: int | None
    single_value: bool
    read_only: bool  # "NO-USER-MODIFICATION" or non-"userApplications"
    obsolete: bool
    description: str
    syntax_known: bool


@dataclass
class ContainerSample:
    dn: str
    entry_count: int
    object_classes: Counter = field(default_factory=Counter)
    rdn_attributes: Counter = field(default_factory=Counter)
    populated: Counter = field(default_factory=Counter)
    multi_valued: set[str] = field(default_factory=set)
    direct_entry: bool = False

    @property
    def structural_object_classes(self) -> list[str]:
        return [name for name, _count in self.object_classes.most_common()]

    @property
    def rdn_attribute(self) -> str | None:
        if not self.rdn_attributes:
            return None
        return self.rdn_attributes.most_common(1)[0][0]


class DatabaseIntrospection(BaseDatabaseIntrospection):
    connection: 'DatabaseWrapper'
    data_types_reverse = {oid: f'ldapdb.models.fields.{cls}' for oid, cls in SYNTAX_FIELD_CLASSES.items()}

    def get_table_list(self, *_):
        return []

    def get_table_description(self, *_):
        return []

    def get_relations(self, *_):
        return {}

    def get_constraints(self, *_):
        return {}

    def get_key_columns(self, *_):
        return []

    def get_sequences(self, *_):
        return []

    def _raw_search(self, dn, scope, attrlist=None, filterstr='(objectClass=*)', sizelimit=0):
        with self.connection.cursor() as cursor:
            cursor.execute(
                LDAPRawSearchOp(dn=dn, scope=scope, attrlist=attrlist, filterstr=filterstr, sizelimit=sizelimit)
            )
            return cursor.fetchall()

    @cached_property
    def subschema_dn(self) -> str:
        advertised = self.connection.features.rootdse_data.get('subschemaSubentry')
        if advertised:
            return advertised[0].decode()
        return 'cn=subschema'  # (fallback only works for OpenLDAP)

    @cached_property
    def subschema(self) -> SubSchema:
        results = self._raw_search(self.subschema_dn, ldap.SCOPE_BASE, attrlist=['*', '+'])
        if not results:
            raise self.connection.Database.DatabaseError(
                f'Server advertised a subschema subentry at {self.subschema_dn!r} but it could not be read.'
            )
        _dn, entry = results[0]
        return SubSchema(entry)

    def resolve_syntax(self, attribute_type: AttributeType) -> tuple[str, int | None]:
        seen = set()
        current = attribute_type
        while current is not None and current.oid not in seen:
            seen.add(current.oid)
            if current.syntax:
                return current.syntax, current.syntax_len
            if not current.sup:
                break
            # some attributes don't have a syntax, so we need to check their respective SUP
            current = self.subschema.get_obj(AttributeType, current.sup[0])
        return DEFAULT_SYNTAX, None

    def attribute_info(self, name: str) -> AttributeInfo | None:
        attribute_type = self.subschema.get_obj(AttributeType, name)
        if attribute_type is None:
            return None

        canonical = attribute_type.names[0] if attribute_type.names else name
        syntax, max_length = self.resolve_syntax(attribute_type)
        field_class = ATTRIBUTE_NAME_FIELD_CLASSES.get(canonical.lower()) or SYNTAX_FIELD_CLASSES.get(syntax)

        operational = attribute_type.usage != 0

        return AttributeInfo(
            aliases=tuple(attribute_type.names or (name,)),
            description=attribute_type.desc or '',
            field_class=field_class or SYNTAX_FIELD_CLASSES[DEFAULT_SYNTAX],
            max_length=max_length,
            name=canonical,
            obsolete=attribute_type.obsolete,
            read_only=attribute_type.no_user_mod or operational,
            single_value=attribute_type.single_value,
            syntax=syntax,
            syntax_known=field_class is not None,
        )

    @staticmethod
    def _find_attribute_names(attribute_types: dict) -> list[str]:
        names = {at.names[0] for at in attribute_types.values() if at is not None and at.names}
        return sorted(names, key=str.lower)

    def _find_object_class(self, name: str) -> str:
        object_class = self.subschema.get_obj(ObjectClass, name)
        if object_class is not None and object_class.names:
            return object_class.names[0]
        return name

    def get_object_class_ancestors(self, name: str) -> set[str]:
        ancestors: set[str] = set()
        pending = [name]
        while pending:
            object_class = self.subschema.get_obj(ObjectClass, pending.pop())
            if object_class is None:
                continue
            for sup in object_class.sup:
                canonical = self._find_object_class(sup)
                if canonical not in ancestors:
                    ancestors.add(canonical)
                    pending.append(canonical)
        return ancestors

    def get_object_class_attributes(self, names) -> tuple[list[str], list[str]]:
        # .attribute_types() here already returns the SUP chain, too
        must, may = self.subschema.attribute_types(list(names), raise_keyerror=0)
        return self._find_attribute_names(must), self._find_attribute_names(may)

    def get_minimal_object_classes(self, names) -> list[str]:
        """Only get the actual required objectClasses without the full SUP chain"""
        names = list(names)
        implied: set[str] = set()
        for name in names:
            implied |= self.get_object_class_ancestors(name)

        minimal = []
        for name in names:
            object_class = self.subschema.get_obj(ObjectClass, name)
            is_abstract = object_class is not None and object_class.kind == 1
            if name not in implied and not is_abstract:
                minimal.append(name)
        return sorted(minimal or names, key=str.lower)

    def sample_container(self, dn: str, limit: int, include_operational: bool = True) -> ContainerSample:
        attrlist = ['*', '+'] if include_operational else ['*']
        entries = self._raw_search(dn, ldap.SCOPE_ONELEVEL, attrlist=attrlist, sizelimit=limit)
        direct_entry = not entries
        if direct_entry:
            entries = self._raw_search(dn, ldap.SCOPE_BASE, attrlist=attrlist)

        sample = ContainerSample(dn=dn, entry_count=len(entries), direct_entry=direct_entry)
        for entry_dn, attrs in entries:
            for value in attrs.get('objectClass', []):
                sample.object_classes[value.decode()] += 1

            rdn = ldap.dn.explode_dn(entry_dn, notypes=False)[0]
            sample.rdn_attributes[rdn.split('=', 1)[0]] += 1

            for attr_name, values in attrs.items():
                info = self.attribute_info(attr_name)
                canonical = info.name if info else attr_name
                sample.populated[canonical] += 1
                if len(values) > 1:
                    sample.multi_valued.add(canonical)

        return sample
