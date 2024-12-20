import hashlib


class UnsupportedHashAlgorithmError(ValueError):
    """Raised when an unsupported hash algorithm is used."""

    def __init__(self, algorithm: str):
        super().__init__(
            f'Unsupported algorithm: {algorithm}. '
            f'Supported algorithms: {hashlib.algorithms_available}. '
            f'Use SSHA$number for salted hashes.'
        )


class MultipleLDAPDatasesError(ValueError):
    """Raised when multiple LDAP databases are found."""

    def __init__(self):
        super().__init__(
            'Multiple LDAP databases found. Please specify a database via Meta.ldap_database or QuerySet.using().'
        )


class LDAPModelTypeError(TypeError):
    def __init__(self, model):
        super().__init__(f'Expected model to be a subclass of LDAPModel but LDAPModel not in MRO: {model.__mro__}')


class LDAPQueryTypeError(TypeError):
    def __init__(self, query):
        super().__init__(f'Expected query to be an instance of LDAPQuery, not {type(query)}')
