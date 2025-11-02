# Quickstart

A minimal example that defines a model mapped to LDAP entries and performs basic CRUD and listing.

For a more complete example, see
the [example app](https://github.com/dracador/django-ldapdb2/blob/main/example/models.py).

## 1. Define a Model

```python
# app/models.py
from ldapdb.models import LDAPModel
from ldapdb.models.fields import (
    CharField,
    EmailField,
    MemberField,
)


class LDAPUser(LDAPModel):
    base_dn = 'ou=Users,dc=example,dc=org'
    base_filter = '(objectClass=inetOrgPerson)'
    object_classes = ['inetOrgPerson', 'organizationalPerson']

    username = CharField(db_column='uid', primary_key=True)
    name = CharField(db_column='cn')
    first_name = CharField(db_column='givenName', null=True)
    last_name = CharField(db_column='sn')
    mail = EmailField(db_column='mail', null=True)

    def __str__(self):
        return self.username

    class Meta:
        managed = False
        ordering = ('username',)


class LDAPGroup(LDAPModel):
    base_dn = 'ou=Groups,dc=example,dc=org'
    base_filter = '(objectClass=groupOfNames)'
    object_classes = ['groupOfNames']

    name = CharField(db_column='cn', primary_key=True)
    org_unit = CharField(db_column='ou')

    # Often, the member attribute requires at least one value.
    # With a default, you're making sure that you don't run into IntegrityErrors.
    members = MemberField(db_column='member', default='dc=example,dc=org')

    class Meta:
        managed = False
        ordering = ('name',)
```

## 2. Use your model the way you'd expect

```python
from django.db.models import Q
from example.models import LDAPUser

LDAPUser.objects.create(
    first_name='Bobby',
    last_name='Bob',
    mail='bob@example.org',
    name='Bobby Bob',
    username='bbob',
)

user = LDAPUser.objects.get(pk='bbob')

qs = LDAPUser.objects.filter(
    Q(name__icontains='Bob') | Q(mail__endswith='@example.org')
).order_by('username')
for u in qs:
    print(u.uid, u.cn)

```