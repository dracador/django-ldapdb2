from collections.abc import Sequence

import ldap


def diff_multi(current: list[bytes], desired: list[bytes]):
    cur = set(current)
    des = set(desired)
    return sorted(des - cur), sorted(cur - des)


class AddRequest(dict):
    charset: str = 'utf-8'  # default

    def add(self, name: str, raw_values: Sequence[bytes | str]):
        vals: list[bytes] = [v.encode(self.charset) if isinstance(v, str) else v for v in raw_values]
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


class ModifyRequest(list):
    charset: str = 'utf-8'

    def replace(self, name: str, raw_values: Sequence[bytes | str]):
        vals = [v.encode(self.charset) if isinstance(v, str) else v for v in raw_values]
        self.append((ldap.MOD_REPLACE, name, vals))

    def __str__(self):
        opnames = {ldap.MOD_REPLACE: 'REPLACE'}
        return '\n'.join(f'{opnames.get(op, op)} {attr}: {vals!r}' for op, attr, vals in self)
