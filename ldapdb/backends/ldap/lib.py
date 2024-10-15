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
