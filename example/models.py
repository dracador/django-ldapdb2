from ldapdb.fields import CharField
from ldapdb.models import LDAPModel


class LDAPUser(LDAPModel):
    base_dn = 'ou=Users,dc=example,dc=org'
    object_classes = ['inetOrgPerson', 'organizationalPerson']
    object_classes_minimal = ['inetOrgPerson']  # These are the values used to search for existing entries

    username = CharField(db_column='uid', primary_key=True)
    name = CharField(db_column='cn')

    class Meta:
        managed = False
        # ordering = ('uid',)
