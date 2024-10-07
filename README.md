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