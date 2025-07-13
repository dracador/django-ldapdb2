from faker import Faker

from example.models import LDAPUser


def create_random_ldap_user(**kwargs) -> LDAPUser:
    fake = Faker()
    first_name = fake.first_name()
    last_name = fake.last_name()
    username = f'{first_name.lower()}.{last_name.lower()}'
    default_kwargs = {
        # dn=f'uid={username},ou=Users,dc=example,dc=org',
        'first_name': first_name,
        'last_name': first_name,
        'mail': f'{username}@example.com',
        'name': f'{first_name} {last_name}',
        'username': username,
    }
    return LDAPUser.objects.create(
        **{**default_kwargs, **kwargs}
    )
