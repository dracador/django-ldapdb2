import datetime
from zoneinfo import ZoneInfo

from ldapdb.models.fields import BooleanField, DateField, DateTimeField, format_generalized_time, parse_generalized_time

from .base import BaseLDAPTestUser, LDAPTestCase
from .generator import generate_random_username


class BooleanTestModel(BaseLDAPTestUser):
    is_active = BooleanField(db_column='x-user-isActive')


class BooleanFieldTests(LDAPTestCase):
    def test_boolean_field_true(self):
        """Test that 'TRUE' from LDAP converts to True."""
        instance = BooleanTestModel(is_active=True, username=generate_random_username())
        instance.full_clean()
        instance.save()
        instance.refresh_from_db()
        self.assertEqual(instance.is_active, True)


class DateTestModel(BaseLDAPTestUser):
    date_field = DateField(db_column='x-user-date')


class DateTimeTestModel(BaseLDAPTestUser):
    date_time_field = DateTimeField(db_column='x-user-dateTime')


class DateTimeWithTimezoneTestModel(BaseLDAPTestUser):
    date_time_tz_field = DateTimeField(db_column='x-user-dateTime', include_tz=True)


class DateFieldTests(LDAPTestCase):
    def test_date_formatting_utc(self):
        datetime_obj = datetime.datetime(1990, 1, 1, 1, 0, 0, tzinfo=ZoneInfo('UTC'))
        self.assertEqual(format_generalized_time(datetime_obj), '19900101010000Z')

    def test_date_formatting_with_tz_to_utc(self):
        datetime_obj_with_tz = datetime.datetime(1990, 1, 1, 1, 0, 0, tzinfo=ZoneInfo('CET'))
        obj = format_generalized_time(datetime_obj_with_tz)
        self.assertEqual(obj, '19900101000000Z')

    def test_date_formatting_with_tz_to_tz_aware(self):
        datetime_obj_with_tz = datetime.datetime(1990, 1, 1, 1, 0, 0, tzinfo=ZoneInfo('CET'))
        obj = format_generalized_time(datetime_obj_with_tz, include_tz=True)
        self.assertEqual(obj, '19900101010000+0100')

    def test_date_parsing(self):
        datetime_obj = datetime.datetime(1990, 1, 1, 1, 0, 0, tzinfo=ZoneInfo('UTC'))
        self.assertEqual(parse_generalized_time('19900101010000Z'), datetime_obj)

    def test_date_parsing_and_formatting_with_tz(self):
        datetime_str = '19900101010000+0100'
        datetime_obj = parse_generalized_time(datetime_str)
        fmt_datetime_str = format_generalized_time(datetime_obj, include_tz=True)
        self.assertEqual(fmt_datetime_str, datetime_str)

    def test_date_field_object(self):
        d = datetime.date(1990, 1, 1)
        instance = DateTestModel(date_field=d, username=generate_random_username())
        instance.full_clean()
        instance.save()
        instance.refresh_from_db()
        self.assertEqual(instance.date_field, d)

    def test_date_field_string(self):
        d = datetime.date(1990, 1, 1)
        instance = DateTestModel(date_field='1990-01-01', username=generate_random_username())
        instance.full_clean()
        instance.save()
        instance.refresh_from_db()
        self.assertEqual(instance.date_field, d)

    def test_datetime_field_object(self):
        dt = datetime.datetime(1990, 1, 1, hour=1, tzinfo=ZoneInfo('UTC'))
        instance = DateTimeTestModel(date_time_field=dt, username=generate_random_username())
        instance.full_clean()
        instance.save()
        instance.refresh_from_db()
        self.assertEqual(instance.date_time_field, dt)

    def test_datetime_field_string(self):
        dt = datetime.datetime(1990, 1, 1, hour=1, tzinfo=ZoneInfo('UTC'))
        instance = DateTimeTestModel(date_time_field='1990-01-01 01:00:00', username=generate_random_username())
        instance.full_clean()
        instance.save()
        instance.refresh_from_db()
        self.assertEqual(instance.date_time_field, dt)

    def test_datetime_tz_field_object(self):
        dt = datetime.datetime(1990, 1, 1, hour=1, tzinfo=datetime.timezone(datetime.timedelta(hours=1)))
        instance = DateTimeWithTimezoneTestModel(date_time_tz_field=dt, username=generate_random_username())
        instance.full_clean()
        instance.save()
        instance.refresh_from_db()
        self.assertEqual(instance.date_time_tz_field, dt)

    def test_datetime_tz_field_string(self):
        dt = datetime.datetime(1990, 1, 1, hour=1, tzinfo=datetime.timezone(datetime.timedelta(hours=1)))
        instance = DateTimeWithTimezoneTestModel(
            date_time_tz_field='1990-01-01 01:00:00+0100', username=generate_random_username()
        )
        instance.full_clean()
        instance.save()
        instance.refresh_from_db()
        self.assertEqual(instance.date_time_tz_field, dt)
