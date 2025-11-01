from collections.abc import Iterable, Sequence

import ldap


class LDAPRequest(dict):
    charset: str = 'utf-8'  # default

    def get_encoded_values(self, values: Iterable[bytes | str]) -> list[bytes]:
        return [v.encode(self.charset) if isinstance(v, str) else v for v in values]


class AddRequest(LDAPRequest):
    def add(self, name: str, raw_values: Sequence[bytes | str]):
        vals: list[bytes] = self.get_encoded_values(raw_values)
        if vals:
            self[name] = vals

    def as_modlist(self) -> list[tuple[str, list[bytes]]]:
        return list(self.items())

    def __str__(self):
        lines = []
        for attr, vals in self.items():
            for v in vals:
                lines.append(f'{attr}: {v!r}')
        return '\n'.join(lines)


class ModifyRequest(LDAPRequest):
    def add(self, attr: str, values: Iterable[bytes | str]):
        lst = self.setdefault(attr, [])
        vals = self.get_encoded_values(values or [])
        lst.extend((ldap.MOD_ADD, val) for val in vals)

    def replace(self, attr, values):
        self[attr] = [(ldap.MOD_REPLACE, list(self.get_encoded_values(values)))]

    def delete(self, attr, values: Iterable | None = None):
        lst = self.setdefault(attr, [])
        if values is None:
            self[attr] = [(ldap.MOD_DELETE, None)]
            return

        vals = self.get_encoded_values(values)
        lst.extend((ldap.MOD_DELETE, val) for val in vals)

    def as_modlist(self) -> list[tuple[int, str, list[bytes]]]:
        modlist = ()
        for attr, mods in self.items():
            for mod in mods:
                modlist += ((mod[0], attr, mod[1]),)
        return modlist

    def __str__(self):
        lines = []
        for attr, vals in self.items():
            for v in vals:
                lines.append(f'{attr}: {v!r}')
        return '\n'.join(lines)
