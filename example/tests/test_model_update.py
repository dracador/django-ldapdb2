from example.models import LDAPUser
from .base import LDAPTestCase
from .constants import TEST_LDAP_USER_1


class ModelUpdateTestCase(LDAPTestCase):
    @staticmethod
    def _get_user_1_object():
        return LDAPUser.objects.get(username=TEST_LDAP_USER_1.username)

    def test_ldapuser_update(self):
        obj = self._get_user_1_object()
        obj.last_name = 'new_last_name'
        obj.save()
        self.assertLDAPModelObjectsAreEqual(TEST_LDAP_USER_1, obj, exclude=['thumbnail_photo'])
