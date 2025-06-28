import base64

from django.core.management.base import BaseCommand

from example.tests.constants import TEST_LDAP_AVAILABLE_USERS


def encode_ldif_attr(key: str, value) -> str:
    if value is None:
        return ''
    if isinstance(value, bool):
        value = 'TRUE' if value else 'FALSE'
    elif isinstance(value, int):
        value = str(value)
    elif isinstance(value, bytes):
        # Base64-encode binary data like jpegPhoto
        encoded = base64.b64encode(value).decode('ascii')
        return f"{key}:: {encoded}"
    else:
        value = str(value)
        # Force base64 for values with leading/trailing spaces or non-ASCII
        needs_b64 = value and (not value.isprintable() or value != value.strip())
        if needs_b64:
            encoded = base64.b64encode(value.encode()).decode('ascii')
            return f"{key}:: {encoded}"
    return f"{key}: {value}"


def model_to_ldif(model) -> str:
    lines = [f'dn: {model.dn}']
    for oc in model.object_classes:
        lines.append(f'objectClass: {oc}')

    for field in model._meta.fields:
        if field.db_column == 'dn':
            # Skip the 'dn' field as it's already included in the first line
            continue

        val = getattr(model, field.attname, None)
        if val is not None:
            lines.append(encode_ldif_attr(field.db_column, val))

    return '\n'.join(lines)


class Command(BaseCommand):
    help = "Export LDAP user data from constants.py to LDIF"

    def add_arguments(self, parser):
        parser.add_argument(
            '--output',
            '-o',
            type=str,
            help="Optional output file. Defaults to tests/openldap-server/ldifs/generated_data.ldif."
        )
        parser.add_argument(
            '--stdout',
            '-s',
            type=str,
            help="Output to stdout, instead."
        )

    def handle(self, *_args, **options):
        ldif_entries = []
        for user in TEST_LDAP_AVAILABLE_USERS:
            ldif_entries.append(model_to_ldif(user))

        ldif_output = "\n\n".join(ldif_entries)

        output_path = options.get('output')
        if output_path:
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(ldif_output)
            self.stdout.write(self.style.SUCCESS(f"LDIF written to {output_path}"))
        else:
            self.stdout.write(ldif_output)
