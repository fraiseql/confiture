"""E2E tests for the `confiture restore` CLI command.

All tests mock DatabaseRestorer.restore via unittest.mock — no real database
or pg_restore binary is required.
"""

from __future__ import annotations

from unittest.mock import patch

from typer.testing import CliRunner

from confiture.cli.main import app
from confiture.core.restorer import RestoreResult
from confiture.exceptions import RestoreError

runner = CliRunner()


class TestRestoreCLI:
    def test_restore_help_shows_expected_options(self):
        import re

        result = runner.invoke(app, ["restore", "--help"])
        assert result.exit_code == 0
        clean = re.sub(r"\x1b\[[0-9;]*m", "", result.output)
        for flag in [
            "--database",
            "--host",
            "--port",
            "--jobs",
            "--min-tables",
            "--exit-on-error",
            "--superuser",
        ]:
            assert flag in clean, f"Flag {flag!r} not found in help output"

    def test_missing_database_exits_nonzero(self, tmp_path):
        backup = tmp_path / "dump.pgdump"
        backup.touch()
        result = runner.invoke(app, ["restore", str(backup)])
        assert result.exit_code != 0

    def test_nonexistent_backup_exits_nonzero(self):
        result = runner.invoke(app, ["restore", "/nonexistent/dump.pgdump", "--database", "db"])
        assert result.exit_code != 0

    def test_successful_restore_exits_zero(self, tmp_path):
        backup = tmp_path / "dump.pgdump"
        backup.touch()
        with patch(
            "confiture.core.restorer.DatabaseRestorer.restore",
            return_value=RestoreResult(
                success=True, phases_completed=["pre-data", "data", "post-data"]
            ),
        ):
            result = runner.invoke(app, ["restore", str(backup), "--database", "mydb"])
        assert result.exit_code == 0

    def test_failed_restore_exits_one(self, tmp_path):
        backup = tmp_path / "dump.pgdump"
        backup.touch()
        with patch(
            "confiture.core.restorer.DatabaseRestorer.restore",
            return_value=RestoreResult(
                success=False,
                phases_completed=["pre-data"],
                errors=["FK constraint violation"],
            ),
        ):
            result = runner.invoke(app, ["restore", str(backup), "--database", "mydb"])
        assert result.exit_code == 1
        assert "FK constraint violation" in result.output

    def test_warnings_shown_even_on_success(self, tmp_path):
        backup = tmp_path / "dump.pgdump"
        backup.touch()
        with patch(
            "confiture.core.restorer.DatabaseRestorer.restore",
            return_value=RestoreResult(
                success=True,
                phases_completed=["pre-data", "data", "post-data"],
                warnings=["pg_restore: warning: table foo does not exist, skipping"],
            ),
        ):
            result = runner.invoke(app, ["restore", str(backup), "--database", "mydb"])
        assert result.exit_code == 0
        assert "warning" in result.output.lower()

    def test_all_options_forwarded_to_restore_options(self, tmp_path):
        backup = tmp_path / "dump.pgdump"
        backup.touch()
        captured: dict = {}

        def capture(opts, on_stderr_line=None):
            captured["opts"] = opts
            return RestoreResult(success=True, phases_completed=["pre-data", "data", "post-data"])

        with patch("confiture.core.restorer.DatabaseRestorer.restore", side_effect=capture):
            runner.invoke(
                app,
                [
                    "restore",
                    str(backup),
                    "--database",
                    "staging",
                    "--host",
                    "myhost",
                    "--port",
                    "5433",
                    "--username",
                    "appuser",
                    "--jobs",
                    "8",
                    "--min-tables",
                    "200",
                    "--min-tables-schema",
                    "myschema",
                    "--superuser",
                    "postgres",
                    "--no-owner",
                    "--no-acl",
                ],
            )
        opts = captured["opts"]
        assert opts.target_db == "staging"
        assert opts.host == "myhost"
        assert opts.port == 5433
        assert opts.username == "appuser"
        assert opts.jobs == 8
        assert opts.min_tables == 200
        assert opts.min_tables_schema == "myschema"
        assert opts.superuser == "postgres"
        assert opts.no_owner is True
        assert opts.no_acl is True

    def test_restore_error_from_bad_format_exits_one(self, tmp_path):
        backup = tmp_path / "dump.pgdump"
        backup.touch()
        with patch(
            "confiture.core.restorer.DatabaseRestorer.restore",
            side_effect=RestoreError("plain-text format not supported"),
        ):
            result = runner.invoke(app, ["restore", str(backup), "--database", "mydb"])
        assert result.exit_code == 1
        assert "plain-text" in result.output

    def test_table_count_shown_when_min_tables_set(self, tmp_path):
        backup = tmp_path / "dump.pgdump"
        backup.touch()
        with patch(
            "confiture.core.restorer.DatabaseRestorer.restore",
            return_value=RestoreResult(
                success=True,
                phases_completed=["pre-data", "data", "post-data"],
                table_count=350,
            ),
        ):
            result = runner.invoke(
                app,
                ["restore", str(backup), "--database", "mydb", "--min-tables", "300"],
            )
        assert result.exit_code == 0
        assert "350" in result.output

    def test_no_owner_defaults_to_false(self, tmp_path):
        backup = tmp_path / "dump.pgdump"
        backup.touch()
        captured: dict = {}

        def capture(opts, on_stderr_line=None):
            captured["opts"] = opts
            return RestoreResult(success=True, phases_completed=["pre-data", "data", "post-data"])

        with patch("confiture.core.restorer.DatabaseRestorer.restore", side_effect=capture):
            runner.invoke(app, ["restore", str(backup), "--database", "db"])
        assert captured["opts"].no_owner is False
        assert captured["opts"].no_acl is False
