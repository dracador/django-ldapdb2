from operator import ge, gt, le, lt

LDAP_OPERATORS = {
    "exact":       ("=%s", lambda a, b: a == b),
    "iexact":      ("=%s", lambda a, b: str(a).lower() == str(b).lower()),
    "contains":    ("=*%s*", lambda a, b: b in a if a is not None else False),
    "icontains":   ("=*%s*", lambda a, b: str(b).lower() in str(a).lower()),
    "startswith":  ("=%s*", lambda a, b: str(a).startswith(b)),
    "istartswith": ("=%s*", lambda a, b: str(a).lower().startswith(str(b).lower())),
    "endswith":    ("=*%s", lambda a, b: str(a).endswith(b)),
    "iendswith":   ("=*%s", lambda a, b: str(a).lower().endswith(str(b).lower())),
    "gt":          (">%s",  gt),
    "gte":         (">=%s", ge),
    "lt":          ("<%s",  lt),
    "lte":         ("<=%s", le),

    # "isnull and "in" will be handled by SQLCompiler._parse_lookup
    "isnull":      (None, lambda a, b: (a is None) == bool(b)),
    "in":          (None, lambda a, b: a in b),
}
