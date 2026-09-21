import logging
from typing import TYPE_CHECKING, Any, NamedTuple, cast

import ldap
from django.db import DatabaseError, NotSupportedError
from django.db.models import Lookup
from django.db.models.expressions import Col, Combinable, Expression, OrderBy, Ref
from django.db.models.fields import Field
from django.db.models.lookups import Exact, In
from django.db.models.sql import compiler
from django.db.models.sql.compiler import SQLCompiler as BaseSQLCompiler
from django.db.models.sql.constants import CURSOR, GET_ITERATOR_CHUNK_SIZE, MULTI
from django.db.models.sql.where import NothingNode, WhereNode
from ldap.filter import escape_filter_chars

from ldapdb.exceptions import LDAPModelTypeError
from ldapdb.models import LDAPModel, LDAPQuery
from ldapdb.models.fields import LDAPField, PrimaryDistinguishedNameField, UpdateStrategy
from .ldif_helpers import AddRequest, ModifyRequest
from .lib import LDAPAddOp, LDAPDeleteOp, LDAPModifyOp, LDAPRawSearchOp, LDAPSearch, LDAPSearchControlType
from .lookups import LDAP_OPERATORS

try:
    from django.db.models.sql.constants import ROW_COUNT
except ImportError:
    # Django 5.2 introduced new ROW_COUNT constant
    ROW_COUNT = 'row count'

if TYPE_CHECKING:
    from collections.abc import Callable

    from .base import DatabaseWrapper

logger = logging.getLogger(__name__)


