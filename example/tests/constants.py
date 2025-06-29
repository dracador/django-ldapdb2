from example.models import LDAPGroup, LDAPUser

# TODO: Maybe use generator.generate_ldap_user() and even use it to create the initial LDIF for server?


TEST_LDAP_ADMIN_USER_1 = LDAPUser(
    dn='uid=admin,ou=Users,dc=example,dc=org',
    username='admin',
    last_name='Admin',
    name='Admin',
)

TEST_LDAP_USER_1 = LDAPUser(
    dn='uid=user1,ou=Users,dc=example,dc=org',
    first_name='User',
    last_name='One',
    mail='user.one@example.org',
    name='User One',
    username='user1',
    is_active=True,
    department_number=1,
)

TEST_LDAP_USER_2 = LDAPUser(
    dn='uid=user2,ou=Users,dc=example,dc=org',
    first_name='User',
    last_name='Two',
    mail='user.two@example.org',
    name='User Two',
    username='user2',
    is_active=False,
    department_number=None,
)


TEST_LDAP_AVAILABLE_USERS = [TEST_LDAP_ADMIN_USER_1, TEST_LDAP_USER_1, TEST_LDAP_USER_2]


TEST_LDAP_GROUP_1 = LDAPGroup(
    dn='cn=Group1,ou=Groups,dc=example,dc=org',
    org_unit='group1',
    name='Group1',
    members=[
        'uid=admin,ou=Users,dc=example,dc=org',
        'uid=user1,ou=Users,dc=example,dc=org',
    ],
    descriptions=[],
)

TEST_LDAP_AVAILABLE_GROUPS = [TEST_LDAP_GROUP_1]
