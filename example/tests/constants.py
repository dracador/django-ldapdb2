from example.models import LDAPUser

# TODO: Maybe use these constants or some kind of factory to create test data in the future?

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
)

TEST_LDAP_AVAILABLE_USERS = [TEST_LDAP_ADMIN_USER_1, TEST_LDAP_USER_1]
