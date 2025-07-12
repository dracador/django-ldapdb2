from typing import TYPE_CHECKING

from django.db import NotSupportedError
from django.db.models import Value
from django.db.models.functions import Lower, Upper
from django.db.models.query import ModelIterable

if TYPE_CHECKING:
    from django.db.models.expressions import Col


class LDAPExpressionIterable(ModelIterable):
    def __iter__(self):
        for obj in super().__iter__():
            for alias, expr in self.queryset.query.annotations.items():
                expr: Value | Lower | Upper
                result = None

                # noinspection PyUnreachableCode
                # Fixed with PyCharm 2025.2 but EAP is unusable right now
                match expr:
                    case Value(value=v):
                        result = v

                    case Lower() | Upper():
                        src_col: Col = expr.get_source_expressions()[0]
                        attr_name = src_col.target.attname
                        raw_val = getattr(obj, attr_name)
                        if raw_val is not None:
                            result = raw_val.lower() if isinstance(expr, Lower) else raw_val.upper()

                    # TODO: add more expression handling
                    case _:
                        raise NotSupportedError(f'Expression of type {type(expr)} is not supported in LDAP queries')

                setattr(obj, alias, result)
            yield obj
