from example.models import LDAPUser

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

TEST_LDAP_AVAILABLE_USERS = [TEST_LDAP_ADMIN_USER_1, TEST_LDAP_USER_1]
