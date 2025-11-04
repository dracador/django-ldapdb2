# Models

LDAP models in `django-ldapdb2` act like Django ORM models, but they’re backed by LDAP objects instead of SQL tables.  
They provide the same QuerySet API (`.objects.filter()`, `.save()`, `.delete()`, etc.), but translate operations into *
*LDAP search* and *modify* operations.

---

## 1. Defining Models

Each LDAP model must inherit from `ldapdb.models.LDAPModel` and declare at least:

- `base_dn`: the search base where entries are stored
- `base_filter`: a class-level LDAP filter string that is ANDed with all user-supplied filters at query time
- `search_scope`: the search scope for LDAP queries. Defaults to `ldap.SCOPE_SUBTREE`.
- `object_classes`: a list of LDAP objectClass definitions for new entries
- Field definitions (subclasses of `ldapdb.models.fields.*`)

Note: All models come with a default field `dn`, which is a read-only field that stores the DN of the entry.

```python
import ldap

from ldapdb.models import LDAPModel
from ldapdb.models.fields import CharField, EmailField


class LDAPUser(LDAPModel):
    """
    A user entry stored under ou=Users,dc=example,dc=org.
    """

    base_dn: str = 'ou=Users,dc=example,dc=org'
    base_filter: str = '(objectClass=*)'
    search_scope: int = ldap.SCOPE_SUBTREE
    object_classes = ['inetOrgPerson', 'organizationalPerson', 'person', 'top']

    uid = CharField(db_column='uid', primary_key=True)
    cn = CharField(db_column='cn')
    sn = CharField(db_column='sn')
    mail = EmailField(db_column='mail', blank=True)

    class Meta:
        managed = False  # no migrations, no SQL table
```

---

## 2. Object Classes

The `object_classes` list determines what schema your object will conform to.
When you `.save()` an entry that doesn’t exist, `django-ldapdb2` will automatically set its `objectClass` attribute to
this list.

For example:

```python
object_classes = ["inetOrgPerson", "organizationalPerson", "top"]
```

is typical for user entries.
If your directory enforces certain mandatory attributes (like `sn` or `cn`), they must be present or the save will fail
with a constraint error.

---

## 3. Migrations (or lack thereof)

Because LDAP is *not a relational database*, migrations do not apply.
Running `python manage.py makemigrations` will detect your models but will *not generate tables* or alter LDAP
schemas.

Typical workflow:

* Keep `managed = False` in your `Meta` class.
* Do not expect Django to track schema evolution.
* Schema changes (new attributes, object classes) are managed externally in your LDAP server configuration (e.g.,
  `slapd.conf`, LDIF imports, or schema extensions).

If you accidentally run `makemigrations appname`, Django may still record a migration file with `managed = False`, which
does nothing when applied - it only serves as metadata.

This also means, that if you write a migration yourself and try to use apps.get_model('myapp', 'LDAPUser'),
you'll very likely run into an error, because django does not know anything about the model state.

> **In short:** LDAP schema evolution is manual. Django’s migrations are metadata-only for LDAP models.

---

## 4. Base Filter (`base_filter`)

`base_filter` is a class-level LDAP filter string that is *ANDed* with all user-supplied filters at query time.
It’s used to scope your model to a specific subset of entries. Specify the depth of the search with `search_scope`.

This ensures all lookups remain within the expected object class scope, even if you forget to specify it manually.

### Default behavior

If you don’t define a `base_filter`, we'll default to `(objectClass=*)`

### Notes

* `base_filter` only affects *searches*, not *writes*.
* It is combined with any Q object filters or lookups using an `AND` clause.
* Use it to filter out non-applicable entries like admin/system accounts or inactive users.

---

## 9. See also

* [Guides: Fields](./fields.md)
* [Guides: Querying LDAP](./queries.md)
* [Guides: Transactions & Atomicity](./transactions.md)
