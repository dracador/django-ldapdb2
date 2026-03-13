from django.db.backends.base.creation import BaseDatabaseCreation


class DatabaseCreation(BaseDatabaseCreation):
    def create_test_db(self, *args, **kwargs) -> str:
        """
        Creates a test database, prompting the user for confirmation if the
        database already exists. Returns the name of the test database created.
        """
        return self.connection.settings_dict['NAME']

    def destroy_test_db(self, *args, **kwargs) -> None:
        """
        Destroy a test database, prompting the user for confirmation if the
        database already exists. Returns the name of the test database created.
        """
        pass

    def get_test_db_clone_settings(self, suffix):
        return self.connection.settings_dict

    def _clone_test_db(self, suffix, verbosity, keepdb=False):
        pass
