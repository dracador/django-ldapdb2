from collections.abc import Collection
from typing import TYPE_CHECKING, Any, Protocol, cast

import ldap
from asgiref.sync import sync_to_async
from django.core.exceptions import ValidationError
from django.db import DEFAULT_DB_ALIAS, NotSupportedError, connections, models as django_models
from django.db.models import QuerySet
from django.db.models.base import ModelState
from django.db.models.sql import Query

from ldapdb.backends.ldap.lib import LDAPScope, escape_ldap_rdn_chars
from ldapdb.exceptions import LDAPModelTypeError
from ldapdb.iterables import (
    LDAPFlatValuesListIterable,
    LDAPModelIterable,
    LDAPNamedValuesListIterable,
    LDAPValuesIterable,
    LDAPValuesListIterable,
)
from ldapdb.typing_compat import Self, override
from .fields import PasswordField, PrimaryDistinguishedNameField

if TYPE_CHECKING:
    from django.db.models.options import Options

    from ldapdb.backends.ldap import LDAPSearch


class LDAPQuery(Query):
    model: 'LDAPModel'

    def __init__(self, model, **kwargs):
        super().__init__(model, **kwargs)

        if not issubclass(model, LDAPModel):
            raise LDAPModelTypeError(model)

        self.annotation_aliases: list = []
        self.ldap_search: LDAPSearch | None = None

    def __str__(self) -> str:
        """
        Normal __str__ method calls self.sql_with_params(),
        which is not compatible with LDAP.
        """
        return f'{self.__class__}.ldap_search: {self.ldap_search.serialize()}'


class LDAPQuerySet(QuerySet):
    query: LDAPQuery

    def __init__(self, model=None, query=None, using=None, hints=None):
        if query is None:
            query = LDAPQuery(model)
        super().__init__(model=model, query=query, using=using, hints=hints)
        self._iterable_class = LDAPModelIterable

    def update(self, **kwargs):
        pk_name = self.model._meta.pk.attname
        if pk_name in kwargs:
            raise NotSupportedError(
                'Updating the primary key requires an LDAP rename. '
                'Assign the field on the instance and call .save() to rename entries, instead.'
            )
        return super().update(**kwargs)

    def values(self, *fields, **expressions):
        qs = super().values(*fields, **expressions)
        qs._iterable_class = LDAPValuesIterable
        return qs

    def values_list(self, *fields, **kwargs):
        flat = kwargs.get('flat', False)
        named = kwargs.get('named', False)

        qs = super().values_list(*fields, **kwargs)

        if named:
            qs._iterable_class = LDAPNamedValuesListIterable
        elif flat:
            qs._iterable_class = LDAPFlatValuesListIterable
        else:
            qs._iterable_class = LDAPValuesListIterable
        return qs

    def raw(self, *_args, **_kwargs):
        # Maybe allow raw to take an LDIF input or an LDAPSearch instance?
        raise AssertionError('Raw queries not supported with LDAP backend')

    # ------------------------------------------------------------------ #
    # Async ORM methods                                                  #
    # ------------------------------------------------------------------ #
    #
    # These override Django's defaults (which are ``await sync_to_async(...)``
    # over the sync method) so that the LDAP search is dispatched on the
    # event loop via :class:`LDAPClient`'s async methods. Inside one event
    # loop, ``asyncio.gather`` over multiple ``aget``/``acount`` calls
    # multiplexes them on a single LDAP connection by msgid.
    #
    # The model-construction step still runs through Django's sync ORM
    # machinery (compiler/iterables/from_db) — but on rows we already
    # fetched. See :class:`PrefetchedDatabaseCursor` for the bridge.

    async def aget(self, *args, **kwargs):
        target_qs = self.filter(*args, **kwargs) if (args or kwargs) else self
        return await _aget_via_async_cursor(target_qs)

    async def acount(self):
        rows, _ = await _async_fetch_rows(self)
        return len(rows)

    async def afirst(self):
        qs = self if self.ordered else self.order_by('pk')
        # ``qs[:1].aget()`` would raise DoesNotExist on empty; we want None
        # to match Django's first() semantics.
        rows, _ = await _async_fetch_rows(qs[:1])
        if not rows:
            return None
        # Materialize via the prefetched-cursor bridge so the model is
        # built by Django's normal machinery.
        return await _aget_from_rows(qs[:1], rows)

    async def aexists(self):
        rows, _ = await _async_fetch_rows(self[:1])
        return bool(rows)


