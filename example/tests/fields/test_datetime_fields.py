import datetime
from zoneinfo import ZoneInfo

from django.conf import settings
from django.test import override_settings
from django.utils import timezone
from ldapdb.models.fields import DateField, DateTimeField, format_generalized_time, parse_generalized_time

from example.tests.base import BaseLDAPTestUser, LDAPTestCase
from example.tests.generator import generate_random_username


class DateTestModel(BaseLDAPTestUser):
    date_field = DateField(db_column='x-user-date')


class DateTimeTestModel(BaseLDAPTestUser):
    date_time_field = DateTimeField(db_column='x-user-dateTime')


class DateTimeWithTimezoneTestModel(BaseLDAPTestUser):
    date_time_tz_field = DateTimeField(db_column='x-user-dateTime', include_tz=True)


class DateFieldTests(LDAPTestCase):
    @staticmethod
    def _adjust_expected_dt(dt):
        """
        Helper to convert the expected datetime to match Django's USE_TZ setting.
        """
        if settings.USE_TZ:
            return dt

        # If USE_TZ=False, the DB returns a naive datetime in the default timezone.
        # We have to convert our expected 'aware' dt to that same naive representation.
        return timezone.make_naive(dt, timezone.get_default_timezone())

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
        self.assertEqual(instance.date_time_field, self._adjust_expected_dt(dt))

    def test_datetime_field_string(self):
        dt = datetime.datetime(1990, 1, 1, hour=1, tzinfo=ZoneInfo('UTC'))
        instance = DateTimeTestModel(date_time_field='1990-01-01 01:00:00', username=generate_random_username())
        instance.full_clean()
        instance.save()
        instance.refresh_from_db()
        self.assertEqual(instance.date_time_field, self._adjust_expected_dt(dt))

    def test_datetime_tz_field_object(self):
        dt = datetime.datetime(1990, 1, 1, hour=1, tzinfo=datetime.timezone(datetime.timedelta(hours=1)))
        instance = DateTimeWithTimezoneTestModel(date_time_tz_field=dt, username=generate_random_username())
        instance.full_clean()
        instance.save()
        instance.refresh_from_db()
        self.assertEqual(instance.date_time_tz_field, self._adjust_expected_dt(dt))

    def test_datetime_tz_field_string(self):
        dt = datetime.datetime(1990, 1, 1, hour=1, tzinfo=datetime.timezone(datetime.timedelta(hours=1)))
        instance = DateTimeWithTimezoneTestModel(
            date_time_tz_field='1990-01-01 01:00:00+0100', username=generate_random_username()
        )
        instance.full_clean()
        instance.save()
        instance.refresh_from_db()
        self.assertEqual(instance.date_time_tz_field, self._adjust_expected_dt(dt))

    @override_settings(TIME_ZONE='Asia/Tokyo', USE_TZ=True)
    def test_datetime_field_string_with_other_timezone(self):
        dt = datetime.datetime(1990, 1, 1, tzinfo=ZoneInfo('UTC'))

        # the string itself does not contain a timezone, so it should be interpreted as the django TIME_ZONE setting
        instance = DateTimeTestModel(date_time_field='1990-01-01 09:00:00', username=generate_random_username())
        instance.full_clean()
        instance.save()
        instance.refresh_from_db()
        self.assertEqual(instance.date_time_field, dt)

    @override_settings(TIME_ZONE='Asia/Tokyo', USE_TZ=True)
    def test_timezone_aware_conversion(self):
        # If TIME_ZONE is Tokyo (UTC+9), a naive input like 12:00
        # should be interpreted as 12:00 JST -> 03:00 UTC.
        naive_dt = datetime.datetime(2023, 1, 1, 12, 0, 0)
        user = DateTimeTestModel.objects.create(username=generate_random_username(), date_time_field=naive_dt)

        user.refresh_from_db()
        expected_utc = datetime.datetime(2023, 1, 1, 3, 0, 0, tzinfo=ZoneInfo('UTC'))
        self.assertEqual(user.date_time_field, expected_utc)

    @override_settings(TIME_ZONE='UTC', USE_TZ=False)
    def test_use_tz_false(self):
        """
        If USE_TZ is False, the database should return naive datetimes.
        """
        aware_dt = datetime.datetime(2023, 1, 1, 12, 0, 0, tzinfo=ZoneInfo('UTC'))

        # Even if we pass an aware DT, Django might strip it or warn,
        # but our field stores it as UTC GeneralizedTime.
        user = DateTimeTestModel.objects.create(username=generate_random_username(), date_time_field=aware_dt)

        # On retrieval, we expect a naive datetime
        user.refresh_from_db()
        self.assertIsNone(user.date_time_field.tzinfo)
        self.assertEqual(user.date_time_field.hour, 12)

    def test_date_field_midnight_utc(self):
        """
        Verify that DateField is always stored as Midnight UTC
        regardless of local time.
        """
        from datetime import date

        d = date(2023, 6, 1)

        user = DateTestModel.objects.create(username=generate_random_username(), date_field=d)

        user.refresh_from_db()
        self.assertEqual(user.date_field, d)
