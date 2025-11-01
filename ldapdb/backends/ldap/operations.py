from typing import TYPE_CHECKING, Any

from django.db.backends.base.operations import BaseDatabaseOperations

from .transaction import TxnRequestControl

if TYPE_CHECKING:
    from ldapdb.models import LDAPQuery
    from .base import DatabaseWrapper


class DatabaseOperations(BaseDatabaseOperations):
    connection: 'DatabaseWrapper'
    compiler_module = 'ldapdb.backends.ldap.compiler'

    def get_db_converters(self, expression):
        converters = super().get_db_converters(expression)
        field = expression.output_field

        def _unwrap_and_decode(value, _, __):
            if value is None:
                return value

            if not getattr(field, 'multi_valued_field', False) and isinstance(value, list | tuple):
                value = value[0]

            if isinstance(value, bytes | bytearray):
                value = value.decode(self.connection.charset)

            return value

        if not getattr(field, 'binary_field', False):
            converters.append(_unwrap_and_decode)
        return converters

    @staticmethod
    def get_txn_serverctrls(db_wrapper: 'DatabaseWrapper') -> list:
        ctrls = []
        if db_wrapper._in_txn:
            ctrls.append(TxnRequestControl(db_wrapper._txn_id))
        return ctrls

    def quote_name(self, name):
        return name

    def sql_flush(self, *_args, **_kwargs):
        # LDAP does not support SQL flush
        return []

    def execute_sql_flush(self, *_args, **_kwargs):
        return None

    def no_limit_value(self):
        # LDAP does not support limiting query results in the query itself.
        # Would need to be done via PAGE_SIZE database setting
        return None

    def last_executed_query(self, cursor: Any, sql: 'LDAPQuery', params: Any) -> str:  # noqa: ARG002
        return str(sql)

    # We *could* implement the following methods, but they are not necessary for the LDAP backend
    def date_extract_sql(self, lookup_type, field_name, **kwargs):
        # LDAP does not support date extraction
        raise NotImplementedError('LDAP does not support date extraction')

    def date_trunc_sql(self, lookup_type, field_name, **kwargs):
        # LDAP does not support date truncation
        raise NotImplementedError('LDAP does not support date truncation')

    def time_trunc_sql(self, lookup_type, field_name, **kwargs):
        # LDAP does not support time truncation
        raise NotImplementedError('LDAP does not support time truncation')

    def datetime_trunc_sql(self, lookup_type, field_name, **kwargs):
        # LDAP does not support datetime truncation
        raise NotImplementedError('LDAP does not support datetime truncation')

    def prepare_sql_script(self, sql):
        # LDAP does not support SQL scripts
        return sql
