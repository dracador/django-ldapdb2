# PrimaryDistinguishedNameField Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Enable `LDAPModel.objects.get(dn='uid=john,...')` by converting DN-exact lookups into SCOPE_BASE searches instead of broken `(dn=xyz)` filters.

**Architecture:** Add `PrimaryDistinguishedNameField` subclass of `DistinguishedNameField` used exclusively for `LDAPModel.dn`. The compiler detects lookups on this field type, extracts the DN value, and uses it as the search base with `SCOPE_BASE` — removing the DN condition from the LDAP filter. Combined filters (DN + other conditions) work naturally since `SCOPE_BASE` still evaluates the filter against the single entry.

**Tech Stack:** Django ORM internals (WhereNode, Lookup), python-ldap scopes

---

### Task 1: Add PrimaryDistinguishedNameField

**Files:**
- Modify: `ldapdb/models/fields.py:252-263` (after `DistinguishedNameField`)
- Modify: `ldapdb/models/base.py:21,99` (import + field declaration)

**Step 1: Add the new field class in `ldapdb/models/fields.py`**

Add after the `DistinguishedNameField` class (after line 281):

```python
class PrimaryDistinguishedNameField(DistinguishedNameField):
    """The entry's own Distinguished Name. Lookups on this field are converted
    to SCOPE_BASE searches by the compiler instead of generating (dn=...) filters."""
    _allowed_lookups = {'exact', 'iexact', 'in', 'isnull'}
```

**Step 2: Update `LDAPModel.dn` to use the new field**

In `ldapdb/models/base.py`:
- Change import on line 21: add `PrimaryDistinguishedNameField`
- Change line 99 from:
  ```python
  dn = DistinguishedNameField(db_column='dn', unique=True, read_only=True, hidden=True)
  ```
  to:
  ```python
  dn = PrimaryDistinguishedNameField(db_column='dn', unique=True, read_only=True, hidden=True)
  ```

**Step 3: Run existing tests to confirm nothing breaks**

