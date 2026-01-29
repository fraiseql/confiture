"""Models for tenant isolation linting.

This module defines the core data structures used for tenant isolation
detection and violation reporting.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class TenantRelationship:
    """Represents a tenant filtering relationship.

    Captures the relationship between a view that derives tenant_id
    and the source table's FK column required for the join.

    Attributes:
        view_name: Name of the view (e.g., "v_item")
        source_table: Name of the source table (e.g., "tb_item")
        required_fk: FK column required for tenant filtering (e.g., "fk_org")
        tenant_column: Output column name in view (default: "tenant_id")
        fk_target_table: Table the FK references (e.g., "tv_organization")
        fk_target_column: Column the FK references (e.g., "pk_organization")

    Example:
        >>> rel = TenantRelationship(
        ...     view_name="v_item",
        ...     source_table="tb_item",
        ...     required_fk="fk_org",
        ... )
        >>> print(rel)
        v_item → tb_item.fk_org
    """

    view_name: str
    source_table: str
    required_fk: str
    tenant_column: str = "tenant_id"
    fk_target_table: str | None = None
    fk_target_column: str | None = None

    def __str__(self) -> str:
        return f"{self.view_name} → {self.source_table}.{self.required_fk}"


@dataclass
class TenantViolation:
    """Represents a tenant isolation violation.

    Captures details about an INSERT statement that is missing
    columns required for tenant filtering.

    Attributes:
        function_name: Name of the function containing the INSERT
        file_path: Path to the SQL file
        line_number: Line number of the INSERT statement
        table_name: Target table of the INSERT
        missing_columns: List of FK columns missing from the INSERT
        affected_views: List of views that depend on the missing columns
        insert_sql: The raw INSERT SQL (optional, for context)
        severity: Severity level (default: "warning")

    Example:
        >>> violation = TenantViolation(
        ...     function_name="fn_create_item",
        ...     file_path="functions/items.sql",
        ...     line_number=15,
        ...     table_name="tb_item",
        ...     missing_columns=["fk_org"],
        ...     affected_views=["v_item"],
        ... )
        >>> print(violation.suggestion)
        Add fk_org to INSERT statement. Required for tenant filtering in: v_item
    """

    function_name: str
    file_path: str
    line_number: int
    table_name: str
    missing_columns: list[str]
    affected_views: list[str]
    insert_sql: str | None = None
    severity: str = "warning"

    @property
    def suggestion(self) -> str:
        """Generate an actionable suggestion for fixing the violation."""
        cols = ", ".join(self.missing_columns)
        views = ", ".join(self.affected_views)
        return f"Add {cols} to INSERT statement. Required for tenant filtering in: {views}"

    def __str__(self) -> str:
        cols = ", ".join(self.missing_columns)
        return (
            f"{self.function_name}:{self.line_number} - "
            f"INSERT INTO {self.table_name} missing: {cols}"
        )


@dataclass
class TenantConfig:
    """Configuration for tenant isolation linting.

    Attributes:
        enabled: Whether tenant isolation linting is enabled
        mode: Detection mode - "auto", "explicit", or "hybrid"
        relationships: Explicitly defined tenant relationships
        tenant_column_patterns: Patterns to match tenant output columns
        fk_patterns: Patterns to match FK columns for tenant filtering

    Example:
        >>> config = TenantConfig()  # Auto mode with defaults
        >>> config.enabled
        True
        >>> config.mode
        'auto'

        >>> # Explicit mode
        >>> config = TenantConfig(
        ...     mode="explicit",
        ...     relationships=[
        ...         TenantRelationship("v_item", "tb_item", "fk_org")
        ...     ]
        ... )
    """

    enabled: bool = True
    mode: str = "auto"  # "auto", "explicit", "hybrid"
    relationships: list[TenantRelationship] = field(default_factory=list)
    tenant_column_patterns: list[str] = field(
        default_factory=lambda: ["tenant_id", "organization_id", "org_id"]
    )
    fk_patterns: list[str] = field(
        default_factory=lambda: [
            "fk_tenant*",
            "fk_org*",
            "fk_organization*",
            "*_tenant_id",
            "*_organization_id",
        ]
    )

    @classmethod
    def from_dict(cls, data: dict) -> TenantConfig:
        """Create TenantConfig from a dictionary (e.g., from YAML).

        Args:
            data: Dictionary with configuration values

        Returns:
            TenantConfig instance

        Example:
            >>> data = {
            ...     "enabled": True,
            ...     "mode": "explicit",
            ...     "relationships": [
            ...         {"view": "v_item", "table": "tb_item", "required_fk": "fk_org"}
            ...     ]
            ... }
            >>> config = TenantConfig.from_dict(data)
        """
        relationships = [
            TenantRelationship(
                view_name=r["view"],
                source_table=r["table"],
                required_fk=r["required_fk"],
                tenant_column=r.get("tenant_column", "tenant_id"),
                fk_target_table=r.get("fk_target_table"),
                fk_target_column=r.get("fk_target_column"),
            )
            for r in data.get("relationships", [])
        ]

        # Get default patterns for fallback
        default_tenant_patterns = ["tenant_id", "organization_id", "org_id"]
        default_fk_patterns = [
            "fk_tenant*",
            "fk_org*",
            "fk_organization*",
            "*_tenant_id",
            "*_organization_id",
        ]

        return cls(
            enabled=data.get("enabled", True),
            mode=data.get("mode", "auto"),
            relationships=relationships,
            tenant_column_patterns=data.get("tenant_column_patterns", default_tenant_patterns),
            fk_patterns=data.get("fk_patterns", default_fk_patterns),
        )
