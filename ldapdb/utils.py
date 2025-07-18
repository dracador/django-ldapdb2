import hashlib
import logging
import os
import re
from base64 import b64encode
from datetime import UTC, datetime, timedelta, timezone

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


_GTIME_RE = re.compile(
    r"""
    ^
    (?P<year>\d{4})
    (?P<mon>\d{2})?
    (?P<day>\d{2})?
    (?P<hour>\d{2})?
    (?P<minute>\d{2})?
    (?P<second>\d{2})?
    (?:\.(?P<frac>\d+))?          # fractional seconds
    (?P<tz>Z|[+\-]\d{4})?         # 'Z' or ±HHMM
    $
    """,
    re.VERBOSE,
)


def parse_generalized_time(s: str) -> datetime:
    m = _GTIME_RE.match(s)
    if not m:
        raise ValueError(f'Invalid GeneralizedTime value: {s!r}')

    parts = {k: int(v) if v and k not in ['frac', 'tz'] else v for k, v in m.groupdict().items()}

    # Missing components default to minimal valid value (RFC says that is OK)
    dt = datetime(
        parts['year'],
        parts['mon'] or 1,
        parts['day'] or 1,
        parts['hour'] or 0,
        parts['minute'] or 0,
        parts['second'] or 0,
        int(float(f"0.{parts['frac']}") * 1_000_000) if parts['frac'] else 0,
    )

    tz = parts['tz']
    if tz == 'Z' or tz is None:
        dt = dt.replace(tzinfo=UTC)
    else:
        sign = 1 if tz[0] == '+' else -1
        offset = (
            timedelta(
                hours=int(tz[1:3]),
                minutes=int(tz[3:5]),
            )
            * sign
        )
        dt = dt.replace(tzinfo=timezone(offset))
    return dt


def format_generalized_time(dt: datetime, include_tz: bool = False) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)

    if include_tz:
        # Format with timezone offset
        dt = dt.astimezone()
        offset = dt.strftime('%z')
        print(f'Offset: {offset}')
        return dt.strftime(f'%Y%m%d%H%M%S{offset}')

    dt = dt.astimezone(UTC)
    return dt.strftime('%Y%m%d%H%M%SZ')
