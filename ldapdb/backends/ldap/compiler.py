import logging
from typing import TYPE_CHECKING, Any, NamedTuple, cast

import ldap
from django.db import NotSupportedError
from django.db.models import Lookup
from django.db.models.expressions import Col, Expression
from django.db.models.fields import Field
from django.db.models.lookups import Exact, In
from django.db.models.sql import compiler
from django.db.models.sql.compiler import PositionRef, SQLCompiler as BaseSQLCompiler
from django.db.models.sql.constants import CURSOR, GET_ITERATOR_CHUNK_SIZE, MULTI
from django.db.models.sql.where import NothingNode, WhereNode

from ldapdb.exceptions import LDAPModelTypeError
from ldapdb.models import LDAPModel, LDAPQuery
from ldapdb.models.fields import UpdateStrategy
from ldapdb.utils import escape_ldap_filter_value
from .ldif_helpers import AddRequest, ModifyRequest
from .lib import LDAPSearch, LDAPSearchControlType
from .lookups import LDAP_OPERATORS

try:
    from django.db.models.sql.constants import ROW_COUNT
except ImportError:
    # Django 5.2 introduced new ROW_COUNT constant
    ROW_COUNT = 'row count'

if TYPE_CHECKING:
    from collections.abc import Callable

    from ldap.ldapobject import ReconnectLDAPObject

    from .base import DatabaseWrapper

logger = logging.getLogger(__name__)


class SelectInfo(NamedTuple):
    """A 3-tuples consisting of (expression, (sql, params), alias)"""

    column: Expression
    sql_data: tuple[str, list[Any]]
    alias: str


