"""Validate ``migrate steps --format json`` output against its schema (issue #200)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from jsonschema import Draft202012Validator

from confiture.core.step_runner import StepRecord
from confiture.models.results import MigrateStepsResult

SCHEMA_FILE = "migrate-steps.schema.json"


def _load(schemas_dir: Path, name: str) -> dict:
    return json.loads((schemas_dir / name).read_text())


def test_schema_is_valid_draft_2020_12(schemas_dir):
    assert Draft202012Validator.check_schema(_load(schemas_dir, SCHEMA_FILE)) is None


def test_a_listing_with_a_resumed_run_validates(schemas_dir, schema_registry):
    when = datetime(2026, 1, 1, tzinfo=UTC)
    rows = [
        StepRecord("20260101000000", 0, "expand", "done", None, 0, when),
        StepRecord("20260101000000", 0, "backfill", "running", 4096, 200000, when),
    ]
    payload = MigrateStepsResult(
        steps=[r.to_dict() for r in rows], resumed="20260101000000"
    ).to_dict()
    validator = Draft202012Validator(_load(schemas_dir, SCHEMA_FILE), registry=schema_registry)
    assert list(validator.iter_errors(payload)) == []


def test_an_empty_listing_validates(schemas_dir, schema_registry):
    validator = Draft202012Validator(_load(schemas_dir, SCHEMA_FILE), registry=schema_registry)
    assert list(validator.iter_errors(MigrateStepsResult().to_dict())) == []