async def _async_fetch_rows(qs: 'LDAPQuerySet') -> tuple[list, list | None]:
    """Compile the queryset and execute it via :class:`AsyncDatabaseCursor`.

    Returns ``(rows, description)`` exactly as the cursor would expose them.
    Used as the primitive for ``acount``/``afirst``/``aexists`` and as the
    first half of ``aget``/``_aget_from_rows``.
    """
    from ldapdb.backends.ldap.async_cursor import AsyncDatabaseCursor

    db = qs.db
    wrapper = connections[db]

    def _compile() -> LDAPQuery:
        compiler = qs.query.get_compiler(using=db)
        return compiler.as_sql()[0]

    ldap_query = await sync_to_async(_compile, thread_sensitive=True)()
    client = await wrapper.aget_async_client()
    async_cursor = AsyncDatabaseCursor(client, settings_dict=wrapper.settings_dict)
    try:
        await async_cursor.aexecute(ldap_query)
        return list(async_cursor.results), async_cursor.description
    finally:
        await async_cursor.aclose()


async def _aget_from_rows(qs: 'LDAPQuerySet', rows: list, description: list | None = None):
    """Materialize a single model from pre-fetched rows.

    Bridges into Django's sync ``qs.get()`` via :class:`PrefetchedDatabaseCursor`.
    Raises ``DoesNotExist``/``MultipleObjectsReturned`` like the sync path.
    """
    from ldapdb.backends.ldap.cursor import (
        PrefetchedDatabaseCursor,
        reset_prefetched_cursor,
        use_prefetched_cursor,
    )

    prefetched = PrefetchedDatabaseCursor(rows, description)
    token = use_prefetched_cursor(prefetched)
    try:
        return await sync_to_async(qs.get, thread_sensitive=True)()
    finally:
        reset_prefetched_cursor(token)


async def _aget_via_async_cursor(qs: 'LDAPQuerySet'):
    rows, description = await _async_fetch_rows(qs)
    return await _aget_from_rows(qs, rows, description)


