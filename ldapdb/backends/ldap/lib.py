import enum

import ldap


class LDAPSearchControlType(int, enum.Enum):
    NO_CONTROL = 0
    PAGED_RESULTS = 1
    SSSVLV = 2


class LDAPSearch:
    def __init__(
        self,
        base: str,
        filterstr: str = '(objectClass=*)',
        attrlist: list[str] = frozenset(['*', '+']),
        scope: ldap.SCOPE_BASE | ldap.SCOPE_ONELEVEL | ldap.SCOPE_SUBTREE = ldap.SCOPE_SUBTREE,
        order_by: list[tuple[str, str]] = None,  # can only be used when using SSSVLV
        control_type: LDAPSearchControlType = LDAPSearchControlType.NO_CONTROL,
        limit: int = 0,  # 0 means no limit
        offset: int = 0,
    ):
        self.base = base
        self.filterstr = filterstr
        self.attrlist = attrlist
        self.scope = scope
        self.order_by = order_by
        self.control_type = control_type
        self.limit = limit
        self.offset = offset

    def __eq__(self, other):
        if not isinstance(other, LDAPSearch):
            return False
        return self.serialize() == other.serialize()

    def __dict__(self):
        return self.serialize()

    def serialize(self):
        return {
            'attrlist': sorted(self.attrlist),
            'base': self.base,
            'control_type': self.control_type,
            'filterstr': self.filterstr,
            'limit': self.limit,
            'offset': self.offset,
            'order_by': sorted(self.order_by) if self.order_by else None,
            'scope': self.scope,
        }


class LDAPDatabase:
    # Base class for all exceptions as defined in PEP-249
    Error = ldap.LDAPError

    class DatabaseError(Error):
        """Database-side errors."""

    class OperationalError(
        DatabaseError,
        ldap.ADMINLIMIT_EXCEEDED,
        ldap.AUTH_METHOD_NOT_SUPPORTED,
        ldap.AUTH_UNKNOWN,
        ldap.BUSY,
        ldap.CONFIDENTIALITY_REQUIRED,
        ldap.CONNECT_ERROR,
        ldap.INAPPROPRIATE_AUTH,
        ldap.INVALID_CREDENTIALS,
        ldap.OPERATIONS_ERROR,
        ldap.RESULTS_TOO_LARGE,
        ldap.SASL_BIND_IN_PROGRESS,
        ldap.SERVER_DOWN,
        ldap.SIZELIMIT_EXCEEDED,
        ldap.STRONG_AUTH_NOT_SUPPORTED,
        ldap.STRONG_AUTH_REQUIRED,
        ldap.TIMELIMIT_EXCEEDED,
        ldap.TIMEOUT,
        ldap.UNAVAILABLE,
        ldap.UNAVAILABLE_CRITICAL_EXTENSION,
        ldap.UNWILLING_TO_PERFORM,
    ):
        """Exceptions related to the database operations, out of the programmer control."""

    class IntegrityError(
        DatabaseError,
        ldap.AFFECTS_MULTIPLE_DSAS,
        ldap.ALREADY_EXISTS,
        ldap.CONSTRAINT_VIOLATION,
        ldap.TYPE_OR_VALUE_EXISTS,
    ):
        """Exceptions related to database Integrity."""

    class DataError(
        DatabaseError,
        ldap.INVALID_DN_SYNTAX,
        ldap.INVALID_SYNTAX,
        ldap.NOT_ALLOWED_ON_NONLEAF,
        ldap.NOT_ALLOWED_ON_RDN,
        ldap.OBJECT_CLASS_VIOLATION,
        ldap.UNDEFINED_TYPE,
    ):
        """Exceptions related to invalid data"""

    class InterfaceError(
        ldap.CLIENT_LOOP,
        ldap.DECODING_ERROR,
        ldap.ENCODING_ERROR,
        ldap.LOCAL_ERROR,
        ldap.LOOP_DETECT,
        ldap.NO_MEMORY,
        ldap.PROTOCOL_ERROR,
        ldap.REFERRAL_LIMIT_EXCEEDED,
        ldap.USER_CANCELLED,
        Error,
    ):
        """Exceptions related to the pyldap interface."""

    class InternalError(
        DatabaseError,
        ldap.ALIAS_DEREF_PROBLEM,
        ldap.ALIAS_PROBLEM,
    ):
        """Exceptions encountered within the database."""

    class ProgrammingError(
        DatabaseError,
        ldap.CONTROL_NOT_FOUND,
        ldap.FILTER_ERROR,
        ldap.INAPPROPRIATE_MATCHING,
        ldap.NAMING_VIOLATION,
        ldap.NO_SUCH_ATTRIBUTE,
        ldap.NO_SUCH_OBJECT,
        ldap.PARAM_ERROR,
    ):
        """Invalid data send by the programmer."""

    class NotSupportedError(
        DatabaseError,
        ldap.NOT_SUPPORTED,
    ):
        """Exception for unsupported actions."""
