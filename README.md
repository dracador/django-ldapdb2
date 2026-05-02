# django-ldapdb2

This project aims to build on top of the existing work of django-ldapdb while providing more functionality and better
support for non-standard use cases.

## Goals
### Improvements
- [ ] Initial rewrite of Database backend to support better configuration and connection pooling, etc
- [ ] Better handling of "hidden" attributes like DNs/RDNs
- [ ] Get rid of the need to make two LDAP requests when resolving a queryset
- [ ] Better support for different types of updates (like modify_replace vs modify_delete/add in ListFields)
- [ ] Better support for standard Django migration behavior
### Features
- [ ] Support for Ordering & Pagination via SSSVLV
- [ ] Support for LDAP Transactions via @transaction.atomic
- [ ] Extend list of supported Fields to include more LDAP-specific fields and more sane defaults
- [ ] Allow for annotating querysets with static values (or maybe even more?)
- [ ] Support for more complex queries (like Q objects)
- [ ] checkdb command to validate the model to the LDAP server schema
- [ ] inspectdb command to generate models from the LDAP server schema
- [ ] Query explanations as LDIF
- [ ] Be compatible with django-debug-toolbar

## Async support (experimental)

`django-ldapdb2` exposes asyncio-native ORM methods alongside the existing sync API. Inside one event loop,
`asyncio.gather` over multiple `aget` / `acount` / `afirst` / `aexists` calls multiplexes them onto a single LDAP
connection by message ID, so wall time is bounded by one round-trip rather than N.

```python
import asyncio
from example.models import LDAPUser

async def expand(usernames):
    return await asyncio.gather(
        *[LDAPUser.objects.aget(username=u) for u in usernames]
    )
```

For the design, supported operations, TLS gotchas, reconnect behavior, and per-event-loop connection model, see
[`docs/async.md`](docs/async.md). A working example lives in [`example/views.py`](example/views.py)
(routes `/users/sync/` and `/users/async/`).
