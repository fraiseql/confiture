"""INSERT statement analyzer for tenant isolation.

This module provides tools to analyze INSERT statements and detect
missing tenant FK columns.
"""

from __future__ import annotations

from confiture.core.linting.tenant.function_parser import FunctionInfo, InsertStatement
from confiture.core.linting.tenant.models import TenantViolation


class InsertAnalyzer:
    """Analyzes INSERT statements for missing tenant FK columns.

    Compares INSERT column lists against required FK columns derived
    from tenant relationship analysis.

    Example:
        >>> analyzer = InsertAnalyzer()
        >>> insert = InsertStatement(
        ...     table_name="tb_item",
        ...     columns=["id", "name"],
        ...     line_number=15,
        ...     raw_sql="INSERT INTO tb_item (id, name) VALUES (...)",
        ... )
        >>> requirements = {"tb_item": ["fk_org"]}
        >>> missing = analyzer.find_missing_columns(insert, requirements)
        >>> print(missing)
        ['fk_org']
    """

    def find_missing_columns(
        self,
        insert: InsertStatement,
        requirements: dict[str, list[str]],
    ) -> list[str] | None:
        """Find FK columns missing from INSERT statement.

        Args:
            insert: The INSERT statement to analyze
            requirements: Dict mapping table_name -> list of required FK columns

        Returns:
            List of missing column names, empty list if all present,
            or None if columns cannot be determined (no column list)
        """
        if insert.columns is None:
            return None

        # Normalize table name (strip schema if present)
        table_name = self._normalize_table_name(insert.table_name)

        # Get required columns for this table
        required = requirements.get(table_name, [])
        if not required:
            return []

        # Normalize column names for comparison (case-insensitive)
        insert_columns_lower = {c.lower() for c in insert.columns}

        # Find missing columns
        missing = [col for col in required if col.lower() not in insert_columns_lower]

        return missing

    def build_violation(
        self,
        function_name: str,
        file_path: str,
        insert: InsertStatement,
        missing_columns: list[str],
        affected_views: list[str],
    ) -> TenantViolation:
        """Build a TenantViolation from analysis results.

        Args:
            function_name: Name of the function containing the INSERT
            file_path: Path to the SQL file
            insert: The INSERT statement with issues
            missing_columns: List of missing FK column names
            affected_views: List of views affected by missing columns

        Returns:
            TenantViolation object
        """
        return TenantViolation(
            function_name=function_name,
            file_path=file_path,
            line_number=insert.line_number,
            table_name=insert.table_name,
            missing_columns=missing_columns,
            affected_views=affected_views,
            insert_sql=insert.raw_sql,
        )

    def analyze_function(
        self,
        func: FunctionInfo,
        requirements: dict[str, list[str]],
        view_map: dict[str, list[str]],
        file_path: str,
    ) -> list[TenantViolation]:
        """Analyze a function for tenant isolation violations.

        Args:
            func: FunctionInfo with parsed INSERT statements
            requirements: Dict mapping table_name -> required FK columns
            view_map: Dict mapping table_name -> list of affected views
            file_path: Path to the SQL file

        Returns:
            List of TenantViolation objects
        """
        violations = []

        for insert in func.inserts:
            missing = self.find_missing_columns(insert, requirements)

            # Skip if no column list (cannot analyze) or no missing columns
            if missing is None or not missing:
                continue

            # Get affected views for this table
            table_name = self._normalize_table_name(insert.table_name)
            affected_views = view_map.get(table_name, [])

            violation = self.build_violation(
                function_name=func.name,
                file_path=file_path,
                insert=insert,
                missing_columns=missing,
                affected_views=affected_views,
            )
            violations.append(violation)

        return violations

    def _normalize_table_name(self, table_name: str) -> str:
        """Normalize table name by stripping schema prefix.

        Args:
            table_name: Table name that may include schema (e.g., "myschema.tb_item")

        Returns:
            Table name without schema (e.g., "tb_item")
        """
        if "." in table_name:
            return table_name.split(".")[-1]
        return table_name
