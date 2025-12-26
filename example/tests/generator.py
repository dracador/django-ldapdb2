import uuid

from faker import Faker

from example.models import LDAPGroup, LDAPUser


def randomize_string(string: str) -> str:
    return f'{string}-{uuid.uuid4().hex}'


def generate_random_group_name() -> str:
    fake = Faker()
    return randomize_string(fake.name())


def generate_random_username() -> str:
    fake = Faker()
    first_name = fake.first_name()
    last_name = fake.last_name()
    return randomize_string(f'{first_name.lower()}.{last_name.lower()}')


def create_random_ldap_group(model_cls=LDAPGroup, do_not_create: bool = False, **kwargs) -> LDAPGroup:
    name = generate_random_group_name()
    default_kwargs = {
        # dn=f'cn={name},ou=Groups,dc=example,dc=org',
        'org_unit': 'group1',
        'name': name,
        'members': [
            'uid=admin,ou=Users,dc=example,dc=org',
            'uid=user1,ou=Users,dc=example,dc=org',
        ],
    }
    if do_not_create:
        return model_cls(**{**default_kwargs, **kwargs})

    return model_cls.objects.create(**{**default_kwargs, **kwargs})


def create_random_ldap_user(model_cls=LDAPUser, do_not_create: bool = False, **kwargs) -> LDAPUser:
    fake = Faker()
    first_name = fake.first_name()
    last_name = fake.last_name()
    username = randomize_string(f'{first_name.lower()}.{last_name.lower()}')
    default_kwargs = {
        # dn=f'uid={username},ou=Users,dc=example,dc=org',
        'password': 'password',
        'first_name': first_name,
        'last_name': last_name,
        'mail': f'{username}@example.com',
        'name': f'{first_name} {last_name}',
        'username': username,
        'is_active': True,
    }
    if do_not_create:
        return model_cls(**{**default_kwargs, **kwargs})

    return model_cls.objects.create(**{**default_kwargs, **kwargs})