class LDAPModel(django_models.Model):
    base_dn: str = None
    base_filter: str = '(objectClass=*)'  # the base filter will be always be applied to all queries
    search_scope: LDAPScope = ldap.SCOPE_SUBTREE
    object_classes: list[str] = None  # TODO: object_classes should be a ListField of some sort

    objects = LDAPQuerySet.as_manager()

    dn = PrimaryDistinguishedNameField(db_column='dn', unique=True, read_only=True, hidden=True)

    class Meta:
        abstract = True

        # Force base manager to use LDAPQuery instances.
        # Will also trickle down to subclasses without them having it explicitly set in model._meta.
        base_manager_name = 'objects'

    @classmethod
    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)

        cls._check_non_abstract_inheritance()
        cls._check_required_attrs()

    def save(self, *args, **kwargs):
        """
        If the PK (RDN) changed, perform an LDAP rename first,
        then proceed with Django's normal save/update.
        """
        using = kwargs.get('using') or self._state.db or DEFAULT_DB_ALIAS

        if not self._state.adding and getattr(self, 'dn', None):
            new_dn = self.build_dn_from_pk(escape_chars=False)
            new_dn_escaped = self.build_dn_from_pk(escape_chars=True)
            if new_dn_escaped != self.escaped_dn:
                new_rdn = self.build_rdn(self.rdn_value, escape_chars=True)
                conn = connections[using]
                with conn.wrap_database_errors:
                    conn.ldap_client.rename(self.escaped_dn, new_rdn)
                self.dn = new_dn

        return super().save(*args, **kwargs)

    @override
    @classmethod
    def from_db(cls, db: str, field_names: Collection[str], values: Collection[Any], fetch_mode: Any = None) -> Self:
        instance = cls.__new__(cls)
        instance.__dict__.update(dict(zip(field_names, values, strict=False)))

        instance._state = ModelState()
        instance._state.adding = False
        instance._state.db = db
        if fetch_mode is not None:
            instance._state.fetch_mode = fetch_mode
        return instance

    @classmethod
    def _check_required_attrs(cls):
        if not cls._meta.abstract:
            for required_attribute in ['base_dn', 'object_classes', 'search_scope']:
                if getattr(cls, required_attribute, None) is None:
                    raise ValueError(f'{cls.__name__} is missing the required attribute {required_attribute}')

    @classmethod
    def _check_non_abstract_inheritance(cls):
        """
        This function is to make sure no non-abstract Django model is subclassed.
        The default Django behavior is to create a new table for each subclass and reference the parent model
        via an automatically generated OneToOneField.
        Since we don't have tables in LDAP, we don't want to allow this behavior.
        Users will have to opt to using abstract models instead.
        """
        for base in cls.__bases__:
            if issubclass(base, django_models.Model) and not base._meta.abstract and base != django_models.Model:
                raise TypeError(
                    f'Cannot subclass non-abstract model "{base.__name__}" in "{cls.__name__}". '
                    'Only abstract models can be subclassed in this LDAP backend.'
                )

    @classmethod
    def build_rdn(cls, rdn_value: str, escape_chars: bool = True) -> str:
        pk_field = cls._meta.pk
        if escape_chars:
            rdn_value = escape_ldap_rdn_chars(rdn_value)

        # sanity check to prevent injections via NUL byte
        if rdn_value.find('\x00') != -1:
            raise ValidationError('RDN value cannot contain NUL bytes')

        return f'{pk_field.column}={rdn_value}'

    @property
    def rdn_value(self) -> str:
        pk_field = self._meta.pk
        return getattr(self, pk_field.attname)

    @classmethod
    def build_dn(cls, rdn_value: str, escape_chars: bool = True) -> str:
        return f'{cls.build_rdn(rdn_value, escape_chars)},{cls.base_dn}'

    @property
    def escaped_dn(self) -> str:
        """
        Extract rdn from dn, escape it, and rebuild dn

        Note: Cannot use str2dn here because self.dn is unencoded.
        If the DN contains a special char, it just breaks since str2dn cannot explode it.

        But: We can just get the correct RDN by stripping the configured base_dn.
        """
        suffix = f',{self.base_dn}'
        if not self.dn.endswith(suffix):
            raise ValueError(f'DN {self.dn!r} does not end with base_dn {self.base_dn!r}')
        rdn = self.dn[: -len(suffix)].split('=', 1)[-1]
        return self.build_dn(rdn, escape_chars=True)

    def build_dn_from_pk(self, escape_chars: bool = True) -> str:
        """
        Build the DN from the *current* PK value.
        When changing the primary key (renaming), "self.dn" still contains the old DN.
        To build the new DN, we need to build it from the current PK value.
        """
        return self.build_dn(self.rdn_value, escape_chars)


class PasswordMixinProtocol(Protocol):
    _meta: 'Options'

    def _get_password_field(self, name: str | None) -> 'PasswordField': ...


class LDAPPasswordMixin:
    """
    Mixin for LDAPModels to provide a set_password API with automatic field discovery.
    Imitates the default django behaviour for User models.
    When updating PasswordFields, we automatically convert them to the correct format in pre_save and get_db_prep_save.
    However, libraries like django-auditlog catch the raw password before pre_save is called.
    We should encourage users to use set_password instead of directly setting the password attribute.
    """

    def _get_password_field(self: 'PasswordMixinProtocol', name: str | None) -> 'PasswordField':
        if name:
            return cast('PasswordField', self._meta.get_field(name))

        password_fields = [f for f in self._meta.fields if isinstance(f, PasswordField)]
        if not password_fields:
            raise ValueError(f'No PasswordField found on {self.__class__.__name__}.')

        if len(password_fields) > 1:
            field_names = [f.name for f in password_fields]
            raise ValueError(
                f'Multiple PasswordFields found ({", ".join(field_names)}). Please specify field_name explicitly.'
            )

        return password_fields[0]

    def set_password(self: 'PasswordMixinProtocol', raw_password: str, field_name: str | None = None) -> None:
        """
        Hashes and sets the password. If field_name is None, it automatically
        finds the PasswordField on the model.
        """
        from ldapdb.models.fields import PasswordField

        field = self._get_password_field(field_name)
        hashed = PasswordField.generate_password_hash(raw_password, field.algorithm, **field.handler_opts)
        setattr(self, field.attname, hashed)
