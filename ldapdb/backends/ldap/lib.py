import enum
import json

import ldap


class LDAPSearchControlType(str, enum.Enum):
    NO_CONTROL = "no_control"
    SIMPLE_PAGED_RESULTS = "simple_paged_results"
    SSSVLV = "sssvlv"


class LDAPSearch:
    def __init__(
        self,
        base: str,
        filterstr: str = '(objectClass=*)',
        attrlist: list[str] = None,
        scope: ldap.SCOPE_BASE | ldap.SCOPE_ONELEVEL | ldap.SCOPE_SUBTREE = ldap.SCOPE_SUBTREE,
        ordering_rules: list[tuple[str, str]] = None,
        control_type: LDAPSearchControlType = LDAPSearchControlType.NO_CONTROL,
        limit: int = 0,
        offset: int = 0,
    ):
        """
        Initialize an LDAPSearch object.

        :param base: The base DN for the search.
        :type base: str
        :param filterstr: The LDAP filter string. Defaults to '(objectClass=*)'.
        :type filterstr: str
        :param attrlist: List of attributes to retrieve. Might contain "dn" attribute - must be ignored on searches!
        :type attrlist: list[str], optional
        :param scope: The scope of the search. Defaults to ldap.SCOPE_SUBTREE.
        :type scope: ldap.SCOPE_BASE | ldap.SCOPE_ONELEVEL | ldap.SCOPE_SUBTREE
        :param ordering_rules: List of tuples specifying the order. Can only be used when using SSSVLV (for now).
        :type ordering_rules: list[tuple[str, str]], optional
        :param control_type: The type of LDAP search control. Defaults to LDAPSearchControlType.NO_CONTROL.
        :type control_type: LDAPSearchControlType
        :param limit: The maximum number of results to return. 0 means no limit. Corresponds to (high_mark - low_mark)
        :type limit: int
        :param offset: The starting index for the search results. 0 based indexing. Corresponds to low_mark.
                       When using SSSVLV, this will be offset+1, since it's using 1-based indexing.
        :type offset: int
        """
        if attrlist is None:
            attrlist = []
        self.base = base
        self.filterstr = filterstr
        self.attrlist = attrlist or []
        self.scope = scope
        self.ordering_rules = ordering_rules or []
        self.control_type = control_type
        self.limit = limit
        self.offset = offset

    def __eq__(self, other):
        if not isinstance(other, LDAPSearch):
            return False
        return self.serialize() == other.serialize()

    def __dict__(self):
        return self.serialize()

    @property
    def attrlist_without_dn(self):
        return [attr for attr in self.attrlist if attr != 'dn']

    def serialize(self):
        return {
            'attrlist': sorted(self.attrlist),
            'attrlist_without_dn': sorted(self.attrlist_without_dn),
            'base': self.base,
            'control_type': self.control_type,
            'filterstr': self.filterstr,
            'limit': self.limit,
            'offset': self.offset,
            'ordering_rules': sorted(self.ordering_rules) if self.ordering_rules else None,
            'scope': self.scope,
        }

    def as_json(self):
        # Mainly used for debugging
        return json.dumps(self.serialize(), indent=4, sort_keys=True)


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