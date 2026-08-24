# django-ldapdb2

This project aims to build on top of the existing work of django-ldapdb while providing more functionality and better
support for non-standard use cases.

## Goals
### Improvements
- [X] Initial rewrite of Database backend to support better configuration and connection pooling, etc
- [X] Better handling of "hidden" attributes like DNs/RDNs
- [X] Get rid of the need to make two LDAP requests when resolving a queryset
- [X] Better support for different types of updates (like modify_replace vs modify_delete/add in ListFields)
### Features
- [X] Support for Ordering & Pagination via SSSVLV
- [ ] Support for LDAP Transactions via @transaction.atomic
- [X] Extend list of supported Fields to include more LDAP-specific fields and more sane defaults
- [X] Allow for annotating querysets with static values (or maybe even more?)
- [X] Support for more complex queries (like Q objects)
- [ ] checkdb command to validate the model to the LDAP server schema
- [ ] inspectdb command to generate models from the LDAP server schema
- [ ] Query explanations as LDIF
- [X] Be compatible with django-debug-toolbar
