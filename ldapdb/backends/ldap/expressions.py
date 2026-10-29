from operator import add, mod, mul, sub, truediv

from django.db.models import Case, Value
from django.db.models.expressions import Col
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
from django.db.models.lookups import Lookup
from django.db.models.sql.where import WhereNode

from ldapdb.backends.ldap.lookups import LDAP_OPERATORS

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


def eval_lookup(expr: Lookup, instance):
    lhs_val = eval_expr(expr.lhs, instance)
    rhs_val = expr.rhs

    if expr.lookup_name == 'in' and not isinstance(rhs_val, list | tuple | set):
        rhs_val = list(rhs_val)

    lookup_name = expr.lookup_name
    if lookup_name is None or lookup_name not in LDAP_OPERATORS:
        raise NotImplementedError(f'Lookup {expr.__class__.__name__} not supported')

    _, py_fn = LDAP_OPERATORS[lookup_name]
    return py_fn(lhs_val, rhs_val)


def eval_expr(expr: object, instance):  # noqa: PLR0911
    match expr:
        case Col(target=field):
            return getattr(instance, field.attname)

        case Lookup():
            return eval_lookup(expr, instance)

        case Value(value=v):
            return v

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
            parts = ['' if (v := eval_expr(p, instance)) is None else str(v) for p in expr.source_expressions]
            return ''.join(parts)

        case Repeat():
            s = eval_expr(expr.source_expressions[0], instance) or ''
            number = eval_expr(expr.source_expressions[1], instance)
            if number is None:
                return None
            return s * number

        case Replace():
            s, old, new = (eval_expr(p, instance) for p in expr.source_expressions)
            if s is None or old is None:
                return None
            return s.replace(old, new if new is not None else '')

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

        case WhereNode(children=children, connector='AND', negated=False):
            return all(eval_expr(c, instance) for c in children)

        case WhereNode(children=children, connector='OR', negated=False):
            return any(eval_expr(c, instance) for c in children)

        case Case():
            for when in expr.cases:
                if eval_expr(when.condition, instance):
                    return eval_expr(when.result, instance)
            return eval_expr(expr.default, instance) if expr.default else None

        case _:
            raise NotImplementedError(f'Expression {expr.__class__.__name__} not supported')
