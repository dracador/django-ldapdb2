import shlex

from .lib import LDAPScope, LDAPSearch, LDAPSearchControlType

LDAPSEARCH_SCOPES = {
    LDAPScope.BASE: 'base',
    LDAPScope.ONELEVEL: 'one',
    LDAPScope.SUBTREE: 'sub',
    LDAPScope.SUBORDINATE: 'children',
}


def _get_python_side_steps(search: LDAPSearch) -> list[str]:
    if search.control_type == LDAPSearchControlType.SSSVLV:
        return []

    steps = []
    if search.ordering_rules:
        attributes = ', '.join(attribute for attribute, _rule in search.ordering_rules)
        steps.append(f'sort by {attributes} (byte order)')
    if search.offset or search.limit:
        end = search.offset + search.limit if search.limit else ''
        steps.append(f'slice [{search.offset}:{end}]')
    return steps


def _get_ctrls_as_text(search: LDAPSearch, page_size: int) -> list[str]:
    # TODO: if we ever need to extend this, maybe migrate to custom formatters per ctrl type instead
    #       and then also merge this with the python/ldapsearch sides?
    if search.control_type == LDAPSearchControlType.SIMPLE_PAGED_RESULTS:
        return [f'simple paged results (page size {page_size})']
    if search.control_type != LDAPSearchControlType.SSSVLV:
        return []

    controls = [f'server-side sort ({", ".join(search.sss_ordering_rules)})']
    if search.uses_vlv:
        controls.append(f'VLV offset={search.ldap_offset} count={search.vlv_after_count + 1}')
    return controls


def _get_ctrls_as_ldapsearch_args(search: LDAPSearch, page_size: int) -> list[str]:
    if search.control_type == LDAPSearchControlType.SIMPLE_PAGED_RESULTS:
        return ['-E', f'!pr={page_size}/noprompt']
    if search.control_type != LDAPSearchControlType.SSSVLV:
        return []

    arguments = ['-E', f'!sss={"/".join(search.sss_ordering_rules)}']
    if search.uses_vlv:
        arguments += ['-E', f'!vlv=0/{search.vlv_after_count}/{search.ldap_offset}/0']
    return arguments


def render_text(search: LDAPSearch, page_size: int) -> list[str]:
    return [
        f'SEARCH {search.base}',
        f'  scope:      {LDAPScope(search.scope).name.lower()}',
        f'  filter:     {search.filterstr}',
        f'  attributes: {", ".join(search.attrlist_without_dn)}',
        f'  controls:   {", ".join(_get_ctrls_as_text(search, page_size)) or "none"}',
        f'  in Python:  {", ".join(_get_python_side_steps(search)) or "nothing"}',
    ]


def render_ldapsearch(search: LDAPSearch, page_size: int, uri: str, bind_dn: str) -> list[str]:
    connect = ['ldapsearch', '-H', uri, '-x']
    if bind_dn:
        connect += ['-D', bind_dn, '-W']

    argument_groups = [
        connect,
        ['-b', search.base, '-s', LDAPSEARCH_SCOPES[LDAPScope(search.scope)]],
        _get_ctrls_as_ldapsearch_args(search, page_size),
        [search.filterstr, *search.attrlist_without_dn],
    ]
    lines = [' \\\n  '.join(shlex.join(group) for group in argument_groups if group)]

    # this is a bit whacky, since if we don't use SSSVLV, we're sorting in python
    python_steps = _get_python_side_steps(search)
    if python_steps:
        lines.append(f'# in Python afterwards: {", ".join(python_steps)}')
    return lines
