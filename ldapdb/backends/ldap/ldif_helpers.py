from collections.abc import Sequence

import ldap


def diff_multi(current: list[bytes], desired: list[bytes]):
    cur = set(current)
    des = set(desired)
    return sorted(des - cur), sorted(cur - des)


class LDAPRequest(dict):
    charset: str = 'utf-8'  # default

    def get_encoded_values(self, values: Sequence[bytes | str]) -> list[bytes]:
        return [v.encode(self.charset) if isinstance(v, str) else v for v in values]


class AddRequest(LDAPRequest):
    def add(self, name: str, raw_values: Sequence[bytes | str]):
        vals: list[bytes] = self.get_encoded_values(raw_values)
        if vals:
            self[name] = vals

    def as_modlist(self):
        return list(self.items())

    def __str__(self):
        lines = []
        for attr, vals in self.items():
            for v in vals:
                lines.append(f'{attr}: {v!r}')
        return '\n'.join(lines)


class ModifyRequest(LDAPRequest):
    def add(self, attr, values):
        op, lst = self.setdefault(attr, (ldap.MOD_ADD, []))
        lst.extend(self.get_encoded_values(values))

    def replace(self, attr, values):
        self[attr] = (ldap.MOD_REPLACE, list(self.get_encoded_values(values)))

    def delete(self, attr):
        self[attr] = (ldap.MOD_DELETE, [])

    def as_modlist(self):
        return [(op, attr, vals) for attr, (op, vals) in self.items()]

    def __str__(self):
        lines = []
        for attr, vals in self.items():
            for v in vals:
                lines.append(f'{attr}: {v!r}')
        return '\n'.join(lines)
