from operator import add, mod, mul, sub, truediv

from django.db.models import Case, F, Value
from django.db.models.expressions import Col, Expression
from django.db.models.functions import (
    Abs,
    Coalesce,
    Concat,
    Length,
    Lower,
    LTrim,
    Repeat,
    Replace,
    Round,
    RTrim,
    Trim,
    Upper,
)

_ARITHM_OPS = {
    '+': add,
    '-': sub,
    '*': mul,
    '/': truediv,
    '%': mod,
    '&': lambda a, b: a & b,
    '|': lambda a, b: a | b,
    '^': lambda a, b: a ^ b,
    '<<': lambda a, b: a << b,
    '>>': lambda a, b: a >> b,
}


# noinspection PyUnreachableCode
# Fixed with PyCharm 2025.2 but EAP is unusable right now
def eval_expr(expr: Expression, instance):  # noqa: PLR0911
    match expr:
        case Col(target=field):
            return getattr(instance, field.attname)

        case Value(value=v):
            return v

        case F(name=field_name):
            return getattr(instance, field_name)

        case Lower() | Upper() | Trim() | LTrim() | RTrim():
            base = eval_expr(expr.source_expressions[0], instance)
            if base is None:
                return None
            elif not isinstance(base, str):
                base = str(base)

            match expr:
                case Lower():
                    return base.lower()
                case Upper():
                    return base.upper()
                case Trim():
                    return base.strip()
                case LTrim():
                    return base.lstrip()
                case RTrim():
                    return base.rstrip()
            return None

        case Length():
            s = eval_expr(expr.source_expressions[0], instance)
            return len(s) if s is not None else None

        # case (Substr(pos=start, length=length) | Left(length=length) | Right(length=length)):
        #    s = eval_expr(expr.source_expressions[0], instance)
        #    if s is None:
        #        return None
        #    match expr:
        #        case Substr():
        #            return s[start - 1 : start - 1 + length]
        #        case Left():
        #            return s[:length]
        #        case Right():
        #            return s[-length:]

        case Concat():
            parts = [eval_expr(p, instance) or '' for p in expr.source_expressions]
            return ''.join(parts)

        case Repeat():
            s = eval_expr(expr.source_expressions[0], instance) or ''
            number = eval_expr(expr.source_expressions[1], instance)
            return s * number

        case Replace():
            s, old, new = (eval_expr(p, instance) for p in expr.source_expressions)
            return s.replace(old, new) if s is not None else None

        case Abs() | Round():
            num = eval_expr(expr.source_expressions[0], instance)
            if num is None:
                return None
            precision = eval_expr(expr.source_expressions[1], instance) if isinstance(expr, Round) else None
            return abs(num) if isinstance(expr, Abs) else round(num, precision)

        case Coalesce():
            for child in expr.source_expressions:
                val = eval_expr(child, instance)
                if val is not None:
                    return val
            return None

        # case NullIf():
        #    a = eval_expr(expr.expressions[0], instance)
        #    b = eval_expr(expr.expressions[1], instance)
        #    return None if a == b else a

        # case CombinedExpression(connector=op):
        #    lhs = eval_expr(expr.lhs, instance)
        #    rhs = eval_expr(expr.rhs, instance)
        #    func = _ARITHM_OPS[op]
        #    return func(lhs, rhs)

        case Case():
            for when in expr.cases:
                if when.condition.resolve_expression(instance, allow_joins=False):
                    return eval_expr(when.result, instance)
            return eval_expr(expr.default, instance) if expr.default else None

        case _:
            raise NotImplementedError(f'Expression {expr.__class__.__name__} not supported')
