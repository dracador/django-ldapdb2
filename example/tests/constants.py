import ldap
from ldapdb.backends.ldap.compiler import LDAPSearch

GROUPS_DN = 'ou=Groups,dc=example,dc=com'
USERS_DN = 'ou=Users,dc=example,dc=com'

LDAP_ALL_GROUPS = LDAPSearch(
    base=GROUPS_DN,
    scope=ldap.SCOPE_ONELEVEL,
    filterstr='(objectClass=groupOfNames)',
)

LDAP_ALL_USERS = LDAPSearch(
    base=USERS_DN,
    scope=ldap.SCOPE_ONELEVEL,
    filterstr='(objectClass=inetOrgPerson)',
)
