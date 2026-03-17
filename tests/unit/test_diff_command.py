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


class TestDiffResultNullFields:
    """Gap G — DiffResult.to_dict() with None fields on changes."""

    def test_diff_result_to_dict_null_fields(self):
        from confiture.models.schema import SchemaChange, SchemaDiff  # noqa: PLC0415

        diff = SchemaDiff(changes=[
            SchemaChange(type="ADD_SEQUENCE", table="order_seq"),
            SchemaChange(type="ADD_ENUM_TYPE", table="status"),
        ])
        data = DiffResult.from_schema_diff(diff).to_dict()
        assert data["summary"]["sequences_added"] == 1
        assert data["summary"]["enum_types_added"] == 1
        seq_change = next(c for c in data["changes"] if c["type"] == "ADD_SEQUENCE")
        assert seq_change["column"] is None
        assert seq_change["old_value"] is None
        assert seq_change["new_value"] is None

    def test_diff_result_to_dict_details_field_present(self):
        diff = SchemaDiff(changes=[
            SchemaChange(type="ADD_INDEX", table="users",
                         details={"index_name": "idx_email", "columns": ["email"]}),
        ])
        data = DiffResult.from_schema_diff(diff).to_dict()
        change = data["changes"][0]
        assert change["details"] is not None
        assert change["details"]["index_name"] == "idx_email"


class TestDiffResultSummaryRenames:
    """Gap H — RENAME changes are not counted in the summary."""

    def test_diff_result_summary_does_not_count_renames(self):
        diff = SchemaDiff(changes=[
            SchemaChange(type="RENAME_TABLE", old_value="old", new_value="new"),
            SchemaChange(type="RENAME_COLUMN", table="t", old_value="a", new_value="b"),
        ])
        data = DiffResult.from_schema_diff(diff).to_dict()
        # tables_renamed tracks RENAME_TABLE; all other counters should be 0
        non_rename_sum = sum(
            v for k, v in data["summary"].items() if k != "tables_renamed"
        )
        assert non_rename_sum == 0

    def test_diff_result_summary_tables_renamed_is_counted(self):
        diff = SchemaDiff(changes=[
            SchemaChange(type="RENAME_TABLE", old_value="old", new_value="new"),
        ])
        data = DiffResult.from_schema_diff(diff).to_dict()
        assert data["summary"]["tables_renamed"] == 1


class TestDiffCommandParseError:
    """Gap I — diff command parse error path exits with code 2."""

    def test_diff_command_parse_error_exits_2(self):
        from unittest.mock import patch  # noqa: PLC0415

        old = _write_sql("CREATE TABLE t (id INT);")
        new = _write_sql("CREATE TABLE t (id INT);")
        with patch(
            "confiture.cli.commands.diff.SchemaDiffer.compare",
            side_effect=RuntimeError("parse failure"),
        ):
            result = runner.invoke(app, ["diff", "--from", old, "--to", new])
        assert result.exit_code == 2


class TestDiffCommandFormatFallthrough:
    """Gap J — unknown --format value falls through to text output."""

    def test_diff_command_unknown_format_falls_through_to_text(self):
        p = _write_sql(OLD_SQL)
        result = runner.invoke(app, ["diff", "--from", p, "--to", p, "--format", "csv"])
        assert result.exit_code == 0
        assert "No changes" in result.output


class TestDiffTextRenameOutput:
    """Gap K — print_diff_text colour branch for RENAME types."""

    def test_diff_text_output_with_rename_table(self):
        old = _write_sql("CREATE TABLE user_accounts (id INT);")
        new = _write_sql("CREATE TABLE user_profiles (id INT);")
        result = runner.invoke(app, ["diff", "--from", old, "--to", new])
        # rename detection may or may not be supported; at minimum it must not crash
        assert result.exit_code in (0, 1)
        assert result.exception is None or isinstance(result.exception, SystemExit)

    def test_diff_text_rename_column_change_renders(self):
        import io  # noqa: PLC0415

        from rich.console import Console  # noqa: PLC0415

        from confiture.cli.formatters.diff_formatter import print_diff_text  # noqa: PLC0415
        from confiture.models.results import DiffResult  # noqa: PLC0415
        from confiture.models.schema import SchemaChange, SchemaDiff  # noqa: PLC0415

        diff = SchemaDiff(changes=[
            SchemaChange(type="RENAME_COLUMN", table="users", old_value="email",
                         new_value="email_address"),
            SchemaChange(type="RENAME_TABLE", old_value="users", new_value="accounts"),
        ])
        result_obj = DiffResult.from_schema_diff(diff)
        buf = io.StringIO()
        con = Console(file=buf, highlight=False, markup=False)
        # Must not raise
        print_diff_text(result_obj, con)
        output = buf.getvalue()
        assert len(output) > 0
