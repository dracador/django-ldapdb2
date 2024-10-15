import logging
from dataclasses import dataclass

import ldap
from django.db.models import Lookup
from django.db.models.expressions import Col
from django.db.models.fields import Field
from django.db.models.sql import compiler
from django.db.models.sql.compiler import SQLCompiler as BaseSQLCompiler
from django.db.models.sql.constants import GET_ITERATOR_CHUNK_SIZE, MULTI
from django.db.models.sql.where import WhereNode
from ldap.ldapobject import ReconnectLDAPObject

from ldapdb.models import LDAPModel
from ldapdb.utils import escape_ldap_filter_value

logger = logging.getLogger(__name__)


@dataclass
class LDAPSearch:
    base: str
    filterstr: str
    attrlist: list[str] = frozenset(['*', '+'])
    scope: ldap.SCOPE_BASE | ldap.SCOPE_ONELEVEL | ldap.SCOPE_SUBTREE = ldap.SCOPE_SUBTREE
    order_by: list[tuple[str, str]] = None  # not part of the default LDAP search itself, but can be used via SSSVLV

    def __eq__(self, other):
        if not isinstance(other, LDAPSearch):
            return False
        return self.serialize() == other.serialize()

    def __dict__(self):
        return self.serialize()

    def serialize(self):
        return {
            'base': self.base,
            'filterstr': self.filterstr,
            'attrlist': sorted(self.attrlist),
            'scope': self.scope,
            'order_by': sorted(self.order_by) if self.order_by else None,
        }

    def search_s(self, connection: ReconnectLDAPObject):
        # Should be called through the Compiler/Query.execute() method but is helpful in tests
        return connection.search_s(self.base, self.scope, self.filterstr, self.attrlist)


class LDAPQuery:
    def __init__(
        self,
        base: str,
        ldap_scope: int,
        ldap_filter: str = None,
        ldap_attributes: set = None,
        ldap_ordering: list[tuple[str, str]] = None,
    ):
        self.ldap_attributes = ldap_attributes or {'*', '+'}
        self.ldap_base = base
        self.ldap_filter = ldap_filter or '(objectClass=*)'
        self.ldap_ordering = ldap_ordering or []
        self.ldap_scope = ldap_scope

    def generate_ldap_search(self) -> LDAPSearch:
        attrlist = [attr for attr in self.ldap_attributes if attr != 'dn'] if self.ldap_attributes else ['*', '+']

        return LDAPSearch(
            base=self.ldap_base,
            filterstr=self.ldap_filter if self.ldap_filter else '(objectClass=*)',
            attrlist=attrlist,
            scope=self.ldap_scope,
            order_by=self.ldap_ordering,
        )


class SQLCompiler(BaseSQLCompiler):
    DEFAULT_ORDERING_RULE = 'caseIgnoreOrderingMatch'  # rfc3417 / 2.5.13.3

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        model = self.query.model
        if issubclass(model, LDAPModel):
            self.ldap_query = LDAPQuery(model.base_dn, model.search_scope)
        else:
            raise TypeError(f'Expected model to be a subclass of LDAPModel but LDAPModel not in MRO: {model.__mro__}')

    def _compile_select(self):
        """
        The default get_select handles the following cases, which we not yet support:
        - annotation_select
        - extra_select
        - select_related
        """
        all_field_names = [field.column for field in self.query.model._meta.fields]

        if self.query.deferred_loading[0]:
            fields: list[Field] = self.query.deferred_loading[0]
            defer: bool = self.query.deferred_loading[1]
            if defer:
                selected_fields = [field for field in all_field_names if field not in fields]
            else:
                selected_fields = [field for field in all_field_names if field in fields]
        else:
            selected_fields = all_field_names

        self.ldap_query.ldap_attributes = selected_fields
        logger.debug('Selected fields for LDAP query: %s', selected_fields)

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

        # TODO: Get optional operator from LDAPField or maybe we can get the Field.is_multiple or something
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
        where_node = self.query.where
        if not where_node:
            return

        ldap_filter = self._where_node_to_ldap_filter(where_node)
        self.ldap_query.ldap_filter = ldap_filter
        logger.debug('Compiled LDAP filter: %s', ldap_filter)

    def _compile_order_by(self):
        ordering_rules = []
        for order_expr, _order_data in self.get_order_by():
            attrname = order_expr.field.column
            ordering_rule = getattr(order_expr.field, 'ordering_rule', None)
            if order_expr.descending:
                attrname = f'-{attrname}'
            ordering_rules.append((attrname, ordering_rule if ordering_rule else self.DEFAULT_ORDERING_RULE))
        if not ordering_rules:
            pk_field = self.query.model._meta.pk
            ordering_rule = getattr(pk_field, 'ordering_rule', None)
            ordering_rules.append((pk_field.column, ordering_rule if ordering_rule else self.DEFAULT_ORDERING_RULE))

        self.ldap_query.ldap_ordering = ordering_rules
        logger.debug("Order by fields for LDAP query: %s", ordering_rules)

    # Debug only
    def as_sql(self, with_limits=True, with_col_aliases=False) -> LDAPSearch:
        logger.debug(f'SQLCompiler.as_sql: with_limits={with_limits}, with_col_aliases={with_col_aliases}')  # noqa: G004
        self._compile_select()
        self._compile_where()
        self._compile_order_by()
        return self.ldap_query.generate_ldap_search()

    def execute_sql(self, result_type=MULTI, chunked_fetch=False, chunk_size=GET_ITERATOR_CHUNK_SIZE):
        logger.debug('SQLCompiler.execute_sql: %s, %s, %s', result_type, chunked_fetch, chunk_size)
        return super().execute_sql(result_type, chunked_fetch, chunk_size)

    def results_iter(
        self,
        results=None,
        tuple_expected=False,
        chunked_fetch=False,
        chunk_size=GET_ITERATOR_CHUNK_SIZE,
    ):
        logger.debug('SQLCompiler.results_iter: %s, %s, %s, %s', results, tuple_expected, chunked_fetch, chunk_size)
        return super().results_iter(results)


class SQLInsertCompiler(compiler.SQLInsertCompiler, SQLCompiler):
    pass


class SQLDeleteCompiler(compiler.SQLDeleteCompiler, SQLCompiler):
    pass


class SQLAggregateCompiler(compiler.SQLAggregateCompiler, SQLCompiler):
    pass
