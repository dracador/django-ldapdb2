from django.core.management.commands.inspectdb import Command as DjangoInspectDB
from django.db import DEFAULT_DB_ALIAS, connections


class Command(DjangoInspectDB):
    # TODO: s/Model/LDAPModel/
    db_module = 'ldapdb'

    def add_arguments(self, parser):
        parser.add_argument(
            'table',
            'dn',
            nargs='*',
            type=str,
            help='Selects which DNs should be introspected.',
        )
        parser.add_argument(
            '--database',
            default=DEFAULT_DB_ALIAS,
            choices=tuple(connections),
            help='Nominates a database to introspect. Defaults to using the "default" database.',
        )
