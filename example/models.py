import ldap
from ldapdb.fields import BinaryField, BooleanField, CharField, EmailField, IntegerField, TextField
from ldapdb.models import LDAPModel


class BaseLDAPUser(LDAPModel):
    """
    Base LDAPUser class that provides some fields needed for an LDAP user model.
    """

    base_dn = 'ou=Users,dc=example,dc=org'
    object_classes = ['inetOrgPerson', 'organizationalPerson']

    username = CharField(db_column='uid', primary_key=True)
    name = CharField(db_column='cn')
    first_name = CharField(db_column='givenName')
    last_name = CharField(db_column='sn')
    mail = EmailField(db_column='mail')
    non_existing_attribute = CharField(db_column='nonExistingAttribute')
    is_active = BooleanField(db_column='x-user-isActive')
    department_number = IntegerField(db_column='departmentNumber')
    description = TextField(db_column='description')
    thumbnail_photo = BinaryField(db_column='jpegPhoto')

    def __str__(self):
        return self.username

    class Meta:
        abstract = True


class LDAPUser(BaseLDAPUser):
    base_filter = '(objectClass=inetOrgPerson)'

    class Meta:
        ordering = ('username',)  # default ordering for SSSVLV is the primary_key. Without SSSVLV, no ordering occurs.


class LDAPAdminUser(BaseLDAPUser):
    # Note: This model is just used to demonstrate a second LDAPUser model with a different base_filter.
    # In a real application this would probably be a QuerySet/Manager method
    # that just appends .filter(cn__contains='admin')
    search_scope = ldap.SCOPE_ONELEVEL
    base_filter = '(&(objectClass=inetOrgPerson)(cn=*admin*))'

    initials = CharField(db_column='initials')

    class Meta:
        ordering = ('mail',)
