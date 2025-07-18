import datetime
from zoneinfo import ZoneInfo

from ldapdb.fields import BooleanField
from ldapdb.utils import format_generalized_time, parse_generalized_time

from .base import BaseLDAPTestUser, LDAPTestCase
from .generator import create_random_ldap_user


class BooleanTestModel(BaseLDAPTestUser):
    ldap_boolean = BooleanField()


class BooleanFieldTests(LDAPTestCase):
    def test_boolean_field_true(self):
        """Test that 'TRUE' from LDAP converts to True."""
        instance = BooleanTestModel(username='username', ldap_boolean=True)
        instance.full_clean()
        self.assertTrue(instance.ldap_boolean)


class DateFieldTests(LDAPTestCase):
    def test_date_formatting(self):
        date_args = (1990, 1, 1, 1, 0, 0)
        ldap_string = '19900101010000Z'
        ldap_string_plus_one = '19900101020000Z'
        ldap_string_plus_one_with_tz = '19900101010000+0100'

        # check formatting to LDAP string
        datetime_obj = datetime.datetime(*date_args, tzinfo=datetime.UTC)
        formatted_datetime = format_generalized_time(datetime_obj)
        self.assertEqual(formatted_datetime, ldap_string)

        # check parsing from LDAP string
        obj = parse_generalized_time(ldap_string)
        self.assertEqual(obj, ldap_string)

        # check parsing from LDAP string with timezone
        datetime_obj_with_tz = datetime.datetime(*date_args, tzinfo=ZoneInfo('Europe/Berlin'))
        obj = format_generalized_time(datetime_obj_with_tz)
        self.assertEqual(obj, ldap_string_plus_one)

        obj = format_generalized_time(datetime_obj_with_tz, include_tz=True)
        self.assertEqual(obj, ldap_string_plus_one_with_tz)

    def test_date_field_datetime_object(self):
        instance = create_random_ldap_user(date_field=datetime.date(1990, 1, 1), do_not_create=True)
        instance.full_clean()
        instance.save()
        self.assertEqual(instance.date_field, datetime.date(1990, 1, 1))

    def test_date_field_string(self):
        instance = create_random_ldap_user(date_field='1990-01-01', do_not_create=True)
        instance.full_clean()
        instance.save()
        self.assertEqual(instance.date_field, datetime.date(1990, 1, 1))
