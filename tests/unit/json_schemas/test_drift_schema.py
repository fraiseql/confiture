"""Validate ``drift`` and ``drift --check-acls`` output against their schemas.

Drift requires a live database, which is out of scope for unit tests.
Instead, we validate the emitted JSON shape against the schema using the
``DriftReport.to_dict()`` output that the CLI prints verbatim (with a
``hints: []`` field injected at the emit site).
"""

from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from confiture.core.drift import (
    DriftItem,
    DriftReport,
    DriftSeverity,
    DriftType,
)

DRIFT_SCHEMA = "drift.schema.json"
ACL_SCHEMA = "drift-check-acls.schema.json"


def _load(schemas_dir: Path, name: str) -> dict:
    return json.loads((schemas_dir / name).read_text())


def _build_registry(schemas_dir: Path) -> Registry:
    """Registry that resolves common.schema.json AND drift.schema.json $refs.

    The ACL schema is a thin $ref to drift.schema.json, so both schema
    files must be resolvable by relative URI.
    """
    registry: Registry = Registry()
    for filename in ("_common.schema.json", "drift.schema.json"):
        content = _load(schemas_dir, filename)
        resource = Resource.from_contents(content, default_specification=DRAFT202012)
        registry = registry.with_resource(uri=filename, resource=resource)
    return registry


def _emit_payload(report: DriftReport) -> dict:
    """Mirror what the drift CLI emits: report.to_dict() + hints: []."""
    payload = report.to_dict()
    payload["hints"] = []
    return payload


def test_schemas_are_valid_draft_2020_12(schemas_dir):
    for name in (DRIFT_SCHEMA, ACL_SCHEMA):
        Draft202012Validator.check_schema(_load(schemas_dir, name))


def test_empty_drift_report_validates(schemas_dir):
    """Clean drift report — no drift items."""
    report = DriftReport(
        database_name="confiture_test",
        expected_schema_source="db/schema.sql",
        drift_items=[],
        tables_checked=10,
        columns_checked=50,
        indexes_checked=15,
        detection_time_ms=42,
    )
    payload = _emit_payload(report)

    registry = _build_registry(schemas_dir)
    Draft202012Validator(_load(schemas_dir, DRIFT_SCHEMA), registry=registry).validate(payload)
    assert payload["hints"] == []
    assert payload["drift_items"] == []


def test_drift_report_with_items_validates(schemas_dir):
    """Drift with several finding types."""
    report = DriftReport(
        database_name="confiture_test",
        expected_schema_source="migrations",
        drift_items=[
            DriftItem(
                drift_type=DriftType.MISSING_TABLE,
                severity=DriftSeverity.CRITICAL,
                object_name="public.orders",
                expected="present",
                actual=None,
                message="Table public.orders missing from live DB",
            ),
            DriftItem(
                drift_type=DriftType.TYPE_MISMATCH,
                severity=DriftSeverity.WARNING,
                object_name="public.users.email",
                expected="varchar(255)",
                actual="text",
                message="Column type differs",
            ),
        ],
        tables_checked=5,
        columns_checked=30,
        indexes_checked=8,
        detection_time_ms=120,
    )
    payload = _emit_payload(report)

    registry = _build_registry(schemas_dir)
    Draft202012Validator(_load(schemas_dir, DRIFT_SCHEMA), registry=registry).validate(payload)
    assert payload["has_critical_drift"] is True
    assert payload["critical_count"] == 1
    assert payload["warning_count"] == 1


def test_drift_check_acls_includes_missing_grant_item(schemas_dir):
    """ACL drift items use the same DriftItem shape — schema is the same."""
    report = DriftReport(
        database_name="confiture_test",
        expected_schema_source="db/schema.sql",
        drift_items=[
            DriftItem(
                drift_type=DriftType.MISSING_GRANT,
                severity=DriftSeverity.CRITICAL,
                object_name="public.orders",
                expected="SELECT to app_reader",
                actual=None,
                message="Expected SELECT grant on public.orders to app_reader is missing",
            ),
        ],
        tables_checked=1,
        columns_checked=0,
        indexes_checked=0,
        detection_time_ms=8,
    )
    payload = _emit_payload(report)

    registry = _build_registry(schemas_dir)
    Draft202012Validator(_load(schemas_dir, ACL_SCHEMA), registry=registry).validate(payload)
