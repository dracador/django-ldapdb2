from django.test import TestCase

from example.models import LDAPUser


class QueryResolverTestCase(TestCase):
    """
    TODO: Implement the following test cases:
    --- Basic ---
    LDAPUser.objects.all()
    LDAPGroup.objects.all()
    LDAPUser.objects.all().exists()
    LDAPUser.objects.filter(uid='test')
    LDAPUser.objects.filter(uid__lookup='test')
    LDAPUser.objects.filter(uid__in=['test1', 'test2'])
    LDAPUser.objects.filter(uid__datetimelookup__transform='test') - optional (see comment in features.py)
    LDAPUser.objects.filter(cn__contains='test').exclude(uid='specific_user')

    --- Hidden DN Field handling ---
    LDAPUser.objects.get(dn='uid=admin,dc=example,dc=com').dn

    --- Ordering ---
    LDAPUser.objects.all().order_by('uid')

    --- Values ---
    LDAPUser.objects.all().values('uid', 'cn')

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

    --- Deferred fields ---
    LDAPUser.objects.defer('cn').get(uid='test').cn

    --- Renaming ---
    u = LDAPUser.objects.get(uid='test'); u.uid = 'test_renamed'; u.save()
    """

    def test_resolve_basic_queryset(self):
        LDAPUser.objects.all()
