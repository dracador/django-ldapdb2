from django.db.models import Value
from django.db.models.functions import Lower, Upper

from .base import LDAPTestCase


class AnnotationTestCase(LDAPTestCase):
    def test_annotation_expression_value(self):
        u = self.get_testuser_objects().annotate(one=Value(1)).first()
        self.assertEqual(u.one, 1)

    def test_annotation_expression_lower(self):
        u = self.get_testuser_objects().annotate(lower=Lower('username')).first()
        self.assertEqual(u.lower, u.username.lower())

    def test_annotation_expression_upper(self):
        u = self.get_testuser_objects().annotate(upper=Upper('username')).first()
        self.assertEqual(u.upper, u.username.upper())
