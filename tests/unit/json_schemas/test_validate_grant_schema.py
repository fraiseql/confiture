"""Validate ``migrate validate --require-grant-migration --format json`` output (issue #162).

This schema is NOT part of the fraisier adapter contract (D13) — it is a
standalone, completeness schema for the grant gate's JSON failure envelope.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from jsonschema import Draft202012Validator
from typer.testing import CliRunner

from confiture.cli.main import app
from confiture.models.git import GrantAccompanimentReport

SCHEMA_FILE = "migrate-validate-grant.schema.json"


def _failing_report() -> GrantAccompanimentReport:
    return GrantAccompanimentReport(
        has_grant_changes=True,
        has_migration_changes=True,
        grant_files_changed=[Path("db/7_grant/71_grant.sql")],
        migration_files_staged=[Path("db/migrations/20260613130000_x.py")],
        unmatched_grants=[
            {
                "statement": "GRANT SELECT ON s.t TO reporter",
                "action": "GRANT",
                "objtype": "TABLE",
                "target_kind": "OBJECT",
                "schema": "s",
                "object": "t",
                "grantee": "reporter",
                "privilege": "SELECT",
                "changed_in": "db/7_grant/71_grant.sql",
                "migrations_inspected": ["db/migrations/20260613130000_x.py"],
            }
        ],
        unverifiable_notes=["db/7_grant/71_grant.sql: dynamic SQL (dynamic_sql)"],
    )


def test_schema_is_valid_draft_2020_12(schemas_dir):
    schema = json.loads((schemas_dir / SCHEMA_FILE).read_text())
    Draft202012Validator.check_schema(schema)


def test_failed_grant_envelope_validates(schemas_dir):
    with (
        patch("confiture.cli.git_validation.validate_git_flags_in_repo"),
        patch("confiture.cli.git_validation.GrantAccompanimentChecker") as mock_cls,
    ):
        mock_checker = MagicMock()
        mock_checker.check_accompaniment.return_value = _failing_report()
        mock_cls.return_value = mock_checker
        result = CliRunner().invoke(
            app,
            ["migrate", "validate", "--require-grant-migration", "--staged", "--format", "json"],
        )

    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    schema = json.loads((schemas_dir / SCHEMA_FILE).read_text())
    Draft202012Validator(schema).validate(payload)
    assert payload["check"] == "grant_accompaniment"
    assert payload["status"] == "failed"
