"""Unit tests for confiture migrate fix-signatures command."""

import re
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from confiture.cli.commands.migrate_analysis import _extract_function_source
from confiture.cli.main import app
from confiture.core.function_signature_drift import FunctionSignatureDriftReport, StaleOverload

runner = CliRunner()


def _strip_ansi(text: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


# ---------------------------------------------------------------------------
# _extract_function_source unit tests
# ---------------------------------------------------------------------------


class TestExtractFunctionSource:
    _SQL = """
CREATE TABLE users (id bigint);

CREATE OR REPLACE FUNCTION public.get_user(user_id bigint)
RETURNS TABLE(id bigint, name text) AS $$
  SELECT id, name FROM users WHERE id = user_id;
$$ LANGUAGE sql;

CREATE OR REPLACE FUNCTION public.set_status(user_id integer, status text)
RETURNS void AS $$ BEGIN END; $$ LANGUAGE plpgsql;
"""

    def test_finds_qualified_name(self):
        result = _extract_function_source(self._SQL, "public", "get_user")
        assert result is not None
        assert "get_user" in result
        assert "bigint" in result

    def test_finds_second_function(self):
        result = _extract_function_source(self._SQL, "public", "set_status")
        assert result is not None
        assert "set_status" in result

    def test_returns_none_when_not_found(self):
        result = _extract_function_source(self._SQL, "public", "no_such_fn")
        assert result is None

    def test_returns_none_on_empty_sql(self):
        result = _extract_function_source("", "public", "get_user")
        assert result is None

    def test_matches_unqualified_name(self):
        sql = "CREATE FUNCTION get_user(id bigint) RETURNS void AS $$ $$ LANGUAGE sql;"
        result = _extract_function_source(sql, "public", "get_user")
        assert result is not None
        assert "get_user" in result


# ---------------------------------------------------------------------------
# CLI tests
# ---------------------------------------------------------------------------

_SCHEMA_SQL = """
CREATE OR REPLACE FUNCTION public.get_user(user_id bigint)
RETURNS TABLE(id bigint) AS $$ SELECT id FROM users WHERE id = user_id; $$ LANGUAGE sql;
"""

_STALE_OVERLOAD = StaleOverload(
    schema="public",
    name="get_user",
    stale_signature="public.get_user(integer)",
    source_signatures=["public.get_user(bigint)"],
)

_CLEAN_REPORT = FunctionSignatureDriftReport(
    stale_overloads=[],
    missing_from_db=[],
    schemas_checked=["public"],
    functions_checked=1,
    has_drift=False,
    detection_time_ms=1.0,
)

_DRIFT_REPORT = FunctionSignatureDriftReport(
    stale_overloads=[_STALE_OVERLOAD],
    missing_from_db=[],
    schemas_checked=["public"],
    functions_checked=1,
    has_drift=True,
    detection_time_ms=1.0,
)


def _make_conn_mock() -> MagicMock:
    """Return a context-manager mock for open_connection."""
    conn = MagicMock()
    conn.autocommit = True
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=conn)
    cm.__exit__ = MagicMock(return_value=False)
    return MagicMock(return_value=cm)


class TestFixSignaturesHelp:
    def test_fix_signatures_flag_exists(self):
        result = runner.invoke(app, ["migrate", "fix-signatures", "--help"])
        assert "--apply" in _strip_ansi(result.output)
        assert "--schema" in _strip_ansi(result.output)


