import hashlib
import os
from base64 import b64encode

import ldap

from .exceptions import UnsupportedHashAlgorithmError

# TODO: Get DN and password from database settings
DEFAULT_USER_DN = 'uid=admin,ou=Users,dc=example,dc=org'
DEFAULT_USER_PASSWORD = 'adminpassword'


def initialize_connection(
    url: str = 'ldap://localhost:389', user: str = DEFAULT_USER_DN, password: str = DEFAULT_USER_PASSWORD
):
    """Initialize connection to LDAP server."""
    connection = ldap.initialize(url)
    connection.simple_bind_s(user, password)
    connection.set_option(ldap.OPT_REFERRALS, 0)
    # connection.set_option(ldap.OPT_PROTOCOL_VERSION, 3)
    # connection.set_option(ldap.OPT_X_TLS_REQUIRE_CERT, ldap.OPT_X_TLS_NEVER)
    # connection.set_option(ldap.OPT_X_TLS_NEWCTX, 0)
    return connection


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
