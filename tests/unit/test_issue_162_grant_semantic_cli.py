"""CLI tests for the semantic grant gate's actionable output (issue #162).

The failure message must name the specific unmatched grant (object,
privilege, grantee) and the migration(s) inspected — not the old generic
".up.sql was not staged" text — and must surface degradation notes.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from confiture.cli.main import app
from confiture.models.git import GrantAccompanimentReport


@contextmanager
def _run_with(report: GrantAccompanimentReport, *cli_args: str):
    """Invoke `migrate validate` with the checker stubbed to return *report*."""
    with (
        patch("confiture.cli.git_validation.validate_git_flags_in_repo"),
        patch("confiture.cli.git_validation.GrantAccompanimentChecker") as mock_cls,
    ):
        mock_checker = MagicMock()
        mock_checker.check_accompaniment.return_value = report
        mock_cls.return_value = mock_checker
        yield CliRunner().invoke(
            app, ["migrate", "validate", "--require-grant-migration", "--staged", *cli_args]
        )


class TestSemanticGrantCli:
    def test_unmatched_grant_is_named_in_failure(self):
        report = GrantAccompanimentReport(
            has_grant_changes=True,
            has_migration_changes=True,
            grant_files_changed=[Path("db/7_grant/71_grant.sql")],
            migration_files_staged=[Path("db/migrations/20260613130000_x.py")],
            unmatched_grants=[
                {
                    "statement": "GRANT SELECT ON some_schema.some_table TO some_role",
                    "action": "GRANT",
                    "objtype": "TABLE",
                    "schema": "some_schema",
                    "object": "some_table",
                    "grantee": "some_role",
                    "privilege": "SELECT",
                    "changed_in": "db/7_grant/71_grant.sql",
                    "migrations_inspected": ["db/migrations/20260613130000_x.py"],
                }
            ],
        )
        with _run_with(report) as result:
            assert result.exit_code == 1
            assert "GRANT SELECT ON some_schema.some_table TO some_role" in result.output
            assert "db/7_grant/71_grant.sql" in result.output
            assert "20260613130000_x.py" in result.output

    def test_degradation_notes_surfaced(self):
        report = GrantAccompanimentReport(
            has_grant_changes=True,
            has_migration_changes=True,
            grant_files_changed=[Path("db/7_grant/71_grant.sql")],
            migration_files_staged=[Path("db/migrations/20260613130000_x.up.sql")],
            unverifiable_notes=[
                "db/7_grant/71_grant.sql: EXECUTE format(...) / dynamic SQL (dynamic_sql)"
            ],
        )
        with _run_with(report) as result:
            # Migration present + only notes → passes (degraded to file-presence).
            assert result.exit_code == 0
            assert "dynamic SQL" in result.output

    def test_no_up_sql_only_wording_in_failure(self):
        report = GrantAccompanimentReport(
            has_grant_changes=True,
            has_migration_changes=False,
            grant_files_changed=[Path("db/7_grant/71_grant.sql")],
            migration_files_staged=[],
            unmatched_grants=[
                {
                    "statement": "GRANT SELECT ON s.t TO r",
                    "action": "GRANT",
                    "objtype": "TABLE",
                    "schema": "s",
                    "object": "t",
                    "grantee": "r",
                    "privilege": "SELECT",
                    "changed_in": "db/7_grant/71_grant.sql",
                    "migrations_inspected": [],
                }
            ],
        )
        with _run_with(report) as result:
            assert result.exit_code == 1
            # The old message claimed only ".up.sql" migrations satisfy the gate.
            assert "(.up.sql)" not in result.output

    def test_json_envelope_carries_new_keys(self):
        report = GrantAccompanimentReport(
            has_grant_changes=True,
            has_migration_changes=False,
            grant_files_changed=[Path("db/7_grant/71_grant.sql")],
            migration_files_staged=[],
            unmatched_grants=[
                {
                    "statement": "GRANT SELECT ON s.t TO r",
                    "action": "GRANT",
                    "objtype": "TABLE",
                    "schema": "s",
                    "object": "t",
                    "grantee": "r",
                    "privilege": "SELECT",
                    "changed_in": "db/7_grant/71_grant.sql",
                    "migrations_inspected": [],
                }
            ],
            unverifiable_notes=["a note"],
        )
        with _run_with(report, "--format", "json") as result:
            assert result.exit_code == 1
            payload = json.loads(result.output)
            assert payload["status"] == "failed"
            assert payload["check"] == "grant_accompaniment"
            assert payload["unmatched_grants"][0]["grantee"] == "r"
            assert payload["unverifiable_notes"] == ["a note"]