class TestFixSignaturesDryRun:
    def test_dry_run_exits_0_when_clean(self, tmp_path):
        config = tmp_path / "confiture.yaml"
        config.write_text("database:\n  url: postgresql://localhost/test\n")
        schema = tmp_path / "schema.sql"
        schema.write_text(_SCHEMA_SQL)

        with (
            patch("confiture.cli.commands.migrate_analysis.load_config", return_value=MagicMock()),
            patch(
                "confiture.cli.commands.migrate_analysis.open_connection",
                _make_conn_mock(),
            ),
            patch("confiture.core.live_function_catalog.FunctionIntrospector") as MockIntrospector,
            patch(
                "confiture.core.function_signature_drift.FunctionSignatureDriftDetector.compare",
                return_value=_CLEAN_REPORT,
            ),
        ):
            MockIntrospector.return_value.introspect.return_value = MagicMock(functions=[])
            result = runner.invoke(
                app,
                [
                    "migrate",
                    "fix-signatures",
                    "--config",
                    str(config),
                    "--schema",
                    str(schema),
                ],
            )
        assert result.exit_code == 0
        assert "no stale" in _strip_ansi(result.output).lower()

    def test_dry_run_shows_sql_and_exits_0(self, tmp_path):
        config = tmp_path / "confiture.yaml"
        config.write_text("database:\n  url: postgresql://localhost/test\n")
        schema = tmp_path / "schema.sql"
        schema.write_text(_SCHEMA_SQL)

        with (
            patch("confiture.cli.commands.migrate_analysis.load_config", return_value=MagicMock()),
            patch(
                "confiture.cli.commands.migrate_analysis.open_connection",
                _make_conn_mock(),
            ),
            patch("confiture.core.live_function_catalog.FunctionIntrospector") as MockIntrospector,
            patch(
                "confiture.core.function_signature_drift.FunctionSignatureDriftDetector.compare",
                return_value=_DRIFT_REPORT,
            ),
        ):
            MockIntrospector.return_value.introspect.return_value = MagicMock(functions=[])
            result = runner.invoke(
                app,
                [
                    "migrate",
                    "fix-signatures",
                    "--config",
                    str(config),
                    "--schema",
                    str(schema),
                ],
            )
        assert result.exit_code == 0
        plain = _strip_ansi(result.output)
        assert "DROP FUNCTION" in plain
        assert "dry" in plain.lower() or "planned" in plain.lower()

    def test_dry_run_json_output(self, tmp_path):
        import json

        config = tmp_path / "confiture.yaml"
        config.write_text("database:\n  url: postgresql://localhost/test\n")
        schema = tmp_path / "schema.sql"
        schema.write_text(_SCHEMA_SQL)

        with (
            patch("confiture.cli.commands.migrate_analysis.load_config", return_value=MagicMock()),
            patch(
                "confiture.cli.commands.migrate_analysis.open_connection",
                _make_conn_mock(),
            ),
            patch("confiture.core.live_function_catalog.FunctionIntrospector") as MockIntrospector,
            patch(
                "confiture.core.function_signature_drift.FunctionSignatureDriftDetector.compare",
                return_value=_DRIFT_REPORT,
            ),
        ):
            MockIntrospector.return_value.introspect.return_value = MagicMock(functions=[])
            result = runner.invoke(
                app,
                [
                    "migrate",
                    "fix-signatures",
                    "--config",
                    str(config),
                    "--schema",
                    str(schema),
                    "--format",
                    "json",
                ],
            )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["status"] == "dry_run"
        assert data["fixes_planned"] == 1
        assert "DROP FUNCTION" in data["sql"]


