import re
import secrets
from typing import TYPE_CHECKING, cast

import ldap
from django.db import connections
from ldapdb.models.fields import LDAPPasswordAlgorithm, PasswordField

from example.tests.base import BaseLDAPTestUser, LDAPTestCase
from example.tests.generator import create_random_ldap_user, generate_random_username

if TYPE_CHECKING:
    from ldapdb.backends.ldap.base import DatabaseWrapper
    from ldapdb.backends.ldap.cursor import DatabaseCursor


class PasswordFieldModelForAlgorithm(BaseLDAPTestUser):
    password: PasswordField  # filled in get_dynamic_password_model()

    class Meta:
        abstract = True


_ARGON2_MEMORY_COST = 1024
_ARGON2_PARALLELISM = 2
_ARGON2_ROUNDS = 10
_PBKDF2_ROUNDS = 100000


class PasswordFieldModelWithCustomHandlerOptionsArgon2(BaseLDAPTestUser):
    password = PasswordField(
        db_column='userPassword',
        algorithm=LDAPPasswordAlgorithm.ARGON2,
        handler_opts={'memory_cost': _ARGON2_MEMORY_COST, 'parallelism': _ARGON2_PARALLELISM, 'rounds': _ARGON2_ROUNDS},
    )


class PasswordFieldModelWithCustomHandlerOptionsPBKDF2(BaseLDAPTestUser):
    password = PasswordField(
        db_column='userPassword', algorithm=LDAPPasswordAlgorithm.PBKDF2_SHA512, handler_opts={'rounds': _PBKDF2_ROUNDS}
    )


ARGON_RE = re.compile(r'^\{ARGON2}\$argon2(?:id|i|d)\$v=\d+\$m=(?P<m>\d+),t=(?P<t>\d+),p=(?P<p>\d+)\$')
PBKDF2_SHA512_RE = re.compile(r'^\{PBKDF2-SHA512}(?P<rounds>\d+)\$(?P<salt>[a-zA-Z0-9+/.]+)\$.*$')


def get_dynamic_password_model(algorithm: LDAPPasswordAlgorithm) -> type[PasswordFieldModelForAlgorithm]:
    """
    Creates a concrete subclass of the template with the specific algorithm field.
    """
    return cast(
        'type[PasswordFieldModelForAlgorithm]',
        type(
            f'DynamicPasswordModel_{algorithm.name}',
            (PasswordFieldModelForAlgorithm,),
            {
                'password': PasswordField(db_column='userPassword', algorithm=algorithm),
                '__module__': __name__,
            },
        ),
    )


class PasswordFieldTests(LDAPTestCase):
    def setUp(self):
        self.user = create_random_ldap_user()

    def tearDown(self):
        self.user.delete()

    def assertSuccessfulBind(self, dn: str, password: str):
        database: DatabaseWrapper = cast('DatabaseWrapper', connections[self.user._state.db])
        conn_params = database.get_connection_params()
        conn_params['bind_dn'] = dn
        conn_params['bind_pw'] = password
        try:
            database.get_new_connection(conn_params)
        except ldap.INVALID_CREDENTIALS as e:
            raise AssertionError('Invalid credentials') from e

    @staticmethod
    def get_hash(password: str, algorithm: LDAPPasswordAlgorithm) -> str:
        return PasswordField.generate_password_hash(password, algorithm)

    def test_password_field_pre_hashed(self):
        """
        A pre-hashed password should just be directly passed through as-is.
        """
        password = str(secrets.token_hex(8))
        algorithm = LDAPPasswordAlgorithm.SSHA512
        hashed_password = self.get_hash(password, algorithm)
        model_cls = get_dynamic_password_model(algorithm)
        instance = model_cls.objects.create(username=generate_random_username(), password=hashed_password)
        self.assertSuccessfulBind(instance.dn, password)

    def _test_password_field_single_algorithm(self, instance: PasswordFieldModelForAlgorithm):
        password = str(secrets.token_hex(8))
        instance.password = password
        instance.save()
        self.assertSuccessfulBind(instance.dn, password)

    def test_password_field_all_algorithms(self):
        for algorithm in LDAPPasswordAlgorithm:
            with self.subTest(algorithm=algorithm):
                model_cls = get_dynamic_password_model(algorithm)
                instance = model_cls.objects.create(username=generate_random_username(), password='')
                self._test_password_field_single_algorithm(instance)

    def _test_single_algorithm_bypassed(self, algorithm: LDAPPasswordAlgorithm):
        """
        Test algorithm functions themselves without any Field shenanigans.
        """
        password = str(secrets.token_hex(8))
        hashed_password = self.get_hash(password, algorithm).encode()

        with connections[self.user._state.db].cursor() as cursor:
            cursor: DatabaseCursor
            cursor.connection.modify_s(self.user.dn, [(ldap.MOD_REPLACE, 'userPassword', hashed_password)])
            self.assertSuccessfulBind(self.user.dn, password)

    def test_all_algorithms_bypassed(self):
        for algorithm in LDAPPasswordAlgorithm:
            with self.subTest(algorithm=algorithm):
                self._test_single_algorithm_bypassed(algorithm)

    def test_password_field_custom_handler_options_argon2(self):
        password = str(secrets.token_hex(8))
        instance = PasswordFieldModelWithCustomHandlerOptionsArgon2.objects.create(
            username=generate_random_username(), password=password
        )
        self.assertSuccessfulBind(instance.dn, password)

        expected = {'m': str(_ARGON2_MEMORY_COST), 'p': str(_ARGON2_PARALLELISM), 't': str(_ARGON2_ROUNDS)}
        match = ARGON_RE.match(instance.password).groupdict()
        self.assertDictEqual(expected, match)

    def test_password_field_custom_handler_options_pbkdf2(self):
        password = str(secrets.token_hex(8))
        instance = PasswordFieldModelWithCustomHandlerOptionsPBKDF2.objects.create(
            username=generate_random_username(), password=password
        )
        self.assertSuccessfulBind(instance.dn, password)

        match = PBKDF2_SHA512_RE.match(instance.password).group('rounds')
        self.assertEqual(str(_PBKDF2_ROUNDS), match)

    def test_password_field_pre_save_hash(self):
        """
        Test if the password field is updated with the hashed value after saving.
        """
        password = str(secrets.token_hex(8))
        algorithm = LDAPPasswordAlgorithm.SSHA512
        model_cls = get_dynamic_password_model(algorithm)
        instance = model_cls.objects.create(username=generate_random_username(), password=password)
        self.assertSuccessfulBind(instance.dn, password)
        self.assertNotEqual(instance.password, password)
