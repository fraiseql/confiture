"""Auto-detection of multi-tenant schemas.

This module provides tools to automatically detect multi-tenant
patterns in PostgreSQL schemas by analyzing VIEWs.
"""

from __future__ import annotations

from confiture.core.linting.tenant.function_parser import FunctionInfo
from confiture.core.linting.tenant.insert_analyzer import InsertAnalyzer
from confiture.core.linting.tenant.models import TenantRelationship, TenantViolation
from confiture.core.linting.tenant.view_parser import ViewParser


class TenantDetector:
    """Detects multi-tenant patterns in PostgreSQL schemas.

    Analyzes VIEW definitions to identify tenant relationships,
    then validates INSERT statements against detected requirements.

    Example:
        >>> detector = TenantDetector()
        >>> view_sqls = ["CREATE VIEW v_item AS SELECT ... tenant_id ..."]
        >>> is_tenant = detector.is_multi_tenant_schema(view_sqls)
        >>> print(is_tenant)
        True
    """

    DEFAULT_TENANT_PATTERNS = ["tenant_id", "organization_id", "org_id"]

    def __init__(self, tenant_patterns: list[str] | None = None):
        """Initialize detector with tenant column patterns.

        Args:
            tenant_patterns: List of column name patterns that indicate
                tenant columns. Defaults to ["tenant_id", "organization_id", "org_id"].
        """
        self.tenant_patterns = tenant_patterns or self.DEFAULT_TENANT_PATTERNS
        self.view_parser = ViewParser()
        self.insert_analyzer = InsertAnalyzer()

    def is_multi_tenant_schema(self, view_sqls: list[str]) -> bool:
        """Determine if schema is multi-tenant based on VIEWs.

        Args:
            view_sqls: List of CREATE VIEW SQL statements

        Returns:
            True if any VIEW has tenant column patterns
        """
        if not view_sqls:
            return False

        for sql in view_sqls:
            tenant_col = self.view_parser.detect_tenant_column(sql, patterns=self.tenant_patterns)
            if tenant_col is not None:
                return True

        return False

    def detect_relationships(self, view_sqls: list[str]) -> list[TenantRelationship]:
        """Detect tenant relationships from VIEW definitions.

        Args:
            view_sqls: List of CREATE VIEW SQL statements

        Returns:
            List of TenantRelationship objects for views with tenant patterns
        """
        relationships = []

        for sql in view_sqls:
            view_name = self.view_parser.extract_view_name(sql)
            if not view_name:
                continue

            relationship = self.view_parser.build_tenant_relationship(
                sql, view_name=view_name, tenant_patterns=self.tenant_patterns
            )
            if relationship:
                relationships.append(relationship)

        return relationships

    def build_requirements_map(
        self, relationships: list[TenantRelationship]
    ) -> dict[str, list[str]]:
        """Build table -> required FK columns map.

        Args:
            relationships: List of TenantRelationship objects

        Returns:
            Dict mapping table_name -> list of required FK column names
        """
        requirements: dict[str, list[str]] = {}

        for rel in relationships:
            # Normalize table name by stripping schema prefix
            table = self._normalize_table_name(rel.source_table)
            fk = rel.required_fk

            if table not in requirements:
                requirements[table] = []

            if fk not in requirements[table]:
                requirements[table].append(fk)

        return requirements

    def build_view_map(self, relationships: list[TenantRelationship]) -> dict[str, list[str]]:
        """Build table -> affected views map.

        Args:
            relationships: List of TenantRelationship objects

        Returns:
            Dict mapping table_name -> list of view names that depend on it
        """
        view_map: dict[str, list[str]] = {}

        for rel in relationships:
            # Normalize table name by stripping schema prefix
            table = self._normalize_table_name(rel.source_table)
            view = rel.view_name

            if table not in view_map:
                view_map[table] = []

            if view not in view_map[table]:
                view_map[table].append(view)

        return view_map

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

    def analyze_schema(
        self,
        view_sqls: list[str],
        functions: list[FunctionInfo],
        file_path: str,
    ) -> list[TenantViolation]:
        """Analyze schema for tenant isolation violations.

        Detects tenant relationships from VIEWs and validates
        INSERT statements in functions against requirements.

        Args:
            view_sqls: List of CREATE VIEW SQL statements
            functions: List of FunctionInfo with parsed INSERT statements
            file_path: Path to the SQL file being analyzed

        Returns:
            List of TenantViolation objects for missing FK columns
        """
        # Detect tenant relationships
        relationships = self.detect_relationships(view_sqls)
        if not relationships:
            return []  # Not a multi-tenant schema

        # Build maps for analysis
        requirements = self.build_requirements_map(relationships)
        view_map = self.build_view_map(relationships)

        # Analyze each function
        violations = []
        for func in functions:
            func_violations = self.insert_analyzer.analyze_function(
                func=func,
                requirements=requirements,
                view_map=view_map,
                file_path=file_path,
            )
            violations.extend(func_violations)

        return violations
