import ldap
from django.core.exceptions import ValidationError


def validate_dn(value: str):
    if not ldap.dn.is_dn(value):
        raise ValidationError(f'Invalid distinguished name: {value}')
