"""CLI output formatter for tenant isolation linting.

This module provides formatted output for tenant isolation
analysis results suitable for command-line display.
"""

from __future__ import annotations

from confiture.core.linting.tenant.models import TenantRelationship, TenantViolation


class TenantIsolationFormatter:
    """Formats tenant isolation results for CLI display.

    Produces human-readable output showing detected tenant patterns,
    violations, and suggestions.

    Example:
        >>> formatter = TenantIsolationFormatter()
        >>> output = formatter.format_violations(violations)
        >>> print(output)
    """

    def format_relationships(self, relationships: list[TenantRelationship]) -> str:
        """Format detected tenant relationships.

        Args:
            relationships: List of TenantRelationship objects

        Returns:
            Formatted string for CLI display
        """
        if not relationships:
            return ""

        lines = ["Detected multi-tenant patterns:"]

        for rel in relationships:
            lines.append(f"  - {rel.view_name} -> {rel.source_table} (requires: {rel.required_fk})")

        return "\n".join(lines)

    def format_violations(self, violations: list[TenantViolation]) -> str:
        """Format tenant isolation violations.

        Args:
            violations: List of TenantViolation objects

        Returns:
            Formatted string for CLI display
        """
        if not violations:
            return ""

        lines = ["TENANT ISOLATION ISSUES", ""]

        for violation in violations:
            lines.append(
                f"  {violation.function_name} ({violation.file_path}:{violation.line_number})"
            )
            lines.append(
                f"  |- INSERT INTO {violation.table_name} missing: {', '.join(violation.missing_columns)}"
            )
            lines.append(
                f"  |- Required for tenant filtering in: {', '.join(violation.affected_views)}"
            )
            lines.append(
                f"  |- Suggestion: Add {', '.join(violation.missing_columns)} to INSERT statement"
            )
            lines.append("")

        return "\n".join(lines)

    def format_summary(
        self,
        functions_checked: int,
        violations_found: int,
    ) -> str:
        """Format summary of lint results.

        Args:
            functions_checked: Number of functions analyzed
            violations_found: Number of violations detected

        Returns:
            Formatted summary string
        """
        if violations_found == 0:
            return f"Summary: {functions_checked} functions checked, no tenant isolation issues"

        return f"Summary: {functions_checked} functions checked, {violations_found} tenant isolation issues"

    def format_complete(
        self,
        relationships: list[TenantRelationship],
        violations: list[TenantViolation],
        functions_checked: int,
    ) -> str:
        """Format complete output with all sections.

        Args:
            relationships: Detected tenant relationships
            violations: Found violations
            functions_checked: Number of functions analyzed

        Returns:
            Complete formatted output string
        """
        sections = []

        # Add relationships section
        rel_output = self.format_relationships(relationships)
        if rel_output:
            sections.append(rel_output)

        # Add violations section
        viol_output = self.format_violations(violations)
        if viol_output:
            sections.append(viol_output)

        # Add summary
        summary = self.format_summary(
            functions_checked=functions_checked,
            violations_found=len(violations),
        )
        sections.append(summary)

        return "\n\n".join(sections)
