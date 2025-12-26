import logging
from typing import TYPE_CHECKING

from django.db import connections

from .router import Router

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from ldapdb.backends.ldap.base import DatabaseWrapper


def initialize_connection(using=None):
    """Shortcut to getting a ReconnectLDAPObject from our database backend."""

    if using is None:
        using = Router().default_database

    db_wrapper: DatabaseWrapper = connections[using]  # type: ignore[assignment]
    return db_wrapper.get_new_connection()
