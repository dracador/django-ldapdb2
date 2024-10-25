from ldapdb.fields import CharField
from ldapdb.models import LDAPModel


class LDAPUser(LDAPModel):
    base_dn = 'ou=Users,dc=example,dc=org'
    base_filter = '(objectClass=inetOrgPerson)'  # the base filter will be always be applied to all queries
    object_classes = ['inetOrgPerson', 'organizationalPerson']

    username = CharField(db_column='uid', primary_key=True)
    name = CharField(db_column='cn')
    first_name = CharField(db_column='givenName', blank=True, null=True)
    last_name = CharField(db_column='sn')
    mail = CharField(db_column='mail', blank=True, null=True)

    class Meta:
        managed = False
        ordering = ('username',)