Run: `python -m django test --settings example.settings -v2 2>&1 | tail -5`
Expected: All existing tests pass (test_ldapuser_get_via_dn will still fail — that's expected).

**Step 4: Commit**

```
feat: add PrimaryDistinguishedNameField for LDAPModel.dn
```

---

### Task 2: Compiler — extract DN lookup and build SCOPE_BASE search

**Files:**
- Modify: `ldapdb/backends/ldap/compiler.py` (import + new methods + modify `_build_ldap_search` and `_parse_lookup`)

**Step 1: Write the failing test**

In `example/tests/test_sql_compiler.py`, the test `test_ldapuser_get_via_dn` (line 27) already exists and fails. Add an additional test for the LDAPSearch shape:

```python
def test_ldapuser_get_via_dn_ldap_search(self):
    """Verify that a DN lookup produces a SCOPE_BASE search with the DN as base."""
    import ldap
    queryset = LDAPUser.objects.filter(dn=TEST_LDAP_USER_1.dn)
    expected_ldap_search = get_new_ldap_search(
        base=TEST_LDAP_USER_1.dn,
        scope=ldap.SCOPE_BASE,
    )
    self.assertLDAPSearchIsEqual(queryset, expected_ldap_search)
```

Run: `python -m django test --settings example.settings example.tests.test_sql_compiler.SQLCompilerTestCase.test_ldapuser_get_via_dn_ldap_search -v2`
Expected: FAIL

**Step 2: Implement DN extraction in the compiler**

In `ldapdb/backends/ldap/compiler.py`:

Add import at the top (around line 18):
```python
from ldapdb.models.fields import PrimaryDistinguishedNameField, UpdateStrategy
```
(replacing the existing `from ldapdb.models.fields import UpdateStrategy`)

Add a new method to `SQLCompiler` (after `_compile_order_by`, before `_build_ldap_search`):

```python
def _extract_primary_dn_value(self, node: WhereNode) -> str | None:
    """Walk the WhereNode tree to find an exact lookup on PrimaryDistinguishedNameField.

    Returns the DN value if found in a simple extractable position (top-level AND child),
    or None if not found / not extractable.
    Raises NotSupportedError for unsupported patterns (OR with DN, dn__in with multiple values).
    """
    if not node.children:
        return None

    for child in node.children:
        if not isinstance(child, Lookup):
            continue

        field = child.lhs.target if isinstance(child.lhs, Col) else child.lhs
        if not isinstance(field, PrimaryDistinguishedNameField):
            continue

        # Found a lookup on the primary DN field
        if node.connector == 'OR':
            raise NotSupportedError(
                'OR conditions involving the primary DN field are not supported. '
                'The DN is used as the search base, not as a filter.'
            )

        if isinstance(child, In):
            if len(child.rhs) == 1:
                return child.rhs[0]
            raise NotSupportedError(
                'dn__in with multiple values is not supported. '
                'The DN is used as the search base, so only a single value is allowed.'
            )

        if isinstance(child, Exact):
            return child.rhs

    return None
```

**Step 3: Modify `_parse_lookup` to skip PrimaryDistinguishedNameField**

In `_parse_lookup` (around line 142), add an early return at the start of the method, after determining `field_name`:

```python
def _parse_lookup(self, lookup: Lookup) -> str:
    """Convert a Lookup to an LDAP filter string using the defined operators."""
    lhs = lookup.lhs
    rhs = lookup.rhs

    if isinstance(lhs, Col):
        field_name = lhs.target.column
    elif isinstance(lhs, Field):
        field_name = lhs.column
    else:
        raise NotImplementedError(f'Unsupported lhs type: {type(lhs)}')

    # Skip primary DN lookups — they are handled by _extract_primary_dn_value
    target_field = lhs.target if isinstance(lhs, Col) else lhs
    if isinstance(target_field, PrimaryDistinguishedNameField):
        return ''

    # ... rest of the method unchanged
```

**Step 4: Modify `_where_node_to_ldap_filter` to handle empty subfilters**

In `_where_node_to_ldap_filter`, the DN lookup now returns `''`. We need to filter those out. Change the subfilters list handling (around line 208-241):

Replace the line:
```python
combined_filter = ''.join(subfilters)
```
with:
```python
subfilters = [sf for sf in subfilters if sf]
combined_filter = ''.join(subfilters)
```

And update the length check to handle the case where all subfilters were DN lookups (the list is now empty):
```python
if not subfilters:
    return ''
```
Add this right after `combined_filter = ''.join(subfilters)`, before the `if len(subfilters) == 1:` block.

**Step 5: Modify `_build_ldap_search` to use extracted DN**

In `_build_ldap_search` (line 277), add DN extraction before calling `_compile_where()`:

```python
def _build_ldap_search(self, with_limits):
    attrlist = self._compile_select()
    control_type = LDAPSearchControlType.NO_CONTROL
    limit = 0
    ordering_rules = None

    # Check if the query filters on the primary DN field
    base = self.query.model.base_dn
    scope = self.query.model.search_scope
    dn_value = self._extract_primary_dn_value(self.query.where) if self.query.where else None
    if dn_value:
        base = dn_value
        scope = ldap.SCOPE_BASE

    if attrlist:
        ordering_rules = self._compile_order_by()
        if self.connection.features.supports_sssvlv and ordering_rules:
            control_type = LDAPSearchControlType.SSSVLV
        elif self.connection.features.supports_simple_paged_results:
            control_type = LDAPSearchControlType.SIMPLE_PAGED_RESULTS

        if with_limits and self.query.high_mark:
            limit = self.query.high_mark - self.query.low_mark
    else:
        attrlist = ['1.1']

    ldap_search = LDAPSearch(
        base=base,
        scope=scope,
        attrlist=attrlist,
        filterstr=self._compile_where(),
        ordering_rules=ordering_rules,
        offset=self.query.low_mark,
        control_type=control_type,
        limit=limit,
    )
    return ldap_search
```

**Step 6: Run tests**

Run: `python -m django test --settings example.settings example.tests.test_sql_compiler.SQLCompilerTestCase.test_ldapuser_get_via_dn_ldap_search example.tests.test_sql_compiler.SQLCompilerTestCase.test_ldapuser_get_via_dn -v2`
Expected: PASS

Also run full suite:
Run: `python -m django test --settings example.settings -v2 2>&1 | tail -5`
Expected: All tests pass.

**Step 7: Commit**

```
feat: compiler extracts DN lookups into SCOPE_BASE searches
```

---

### Task 3: Edge case tests

**Files:**
- Modify: `example/tests/test_sql_compiler.py`

**Step 1: Add edge case tests**

```python
def test_ldapuser_filter_dn_with_other_conditions(self):
    """DN lookup combined with other filters uses SCOPE_BASE + remaining filter."""
    import ldap
    queryset = LDAPUser.objects.filter(dn=TEST_LDAP_USER_1.dn, username='user1')
    expected_ldap_search = get_new_ldap_search(
        base=TEST_LDAP_USER_1.dn,
        scope=ldap.SCOPE_BASE,
        filterstr='(uid=user1)',
    )
    self.assertLDAPSearchIsEqual(queryset, expected_ldap_search)

def test_ldapuser_filter_dn_in_single_value(self):
    """dn__in with a single value is treated as an exact match."""
    import ldap
    queryset = LDAPUser.objects.filter(dn__in=[TEST_LDAP_USER_1.dn])
    expected_ldap_search = get_new_ldap_search(
        base=TEST_LDAP_USER_1.dn,
        scope=ldap.SCOPE_BASE,
    )
    self.assertLDAPSearchIsEqual(queryset, expected_ldap_search)

def test_ldapuser_filter_dn_in_multiple_values_raises(self):
    """dn__in with multiple values is not supported."""
    from django.db import NotSupportedError
    with self.assertRaises(NotSupportedError):
        list(LDAPUser.objects.filter(dn__in=[TEST_LDAP_USER_1.dn, 'cn=other,dc=example,dc=org']))

def test_ldapuser_filter_dn_or_raises(self):
    """OR conditions with DN are not supported."""
    from django.db import NotSupportedError
    from django.db.models import Q
    with self.assertRaises(NotSupportedError):
        list(LDAPUser.objects.filter(Q(dn=TEST_LDAP_USER_1.dn) | Q(username='user1')))
```

**Step 2: Run all new tests**

Run: `python -m django test --settings example.settings example.tests.test_sql_compiler -v2`
Expected: All pass.

**Step 3: Run full test suite**

Run: `python -m django test --settings example.settings -v2 2>&1 | tail -5`
Expected: All pass.

**Step 4: Commit**

```
test: add edge case tests for DN-based lookups
```

---

### Task 4: Export PrimaryDistinguishedNameField for end users

**Files:**
- Modify: `example/models.py:3-17` (add to imports, no usage change needed — but confirms it's importable)

**Step 1: Add to the fields import in example/models.py**

This is optional but confirms the field is properly importable. Add `PrimaryDistinguishedNameField` to the import list in `example/models.py` (line 3-17).

**Step 2: Run linter**

Run: `ruff check .`
Expected: No errors (remove unused import if ruff flags it — it's just for verification).

**Step 3: Commit**

```
feat: export PrimaryDistinguishedNameField from fields module
```
