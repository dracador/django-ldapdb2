import ldap
from django.core.exceptions import ValidationError

from ldapdb.backends.ldap.lib import escape_ldap_dn_chars


def validate_dn(value: str):
    if not ldap.dn.is_dn(escape_ldap_dn_chars(value)):
        raise ValidationError(f'Invalid distinguished name: {value}')
