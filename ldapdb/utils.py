import ldap

DEFAULT_USER_DN = 'uid=admin,ou=Users,dc=example,dc=org'
DEFAULT_USER_PASSWORD = 'adminpassword'


def initialize_connection(url: str = "ldap://localhost:389", user: str = DEFAULT_USER_DN, password: str = DEFAULT_USER_PASSWORD):
    """Initialize connection to LDAP server."""
    connection = ldap.initialize(url)
    connection.simple_bind_s(user, password)
    connection.set_option(ldap.OPT_REFERRALS, 0)
    #connection.set_option(ldap.OPT_PROTOCOL_VERSION, 3)
    #connection.set_option(ldap.OPT_X_TLS_REQUIRE_CERT, ldap.OPT_X_TLS_NEVER)
    #connection.set_option(ldap.OPT_X_TLS_NEWCTX, 0)
    return connection
