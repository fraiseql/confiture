"""Unit tests for the confiture diff CLI command and DiffResult model."""

import json
import tempfile

from typer.testing import CliRunner

from confiture.cli.main import app
from confiture.models.results import DiffResult
from confiture.models.schema import SchemaChange, SchemaDiff

runner = CliRunner()

OLD_SQL = "CREATE TABLE users (id INT, name TEXT);"
NEW_SQL = "CREATE TABLE users (id INT, name TEXT, bio TEXT);"


def _write_sql(content: str) -> str:
    """Write SQL to a temp file, return path string."""
    with tempfile.NamedTemporaryFile(suffix=".sql", mode="w", delete=False) as f:
        f.write(content)
        return f.name


class TestDiffResult:
    """Phase 03 Cycle 1: DiffResult model."""

    def test_diff_result_no_changes(self):
        diff = SchemaDiff(changes=[])
        result = DiffResult.from_schema_diff(diff)
        assert result.has_changes is False
        data = result.to_dict()
        assert data["has_changes"] is False
        assert data["changes"] == []

    def test_diff_result_with_changes(self):
        diff = SchemaDiff(
            changes=[SchemaChange(type="ADD_COLUMN", table="users", column="bio")]
        )
        result = DiffResult.from_schema_diff(diff)
        assert result.has_changes is True
        data = result.to_dict()
        assert data["has_changes"] is True
        assert len(data["changes"]) == 1
        assert data["changes"][0]["type"] == "ADD_COLUMN"

    def test_diff_result_summary_counts(self):
        diff = SchemaDiff(
            changes=[
                SchemaChange(type="ADD_COLUMN", table="users", column="bio"),
                SchemaChange(type="DROP_TABLE", table="legacy"),
            ]
        )
        result = DiffResult.from_schema_diff(diff)
        data = result.to_dict()
        assert data["summary"]["columns_added"] == 1
        assert data["summary"]["tables_dropped"] == 1

    def test_diff_result_summary_has_all_keys(self):
        diff = SchemaDiff(changes=[])
        data = DiffResult.from_schema_diff(diff).to_dict()
        summary = data["summary"]
        for key in (
            "tables_added", "tables_dropped", "tables_renamed",
            "columns_added", "columns_dropped",
            "indexes_added", "indexes_dropped",
            "foreign_keys_added", "foreign_keys_dropped",
            "constraints_added", "constraints_dropped",
            "enum_types_added", "enum_types_dropped",
            "sequences_added", "sequences_dropped",
        ):
            assert key in summary

    def test_diff_result_from_confiture_public_api(self):
        from confiture import DiffResult as PublicDiffResult  # noqa: PLC0415
        assert PublicDiffResult is DiffResult


class TestDiffCommand:
    """Phase 03 Cycle 2: diff CLI command."""

    def test_diff_command_text_no_changes(self):
        p = _write_sql(OLD_SQL)
        result = runner.invoke(app, ["diff", "--from", p, "--to", p])
        assert result.exit_code == 0
        assert "No changes" in result.output

    def test_diff_command_text_with_changes(self):
        old = _write_sql(OLD_SQL)
        new = _write_sql(NEW_SQL)
        result = runner.invoke(app, ["diff", "--from", old, "--to", new])
        assert result.exit_code == 1
        assert "bio" in result.output or "ADD_COLUMN" in result.output

    def test_diff_command_json_output(self):
        old = _write_sql(OLD_SQL)
        new = _write_sql(NEW_SQL)
        result = runner.invoke(app, ["diff", "--from", old, "--to", new, "--format", "json"])
        assert result.exit_code == 1
        data = json.loads(result.output)
        assert data["has_changes"] is True
        assert any(c["type"] == "ADD_COLUMN" for c in data["changes"])

    def test_diff_command_json_no_changes(self):
        p = _write_sql(OLD_SQL)
        result = runner.invoke(app, ["diff", "--from", p, "--to", p, "--format", "json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["has_changes"] is False

    def test_diff_command_missing_file(self):
        result = runner.invoke(
            app, ["diff", "--from", "nonexistent.sql", "--to", "also_missing.sql"]
        )
        assert result.exit_code == 2

    def test_diff_command_text_shows_change_count(self):
        old = _write_sql(OLD_SQL)
        new = _write_sql(NEW_SQL)
        result = runner.invoke(app, ["diff", "--from", old, "--to", new])
        assert "1 change" in result.output
