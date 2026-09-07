"""Behaviour of the typed hook contexts (``core/hooks/context.py``).

These are the payloads a hook receives per phase. The tests pin what a hook author
can rely on: the defaults each context starts with, that ``HookContext`` carries a
correlation id and an aware timestamp, and that ``add_metadata`` writes into the
payload's ``metadata`` mapping when it has one and is a no-op otherwise.
"""

from __future__ import annotations

from datetime import UTC
from uuid import UUID, uuid4

from confiture.core.hooks.context import (
    ExecutionContext,
    HookContext,
    MigrationPlanContext,
    MigrationStep,
    RebuildContext,
    RiskAssessment,
    RollbackContext,
    Schema,
    SchemaAnalysisContext,
    SchemaDiffContext,
    SchemaDifference,
    ValidationContext,
)


def _schema(name: str, *tables: str) -> Schema:
    return Schema(name=name, tables=list(tables))


def test_schema_and_difference_defaults() -> None:
    schema = _schema("public", "users")
    assert schema.tables == ["users"]
    assert schema.metadata == {}
    diff = SchemaDifference(type="added_table")
    assert diff.details == {}


def test_analysis_context_records_what_was_analysed() -> None:
    ctx = SchemaAnalysisContext(
        source_schema=_schema("public", "users"),
        target_schema=_schema("public", "users", "orders"),
        analysis_time_ms=12,
        tables_analyzed=2,
        columns_analyzed=9,
    )
    assert ctx.tables_analyzed == 2
    assert ctx.metadata == {}


def test_diff_context_separates_breaking_from_safe_changes() -> None:
    ctx = SchemaDiffContext(
        source_schema=_schema("public", "users"),
        target_schema=_schema("public", "users"),
        differences=[SchemaDifference(type="dropped_column", details={"column": "email"})],
        breaking_changes=["dropped_column users.email"],
    )
    assert ctx.safe_changes == []
    assert ctx.differences[0].details["column"] == "email"
    assert ctx.diff_time_ms == 0


def test_plan_context_carries_steps_and_risk() -> None:
    step = MigrationStep(id="001", description="add index", estimated_duration_ms=250)
    ctx = MigrationPlanContext(
        migration_steps=[step],
        estimated_duration_ms=250,
        risk_assessment=RiskAssessment(level="LOW", score=0.1, factors={"rows": 0.1}),
        affected_tables=["users"],
    )
    assert ctx.migration_steps[0].query is None
    assert ctx.risk_assessment is not None
    assert ctx.risk_assessment.level == "LOW"
    assert ctx.estimated_downtime_ms == 0


def test_execution_context_starts_at_zero() -> None:
    ctx = ExecutionContext(total_steps=3)
    assert (ctx.steps_completed, ctx.elapsed_time_ms, ctx.rows_affected) == (0, 0, 0)
    assert ctx.current_step is None


def test_rollback_context_keeps_the_original_error() -> None:
    error = RuntimeError("boom")
    ctx = RollbackContext(rollback_reason="step 2 failed", original_error=error)
    assert ctx.original_error is error
    assert ctx.steps_to_rollback == []


def test_validation_context_passes_by_default() -> None:
    ctx = ValidationContext()
    assert ctx.passed is True
    assert (ctx.errors, ctx.warnings, ctx.validation_results) == ([], [], [])


def test_rebuild_context_requires_its_facts() -> None:
    ctx = RebuildContext(
        env="local", drop_schemas=True, migrations_count=4, schemas_dropped=["app"]
    )
    assert ctx.schemas_dropped == ["app"]
    assert ctx.metadata == {}


def test_hook_context_generates_a_correlation_id_and_aware_timestamp() -> None:
    wrapped = HookContext(phase="before_ddl", data=ExecutionContext())
    assert isinstance(wrapped.execution_id, UUID)
    assert wrapped.hook_id == "unknown"
    assert wrapped.parent_execution_id is None
    assert wrapped.timestamp.tzinfo is UTC
    assert wrapped.get_data() is wrapped.data


def test_hook_context_keeps_an_explicit_execution_id_and_hook_id() -> None:
    given = uuid4()
    wrapped = HookContext(
        phase="after_ddl", data=ValidationContext(), execution_id=given, hook_id="h1"
    )
    assert wrapped.execution_id == given
    assert wrapped.hook_id == "h1"


def test_add_metadata_writes_into_the_payload_metadata() -> None:
    payload = ExecutionContext()
    wrapped = HookContext(phase="before_ddl", data=payload)
    wrapped.add_metadata("attempt", 2)
    assert payload.metadata == {"attempt": 2}


def test_add_metadata_is_a_no_op_without_a_metadata_mapping() -> None:
    wrapped = HookContext(phase="before_ddl", data="plain string payload")
    wrapped.add_metadata("attempt", 2)  # must not raise
    assert wrapped.get_data() == "plain string payload"
