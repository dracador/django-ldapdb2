# Contributing

Thanks for considering a contribution!

## Environment

We recommend Python 3.12+ and a virtual environment.

### Setup

#### Virtual Environment

```bash
# via uv (recommended)
uv sync --dev

# or manually
python -m venv .venv
. .venv/bin/activate
pip install -e .[dev]
```

#### Start LDAP server

```bash
docker-compose up openldap -f tests/openldap-server/docker-compose.yml
```

## Tests
```bash
# make sure 'dev' dependencies are installed
uv sync --group dev

./manage.py test
```

## Linting
```bash
uv run ruff check .
```

## Build documentation
```bash
# make sure 'docs' dependencies are installed
uv sync --group docs

# serve locally
uv run mkdocs serve

# build static files
uv run mkdocs build
```