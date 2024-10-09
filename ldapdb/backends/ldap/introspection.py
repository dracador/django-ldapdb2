from django.db.backends.base.introspection import BaseDatabaseIntrospection


class DatabaseIntrospection(BaseDatabaseIntrospection):  #
    # TODO: If get_table_list and get_table_description are needed for checkdb/inspectdb, implement them.

    def get_table_list(self, *_):
        return []

    def get_table_description(self, *_):
        return []

    def get_relations(self, *_):
        return {}

    def get_constraints(self, *_):
        return {}
