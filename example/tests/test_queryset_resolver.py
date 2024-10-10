from django.test import TestCase

from example.models import LDAPUser


class QueryResolverTestCase(TestCase):
    """
    TODO: Implement the following test cases:
    --- Basic ---
    LDAPUser.objects.all()
    LDAPGroup.objects.all()
    LDAPUser.objects.filter(uid='test')
    LDAPUser.objects.filter(uid__lookup='test')
    LDAPUser.objects.filter(uid__in=['test1', 'test2'])
    LDAPUser.objects.filter(uid__datetimelookup__transform='test') - optional (see comment in features.py)
    LDAPUser.objects.filter(cn__contains='test').exclude(uid='specific_user')

    --- Aggregation ---
    LDAPUser.objects.all().count()
    LDAPUser.objects.aggregate(Count('uid'))

    --- Annotation ---
    LDAPUser.objects.annotate(num_uids=Count('uid'))

    --- Q queries ---
    LDAPUser.objects.filter(Q(uid='test') & Q(uid='test2'))
    LDAPUser.objects.filter(Q(uid='test') | Q(uid='test2'))
    LDAPUser.objects.filter(~Q(uid='test'))
    LDAPUser.objects.filter(Q(uid='test') & ~Q(uid='test2'))
    LDAPUser.objects.filter(Q(uid='test') | ~Q(uid='test2'))
    """

    def test_resolve_basic_queryset(self):
        LDAPUser.objects.all()
