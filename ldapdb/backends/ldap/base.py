from django.db.backends.base.base import BaseDatabaseWrapper
from django.db.backends.base.introspection import BaseDatabaseIntrospection
from django.db.backends.base.operations import BaseDatabaseOperations
from django.db.backends.base.validation import BaseDatabaseValidation

from .client import DatabaseClient
from .creation import DatabaseCreation
from .features import DatabaseFeatures


class DatabaseWrapper(BaseDatabaseWrapper):
    display_name = "ldap"
    vendor = "ldap"

    client_class = DatabaseClient
    creation_class = DatabaseCreation
    features_class = DatabaseFeatures

    # TODO: Implement the following classes
    introspection_class = BaseDatabaseIntrospection
    ops_class = BaseDatabaseOperations
    validation_class = BaseDatabaseValidation

    # Mapping of Field objects to their column types.
    data_types = {}