class SQLCompiler(BaseSQLCompiler):
    connection: 'DatabaseWrapper'
    query: LDAPQuery
    DEFAULT_ORDERING_RULE = 'caseIgnoreOrderingMatch'  # rfc3417 / 2.5.13.3

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        model = self.query.model
        if not issubclass(model, LDAPModel):
            raise LDAPModelTypeError(model)

        self.annotation_aliases = []
        self.field_mapping = {field.attname: field.column for field in model._meta.fields}
        self.reverse_field_mapping = {field.column: field for field in model._meta.fields}

    def _get_ldap_conn(self) -> 'ReconnectLDAPObject':
        """
        Makes sure the connection is established and returns the underlying LDAP connection object.
        The alternative to this method would be to use something like the following:

        with self.connection.cursor() as cursor:
            cursor.db.connection.add_s(dn, add.as_modlist())

        That however always builds a new cursor object, which is not needed here,
        since we don't use anything in the cursor.
        Maybe revisit this later if we need to use cursors for something else.
        Something like django-debug-toolbar would use the cursor to display the executed queries,
        but since we want to provide proper LDAP search/query information,
        we'd have to implement custom handling via Signals or another solution, anyway.

        Also: This works without ensure_connection() for django versions >= 5.1. Not for 4.2.
        """
        self.connection.ensure_connection()
        return self.connection.connection

    def _pk_value_from_where(self):
        # only used in Update and Delete compilers
        where = self.query.where
        model = self.query.model
        pk_field = model._meta.pk

        if where.connector != 'AND' or len(where.children) != 1:
            raise NotSupportedError('Only simple primary-key updates are supported.')

        cond = where.children[0]
        if isinstance(cond, Exact) and cond.lhs.target is pk_field:
            return cond.rhs

        if isinstance(cond, In) and cond.lhs.target is pk_field and len(cond.rhs) == 1:
            # obj.delete() resolves to Model.objects.filter(pk__in=[pk])._raw_delete(), so it used the "In" lookup
            return cond.rhs[0]

        raise NotSupportedError('UPDATE/DELETE must be filtered by the primary key.')

    def _get_annotated_target_colums(self, expr):
        from django.db.models.expressions import Col

        if isinstance(expr, Col):
            yield expr.target.column
            return

        # recurse only on real sub‑expressions
        for node in expr.get_source_expressions() or ():
            if node is not None:
                yield from self._get_annotated_target_colums(node)

    def _compile_select(self) -> list[str]:
        """
        Compile the SELECT part of the query.
        This is used to determine which attributes are fetched from the server.

        The order in which the selected_fields are returned is very important here.
        Otherwise the instanced LDAPModel objects might have the values of their fields swapped.

        :return: An ordered list of LDAP attribute names to fetch (including DN, which won't be passed to search call).
        """
        attrlist = []

        for sel in self.select:
            sel = SelectInfo(*sel)
            if isinstance(sel.column, Col):
                ldap_attr = sel.column.target.column
                attrlist.append(ldap_attr)
            else:
                self.annotation_aliases.append(sel.alias)

        # There might be columns referenced in annotations that are not selected via .values/values_list()
        extra_cols = set()
        for expr in self.query.annotations.values():
            extra_cols.update(self._get_annotated_target_colums(expr))
        attrlist.extend([attr for attr in extra_cols if attr not in attrlist])
        self.query.annotation_source_cols = frozenset(extra_cols)  # keep them for later annotations
        return attrlist

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

        render: Callable[[str, str, Any], str | None] | None = getattr(lhs.field, 'render_lookup', None)
        if callable(render):
            ldap_filter: str = render(field_name, lookup_type, rhs)
            if ldap_filter is not None:
                return ldap_filter

        operator_format, _ = LDAP_OPERATORS.get(lookup_type, (None, None))

        if lookup_type == 'in':
            values = ''.join([f'({field_name}={escape_ldap_filter_value(v)})' for v in rhs])
            ldap_filter = f'(|{values})'
            logger.debug("Generated LDAP filter for 'in' lookup: %s", ldap_filter)
            return ldap_filter
        elif lookup_type == 'isnull':
            ldap_filter = f'(!({field_name}=*))' if rhs else f'({field_name}=*)'
            logger.debug("Generated LDAP filter for 'isnull' lookup: %s", ldap_filter)
            return ldap_filter
        elif isinstance(rhs, list | tuple):
            if len(rhs) == 0:
                # Empty list means no matches; return an always-false filter
                return '(!(objectClass=*))'
            if not operator_format:
                raise NotImplementedError(f'Unsupported lookup type: {lookup_type}')
            parts = []
            for v in rhs:
                escaped_value = escape_ldap_filter_value(v)
                parts.append(f'({field_name}{operator_format % escaped_value})')
            ldap_filter = f'(|{"".join(parts)})'
            logger.debug(
                "Generated LDAP filter for lookup '%s' with list RHS: %s",
                lookup_type,
                ldap_filter,
            )
            return ldap_filter
        elif operator_format:
            escaped_value = escape_ldap_filter_value(rhs)
            ldap_filter = f'({field_name}{operator_format % escaped_value})'
            logger.debug("Generated LDAP filter for lookup '%s': %s", lookup_type, ldap_filter)
            return ldap_filter
        raise NotImplementedError(f'Unsupported lookup type: {lookup_type}')

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
            elif isinstance(child, NothingNode):
                subfilters.append('(!(objectClass=*))')
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

    def _compile_order_by(self) -> list[tuple[str, str]]:
        ordering_rules = []
        for order_expr, _order_data in self.get_order_by():
            order_expr: Col | PositionRef
            if not isinstance(order_expr.expression, Col | PositionRef):
                raise NotImplementedError(f'Unsupported order expression type: {type(order_expr.expression)}')

            attrname = order_expr.field.column
            ordering_rule = getattr(order_expr.field, 'ordering_rule', None)
            if order_expr.descending:
                attrname = f'-{attrname}'
            ordering_rules.append((attrname, ordering_rule if ordering_rule else self.DEFAULT_ORDERING_RULE))

        if not ordering_rules:
            # Use the primary key as a fallback if no order_by is specified. We need some kind of ordering for SSSVLV.
            # TODO: Maybe swap to Simple Pagination when order_by is unset?
            pk_field = self.query.model._meta.pk
            ordering_rule = getattr(pk_field, 'ordering_rule', None)
            ordering_rules.append((pk_field.db_column, ordering_rule if ordering_rule else self.DEFAULT_ORDERING_RULE))

        logger.debug('Order by fields for LDAP query: %s', ordering_rules)
        return ordering_rules

    def _build_ldap_search(self, with_limits):
        ordering_rules = self._compile_order_by()
        ldap_search = LDAPSearch(
            base=self.query.model.base_dn,
            scope=self.query.model.search_scope,
            attrlist=self._compile_select(),
            filterstr=self._compile_where(),
            ordering_rules=ordering_rules,  # only used when searching via SSSVLV for now
            offset=self.query.low_mark,
        )
        if with_limits and self.query.high_mark:
            ldap_search.limit = self.query.high_mark - self.query.low_mark

        if self.connection.features.supports_sssvlv and ordering_rules:
            ldap_search.control_type = LDAPSearchControlType.SSSVLV
        elif self.connection.features.supports_simple_paged_results:
            ldap_search.control_type = LDAPSearchControlType.SIMPLE_PAGED_RESULTS
        else:
            ldap_search.control_type = LDAPSearchControlType.NO_CONTROL
        return ldap_search

    def as_sql(self, with_limits=True, with_col_aliases=False) -> tuple[LDAPQuery, tuple]:
        logger.debug('SQLCompiler.as_sql: with_limits=%s, with_col_aliases=%s', with_limits, with_col_aliases)

        # Run pre_sql_setup to make sure self.has_extra_select is set
        self.pre_sql_setup(
            with_col_aliases=with_col_aliases or bool(self.query.combinator),
        )

        # TODO: Handle slicing on Non-SSSVLV queries
        if (self.query.low_mark or self.query.high_mark) and not self.connection.features.supports_sssvlv:
            raise NotSupportedError('Slicing is not supported without VLV control.')

        self.query.annotation_aliases = self.annotation_aliases
        self.query.ldap_search = self._build_ldap_search(with_limits)

        # Normally returns "sql, params" but we want the whole query instance passed to the cursors execute() method
        return self.query, ()

    def execute_sql(self, result_type=MULTI, chunked_fetch=False, chunk_size=GET_ITERATOR_CHUNK_SIZE):
        logger.debug('SQLCompiler.execute_sql: %s, %s, %s', result_type, chunked_fetch, chunk_size)
        return super().execute_sql(result_type, chunked_fetch, chunk_size)


