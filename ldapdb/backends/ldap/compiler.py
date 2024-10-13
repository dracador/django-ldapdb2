import logging
from collections.abc import Sequence
from dataclasses import dataclass

import ldap
from django.db.models.expressions import BaseExpression
from django.db.models.sql import compiler
from django.db.models.sql.compiler import SQLCompiler as BaseSQLCompiler
from django.db.models.sql.constants import GET_ITERATOR_CHUNK_SIZE, MULTI

logger = logging.getLogger(__name__)


@dataclass
class LDAPSearch:
    base: str
    filterstr: str
    attrlist: list[str] = frozenset(['*', '+'])
    scope: ldap.SCOPE_BASE | ldap.SCOPE_ONELEVEL | ldap.SCOPE_SUBTREE = ldap.SCOPE_SUBTREE
    order_by: list[str] = None  # not part of the default LDAP search itself, but can be used via SSSVLV control



class SQLCompiler(BaseSQLCompiler):
    def get_combinator_sql(self, combinator, all):
        logger.debug('SQLCompiler.get_combinator_sql: %s, %s', combinator, all)
        return super().get_combinator_sql(combinator, all)

    def compile(self, node: BaseExpression):
        logger.debug('SQLCompiler.compile: %s, %s', node, type(node))
        # if isinstance(node, WhereNode):
        #    return where_node_as_ldap(node, self, self.connection)
        return super().compile(node)

    # Debug only
    def as_sql(self, with_limits=True, with_col_aliases=False):
        logger.debug('SQLCompiler.as_sql: %s, %s', with_limits, with_col_aliases)
        return super().as_sql(with_limits, with_col_aliases)

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
