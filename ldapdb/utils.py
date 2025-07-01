import hashlib
import logging
import os
from base64 import b64encode

from django.db import connections

from .exceptions import UnsupportedHashAlgorithmError
from .router import Router

logger = logging.getLogger(__name__)


def initialize_connection(using=None):
    """Shortcut to getting a ReconnectLDAPObject from our database backend."""
    if using is None:
        using = Router().default_database
    db_wrapper = connections[using]
    return db_wrapper.get_new_connection()


def generate_password_hash(password: str, algorithm: str = 'ssha512') -> str:
    """
    Generate an SSHA hash for the given password using the specified algorithm.
    returns: str in the form of {algorithm}base64hash
    """
    hashlib_algorithm = algorithm.lower().replace('-', '').replace('ssha', 'sha')

    if hashlib_algorithm not in hashlib.algorithms_available:
        raise UnsupportedHashAlgorithmError(hashlib_algorithm)

    sha = hashlib.new(hashlib_algorithm)
    sha.update(password.encode('utf-8'))
    hashed_value = sha.digest()
    if algorithm.startswith('ssha'):
        salt = os.urandom(8)
        sha.update(salt)
        hashed_value += salt
    return f'{{{algorithm.upper()}}}{b64encode(hashed_value).decode("utf-8")}'


def escape_ldap_filter_value(value: str):
    """
    Escape special characters in LDAP filter values.
    """
    value = value.replace('\\', '\\5c')
    value = value.replace('*', '\\2a')
    value = value.replace('(', '\\28')
    value = value.replace(')', '\\29')
    value = value.replace('\x00', '\\00')
    return value


def create_ldap_entry(dn: str, attributes: dict):
    """
    Create an LDAP entry with the given DN and attributes.
    :param dn: Distinguished Name of the entry.
    :param attributes: Dictionary of attributes to set on the entry.
    :return: None
    """
    connection = initialize_connection()
    try:
        attrs = [
            ('objectClass', [b'inetOrgPerson']),
            ('uid', [b'jdoe']),
            ('cn', [b'John Doe']),
            ('sn', [b'Doe']),
            ('mail', [b'jdoe@example.org']),
        ]
        result = connection.add_s(
            dn,
            attrs,
        )
        print(f'LDAP entry created: {dn}')
    except Exception as e:
        print(f'Failed to create LDAP entry {dn}: {e}')
        raise
    finally:
        connection.unbind_s()
    return result
