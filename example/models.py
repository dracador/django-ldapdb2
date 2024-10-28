from ldapdb.fields import CharField
from ldapdb.models import LDAPModel


class LDAPUser(LDAPModel):
    base_dn = 'ou=Users,dc=example,dc=org'
    base_filter = '(objectClass=inetOrgPerson)'
    object_classes = ['inetOrgPerson', 'organizationalPerson']

    username = CharField(db_column='uid', primary_key=True)
    name = CharField(db_column='cn')
    first_name = CharField(db_column='givenName')
    last_name = CharField(db_column='sn')
    mail = CharField(db_column='mail')
    non_existing_attribute = CharField(db_column='nonExistingAttribute')

    class Meta:
        managed = False
        ordering = ('username',)  # default ordering for SSSVLV is the primary_key. Without SSSVLV, no ordering occurs.
