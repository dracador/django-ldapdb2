from collections import namedtuple
from collections.abc import Iterator
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

from django.db import NotSupportedError
from django.db.models.expressions import Col, F
from django.db.models.query import (
    BaseIterable,
    FlatValuesListIterable,
    ModelIterable,
    NamedValuesListIterable,
    ValuesIterable,
    ValuesListIterable,
)

from ldapdb.backends.ldap.expressions import eval_expr

if TYPE_CHECKING:
    from django.db.models import Model

    from ldapdb.models import LDAPQuerySet


class LDAPBaseIterable(BaseIterable):
    queryset: 'LDAPQuerySet'

    def _columns(self) -> list[str]:
        """
        Return the exact column order requested by the caller.

        • If the user passed explicit field names to values_list(), Django stores them on `self._fields`.
        • Otherwise fall back to model field list plus annotation aliases.
        """
        if getattr(self.queryset, '_fields', None):
            return list(self.queryset._fields)  # type: ignore[attr-defined]

        # fallback for .values_list() with no arguments
        return list(self.queryset.query.values_select) + list(self.queryset.query.annotation_aliases)

    def _extra_columns(self) -> list[str]:
        q = self.queryset.query
        return list(getattr(q, 'annotation_source_cols', ())) or list(q.values_select)

    def _get_annotation_fields(self) -> set[str]:
        """Extract field names referenced in annotation expressions."""
        referenced_fields = set()
        annotations = self.queryset.query.annotations

        if not annotations:
            return referenced_fields

        def extract_fields(expr):
            if hasattr(expr, 'source_expressions'):
                for sub_expr in expr.source_expressions:
                    extract_fields(sub_expr)
            elif hasattr(expr, 'children'):
                for child in expr.children:
                    extract_fields(child)
            elif hasattr(expr, 'cases'):  # Case expression
                for when in expr.cases:
                    extract_fields(when.condition)
                    extract_fields(when.result)
                if expr.default:
                    extract_fields(expr.default)
            elif hasattr(expr, 'lhs'):  # Lookup
                extract_fields(expr.lhs)
            elif isinstance(expr, Col) and hasattr(expr.target, 'attname'):
                referenced_fields.add(expr.target.attname)
            elif isinstance(expr, F):
                referenced_fields.add(expr.name)

        for expr in annotations.values():
            extract_fields(expr)

        return referenced_fields

    def __iter__(self) -> Iterator:
        # Get annotation fields once for the entire iteration
        annotation_fields = self._get_annotation_fields()

        for raw in super().__iter__():  # type: ignore[attr-defined]
            columns = self._columns()
            extra_columns = self._extra_columns()

            row = self._row_to_dict(raw, columns, extra_columns)

            # Ensure annotation fields exist once per row
            for field_name in annotation_fields:
                row.setdefault(field_name, None)

            self._evaluate_annotations(row)
            output = self._dict_to_output(row, columns)
            yield output

    def _evaluate_annotations(self, row_dict: dict) -> None:
        annotations = self.queryset.query.annotations
        if not annotations:
            return

        proxy = SimpleNamespace(**row_dict)
        try:
            for alias, expr in annotations.items():
                row_dict[alias] = eval_expr(expr, proxy)
        except NotImplementedError as e:
            raise NotSupportedError('Expression not allowed.') from e

    def _row_to_dict(self, raw: Any, columns: list[str], extra_columns: list[str]) -> dict:
        raise NotImplementedError()

    def _dict_to_output(self, raw, columns: list[str]):
        raise NotImplementedError()


class LDAPModelIterable(LDAPBaseIterable, ModelIterable):
    def _row_to_dict(self, obj: 'Model', *_) -> dict:
        return obj.__dict__.copy()  # Copy to avoid mutating original

    def _dict_to_output(self, row_dict: dict, *_) -> 'Model':
        model_cls = self.queryset.model
        return model_cls.from_db(
            self.queryset.db,
            list(row_dict.keys()),
            list(row_dict.values()),
        )


class LDAPValuesIterable(LDAPBaseIterable, ValuesIterable):
    def _row_to_dict(self, raw_dict, *_):
        return raw_dict

    def _dict_to_output(self, row_dict, *_):
        return row_dict


class LDAPValuesListIterable(LDAPBaseIterable, ValuesListIterable):
    def _row_to_dict(self, raw_data, columns, extra_columns):
        if isinstance(raw_data, tuple | list):
            data = dict(zip(extra_columns, raw_data, strict=False))
        else:
            data = {extra_columns[0]: raw_data} if extra_columns else {}

        for col in columns:
            data.setdefault(col, None)

        return data

    def _dict_to_output(self, row_dict, columns):
        return tuple(row_dict[col] for col in columns)


class LDAPFlatValuesListIterable(LDAPBaseIterable, FlatValuesListIterable):
    def _row_to_dict(self, raw_data, columns, extra_columns):
        if hasattr(raw_data, '__dict__') and hasattr(raw_data, '_meta'):
            data = raw_data.__dict__.copy()
            for col in columns:
                if col not in data:
                    try:
                        data[col] = getattr(raw_data, col, None)
                    except AttributeError:
                        data[col] = None
        else:
            if isinstance(raw_data, tuple | list):
                data = dict(zip(extra_columns, raw_data, strict=False))
            else:
                data = {extra_columns[0]: raw_data} if extra_columns else {}

            for col in columns:
                data.setdefault(col, None)

        return data

    def _dict_to_output(self, row_dict, columns):
        return row_dict.get(columns[0]) if columns else None


class LDAPNamedValuesListIterable(LDAPBaseIterable, NamedValuesListIterable):
    def _row_to_dict(self, named: 'namedtuple', *_) -> dict:
        data = named._asdict()
        return data

    def _dict_to_output(self, row_dict: dict, columns: list[str]) -> 'namedtuple':
        NamedRow = namedtuple('Row', columns)
        return NamedRow(*(row_dict[col] for col in columns))
