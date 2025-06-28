from functools import cached_property
from typing import TYPE_CHECKING

from django.db.backends.base.features import BaseDatabaseFeatures
from ldap.controls import SimplePagedResultsControl
from ldap.controls.sss import SSSRequestControl
from ldap.controls.vlv import VLVRequestControl

if TYPE_CHECKING:
    from ldap.ldapobject import ReconnectLDAPObject

# TODO: Since neither python-ldap nor ldap3 support Request/ResponseControls for transactions,
#  we'll need to implement our own transaction support. Put these in controls.py
LDAP_OID_TRANSACTION_START = '1.3.6.1.1.21.1'
LDAP_OID_TRANSACTION_END = '1.3.6.1.1.21.3'


class DatabaseFeatures(BaseDatabaseFeatures):
    """
    Overrides all attributes that differ from BaseDatabaseFeatures in Django 5.1 in the order they appear
    There are a lot we probably don't need or it does not make a difference settings them.
    We'll just do it for the sake of completeness.
    """

    delete_can_self_reference_subquery = False
    supports_nullable_unique_constraints = False
    supports_partially_nullable_unique_constraints = False
    uses_savepoints = False
    allow_sliced_subqueries_with_in = False
    test_db_allows_multiple_connections = False
    supports_forward_references = False
    supports_subqueries_in_group_by = False
    ignores_unnecessary_order_by_in_subqueries = False
    supports_regex_backreferencing = False
    supports_date_lookup_using_string = False
    supports_timezones = False  # All timestamps are UTC
    has_zoneinfo_database = False
    supports_order_by_nulls_modifier = False  # we probably could implement this in python
    allows_auto_pk_0 = False
    supports_sequence_reset = False

    # TODO: Check if we want/need introspection. Maybe for inspectdb?
    can_introspect_default = False
    can_introspect_foreign_keys = False
    introspected_field_types = {}
    supports_index_column_ordering = False

    supports_foreign_keys = False  # TODO: Check what the ramifications of this setting are. Maybe we can use it?
    can_create_inline_fk = False
    indexes_foreign_keys = False
    supports_column_check_constraints = False
    supports_table_check_constraints = False
    can_introspect_check_constraints = False
    supports_paramstyle_pyformat = False  # we could support it, but it's not worth the effort
    supports_expression_defaults = False
    supports_default_keyword_in_insert = False
    supports_default_keyword_in_bulk_insert = False

    # most attributes are case-insensitive. Maybe allow changing this attribute via settings?
    has_case_insensitive_like = True
    ignores_table_name_case = True

    supports_select_for_update_with_limit = False
    supports_index_on_text_field = False
    supports_default_in_lead_lag = False
    supports_ignore_conflicts = False

    supports_partial_indexes = False
    supports_functions_in_partial_indexes = False
    supports_expression_indexes = False
    supports_json_field = False
    can_introspect_json_field = False
    supports_primitives_in_json_field = False
    supports_json_field_contains = False
    has_json_object_function = False
    supports_collation_on_charfield = False
    supports_collation_on_textfield = False
    supports_non_deterministic_collations = False
    supports_unlimited_charfield = True  # not sure if this is dependent on the ldap server

    # Maybe also implement django_test_expected_failures & django_test_skips?

    @cached_property
    def rootdse_data(self) -> dict:
        with self.connection.cursor() as cursor:
            conn: ReconnectLDAPObject = cursor.connection
            return conn.read_rootdse_s()

    @cached_property
    def supported_ldap_versions(self) -> list[int]:
        """Return a list of supported LDAP protocol versions by the server."""
        return [int(version.decode()) for version in self.rootdse_data.get('supportedLDAPVersion', [])]

    @cached_property
    def supported_controls(self) -> list[str]:
        """
        Return a list of supported control OIDs

        May include controls like:
        - Simple Paged Results Control
        - Server Side Sorting (SSS) Control
        - Virtual List View (VLV) Control
        - Sync Request Control
        - Password Policy Control
        """
        return [control.decode() for control in self.rootdse_data.get('supportedControl', [])]

    @cached_property
    def supported_extensions(self) -> list[str]:
        """
        Return a list of supported extensions

        May include extensions like:
        - StartTLS
        - Transaction Start/End
        - Who Am I
        - LDAP Password Modify
        """
        return [extension.decode() for extension in self.rootdse_data.get('supportedExtension', [])]

    @cached_property
    def supported_features(self) -> list[str]:
        """
        Return a list of supported feature OIDs

        May include features like:
        - Modify-Increment
        - "All Operational Attributes"
        - True/False filters
        """
        return [feature.decode() for feature in self.rootdse_data.get('supportedFeatures', [])]

    @cached_property
    def supported_sasl_mechanisms(self) -> list[str]:
        """
        Return a list of supported SASL mechanism OIDs

        May include mechanisms like:
        - CRAM-MD5
        - DIGEST-MD5
        - LOGIN
        - NTLM
        - PLAIN
        - SCRAM-SHA-1
        - SCRAM-SHA-256
        - SCRAM-SHA-384
        - SCRAM-SHA-512
        """
        return [mech.decode() for mech in self.rootdse_data.get('supportedSASLMechanisms', [])]

    @cached_property
    def supports_simple_paged_results(self) -> bool:
        """Confirm support for Simple Paged Results."""
        return SimplePagedResultsControl.controlType in self.supported_controls

    @cached_property
    def supports_sss(self) -> bool:
        """Confirm support for Server Side Sorting."""
        return SSSRequestControl.controlType in self.supported_controls

    @cached_property
    def supports_vlv(self) -> bool:
        """Confirm support for Virtual List View."""
        return VLVRequestControl.controlType in self.supported_controls

    @cached_property
    def supports_sssvlv(self) -> bool:
        """Confirm support for Server Side Sorting and Virtual List View."""
        return self.supports_sss and self.supports_vlv

    @cached_property
    def can_use_chunked_reads(self) -> bool:
        """
        Confirm support for Server Side Sorting and Virtual List View.

        In theory, we could also set this to True if the server supports the Paged Results control.
        However, it's pretty useless without the SSS & VLV controls since we can't do any ordering and the use case for
        an unordered paginitation is more of an exception than the rule.
        """
        return self.supports_sssvlv or self.supports_simple_paged_results

    @cached_property
    def supports_transactions(self) -> bool:
        """Confirm support for transactions. Transactions have been introduced in OpenLDAP 2.5"""
        return LDAP_OID_TRANSACTION_START in self.supported_extensions
