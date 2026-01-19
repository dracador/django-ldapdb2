import ldap
from ldapdb.models import LDAPModel
from ldapdb.models.fields import (
    BinaryField,
    BooleanField,
    CharField,
    DateField,
    DateTimeField,
    DistinguishedNameField,
    EmailField,
    IntegerField,
    LDAPPasswordAlgorithm,
    MemberField,
    PasswordField,
    TextField,
    UpdateStrategy,
)


class BaseLDAPUser(LDAPModel):
    """
    Base LDAPUser class that provides some fields needed for an LDAP user model.
    """

    base_dn = 'ou=Users,dc=example,dc=org'
    object_classes = ['inetOrgPerson', 'organizationalPerson', 'x-extendedUser']

    username = CharField(db_column='uid', primary_key=True)
    password = PasswordField(db_column='userPassword', algorithm=LDAPPasswordAlgorithm.ARGON2)
    name = CharField(db_column='cn')
    first_name = CharField(db_column='givenName', null=True)
    last_name = CharField(db_column='sn')
    mail = EmailField(db_column='mail', null=True)
    non_existing_attribute = CharField(db_column='nonExistingAttribute', blank=True, null=True)
    is_active = BooleanField(db_column='x-user-isActive')
    department_number = IntegerField(db_column='departmentNumber', blank=True, null=True)
    description = TextField(db_column='description', blank=True, null=True)
    thumbnail_photo = BinaryField(db_column='jpegPhoto', null=True)
    date_field = DateField(db_column='x-user-date', blank=True, null=True)
    date_time_field = DateTimeField(db_column='x-user-dateTime', fmt='%Y-%m-%d %H:%M:%S', blank=True, null=True)

    # operational attributes
    entry_dn = DistinguishedNameField(db_column='entryDN', unique=True, read_only=True)

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


class BaseLDAPGroup(LDAPModel):
    base_dn = 'ou=Groups,dc=example,dc=org'
    base_filter = '(objectClass=groupOfNames)'
    object_classes = ['groupOfNames']

    name = CharField(db_column='cn', primary_key=True)
    org_unit = CharField(db_column='ou')

    members = MemberField(db_column='member', default='dc=example,dc=org', update_strategy=UpdateStrategy.REPLACE)

    # Only for demonstration purposes. In praxis you'd probably not use multiple description attributes.
    descriptions = CharField(db_column='description', multi_valued_field=True, blank=True, null=True)

    class Meta:
        abstract = True
        ordering = ('name',)


class LDAPGroup(BaseLDAPGroup):
    ...
