"""Type-safe hook contexts."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Generic, TypeVar
from uuid import UUID, uuid4

T = TypeVar("T")


@dataclass
class Schema:
    """Basic schema representation."""

    name: str
    tables: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class SchemaDifference:
    """Represents a difference between schemas."""

    type: str  # e.g., "added_table", "dropped_column", "type_change"
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class RiskAssessment:
    """Risk assessment for a migration."""

    level: str  # "LOW", "MEDIUM", "HIGH", "CRITICAL"
    score: float  # 0.0-1.0
    factors: dict[str, float] = field(default_factory=dict)


@dataclass
class MigrationStep:
    """Individual migration step."""

    id: str
    description: str
    estimated_duration_ms: int
    query: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class SchemaAnalysisContext:
    """Context available in before/after_analyze_schema hooks."""

    source_schema: Schema
    target_schema: Schema
    analysis_time_ms: int
    tables_analyzed: int
    columns_analyzed: int
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class SchemaDiffContext:
    """Context available in before/after_diff_schemas hooks."""

    source_schema: Schema
    target_schema: Schema
    differences: list[SchemaDifference] = field(default_factory=list)
    diff_time_ms: int = 0
    breaking_changes: list[str] = field(default_factory=list)
    safe_changes: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class MigrationPlanContext:
    """Context available in before/after_plan_migration hooks."""

    migration_steps: list[MigrationStep] = field(default_factory=list)
    estimated_duration_ms: int = 0
    estimated_downtime_ms: int = 0
    risk_assessment: RiskAssessment | None = None
    affected_tables: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ExecutionContext:
    """Context available during before/after_execute."""

    current_step: MigrationStep | None = None
    steps_completed: int = 0
    total_steps: int = 0
    elapsed_time_ms: int = 0
    rows_affected: int = 0
    current_connections: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class RollbackContext:
    """Context available during before/after_rollback."""

    rollback_reason: str
    steps_to_rollback: list[MigrationStep] = field(default_factory=list)
    original_error: Exception | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ValidationContext:
    """Context available during before/after_validate."""

    validation_results: list[dict[str, Any]] = field(default_factory=list)
    passed: bool = True
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class HookContext(Generic[T]):
    """Type-safe hook context with phase-specific information."""

    def __init__(
        self,
        phase: Any,  # HookPhase | HookEvent | HookAlert
        data: T,
        execution_id: UUID | None = None,
        hook_id: str | None = None,
    ):
        self.phase = phase
        self.data: T = data  # Type-safe data
        self.execution_id = execution_id or uuid4()  # Correlation ID for tracing
        self.hook_id = hook_id or "unknown"
        self.timestamp = datetime.now(UTC)
        self.parent_execution_id: UUID | None = None  # For nested hooks

    def get_data(self) -> T:
        """Get phase-specific data (type-safe)."""
        return self.data

    def add_metadata(self, key: str, value: Any) -> None:
        """Add metadata for observability."""
        if hasattr(self.data, "metadata") and isinstance(self.data.metadata, dict):
            metadata: dict[str, Any] = self.data.metadata  # type: ignore[union-attr]
            metadata[key] = value
