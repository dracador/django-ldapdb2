from collections import namedtuple

from django.db.models import Value
from django.db.models.functions import Lower, LTrim, RTrim, Trim, Upper

from example.models import LDAPUser
from .base import LDAPTestCase


class AnnotationTestCase(LDAPTestCase):
    user: LDAPUser = None

    @classmethod
    def setUpTestData(cls):
        if not cls.user:
            cls.user, _created = LDAPUser.objects.get_or_create(
                username="annotation_test",
                name=" Annotation  Test ",
                first_name="Annotation",
                last_name="Test",
                mail="annotation_test@example.com",
            )

    def get_annotation_qs(self):
        return LDAPUser.objects.filter(username=self.user.username)

    def test_annotation_expression_value(self):
        u = self.get_annotation_qs().annotate(one=Value(1)).first()
        self.assertEqual(u.one, 1)

    def test_annotation_expression_value_values(self):
        values = self.get_annotation_qs().annotate(one=Value(1)).values().first()
        self.assertEqual(values['one'], 1)

    def test_annotation_expression_value_values_list(self):
        values = self.get_annotation_qs().annotate(one=Value(1)).values_list('one')
        self.assertEqual(list(values), [(1,)])

    def test_annotation_expression_value_values_list_flat(self):
        values = self.get_annotation_qs().annotate(one=Value(1)).values_list('one', flat=True)
        self.assertEqual(list(values), [1])

    def test_annotation_expression_value_values_list_named(self):
        value_row = self.get_annotation_qs().annotate(one=Value(1)).values_list('one', named=True).first()
        row_tuple_cls = namedtuple('Row', 'one')
        self.assertEqual(value_row, row_tuple_cls(one=1),)

    def test_annotation_expression_lower(self):
        u = self.get_annotation_qs().annotate(lower=Lower('username')).first()
        self.assertEqual(u.lower, u.username.lower())

    def test_annotation_expression_upper(self):
        u = self.get_annotation_qs().annotate(upper=Upper('username')).first()
        self.assertEqual(u.upper, u.username.upper())

    def test_trims(self):
        qs = self.get_annotation_qs().annotate(
            trim=Trim('name'),
            ltrim=LTrim('name'),
            rtrim=RTrim('name'),
        )
        obj = qs.first()
        self.assertEqual(obj.trim, 'Annotation  Test')
        self.assertEqual(obj.ltrim, 'Annotation  Test ')
        self.assertEqual(obj.rtrim, ' Annotation  Test')

    @classmethod
    def tearDownClass(cls):
        cls.user.delete()
