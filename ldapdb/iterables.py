from collections.abc import Iterator
from types import SimpleNamespace
from typing import TYPE_CHECKING

from django.db import NotSupportedError
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
    from collections import namedtuple
    from typing import Any

    from django.db.models import Model

    from ldapdb.models import LDAPQuerySet


class LDAPBaseIterable(BaseIterable):
    queryset: 'LDAPQuerySet'

    def _columns(self):
        """
        Return the exact column order requested by the caller.

        • If the user passed explicit field names to values_list(), Django stores them on `self._fields`.
        • Otherwise fall back to model field list plus annotation aliases.
        """
        if getattr(self.queryset, '_fields', None):
            return list(self.queryset._fields)  # type: ignore[attr-defined]

        # fallback for .values_list() with no arguments
        return list(self.queryset.query.values_select) + list(self.queryset.query.annotation_aliases)

    def __iter__(self) -> Iterator:
        for raw in super().__iter__():  # type: ignore[attr-defined]
            data = self._row_to_dict(raw)
            self._evaluate_annotations(data)
            output = self._dict_to_output(raw, data)
            yield output

    def _evaluate_annotations(self, row_dict: dict) -> None:
        annotations = self.queryset.query.annotations
        if not annotations:
            return

        proxy = SimpleNamespace(**row_dict)
        for alias, expr in annotations.items():
            try:
                row_dict[alias] = eval_expr(expr, proxy)
            except NotImplementedError as e:
                raise NotSupportedError(f'Expression {expr.__class__.__name__} not supported in LDAP queries') from e

    def _row_to_dict(self, raw) -> dict:
        raise NotImplementedError()

    def _dict_to_output(self, raw, data: dict):
        raise NotImplementedError()


class LDAPModelIterable(LDAPBaseIterable, ModelIterable):
    def _row_to_dict(self, obj: 'Model') -> dict:
        return obj.__dict__

    def _dict_to_output(self, obj: 'Model', _data: dict) -> 'Model':
        return obj


class LDAPValuesIterable(LDAPBaseIterable, ValuesIterable):
    def _row_to_dict(self, data: dict) -> dict:
        return data

    def _dict_to_output(self, _raw, data: dict):
        return data


class LDAPValuesListIterable(LDAPBaseIterable, ValuesListIterable):
    def _row_to_dict(self, raw: tuple):
        return dict(zip(self._columns(), raw, strict=False))

    def _dict_to_output(self, _raw: tuple, data: dict) -> tuple:
        return tuple(data[c] for c in self._columns())


class LDAPFlatValuesListIterable(LDAPBaseIterable, FlatValuesListIterable):
    def _row_to_dict(self, raw: 'Any') -> dict:
        col = self._columns()[0]
        return {col: raw}

    def _dict_to_output(self, _raw: 'Any', data: dict):
        return data[self._columns()[0]]


class LDAPNamedValuesListIterable(LDAPBaseIterable, NamedValuesListIterable):
    def _row_to_dict(self, named: 'namedtuple') -> dict:
        return named._asdict()

    def _dict_to_output(self, named: 'namedtuple', data: dict) -> 'namedtuple':
        return named.__class__(**data)
