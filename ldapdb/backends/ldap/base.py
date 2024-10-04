from django.db.backends.base.base import BaseDatabaseWrapper
from .client import DatabaseClient
from .creation import DatabaseCreation


class DatabaseWrapper(BaseDatabaseWrapper):
    display_name = "ldap"
    vendor = "ldap"

    client_class = DatabaseClient
    creation_class = DatabaseCreation
    """ TODO 
    # Mapping of Field objects to their column types.
    data_types = {}
    # Mapping of Field objects to their SQL suffix such as AUTOINCREMENT.
    data_types_suffix = {}
    # Mapping of Field objects to their SQL for CHECK constraints.
    data_type_check_constraints = {}
    ops = None
    SchemaEditorClass = None
    # Classes instantiated in __init__().
    features_class = None
    introspection_class = None
    ops_class = None
    validation_class = BaseDatabaseValidation
    """