class BaseUser:
    base_dn = 'ou=People,dc=smhss,dc=de'
    object_classes = ['inetOrgPerson', 'organizationalPerson', 'x-de-smedia-extendedUser']
    object_classes_minimal = ['inetOrgPerson', 'organizationalPerson']

    class Meta:
        abstract = True
        managed = False
        ordering = ('uid',)

    """
    uid = CharField(db_column='uid', primary_key=True, verbose_name=_('Username'))
    given_name = CharField(db_column='givenName', verbose_name=_('First name'))
    sn = CharField(db_column='sn', verbose_name=_('Last name'))
    cn = CharField(db_column='cn', verbose_name=_('Full name'))
    mail = CharField(db_column='mail', verbose_name=_('E-Mail address'))
    active = ActiveField(db_column='x-de-smedia-isActive', default=True, verbose_name=_('Active'))

    # Only used for getting DNs https://github.com/django-ldapdb/django-ldapdb/issues/103
    entry_dn = CharField(db_column='entryDN')

    # Used for password expiry notifications and customer reset links
    password_changed_date = DateTimeField(db_column='pwdChangedTime', verbose_name=_('Last password change'))

    def set_password(self, password):
        # We can't use a normal ModelField, because it would be changed every time this object is saved.
        hashed_password = generate_password_hash(password)
        modify_replace(self.dn, 'userPassword', hashed_password)

    def __str__(self):
        return self.uid

    """