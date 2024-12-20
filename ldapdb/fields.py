from typing import TYPE_CHECKING

from django.db.models import fields as dj_fields

from .validators import validate_dn

if TYPE_CHECKING:
    # hack to make type checkers happy
    TypeProxyField = dj_fields.Field
else:
    TypeProxyField = object


"""
TODO: Implement the following fields if they make sense
Done:
- CharField
- TextField
- BooleanField
- EmailField
- BinaryField

Untested:
- IntegerField
- FloatField
- DecimalField


Not fully implemented:
- ListField
- DateField
- DateTimeField
- TimeField

- URLField
- UUIDField
- SlugField
- PositiveIntegerField
- PositiveSmallIntegerField
- ManyToManyField
- OneToOneField
- ForeignKey
- GenericIPAddressField
- JSONField
- DurationField
"""


class LDAPFieldMixin(TypeProxyField):
    """
    Base class for all LDAP fields.
    You can opt to subclass this class and handle how the field gets populated.

    Most of Djangos fields actually work without having to subclass LDAPField.
    To make sure we give users a single point of entry for all available LDAP fields,
    we subclass all Django fields here.

    We'll have to make sure that all lookups are either supported or raise an error.

    :param binary_field: If True, the field is a binary field.
    :param multi_valued_field: If True, the field is a multi-valued field.
    :param ordering_rule: The LDAP ordering rule for this field. Is only used when using Server Side Sorting.
    """

    binary_field: bool = False
    multi_valued_field: bool = False
    ordering_rule: str | None = None

    def __init__(
        self,
        *args,
        ordering_rule: str | None = None,
        hidden: bool = False,
        multi_valued_field: bool | None = None,
        **kwargs,
    ):
        """
        :param args:
        :param ordering_rule: Override the LDAP ordering rule for this field.
                              The fields provided by django-ldapdb already have the correct ordering rules set.
        :param hidden: Hide this field from all autogenerated forms and admin interfaces.
        :param kwargs:
        """
        super().__init__(*args, **kwargs)
        if hidden is not None:
            self.hidden = hidden

        if multi_valued_field is not None:
            self.multi_valued_field = multi_valued_field

        if ordering_rule is not None:
            self.ordering_rule = ordering_rule

    @property
    def non_db_attrs(self):
        return super().non_db_attrs + ('binary_field', 'multi_valued_field', 'ordering_rule')

    @classmethod
    def _decode_value(
        cls, value: bytes | str | list[bytes | str] | None, charset='utf-8'
    ) -> str | list[bytes | str] | None:
        if value is None or isinstance(value, str):
            return value
        if isinstance(value, list):
            return [cls._decode_value(v) for v in value]
        return value.decode(charset)

    def from_db_value(self, value, _expression, connection):
        """
        # TODO: Design Decision: Return None or '' for non-existing fields?
        We're returning non-existing fields as None here but django-ldapdb returns an empty string.
        With our current implementation we'd be able to create new objects with only a subset of attributes.
        Not sure if we want to break or keep the django-ldapdb behavior. Maybe make it configurable?

        TODO: Write tests for all fields.
        Maybe take inspiration from django-firebird?:
        https://github.com/maxirobaina/django-firebird/tree/master/tests/test_main/model_fields
        """
        if not self.binary_field:
            value = self._decode_value(value, connection.charset)

        if value is None:
            if self.has_default():
                return self.get_default()
            if self.multi_valued_field:
                return []

        if isinstance(value, list) and not self.multi_valued_field:
            value = value[0]

        value = self.from_ldap(value)
        if value is None and not self.null:
            return ''  # See comment in docstring above

        value = self.to_python(value)
        return value

    # noinspection PyMethodMayBeStatic
    def from_ldap(self, value):
        """
        Might be overridden in subclasses to handle the value before it gets converted to Python.
        Example:
            - Convert a binary field to a base64 encoded string
            - "TRUE" and "FALSE" to True and False in a BooleanField.
        """
        return value

    def run_validators(self, value):
        """
        Override run_validators to make sure we validate individual values if this is a multi_valued_field.
        """
        if self.multi_valued_field and isinstance(value, list):
            for v in value:
                super().run_validators(v)
        else:
            super().run_validators(value)

    def to_python(self, value):
        """
        Override to_python to return a list of values instead of casting the whole list to a string when
        this is a multi_valued_field.

        As per https://datatracker.ietf.org/doc/html/rfc4511#section-4.1.7, the attributes in a list are unsorted,
        so let's sort them to make it easier to compare them.
        """
        if self.multi_valued_field and isinstance(value, list):
            return [super().to_python(v) for v in value]
        return super().to_python(value)


class CharField(LDAPFieldMixin, dj_fields.CharField):
    def __init__(self, *args, **kwargs):
        defaults = {'max_length': 200}
        defaults.update(kwargs)
        super().__init__(*args, **defaults)


class TextField(CharField):
    pass  # just the same thing as CharField in LDAP


class DistinguishedNameField(CharField):
    default_validators = [validate_dn]


class IntegerField(LDAPFieldMixin, dj_fields.IntegerField):
    pass


class FloatField(LDAPFieldMixin, dj_fields.FloatField):
    pass


class DecimalField(LDAPFieldMixin, dj_fields.DecimalField):
    pass


class BooleanField(LDAPFieldMixin, dj_fields.BooleanField):
    """
    LDAP stores boolean values as 'TRUE' and 'FALSE'.
    Returns True if field is 'TRUE', None if field.null=True and 'FALSE' otherwise.
    Default value is None if field.null=True but can be overridden by setting default=True or False.
    """

    def from_ldap(self, value):
        return None if value is None and self.null else value == 'TRUE'


class EmailField(LDAPFieldMixin, dj_fields.EmailField):
    pass


class BinaryField(LDAPFieldMixin, dj_fields.BinaryField):
    # No need to use djangos ImageField, as it's just a BinaryField.
    # When using this field, you'll have to handle the image data yourself.
    binary_field = True


class MemberField(DistinguishedNameField):
    multi_valued_field = True


class DateField(dj_fields.DateField):
    def __init__(self, *args, fmt='%Y-%m-%d', **kwargs):
        self.date_format = fmt
        super().__init__(*args, **kwargs)
