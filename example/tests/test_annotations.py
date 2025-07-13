from django.db.models import Value
from django.db.models.functions import Lower, LTrim, RTrim, Trim, Upper

from example.models import LDAPUser
from .base import LDAPTestCase


class AnnotationTestCase(LDAPTestCase):
    user: LDAPUser = None

    @classmethod
    def setUpTestData(cls):
        if not cls.user:
            cls.user = LDAPUser.objects.create(
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

    def test_annotation_expression_lower(self):
        u = self.get_annotation_qs().annotate(lower=Lower('username')).first()
        self.assertEqual(u.lower, u.username.lower())

    def test_annotation_expression_upper(self):
        u = self.get_annotation_qs().annotate(upper=Upper('username')).first()
        self.assertEqual(u.upper, u.username.upper())

    @classmethod
    def tearDownClass(cls):
        cls.user.delete()
