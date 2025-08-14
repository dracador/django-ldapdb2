from typing import Any

from ldapdb.models.fields import BooleanField


class IsActiveWithCustomLookupField(BooleanField):
    """
    Let's pretend we have a field called `optional_is_active`,
    which maps to an LDAP boolean attribute called `optionalIsActive`, which *might* exist.
    If it does not exist, we want to pretend the attribute to be True.

    To make sure the backend resolves this correctly,
    we'll need to implement a custom `from_db_value` and a `render_lookup()` method.

    Example:
        With a standard BooleanField:
        LDAPUser.objects.filter(optional_is_active=True) = "(optionalIsActive=TRUE)"
        LDAPUser.objects.filter(optional_is_active=False) = "(optionalIsActive=FALSE)"

        With a custom render_lookup() method:
        LDAPUser.objects.filter(optional_is_active=True) = "(!(optionalIsActive=FALSE))"
        LDAPUser.objects.filter(optional_is_active=False) = "(optionalIsActive=FALSE)"

        So FALSE will be handled the same way as before, but optional_is_active=True will result in a negated search.
    """

    def from_db_value(self, value, *args, **kwargs):
        """Convert the value returned by the LDAP server to a Python object."""
        value = super().from_db_value(value, *args, **kwargs)

        if value is None:
            return True
        return value

    def render_lookup(self, field_name: str, lookup_name: str, value: Any) -> str | None:
        """Convert the value passed to the QuerySet filter to an LDAP filter string."""
        if lookup_name != 'exact':
            return None  # returning None here just lets the backend execute the default behavior

        if value == 'TRUE':
            return f'(!({field_name}=FALSE))'
        elif value == 'FALSE':
            return f'({field_name}=FALSE)'
        else:
            raise ValueError(f'Invalid value for {lookup_name}: {value}')
