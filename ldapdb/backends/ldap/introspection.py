from collections import namedtuple
from functools import cached_property
from typing import TYPE_CHECKING

import ldap
from django.db.backends.base.introspection import BaseDatabaseIntrospection
from django.db.backends.utils import CursorWrapper
from ldap import explode_dn
from ldap.schema import AttributeType, ObjectClass, SubSchema

if TYPE_CHECKING:
    from ldapdb.backends.ldap.base import DatabaseWrapper

FieldInfo = namedtuple(
    'FieldInfo',
    (
        'name',
        'type_code',
        'display_size',
        'internal_size',
        'precision',
        'scale',
        'null_ok',
        'default',
        'collation',
        'is_autofield',
        'comment',
    ),
)
TableInfo = namedtuple('TableInfo', ['name', 'type'])
LDAPObjectInfo = namedtuple('LDAPObjectInfo', ['dn', 'attrs'])


class DatabaseIntrospection(BaseDatabaseIntrospection):
    connection: 'DatabaseWrapper'
    data_types_reverse = {
        '1.3.6.1.4.1.1466.115.121.1.5': 'ldapdb.fields.BinaryField',  # Binary
        '1.3.6.1.4.1.1466.115.121.1.7': 'ldapdb.fields.BooleanField',  # Boolean
        '1.3.6.1.4.1.1466.115.121.1.12': 'ldapdb.fields.DistinguishedNameField',  # DistinguishedName
        '1.3.6.1.4.1.1466.115.121.1.15': 'ldapdb.fields.CharField',  # DirectoryString
        '1.3.6.1.4.1.1466.115.121.1.24': 'ldapdb.fields.DateTimeField',  # GeneralizedTime
        '1.3.6.1.4.1.1466.115.121.1.26': 'ldapdb.fields.CharField',  # IA5String
        '1.3.6.1.4.1.1466.115.121.1.27': 'ldapdb.fields.IntegerField',  # Integer
        '1.3.6.1.4.1.1466.115.121.1.40': 'ldapdb.fields.BinaryField',  # OctetString
        # Unsupported Fields (for now):
        # '1.3.6.1.1.16.1': 'UUIDField',  # UUID
    }
    default_data_type = '1.3.6.1.4.1.1466.115.121.1.15'  # -> CharField
    ldap_objects: dict[str, LDAPObjectInfo] = {}

    def get_object(self, dn: str) -> LDAPObjectInfo:
        if dn not in self.ldap_objects:
            res = self.connection.connection.search_s(
                base=dn,
                scope=ldap.SCOPE_BASE,
                filterstr='(objectClass=*)',
                attrlist=['*']
            )
            if not res:
                raise ldap.NO_SUCH_OBJECT  # TODO: Check what to raise here

            dn, attrs = res[0]
            self.ldap_objects[dn] = LDAPObjectInfo(dn, attrs)
        return self.ldap_objects[dn]

    @cached_property
    def subschema(self) -> SubSchema:
        res = self.connection.connection.search_s(
            'cn=subschema',
            ldap.SCOPE_BASE,
            attrlist=['*', '+'],  # ["attributeTypes", "objectClasses"]
        )
        _, entry = res[0]
        return SubSchema(entry)

    def get_syntax(self, attribute: AttributeType) -> str:
        """
        Returns the syntax OID for the given attribute.
        If the attribute is not found, returns the default data type OID.
        """
        if attribute.syntax:
            return attribute.syntax

        for sup in attribute.sup:
            syntax = self.subschema.get_syntax(sup)
            if syntax:
                return syntax
        return self.default_data_type

    def get_table_list(self, cursor: CursorWrapper | None):
        # In our implementation, a table is pointing to a specific DN from which the model will be built.
        # We *could* search via SUBTREE scope to create models of all objects we find, but for now we force "tables" to
        # be specified via inspectdb/inspectldap options. So let's return an empty list.
        # table_list = [TableInfo(oc.decode(), 't') for oc in self._obj.attrs['objectClass']]
        # return table_list
        return []

    def get_required_attributes(self, object_classes: list[bytes]) -> set[str]:
        required_attributes = set()
        for oc_name in object_classes:
            oc: ObjectClass = self.subschema.get_obj(ObjectClass, oc_name.decode())
            if oc.must:
                required_attributes.update(oc.must)
        return required_attributes

    def get_table_description(self, cursor, table_name) -> list[FieldInfo]:
        obj = self.get_object(table_name)
        object_classes = obj.attrs['objectClass']
        required_attributes = self.get_required_attributes(object_classes)

        description: list[FieldInfo] = []
        for attribute in obj.attrs:
            if attribute == 'objectClass':
                continue

            at: AttributeType = self.subschema.get_obj(AttributeType, attribute)

            default = None
            comment = ''
            syntax = self.get_syntax(at)
            if syntax not in self.data_types_reverse:
                comment = f'Unknown attribute type with OID: {at.syntax}. Defaulting to TextField.'
                syntax = self.default_data_type

            max_length = None
            # TODO: set is_multi_value from at.single_value, db_column, max_length
            fi = FieldInfo(
                attribute,
                type_code=syntax,
                display_size=None,
                internal_size=max_length,
                precision=None,
                scale=None,
                null_ok=attribute not in required_attributes,
                default=default,
                collation='',  # LDAP does not use collation
                comment=comment,
                is_autofield=False,
            )
            description.append(fi)
        return description

    def get_primary_key_columns(self, cursor: CursorWrapper | None, table_name: str) -> list[str] | None:
        rdn = explode_dn(table_name)[0]
        return [rdn.split('=')[0]]

    def get_relations(self, *_):
        return {}

    def get_constraints(self, *_):
        return {}

    def get_key_columns(self, *_):
        return []

    def get_sequences(self, *_):
        return []
