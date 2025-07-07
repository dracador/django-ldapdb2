from typing import TYPE_CHECKING

from django.db.models.query import ModelIterable

if TYPE_CHECKING:
    from django.db.models import Expression


class LDAPExpressionIterable(ModelIterable):
    def __iter__(self):
        base_iter = super().__iter__()

        query = self.queryset.query
        if not query.annotations:
            yield from base_iter
            return

        # Pre-resolve the compiled annotation expressions once
        annotations: dict[str, Expression] = {
            alias: expr.resolve_expression(query=query, allow_joins=False) for alias, expr in query.annotations.items()
        }

        for obj in base_iter:
            for alias, expr in annotations.items():
                print(f'Evaluating annotation {alias=} for {obj=}, {expr=}')
                # setattr(obj, alias, expr.eval(obj, connection=compiler.connection.get_connection()))
            yield obj
