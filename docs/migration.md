Migrating from django-ldapdb
============================

# Models

## Behaviour of ```object_classes``` has changed

Before, running a QuerySet on a model included ```object_classes``` in the resulting search filter.
This caused issues when trying to add a new objectClass value to the object because you'd have to make sure that new
objectClass has been added to the object before you make changes to the models ```object_classes```.
This also forced all entries to have the same objectClass values, which might not be desired.

To keep the existing behaviour, set the ```base_filter``` attribute to include the object_classes.

::: ldapdb.models.LDAPModel

# Fields

## Custom fields

If you created any custom fields, the behavior has changed slightly. Fields now inherit from ```LDAPField```.
Check the documentation for LDAPField to see what methods you need to implement.

- [ ] ref: [LDAPField](../ldapdb/fields.py)

# Lookups

## Registering custom lookups

The way to register lookups on fields has changed. All fields use the same lookups their respective Django fields use.
If you have custom lookups, you need to register them again. In most cases, you won't have to change any lookups.

## Handling of placeholder values

The ```Lookup._as_ldap()``` method which was used to provide custom formatting for how values are inserted into the
LDAP filter has been removed. For now, all formatting happens in the backend.
With this, the ```LDAP_PLACEHOLDER``` attribute has also been removed from the fields.
See ```SQLCompiler.operators``` for more information.

- [ ] ref: [SQLCompiler](../ldapdb/backends/ldap/compiler.py)
