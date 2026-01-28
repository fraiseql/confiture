"""VIEW parsing for tenant detection.

This module provides tools to parse PostgreSQL VIEW definitions
and extract tenant relationship information.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from confiture.core.linting.tenant.models import TenantRelationship


@dataclass
class JoinCondition:
    """Represents a JOIN condition extracted from SQL.

    Attributes:
        left_alias: Table alias on left side of condition
        left_column: Column name on left side
        right_alias: Table alias on right side
        right_column: Column name on right side
    """

    left_alias: str
    left_column: str
    right_alias: str
    right_column: str


@dataclass
class TenantColumnInfo:
    """Information about a tenant column in a VIEW.

    Attributes:
        alias: The output column alias (e.g., "tenant_id")
        source_alias: Table alias the column comes from
        source_column: Original column name from the source table
    """

    alias: str
    source_alias: str
    source_column: str


class ViewParser:
    """Parses PostgreSQL VIEW definitions for tenant relationships.

    Extracts table aliases, JOIN conditions, and tenant column information
    from VIEW SQL to build TenantRelationship objects.

    Example:
        >>> parser = ViewParser()
        >>> sql = '''
        ... CREATE VIEW v_item AS
        ... SELECT i.*, o.id AS tenant_id
        ... FROM tb_item i
        ... LEFT JOIN tv_organization o ON i.fk_org = o.pk_organization;
        ... '''
        >>> rel = parser.build_tenant_relationship(sql, "v_item")
        >>> print(rel)
        v_item → tb_item.fk_org
    """

    # Pattern: CREATE [OR REPLACE] VIEW [schema.]name AS
    VIEW_NAME_PATTERN = re.compile(
        r"CREATE\s+(?:OR\s+REPLACE\s+)?VIEW\s+((?:\w+\.)?\w+)\s+AS",
        re.IGNORECASE,
    )

    # Pattern: FROM [schema.]table [[AS] alias]
    FROM_PATTERN = re.compile(
        r"\bFROM\s+((?:\w+\.)?(\w+))(?:\s+(?:AS\s+)?(\w+))?",
        re.IGNORECASE,
    )

    # Pattern: [LEFT|RIGHT|INNER|CROSS] JOIN [schema.]table [[AS] alias] ON
    JOIN_PATTERN = re.compile(
        r"\b(?:LEFT\s+|RIGHT\s+|INNER\s+|OUTER\s+|CROSS\s+)?JOIN\s+"
        r"((?:\w+\.)?(\w+))(?:\s+(?:AS\s+)?(\w+))?\s+ON",
        re.IGNORECASE,
    )

    # Pattern: alias.column = alias.column (JOIN condition)
    JOIN_CONDITION_PATTERN = re.compile(
        r"(\w+)\.(\w+)\s*=\s*(\w+)\.(\w+)",
        re.IGNORECASE,
    )

    # Pattern: alias.column AS output_name (SELECT clause)
    SELECT_ALIAS_PATTERN = re.compile(
        r"(\w+)\.(\w+)\s+AS\s+(\w+)",
        re.IGNORECASE,
    )

    def extract_view_name(self, sql: str) -> str | None:
        """Extract the view name from CREATE VIEW statement.

        Args:
            sql: SQL containing CREATE VIEW statement

        Returns:
            View name or None if not a VIEW statement
        """
        match = self.VIEW_NAME_PATTERN.search(sql)
        if match:
            return match.group(1)
        return None

    def extract_table_aliases(self, sql: str) -> dict[str, str]:
        """Extract table aliases from VIEW definition.

        Args:
            sql: SQL containing VIEW definition

        Returns:
            Dict mapping alias -> table_name
        """
        aliases: dict[str, str] = {}

        # Extract FROM clause
        for match in self.FROM_PATTERN.finditer(sql):
            full_name = match.group(1)  # schema.table or table
            alias = match.group(3)  # alias if present
            if alias:
                aliases[alias] = full_name
            else:
                aliases[full_name] = full_name

        # Extract JOIN clauses
        for match in self.JOIN_PATTERN.finditer(sql):
            full_name = match.group(1)
            alias = match.group(3)
            if alias:
                aliases[alias] = full_name
            else:
                aliases[full_name] = full_name

        return aliases

    def extract_join_conditions(self, sql: str) -> list[JoinCondition]:
        """Extract JOIN conditions from VIEW definition.

        Args:
            sql: SQL containing VIEW definition

        Returns:
            List of JoinCondition objects
        """
        conditions = []

        for match in self.JOIN_CONDITION_PATTERN.finditer(sql):
            conditions.append(
                JoinCondition(
                    left_alias=match.group(1),
                    left_column=match.group(2),
                    right_alias=match.group(3),
                    right_column=match.group(4),
                )
            )

        return conditions

    def detect_tenant_column(
        self,
        sql: str,
        patterns: list[str] | None = None,
    ) -> TenantColumnInfo | None:
        """Detect tenant column in SELECT clause.

        Looks for columns aliased as tenant_id, organization_id, etc.

        Args:
            sql: SQL containing VIEW definition
            patterns: List of column alias patterns to match

        Returns:
            TenantColumnInfo if found, None otherwise
        """
        if patterns is None:
            patterns = ["tenant_id", "organization_id", "org_id"]

        # Convert patterns to lowercase for case-insensitive matching
        patterns_lower = [p.lower() for p in patterns]

        for match in self.SELECT_ALIAS_PATTERN.finditer(sql):
            source_alias = match.group(1)
            source_column = match.group(2)
            output_alias = match.group(3)

            if output_alias.lower() in patterns_lower:
                return TenantColumnInfo(
                    alias=output_alias,
                    source_alias=source_alias,
                    source_column=source_column,
                )

        return None

    def build_tenant_relationship(
        self,
        sql: str,
        view_name: str,
        tenant_patterns: list[str] | None = None,
    ) -> TenantRelationship | None:
        """Build a TenantRelationship from VIEW SQL.

        Analyzes the VIEW to find:
        1. The tenant column (e.g., "tenant_id")
        2. The source table for the tenant column
        3. The FK column in the main table that joins to the tenant source
        4. The main source table

        Args:
            sql: SQL containing VIEW definition
            view_name: Name of the view
            tenant_patterns: Custom patterns for tenant column detection

        Returns:
            TenantRelationship if tenant pattern detected, None otherwise
        """
        # Detect tenant column
        tenant_col = self.detect_tenant_column(sql, tenant_patterns)
        if tenant_col is None:
            return None

        # Get table aliases
        aliases = self.extract_table_aliases(sql)
        if not aliases:
            return None

        # Get JOIN conditions
        joins = self.extract_join_conditions(sql)
        if not joins:
            return None

        # Find which table the tenant column comes from
        tenant_source_alias = tenant_col.source_alias
        tenant_source_table = aliases.get(tenant_source_alias)

        if tenant_source_table is None:
            return None

        # Find the JOIN condition that connects to the tenant source
        # This gives us the FK column in the main table
        required_fk = None
        source_table = None
        source_alias = None

        for join in joins:
            if join.right_alias == tenant_source_alias:
                # Found: main_table.fk_col = tenant_table.pk_col
                required_fk = join.left_column
                source_alias = join.left_alias
                break
            elif join.left_alias == tenant_source_alias:
                # Found: tenant_table.pk_col = main_table.fk_col
                required_fk = join.right_column
                source_alias = join.right_alias
                break

        if required_fk is None or source_alias is None:
            return None

        # Get the source table name from alias
        source_table = aliases.get(source_alias)
        if source_table is None:
            return None

        return TenantRelationship(
            view_name=view_name,
            source_table=source_table,
            required_fk=required_fk,
            tenant_column=tenant_col.alias,
            fk_target_table=tenant_source_table,
            fk_target_column=tenant_col.source_column,
        )