class SQLUpdateCompiler(compiler.SQLUpdateCompiler, SQLCompiler):
    def execute_sql(self, returning_fields=None):  # noqa: ARG002 - don't need returning_fields, we just force another search
        model = cast('LDAPModel', cast('object', self.query.model))
        db = cast('DatabaseWrapper', self.connection)
        ldap_conn = self._get_ldap_conn()
        charset = db.charset

        pk_val = self._pk_value_from_where()
        dn = f'{model._meta.pk.column}={pk_val},{model.base_dn}'

        with db.wrap_database_errors:
            try:
                _, entry = ldap_conn.search_s(dn, ldap.SCOPE_BASE)[0]
            except ldap.NO_SUCH_OBJECT:
                # This might happen if an object is created via .save().
                # Returning 0 here forces Django to use the SQLInsertCompiler.
                return 0

        mod = ModifyRequest()
        mod.charset = charset

        for field, _model, raw_val in self.query.values:
            attr = field.column
            old_vals: list[bytes] = entry.get(attr, [])

            if raw_val is None:
                new_vals = []
            else:
                prepped = field.get_db_prep_save(raw_val, db)
                new_vals = list(prepped) if isinstance(prepped, list | tuple) else [prepped]

            if not getattr(field, 'binary_field', False):
                old_vals = [v.decode(charset) if isinstance(v, bytes | bytearray) else v for v in old_vals]
                new_vals = [v.decode(charset) if isinstance(v, bytes | bytearray) else v for v in new_vals]

            if old_vals == new_vals:
                continue

            if not new_vals:
                mod.delete(attr)
            elif not old_vals:
                mod.add(attr, new_vals)
            else:
                if (
                    getattr(field, 'update_strategy', UpdateStrategy.REPLACE) == UpdateStrategy.ADD_DELETE
                    and field.multi_valued_field
                ):
                    to_add = set(new_vals) - set(old_vals)
                    to_delete = set(old_vals) - set(new_vals)
                    if to_add:
                        mod.add(attr, to_add)
                    if to_delete:
                        mod.delete(attr, to_delete)
                else:
                    mod.replace(attr, new_vals)

        if not mod:
            logger.debug('No changes after diff for %s — skipping modify_s().', dn)
            return 1

        logger.debug('LDAP modify request for %s\n%s', dn, mod)

        with db.wrap_database_errors:
            ldap_conn.modify_s(dn, mod.as_modlist())

        return 1


class SQLInsertCompiler(compiler.SQLInsertCompiler, SQLCompiler):
    """
    Supports `Model.objects.create(...)` and `obj.save(force_insert=True)`.
    """

    def execute_sql(self, returning_fields=None):  # noqa: ARG002
        if len(self.query.objs) != 1:
            raise NotSupportedError('bulk_insert() not implemented yet')

        obj = cast('LDAPModel', self.query.objs[0])
        model = cast('LDAPModel', cast('object', self.query.model))
        db = cast('DatabaseWrapper', self.connection)
        ldap_conn = self._get_ldap_conn()

        # build DN
        pk_field = model._meta.pk
        rdn_val = getattr(obj, pk_field.attname)
        obj.dn = obj.build_dn(rdn_val)

        add = AddRequest()
        add.charset = db.charset
        add.add('objectClass', model.object_classes)

        for field in model._meta.local_fields:
            if field.primary_key:
                continue

            value = getattr(obj, field.attname)
            if value is None:
                continue

            prep = field.get_db_prep_save(value, db)
            if not isinstance(prep, list | tuple):
                prep = [prep]

            add.add(field.column, prep)

        logger.debug('LDAP add request for %s\n%s', obj.dn, add)

        with self.connection.wrap_database_errors:
            # make sure any exceptions bubble up as proper Django errors
            ldap_conn.add_s(obj.dn, add.as_modlist())

        return []  # Django does not care about the return value of execute_sql() for INSERTs


class SQLDeleteCompiler(compiler.SQLDeleteCompiler, SQLCompiler):
    def execute_sql(
        self,
        # result_type here is set via DeleteQuery.do_query().
        # Starting with Django 5.2 it should be ROW_COUNT. Before that it was CURSOR.
        result_type=MULTI,
        **_kwargs,
    ):
        model = cast('LDAPModel', cast('object', self.query.model))
        ldap_conn = self._get_ldap_conn()

        pk_val = self._pk_value_from_where()
        dn = f'{model._meta.pk.column}={pk_val},{model.base_dn}'

        logger.debug('LDAP delete request for %s', dn)

        with self.connection.wrap_database_errors:
            try:
                ldap_conn.delete_s(dn)
                deleted_count = 1
            except ldap.NO_SUCH_OBJECT:
                deleted_count = 0

        if result_type is CURSOR:  # Django <= 5.1
            cur = self.connection.cursor()
            cur.rowcount = deleted_count
            return cur

        return deleted_count


class SQLAggregateCompiler(compiler.SQLAggregateCompiler, SQLCompiler):
    pass
