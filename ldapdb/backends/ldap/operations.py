from django.db.backends.base.operations import BaseDatabaseOperations


class DatabaseOperations(BaseDatabaseOperations):
    compiler_module = 'ldapdb.backends.ldap.compiler'

    def quote_name(self, name):
        return name

    def sql_flush(self, *_args, **_kwargs):
        # LDAP does not support SQL flush
        return []

    def no_limit_value(self):
        # LDAP does not support limiting query results in the query itself.
        # Would need to be done via PAGE_SIZE database setting
        return None

    # We *could* implement the following methods, but they are not necessary for the LDAP backend
    def date_extract_sql(self, lookup_type, field_name, **kwargs):
        # LDAP does not support date extraction
        raise NotImplementedError('LDAP does not support date extraction')

    def date_trunc_sql(self, lookup_type, field_name, **kwargs):
        # LDAP does not support date truncation
        raise NotImplementedError('LDAP does not support date truncation')

    def time_trunc_sql(self, lookup_type, field_name, **kwargs):
        # LDAP does not support time truncation
        raise NotImplementedError('LDAP does not support time truncation')

    def datetime_trunc_sql(self, lookup_type, field_name, **kwargs):
        # LDAP does not support datetime truncation
        raise NotImplementedError('LDAP does not support datetime truncation')

    def prepare_sql_script(self, sql):
        # LDAP does not support SQL scripts
        return sql