class TestFixSignaturesApply:
    def test_apply_executes_and_exits_0_on_clean_after(self, tmp_path):
        config = tmp_path / "confiture.yaml"
        config.write_text("database:\n  url: postgresql://localhost/test\n")
        schema = tmp_path / "schema.sql"
        schema.write_text(_SCHEMA_SQL)

        with (
            patch("confiture.cli.commands.migrate_analysis.load_config", return_value=MagicMock()),
            patch(
                "confiture.cli.commands.migrate_analysis.open_connection",
                _make_conn_mock(),
            ),
            patch("confiture.core.live_function_catalog.FunctionIntrospector") as MockIntrospector,
            patch(
                "confiture.core.function_signature_drift.FunctionSignatureDriftDetector.compare",
                side_effect=[_DRIFT_REPORT, _CLEAN_REPORT],
            ),
        ):
            MockIntrospector.return_value.introspect.return_value = MagicMock(functions=[])
            result = runner.invoke(
                app,
                [
                    "migrate",
                    "fix-signatures",
                    "--config",
                    str(config),
                    "--schema",
                    str(schema),
                    "--apply",
                ],
            )
        assert result.exit_code == 0
        plain = _strip_ansi(result.output)
        assert "applied" in plain.lower() or "1" in plain

    def test_apply_exits_1_when_residual_drift(self, tmp_path):
        config = tmp_path / "confiture.yaml"
        config.write_text("database:\n  url: postgresql://localhost/test\n")
        schema = tmp_path / "schema.sql"
        schema.write_text(_SCHEMA_SQL)

        with (
            patch("confiture.cli.commands.migrate_analysis.load_config", return_value=MagicMock()),
            patch(
                "confiture.cli.commands.migrate_analysis.open_connection",
                _make_conn_mock(),
            ),
            patch("confiture.core.live_function_catalog.FunctionIntrospector") as MockIntrospector,
            patch(
                "confiture.core.function_signature_drift.FunctionSignatureDriftDetector.compare",
                side_effect=[_DRIFT_REPORT, _DRIFT_REPORT],
            ),
        ):
            MockIntrospector.return_value.introspect.return_value = MagicMock(functions=[])
            result = runner.invoke(
                app,
                [
                    "migrate",
                    "fix-signatures",
                    "--config",
                    str(config),
                    "--schema",
                    str(schema),
                    "--apply",
                ],
            )
        assert result.exit_code == 1

    def test_apply_rolls_back_on_error(self, tmp_path):
        config = tmp_path / "confiture.yaml"
        config.write_text("database:\n  url: postgresql://localhost/test\n")
        schema = tmp_path / "schema.sql"
        schema.write_text(_SCHEMA_SQL)

        failing_conn = MagicMock()
        failing_conn.autocommit = True
        failing_conn.cursor.return_value.__enter__ = MagicMock(side_effect=Exception("db error"))
        failing_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        cm = MagicMock()
        cm.__enter__ = MagicMock(return_value=failing_conn)
        cm.__exit__ = MagicMock(return_value=False)

        with (
            patch("confiture.cli.commands.migrate_analysis.load_config", return_value=MagicMock()),
            patch(
                "confiture.cli.commands.migrate_analysis.open_connection",
                MagicMock(return_value=cm),
            ),
            patch("confiture.core.live_function_catalog.FunctionIntrospector") as MockIntrospector,
            patch(
                "confiture.core.function_signature_drift.FunctionSignatureDriftDetector.compare",
                return_value=_DRIFT_REPORT,
            ),
        ):
            MockIntrospector.return_value.introspect.return_value = MagicMock(functions=[])
            result = runner.invoke(
                app,
                [
                    "migrate",
                    "fix-signatures",
                    "--config",
                    str(config),
                    "--schema",
                    str(schema),
                    "--apply",
                ],
            )
        assert result.exit_code == 1
        failing_conn.rollback.assert_called_once()


class TestFixSignaturesMissingConfig:
    def test_exits_2_when_config_missing(self, tmp_path):
        result = runner.invoke(
            app,
            [
                "migrate",
                "fix-signatures",
                "--config",
                str(tmp_path / "missing.yaml"),
                "--schema",
                str(tmp_path / "schema.sql"),
            ],
        )
        assert result.exit_code == 2

    def test_exits_2_when_no_source_and_no_schema(self, tmp_path):
        config = tmp_path / "confiture.yaml"
        config.write_text("database:\n  url: postgresql://localhost/test\n")

        with patch("confiture.cli.commands.migrate_analysis.load_config", return_value=MagicMock()):
            result = runner.invoke(
                app,
                ["migrate", "fix-signatures", "--config", str(config)],
            )
        assert result.exit_code == 2
