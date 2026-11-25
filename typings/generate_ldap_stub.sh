#!/usr/bin/env bash

# Since python-ldap is just the C wrapper we don't have proper types in code, so we have to generate them.
# This is all horrible but for now, the best way to do it until python-ldap brings their own.

set -euo pipefail

cd "$(dirname "$0")/.."

python_version=$(uv run python -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
site_packages=$(uv run python -c 'import sysconfig; print(sysconfig.get_path("purelib"))')
ldap_version=$(uv run python -c 'import ldap; print(ldap.__version__)')

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

# to make stubgen see the stuff from the C extension, it needs --inspect-mode
PYTHONPATH=$site_packages uvx -p "$python_version" --from mypy stubgen --inspect-mode -m ldap -o "$tmp" > /dev/null

# create only a partial stub for ldap/__init__.py. Everything else should be from the python side
mkdir -p typings/ldap-stubs
printf 'partial\n' > typings/ldap-stubs/py.typed
{
    echo "# Generated from python-ldap $ldap_version by typings/generate_ldap_stub.sh. Do not edit by hand."
    echo
    cat "$tmp/ldap/__init__.pyi"
} > typings/ldap-stubs/__init__.pyi
