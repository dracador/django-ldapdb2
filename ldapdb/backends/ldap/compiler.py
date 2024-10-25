import logging
from typing import TYPE_CHECKING

from django.db import NotSupportedError
from django.db.models import Lookup
from django.db.models.expressions import Col
from django.db.models.fields import Field
from django.db.models.sql import compiler
from django.db.models.sql.compiler import SQLCompiler as BaseSQLCompiler
from django.db.models.sql.constants import GET_ITERATOR_CHUNK_SIZE, MULTI
from django.db.models.sql.where import WhereNode

from ldapdb.models import LDAPModel
from ldapdb.utils import escape_ldap_filter_value
from .lib import LDAPSearch, LDAPSearchControlType

if TYPE_CHECKING:
    from .base import DatabaseWrapper

logger = logging.getLogger(__name__)


class SQLCompiler(BaseSQLCompiler):
    connection: 'DatabaseWrapper'
    DEFAULT_ORDERING_RULE = 'caseIgnoreOrderingMatch'  # rfc3417 / 2.5.13.3

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        model = self.query.model
        if issubclass(model, LDAPModel):
            self.ldap_query = LDAPSearch(base=model.base_dn, scope=model.search_scope)
        else:
            raise TypeError(f'Expected model to be a subclass of LDAPModel but LDAPModel not in MRO: {model.__mro__}')

        self.field_mapping = {field.attname: field.column for field in self.query.model._meta.fields}
        self.reverse_field_mapping = {field.column: field for field in self.query.model._meta.fields}

    def _compile_select(self) -> set[str]:
        # TODO: Implement annotations & Related fields
        selected_fields = set()

        for select_info in self.query.select:
            if hasattr(select_info, 'target'):
                field = select_info.target
                field_name = field.attname
                selected_fields.add(field_name)

        # if self.query.annotations:
        #     selected_fields.update(self.query.annotations.keys())

        if selected_fields:
            selected_columns = {self.field_mapping[field_name] for field_name in selected_fields}
        else:
            selected_columns = set(self.field_mapping.values())

        logger.debug('Selected LDAP attributes for query: %s', selected_columns)
        return selected_columns

    def _parse_lookup(self, lookup: Lookup) -> str:
        """Convert a Lookup to an LDAP filter string using the defined operators."""
        lhs = lookup.lhs
        rhs = lookup.rhs

        if isinstance(lhs, Col):
            field_name = lhs.target.column
        elif isinstance(lhs, Field):
            field_name = lhs.column
        else:
            raise NotImplementedError(f'Unsupported lhs type: {type(lhs)}')

        lookup_type = lookup.lookup_name

        # TODO: Get optional operator from LDAPField
        operator_format = self.connection.operators.get(lookup_type)

        if operator_format is None:
            raise NotImplementedError(f'Unsupported lookup type: {lookup_type}')

        if lookup_type == 'in':
            values = ''.join([f'({field_name}={escape_ldap_filter_value(v)})' for v in rhs])
            ldap_filter = f'(|{values})'
            logger.debug("Generated LDAP filter for 'in' lookup: %s", ldap_filter)
            return ldap_filter
        elif lookup_type == 'isnull':
            ldap_filter = f'(!({field_name}=*))' if rhs else f'({field_name}=*)'
            logger.debug("Generated LDAP filter for 'isnull' lookup: %s", ldap_filter)
            return ldap_filter
        else:
            escaped_value = escape_ldap_filter_value(rhs)
            ldap_filter = f'({field_name}{operator_format % escaped_value})'
            logger.debug("Generated LDAP filter for lookup '%s': %s", lookup_type, ldap_filter)
            return ldap_filter

    def _where_node_to_ldap_filter(self, node: WhereNode) -> str:
        """Recursively convert a WhereNode to an LDAP filter string."""
        if node.connector == 'AND':
            ldap_operator = '&'
        elif node.connector == 'OR':
            ldap_operator = '|'
        else:
            raise NotImplementedError(f'Unsupported connector type: {node.connector}')

        subfilters = []
        logger.debug('WhereNode: %s, %s, %s', node, node.negated, len(node.children))
        for child in node.children:
            if isinstance(child, WhereNode):
                subfilter = self._where_node_to_ldap_filter(child)
                subfilters.append(subfilter)
            elif isinstance(child, Lookup):
                subfilter = self._parse_lookup(child)
                subfilters.append(subfilter)
            else:
                raise TypeError(f'Unsupported child type: {type(child)}')

        combined_filter = ''.join(subfilters)

        logger.debug(
            'WhereNode: negated=%s, operator=%s, combined=%s, length=%s',
            node.negated,
            ldap_operator,
            combined_filter,
            len(subfilters),
        )

        if len(subfilters) == 1:
            if node.negated:
                return f'(!{combined_filter})'
            else:
                return combined_filter
        else:
            if node.negated:
                return f'(!({ldap_operator}{combined_filter}))'
            else:
                return f'({ldap_operator}{combined_filter})'

    def _compile_where(self):
        base_filter = getattr(self.query.model, 'base_filter', '(objectClass=*)')
        where_node = self.query.where
        if not where_node:
            return base_filter

        ldap_filter = self._where_node_to_ldap_filter(where_node)
        ldap_filter = f'(&{base_filter}{ldap_filter})'
        logger.debug('Compiled LDAP filter: %s', ldap_filter)
        return ldap_filter

    def _compile_order_by(self):
        ordering_rules = []
        for order_expr, _order_data in self.get_order_by():
            if not isinstance(order_expr.expression, Col):
                raise NotImplementedError(f'Unsupported order expression type: {type(order_expr.expression)}')

            attrname = order_expr.field.column
            ordering_rule = getattr(order_expr.field, 'ordering_rule', None)
            if order_expr.descending:
                attrname = f'-{attrname}'
            ordering_rules.append((attrname, ordering_rule if ordering_rule else self.DEFAULT_ORDERING_RULE))

        logger.debug('Order by fields for LDAP query: %s', ordering_rules)
        return ordering_rules

    def as_sql(self, with_limits=True, with_col_aliases=False) -> tuple[LDAPSearch, tuple]:
        logger.debug('SQLCompiler.as_sql: with_limits=%s, with_col_aliases=%s', with_limits, with_col_aliases)

        # Run pre_sql_setup to make sure self.has_extra_select is set
        self.pre_sql_setup(
            with_col_aliases=with_col_aliases or bool(self.query.combinator),
        )

        # TODO: Handle slicing on Non-SSSVLV queries
        if (self.query.low_mark or self.query.high_mark) and not self.connection.features.supports_sssvlv:
            raise NotSupportedError('Slicing is not supported without VLV control.')

        self.ldap_query.attrlist = self._compile_select()
        self.ldap_query.filterstr = self._compile_where()
        self.ldap_query.order_by = self._compile_order_by()  # only used when searching via SSSVLV

        self.ldap_query.offset = self.query.low_mark
        if with_limits and self.query.high_mark:
            self.ldap_query.limit = self.query.high_mark - self.query.low_mark

        if self.connection.features.supports_sssvlv:
            self.ldap_query.control_type = LDAPSearchControlType.SSSVLV
        elif self.connection.features.supports_simple_paged_results:
            self.ldap_query.control_type = LDAPSearchControlType.PAGED_RESULTS

        return self.ldap_query, ()

    def execute_sql(self, result_type=MULTI, chunked_fetch=False, chunk_size=GET_ITERATOR_CHUNK_SIZE):
        logger.debug('SQLCompiler.execute_sql: %s, %s, %s', result_type, chunked_fetch, chunk_size)
        return super().execute_sql(result_type, chunked_fetch, chunk_size)


class SQLInsertCompiler(compiler.SQLInsertCompiler, SQLCompiler):
    pass


class SQLDeleteCompiler(compiler.SQLDeleteCompiler, SQLCompiler):
    pass


class SQLAggregateCompiler(compiler.SQLAggregateCompiler, SQLCompiler):
    pass
