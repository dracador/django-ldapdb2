from django.db.models import Value
from django.db.models.functions import Length, Lower

from example.models import LDAPUser
from .base import LDAPTestCase
from .constants import TEST_LDAP_USER_1


class AnnotationTestCase(LDAPTestCase):
    def test_annotation_constant(self):
        qs = LDAPUser.objects.annotate(one=Value(1))
        assert qs.first().one == 1

    def test_annotation_expression(self):
        qs = LDAPUser.objects.annotate(lower=Lower("username")).order_by("lower")
        usernames = list(qs.values_list("lower", flat=True))
        assert usernames == sorted(u.lower() for u in usernames)

    def test_annotation_length_and_filter(self):
        qs = (
            LDAPUser.objects
            .annotate(n=Length("username"))
            .filter(n__gt=3)
            .values_list("username", flat=True)
        )
        assert all(len(u) > 3 for u in qs)

    def test_slice_with_annotation(self):
        obj = LDAPUser.objects.annotate(lower=Lower("username")).order_by("lower")[1]
        assert obj.username == TEST_LDAP_USER_1.username
