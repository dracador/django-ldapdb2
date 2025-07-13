from django.db import NotSupportedError
from django.db.models.query import ModelIterable

from ldapdb.backends.ldap.expressions import eval_expr


class LDAPExpressionIterable(ModelIterable):
    def __iter__(self):
        for obj in super().__iter__():
            for alias, expr in self.queryset.query.annotations.items():
                try:
                    result = eval_expr(expr, obj)
                except NotImplementedError as e:
                    raise NotSupportedError(f'Expression of type {type(expr)} is not supported in LDAP queries') from e

                setattr(obj, alias, result)
            yield obj
