# TODO: Since neither python-ldap nor ldap3 support Request/ResponseControls for transactions,
#  we'll need to implement our own transaction support.

# From RFC 5805, section 3.1:
# Start and end transaction OIDs are found in supportedExtension.
# Specification Control is found in supportedControl.
LDAP_OID_TRANSACTION_START = '1.3.6.1.1.21.1'
LDAP_OID_TRANSACTION_SPECIFICATION_CONTROL = '1.3.6.1.1.21.2'
LDAP_OID_TRANSACTION_END = '1.3.6.1.1.21.3'
LDAP_OID_TRANSACTION_ABORT = '1.3.6.1.1.21.4'
