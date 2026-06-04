"""End-to-end happy-path for the ``migrate schema-to-schema`` workflow.

Drives the full Medium-4 cutover sequence — setup → analyze → migrate →
migrate-table → verify → cleanup — through the real Typer ``app`` (the same
entrypoint the ``confiture`` console script invokes). The ``SchemaToSchemaMigrator``
is mocked at the ``_migrator`` factory seam so the workflow runs without a
database; everything *around* the core (arg parsing, the mapping-YAML loader,
output formatting, exit codes, the JSON envelope) is exercised for real.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from confiture.cli.main import app

runner = CliRunner()

S2S = ["migrate", "schema-to-schema"]
CONN = ["--source", "old_prod", "--target", "new_prod"]


def _fake_migrator() -> MagicMock:
    """A migrator whose every operation reports a clean, successful run."""
    m = MagicMock()
    m.analyze_tables.return_value = {
        "users": {"recommended_strategy": "fdw", "row_count": 1_000},
        "events": {"recommended_strategy": "copy", "row_count": 50_000_000},
    }
    m.migrate_table.return_value = 1_000
    m.migrate_table_copy.return_value = 50_000_000
    m.verify_migration.return_value = {
        "users": {"match": True, "source_count": 1_000, "target_count": 1_000},
        "events": {"match": True, "source_count": 50_000_000, "target_count": 50_000_000},
    }
    return m


def test_full_cutover_workflow(tmp_path) -> None:
    """setup → analyze → migrate → migrate-table → verify → cleanup all succeed."""
    mapping = tmp_path / "column_mapping.yaml"
    mapping.write_text(
        "users:\n"
        "  source_table: old_users\n"
        "  target_table: users\n"
        "  columns:\n"
        "    full_name: display_name\n"
        "    email: email\n"
    )

    m = _fake_migrator()
    with patch("confiture.cli.schema_to_schema._migrator", return_value=m):
        # 1. Set up the FDW
        r = runner.invoke(app, [*S2S, "setup", *CONN])
        assert r.exit_code == 0, r.output
        m.setup_fdw.assert_called_once_with(skip_import=False)

        # 2. Analyze — strategy recommendations are rendered
        r = runner.invoke(app, [*S2S, "analyze", *CONN])
        assert r.exit_code == 0, r.output
        assert "users" in r.output and "events" in r.output

        # 3. Migrate every table in the mapping file (real YAML parse)
        r = runner.invoke(app, [*S2S, "migrate", *CONN, "--mapping", str(mapping)])
        assert r.exit_code == 0, r.output
        m.migrate_table.assert_called_once_with(
            source_table="old_users",
            target_table="users",
            column_mapping={"full_name": "display_name", "email": "email"},
        )
        assert "1000 rows migrated" in r.output

        # 4. Migrate a single table with an inline mapping
        r = runner.invoke(
            app,
            [
                *S2S, "migrate-table", *CONN,
                "--source-table", "old_events",
                "--target-table", "events",
                "--mapping", "ts:created_at",
                "--strategy", "copy",
            ],
        )
        assert r.exit_code == 0, r.output
        m.migrate_table_copy.assert_called_once_with(
            source_table="old_events",
            target_table="events",
            column_mapping={"ts": "created_at"},
        )

        # 5. Verify — all tables match → clean exit
        r = runner.invoke(app, [*S2S, "verify", *CONN, "--tables", "users,events"])
        assert r.exit_code == 0, r.output
        assert "All tables match" in r.output

        # 6. Cleanup tears down the FDW
        r = runner.invoke(app, [*S2S, "cleanup", *CONN])
        assert r.exit_code == 0, r.output
        m.cleanup_fdw.assert_called_once_with()


def test_workflow_json_envelopes_are_well_formed(tmp_path) -> None:
    """The happy-path JSON output is valid JSON on each step."""
    import json

    m = _fake_migrator()
    with patch("confiture.cli.schema_to_schema._migrator", return_value=m):
        r = runner.invoke(app, [*S2S, "setup", *CONN, "--format", "json"])
        assert r.exit_code == 0, r.output
        assert json.loads(r.output) == {
            "ok": True,
            "command": "setup",
            "skip_import": False,
        }

        r = runner.invoke(
            app, [*S2S, "verify", *CONN, "--tables", "users,events", "--format", "json"]
        )
        assert r.exit_code == 0, r.output
        payload = json.loads(r.output)
        assert payload["command"] == "verify"
        assert payload["matched"] is True