def _raised_no_such_object(exc: Exception) -> bool:
    """
    True if *exc* is (or wraps) ldap.NO_SUCH_OBJECT.

    Routing writes through cursor.execute() means Django's CursorWrapper has already
    translated the raw ldap.NO_SUCH_OBJECT into a django.db error by the time it reaches
    the compiler; the original is preserved as __cause__.
    """
    return isinstance(exc, ldap.NO_SUCH_OBJECT) or isinstance(getattr(exc, '__cause__', None), ldap.NO_SUCH_OBJECT)


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

        # Skip primary DN lookups. They are handled by _extract_primary_dn_value
        target_field = lhs.target if isinstance(lhs, Col) else lhs
        if isinstance(target_field, PrimaryDistinguishedNameField):
            return ''

        lookup_type = lookup.lookup_name

        render: Callable[[str, str, Any], str | None] | None = getattr(lhs.field, 'render_lookup', None)
        if callable(render):
            ldap_filter: str = render(field_name, lookup_type, rhs)
            if ldap_filter is not None:
                return ldap_filter

        operator_format, _ = LDAP_OPERATORS.get(lookup_type, (None, None))

        if lookup_type == 'in':
            if not rhs:
                return '(!(objectClass=*))'
            values = ''.join([f'({field_name}={escape_filter_chars(str(v))})' for v in rhs])
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
                escaped_value = escape_filter_chars(str(v))
                parts.append(f'({field_name}{operator_format % escaped_value})')
            ldap_filter = f'(|{"".join(parts)})'
            logger.debug(
                "Generated LDAP filter for lookup '%s' with list RHS: %s",
                lookup_type,
                ldap_filter,
            )
            return ldap_filter
        elif operator_format:
            escaped_value = escape_filter_chars(str(rhs))
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

        subfilters = [sf for sf in subfilters if sf]
        combined_filter = ''.join(subfilters)

        if not subfilters:
            return ''

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

    def _combined_branch_compilers(self) -> list['SQLCompiler']:
        """
        To support stuff like .union(), .intersection() and .difference(), we need to evaluate
        multiple queries inside of self.query.combined_queries.

        Using only the self.query part would lead to only handling the left hand side.
        Example:
             q1 = LDAPUser.objects.filter(username='user1')
             q2 = LDAPUser.objects.filter(username='user2')
             q3 = q1.union(q2)
             ^- q3 here would just evaluate to q1.
        """
        inner_compilers = [
            query.get_compiler(self.using, self.connection, self.elide_empty) for query in self.query.combined_queries
        ]

        model = self.query.model

        reference = inner_compilers[0].query  # the left hand side
        for inner_query in (inner_compiler.query for inner_compiler in inner_compilers):
            if inner_query.model is not model:
                raise NotSupportedError(
                    f'Combining querysets of different models is not supported by the LDAP backend. '
                    f'{model.__name__} and {inner_query.model.__name__} may differ in base_dn, search_scope '
                    f'or base_filter, so they cannot become one search.'
                )
            if inner_query.is_sliced:
                raise NotSupportedError(
                    'Slicing inside of a combined queryset is not supported by the LDAP backend. '
                    'Apply the slicing to the combined queryset instead.'
                )
            if inner_query.where and self._extract_primary_dn_value(inner_query.where) is not None:
                raise NotSupportedError(
                    'Filtering inside of a combined queryset on the primary DN field is not supported. '
                    'The DN is used as the search base, which all queries have to share.'
                )

            selects_match = (
                (inner_query.selected is None or inner_query.selected == reference.selected)
                and inner_query.deferred_loading == reference.deferred_loading
                and tuple(inner_query.annotation_select) == tuple(reference.annotation_select)
            )
            if not selects_match:
                raise NotSupportedError('All individual queries of a combined queryset must select the same fields. ')

        return inner_compilers

    def _compile_combined_where(self) -> str:
        combinator = self.query.combinator
        if combinator not in ('union', 'intersection', 'difference'):
            raise NotSupportedError(f'{combinator}() is not supported by the LDAP backend.')

        if combinator == 'union' and self.query.combinator_all:
            raise NotSupportedError(
                'union(all=True) is not supported by the LDAP backend. Since an LDAP search cannot return '
                'the same entry twice, so there are no duplicates to be preserved.'
            )

        filters = [branch._compile_where() for branch in self._combined_branch_compilers()]

        if combinator == 'union':
            return f'(|{"".join(filters)})'
        if combinator == 'intersection':
            return f'(&{"".join(filters)})'

        head, *subtracted = filters
        negated = ''.join(f'(!{ldap_filter})' for ldap_filter in subtracted)
        return f'(&{head}{negated})'

    def _compile_where(self):
        if self.query.combinator:
            return self._compile_combined_where()

        base_filter = getattr(self.query.model, 'base_filter', '(objectClass=*)')
        where_node = self.query.where
        if not where_node:
            return base_filter

        ldap_filter = self._where_node_to_ldap_filter(where_node)
        if not ldap_filter:
            return base_filter
        ldap_filter = f'(&{base_filter}{ldap_filter})'
        logger.debug('Compiled LDAP filter: %s', ldap_filter)
        return ldap_filter

    def _compile_order_by(self) -> list[tuple[str, str]]:
        ordering_rules = []
        for expr, _order_data in self.get_order_by():
            order_by = cast('OrderBy', expr)

            expression: Combinable = order_by.expression
            if isinstance(expression, Ref):
                # combined querysets (e.g. union + order_by) + bare union via Meta.ordering on django 6.1+
                expression = expression.get_source_expressions()[0]
            if not isinstance(expression, Col):
                raise NotImplementedError(f'Unsupported order expression type: {type(order_by.expression)}')

            field = cast('LDAPField', expression.target)
            attrname = f'-{field.column}' if order_by.descending else field.column
            ordering_rules.append((attrname, field.ordering_rule or self.DEFAULT_ORDERING_RULE))

        if not ordering_rules:
            # Use the primary key as a fallback if no order_by is specified. We need some kind of ordering for SSSVLV.
            # TODO: Maybe swap to Simple Pagination when order_by is unset?
            pk_field = cast('LDAPField', self.query.model._meta.pk)
            attrname = pk_field.db_column if self.query.standard_ordering else f'-{pk_field.db_column}'
            ordering_rules.append((attrname, pk_field.ordering_rule or self.DEFAULT_ORDERING_RULE))

        logger.debug('Order by fields for LDAP query: %s', ordering_rules)
        return ordering_rules

    def _extract_primary_dn_value(self, node: WhereNode) -> str | None:
        """
        Walks the WhereNode to find an exact lookup on PrimaryDistinguishedNameField.

        Returns the DN value if it's in a simple extractable position (top-level AND child),
        or None if not found / not extractable.

        Raises NotSupportedError for unsupported patterns (OR with DN, dn__in with multiple values).
        """
        if not node.children:
            return None

        for child in node.children:
            if isinstance(child, WhereNode):
                result = self._extract_primary_dn_value(child)
                if result is not None:
                    return result
                continue

            if not isinstance(child, Lookup):
                continue

            field = child.lhs.target if isinstance(child.lhs, Col) else child.lhs
            if not isinstance(field, PrimaryDistinguishedNameField):
                continue

            # Found a lookup on the primary DN field
            if node.connector == 'OR':
                raise NotSupportedError(
                    'OR conditions involving the primary DN field are not supported. '
                    'The DN is used as the search base, not as a filter.'
                )

            if isinstance(child, In):
                if len(child.rhs) == 1:
                    return child.rhs[0]
                raise NotSupportedError(
                    'dn__in with multiple values is not supported. '
                    'The DN is used as the search base, so only a single value is allowed.'
                )

            if isinstance(child, Exact):
                return child.rhs

        return None

    def _build_ldap_search(self, with_limits):
        attrlist = self._compile_select()
        control_type = LDAPSearchControlType.NO_CONTROL
        limit = 0
        ordering_rules = None

        # check if the query filters on the primary DN field
        base = self.query.model.base_dn
        scope = self.query.model.search_scope
        dn_value = None

        if self.query.where and not self.query.combinator:
            dn_value = self._extract_primary_dn_value(self.query.where)

        if dn_value:
            base = dn_value
            scope = ldap.SCOPE_BASE

        if attrlist:
            ordering_rules = self._compile_order_by()
            if self.connection.features.supports_sssvlv and ordering_rules:
                control_type = LDAPSearchControlType.SSSVLV
            elif self.connection.features.supports_simple_paged_results:
                control_type = LDAPSearchControlType.SIMPLE_PAGED_RESULTS

            if with_limits and self.query.high_mark:
                limit = self.query.high_mark - self.query.low_mark
        else:
            # tell LDAP server to return no attributes at all,
            # otherwise the server itself will default to all attributes (["*"]).
            # This speeds up queries like .count() significantly.
            attrlist = ['1.1']

        ldap_search = LDAPSearch(
            base=base,
            scope=scope,
            attrlist=attrlist,
            filterstr=self._compile_where(),
            ordering_rules=ordering_rules,  # only used when searching via SSSVLV for now
            offset=self.query.low_mark,
            control_type=control_type,
            limit=limit,
        )
        return ldap_search

    def as_sql(self, with_limits=True, with_col_aliases=False) -> tuple[LDAPQuery, tuple]:
        logger.debug('SQLCompiler.as_sql: with_limits=%s, with_col_aliases=%s', with_limits, with_col_aliases)

        # Run pre_sql_setup to make sure self.has_extra_select is set
        self.pre_sql_setup(
            with_col_aliases=with_col_aliases or bool(self.query.combinator),
        )

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
        db = self.connection
        charset = db.charset

        pk_val = self._pk_value_from_where()
        dn = model.build_dn(pk_val, escape_chars=True)

        # One cursor for the search + modify pair so both count as separate query-log entries.
        with db.wrap_database_errors, db.cursor() as cursor:
            try:
                cursor.execute(LDAPRawSearchOp(dn, ldap.SCOPE_BASE))  # type: ignore[arg-type]
            except (ldap.NO_SUCH_OBJECT, DatabaseError) as exc:
                # This might happen if an object is created via .save().
                # Returning 0 here forces Django to use the SQLInsertCompiler.
                if _raised_no_such_object(exc):
                    return 0
                raise
            _, entry = cursor.fetchall()[0]

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

                use_add_delete = (
                    getattr(field, 'update_strategy', UpdateStrategy.REPLACE) == UpdateStrategy.ADD_DELETE
                    and field.multi_valued_field
                )

                if not new_vals:
                    mod.delete(attr)
                elif not old_vals:
                    mod.add(attr, new_vals)
                elif use_add_delete:
                    to_add = set(new_vals) - set(old_vals)
                    to_delete = set(old_vals) - set(new_vals)
                    if to_add:
                        mod.add(attr, to_add)
                    if to_delete:
                        mod.delete(attr, to_delete)
                else:
                    mod.replace(attr, new_vals)

            if not mod.as_modlist():
                logger.debug('No changes after diff for %s, skipping modify.', dn)
                return 1

            logger.debug('LDAP modify request for %s\n%s', dn, mod)
            cursor.execute(LDAPModifyOp(dn, mod.as_modlist()))  # type: ignore[arg-type]

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
        db = self.connection

        # DN to use for LDAP operation
        dn = obj.build_dn_from_pk(escape_chars=True)

        add = AddRequest()
        add.charset = db.charset
        add.add('objectClass', model.object_classes)

        for field in model._meta.local_fields:
            if field.primary_key:
                continue

            value = self.pre_save_val(field, obj)

            if value is None:
                continue

            prep = field.get_db_prep_save(value, db)
            if not isinstance(prep, list | tuple):
                prep = [prep]

            add.add(field.column, prep)

        logger.debug('LDAP add request for %s\n%s', dn, add)

        with db.wrap_database_errors, db.cursor() as cursor:
            # make sure any exceptions bubble up as proper Django errors
            cursor.execute(LDAPAddOp(dn, add.as_modlist()))  # type: ignore[arg-type]

        # Set obj.dn only for representation in django space.
        obj.dn = obj.build_dn_from_pk(escape_chars=False)

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

        pk_val = self._pk_value_from_where()
        dn = model.build_dn(pk_val, escape_chars=True)

        logger.debug('LDAP delete request for %s', dn)

        with self.connection.wrap_database_errors, self.connection.cursor() as cursor:
            try:
                cursor.execute(LDAPDeleteOp(dn))  # type: ignore[arg-type]
                deleted_count = 1
            except (ldap.NO_SUCH_OBJECT, DatabaseError) as exc:
                if _raised_no_such_object(exc):
                    deleted_count = 0
                else:
                    raise

        if result_type is CURSOR:  # Django <= 5.1
            cur = self.connection.cursor()
            cur.rowcount = deleted_count
            return cur

        return deleted_count


class SQLAggregateCompiler(compiler.SQLAggregateCompiler, SQLCompiler):
    def as_sql(self, with_limits=True, with_col_aliases=False) -> tuple[LDAPQuery, tuple]:
        """
        Django translates aggregates over combined querysets into subqueries.
        Since LDAP has no subqueries, we gotta unwrap the AggregateQuery.
        """
        inner_query: LDAPQuery = self.query.inner_query

        if inner_query.is_sliced:
            raise NotSupportedError('Aggregating over a sliced queryset is not supported by the LDAP backend. ')

        inner_query.annotations = self.query.annotations
        inner_query.default_cols = False
        inner_query.select = ()
        inner_query.set_annotation_mask(self.query.annotation_select)
        inner_query.subquery = False

        self.col_count = len(self.query.annotation_select)
        inner_compiler = inner_query.get_compiler(self.using, self.connection, self.elide_empty)
        return inner_compiler.as_sql(with_limits=with_limits, with_col_aliases=with_col_aliases)
