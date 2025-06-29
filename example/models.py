import ldap
from ldapdb.fields import (
    BinaryField,
    BooleanField,
    CharField,
    EmailField,
    IntegerField,
    MemberField,
    TextField,
)
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


class LDAPGroup(LDAPModel):
    base_dn = 'ou=Groups,dc=example,dc=org'
    base_filter = '(objectClass=groupOfNames)'
    object_classes = ['groupOfNames']

    name = CharField(db_column='cn', primary_key=True)
    org_unit = CharField(db_column='ou')
    members = MemberField(db_column='member')

    # Only for demonstration purposes. In praxis you'd probably not use multiple description attributes.
    descriptions = CharField(db_column='description', multi_valued_field=True)

    class Meta:
        ordering = ('name',)
