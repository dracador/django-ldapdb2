# Installation & Setup

> If the package isn’t published yet, install from source in editable mode. Otherwise, prefer a published release from PyPI.

## Install

```bash
pip install django-ldapdb2
```

## Setup

Add an LDAP database to your DATABASES and register the router. Values will differ for your environment.

```python
# settings.py
DATABASES = {
    "default": {...},
    "ldap": {
        "ENGINE": "ldapdb.backends.ldap",
        "NAME": "ldap://localhost",       # or ldaps://server
        "BIND_DN": "cn=admin,dc=example,dc=org",
        "BIND_PASSWORD": "secret",
        "START_TLS": True,
        # TODO: add more options
    },
}

DATABASE_ROUTERS = ["ldapdb.router.Router"]
```

> Note: LDAP models are not migrated with Django migrations. The router keeps SQL models and LDAP models separate.

