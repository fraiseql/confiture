"""Unit tests for the `confiture introspect` CLI command.

All network and database interactions are mocked.
"""

import json
from unittest.mock import MagicMock, patch

import yaml
from typer.testing import CliRunner

from confiture.cli.main import app
from confiture.models.introspection import IntrospectionResult

runner = CliRunner()


def _make_result(**kwargs) -> IntrospectionResult:
    """Build a minimal IntrospectionResult for mocking."""
    defaults = {
        "database": "testdb",
        "schema": "public",
        "introspected_at": "2026-02-21T12:00:00Z",
        "tables": [],
    }
    defaults.update(kwargs)
    return IntrospectionResult(**defaults)


class TestIntrospectCommand:
    """Tests for the introspect CLI command."""

    @patch("confiture.cli.main.SchemaIntrospector")
    @patch("confiture.cli.main.create_connection")
    def test_requires_db_option(self, mock_conn, mock_introspector):
        """Missing --db should exit with non-zero code."""
        result = runner.invoke(app, ["introspect"])
        assert result.exit_code != 0

    @patch("confiture.cli.main.SchemaIntrospector")
    @patch("confiture.cli.main.create_connection")
    def test_json_output_is_valid(self, mock_create_conn, mock_introspector_class):
        """Default format produces valid, parseable JSON on stdout."""
        mock_create_conn.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_create_conn.return_value.__exit__ = MagicMock(return_value=False)

        mock_introspector = MagicMock()
        mock_introspector_class.return_value = mock_introspector
        mock_introspector.introspect.return_value = _make_result()

        result = runner.invoke(app, ["introspect", "--db", "postgresql://localhost/test"])

        assert result.exit_code == 0
        parsed = json.loads(result.stdout)
        assert parsed["database"] == "testdb"
        assert parsed["schema"] == "public"
        assert "tables" in parsed

    @patch("confiture.cli.main.SchemaIntrospector")
    @patch("confiture.cli.main.create_connection")
    def test_yaml_output_is_valid(self, mock_create_conn, mock_introspector_class):
        """--format yaml produces valid, parseable YAML on stdout."""
        mock_create_conn.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_create_conn.return_value.__exit__ = MagicMock(return_value=False)

        mock_introspector = MagicMock()
        mock_introspector_class.return_value = mock_introspector
        mock_introspector.introspect.return_value = _make_result()

        result = runner.invoke(
            app, ["introspect", "--db", "postgresql://localhost/test", "--format", "yaml"]
        )

        assert result.exit_code == 0
        parsed = yaml.safe_load(result.stdout)
        assert parsed["database"] == "testdb"

    @patch("confiture.cli.main.SchemaIntrospector")
    @patch("confiture.cli.main.create_connection")
    def test_invalid_format_exits_with_error(self, mock_create_conn, mock_introspector_class):
        """Unsupported --format value exits 1 with an error message."""
        result = runner.invoke(
            app, ["introspect", "--db", "postgresql://localhost/test", "--format", "csv"]
        )
        assert result.exit_code == 1

    @patch("confiture.cli.main.SchemaIntrospector")
    @patch("confiture.cli.main.create_connection")
    def test_connection_failure_exits_with_error(self, mock_create_conn, mock_introspector_class):
        """Connection failure exits 1 with an error message."""
        mock_create_conn.side_effect = Exception("could not connect")

        result = runner.invoke(app, ["introspect", "--db", "postgresql://bad/db"])

        assert result.exit_code == 1

    @patch("confiture.cli.main.SchemaIntrospector")
    @patch("confiture.cli.main.create_connection")
    def test_all_tables_flag_passed_through(self, mock_create_conn, mock_introspector_class):
        """--all-tables is forwarded to SchemaIntrospector.introspect()."""
        mock_create_conn.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_create_conn.return_value.__exit__ = MagicMock(return_value=False)

        mock_introspector = MagicMock()
        mock_introspector_class.return_value = mock_introspector
        mock_introspector.introspect.return_value = _make_result()

        runner.invoke(app, ["introspect", "--db", "postgresql://localhost/test", "--all-tables"])

        mock_introspector.introspect.assert_called_once_with(
            schema="public",
            all_tables=True,
            include_hints=True,
        )

    @patch("confiture.cli.main.SchemaIntrospector")
    @patch("confiture.cli.main.create_connection")
    def test_no_hints_flag_passed_through(self, mock_create_conn, mock_introspector_class):
        """--no-hints sets include_hints=False in SchemaIntrospector.introspect()."""
        mock_create_conn.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_create_conn.return_value.__exit__ = MagicMock(return_value=False)

        mock_introspector = MagicMock()
        mock_introspector_class.return_value = mock_introspector
        mock_introspector.introspect.return_value = _make_result()

        runner.invoke(app, ["introspect", "--db", "postgresql://localhost/test", "--no-hints"])

        mock_introspector.introspect.assert_called_once_with(
            schema="public",
            all_tables=False,
            include_hints=False,
        )

    @patch("confiture.cli.main.SchemaIntrospector")
    @patch("confiture.cli.main.create_connection")
    def test_schema_option_passed_through(self, mock_create_conn, mock_introspector_class):
        """--schema is forwarded to SchemaIntrospector.introspect()."""
        mock_create_conn.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_create_conn.return_value.__exit__ = MagicMock(return_value=False)

        mock_introspector = MagicMock()
        mock_introspector_class.return_value = mock_introspector
        mock_introspector.introspect.return_value = _make_result(schema="myschema")

        runner.invoke(
            app,
            ["introspect", "--db", "postgresql://localhost/test", "--schema", "myschema"],
        )

        mock_introspector.introspect.assert_called_once_with(
            schema="myschema",
            all_tables=False,
            include_hints=True,
        )

    @patch("confiture.cli.main.SchemaIntrospector")
    @patch("confiture.cli.main.create_connection")
    def test_output_file_written(self, mock_create_conn, mock_introspector_class, tmp_path):
        """--output writes JSON to file instead of stdout."""
        mock_create_conn.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_create_conn.return_value.__exit__ = MagicMock(return_value=False)

        mock_introspector = MagicMock()
        mock_introspector_class.return_value = mock_introspector
        mock_introspector.introspect.return_value = _make_result()

        out_file = tmp_path / "schema.json"
        result = runner.invoke(
            app,
            ["introspect", "--db", "postgresql://localhost/test", "--output", str(out_file)],
        )

        assert result.exit_code == 0
        assert out_file.exists()
        parsed = json.loads(out_file.read_text())
        assert parsed["database"] == "testdb"
