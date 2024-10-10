import hashlib
import logging
import os
from base64 import b64encode

from django.contrib.auth.models import User
from django.db import connections
from django.db.models import QuerySet
from django.db.models.sql import Query

from .backends.ldap.compiler import LDAPSearchObject
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
    return f'{{{algorithm.upper()}}}{b64encode(hashed_value).decode('utf-8')}'
