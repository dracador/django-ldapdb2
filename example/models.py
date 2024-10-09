from ldapdb.fields import CharField
from ldapdb.models import LDAPModel


class LDAPUser(LDAPModel):
    base_dn = 'ou=People,dc=smhss,dc=de'
    object_classes = ['inetOrgPerson', 'organizationalPerson']
    object_classes_minimal = ['inetOrgPerson']

    uid = CharField(db_column='uid', primary_key=True)

    class Meta:
        managed = False
        ordering = ('uid',)
