"""Unit tests for confiture migrate fix-signatures command."""

import json
from unittest.mock import MagicMock, patch

import psycopg
from typer.testing import CliRunner

from confiture.cli.main import app
from confiture.core.function_signature_drift import FunctionSignatureDriftReport, StaleOverload
from tests._helpers import strip_ansi as _strip_ansi

runner = CliRunner()


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
        assert "--mode" in _strip_ansi(result.output)
        assert "--schema" in _strip_ansi(result.output)


class TestFixSignaturesDryRun:
    def test_dry_run_exits_0_when_clean(self, tmp_path):
        config = tmp_path / "confiture.yaml"
        config.write_text("database:\n  url: postgresql://localhost/test\n")
        schema = tmp_path / "schema.sql"
        schema.write_text(_SCHEMA_SQL)

        with (
            patch(
                "confiture.cli.commands.migrate.fix_signatures.load_config",
                return_value=MagicMock(),
            ),
            patch(
                "confiture.cli.commands.migrate.fix_signatures.open_connection",
                _make_conn_mock(),
            ),
            patch("confiture.core.live_catalog.routines") as MockIntrospector,
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
            patch(
                "confiture.cli.commands.migrate.fix_signatures.load_config",
                return_value=MagicMock(),
            ),
            patch(
                "confiture.cli.commands.migrate.fix_signatures.open_connection",
                _make_conn_mock(),
            ),
            patch("confiture.core.live_catalog.routines") as MockIntrospector,
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
        assert "pass --mode apply to execute" in plain  # the plan names how to act

    def test_dry_run_json_output(self, tmp_path):
        import json

        config = tmp_path / "confiture.yaml"
        config.write_text("database:\n  url: postgresql://localhost/test\n")
        schema = tmp_path / "schema.sql"
        schema.write_text(_SCHEMA_SQL)

        with (
            patch(
                "confiture.cli.commands.migrate.fix_signatures.load_config",
                return_value=MagicMock(),
            ),
            patch(
                "confiture.cli.commands.migrate.fix_signatures.open_connection",
                _make_conn_mock(),
            ),
            patch("confiture.core.live_catalog.routines") as MockIntrospector,
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
        data = json.loads(result.stdout)
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
            patch(
                "confiture.cli.commands.migrate.fix_signatures.load_config",
                return_value=MagicMock(),
            ),
            patch(
                "confiture.cli.commands.migrate.fix_signatures.open_connection",
                _make_conn_mock(),
            ),
            patch("confiture.core.live_catalog.routines") as MockIntrospector,
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
                    "--mode",
                    "apply",
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
            patch(
                "confiture.cli.commands.migrate.fix_signatures.load_config",
                return_value=MagicMock(),
            ),
            patch(
                "confiture.cli.commands.migrate.fix_signatures.open_connection",
                _make_conn_mock(),
            ),
            patch("confiture.core.live_catalog.routines") as MockIntrospector,
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
                    "--mode",
                    "apply",
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
        failing_conn.cursor.return_value.__enter__ = MagicMock(
            side_effect=psycopg.OperationalError("db error")
        )
        failing_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        cm = MagicMock()
        cm.__enter__ = MagicMock(return_value=failing_conn)
        cm.__exit__ = MagicMock(return_value=False)

        with (
            patch(
                "confiture.cli.commands.migrate.fix_signatures.load_config",
                return_value=MagicMock(),
            ),
            patch(
                "confiture.cli.commands.migrate.fix_signatures.open_connection",
                MagicMock(return_value=cm),
            ),
            patch("confiture.core.live_catalog.routines") as MockIntrospector,
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
                    "--mode",
                    "apply",
                ],
            )
        assert result.exit_code == 1
        # One rollback ends the drift reads' transaction, the other undoes the fix.
        assert failing_conn.rollback.call_count == 2
        failing_conn.commit.assert_not_called()


class TestFixSignaturesMissingConfig:
    def test_a_missing_config_is_config_004_as_everywhere(self, tmp_path):
        """Exit 5, as every other command's missing config (exit 2 through 1.15)."""
        result = runner.invoke(
            app,
            [
                "migrate",
                "fix-signatures",
                "--config",
                str(tmp_path / "missing.yaml"),
                "--schema",
                str(tmp_path / "schema.sql"),
                "--format",
                "json",
            ],
        )
        assert result.exit_code == 5
        assert json.loads(result.stdout)["error"]["code"] == "CONFIG_004"

    def test_no_schema_and_no_env_name_is_config_001(self, tmp_path):
        """The auto-build's error, with its own code (exit 2 with no envelope through 1.23)."""
        config = tmp_path / "confiture.yaml"
        config.write_text("database:\n  url: postgresql://localhost/test\n")

        with patch(
            "confiture.cli.commands.migrate.fix_signatures.load_config", return_value=MagicMock()
        ):
            result = runner.invoke(
                app,
                ["migrate", "fix-signatures", "--config", str(config)],
            )
        assert result.exit_code == 5
        assert "auto-build failed" in _strip_ansi(result.output)


class TestFixSignaturesJsonOnEveryPath:
    """``--format json`` writes JSON on stdout whatever the outcome."""

    _NO_SOURCE_SQL = (
        "CREATE OR REPLACE FUNCTION public.other() RETURNS int AS $$ SELECT 1 $$ LANGUAGE sql;"
    )

    def _invoke(self, tmp_path, schema_sql, *extra, conn=None):
        config = tmp_path / "confiture.yaml"
        config.write_text("database:\n  url: postgresql://localhost/test\n")
        schema = tmp_path / "schema.sql"
        schema.write_text(schema_sql)
        with (
            patch(
                "confiture.cli.commands.migrate.fix_signatures.load_config",
                return_value=MagicMock(),
            ),
            patch(
                "confiture.cli.commands.migrate.fix_signatures.open_connection",
                conn or _make_conn_mock(),
            ),
            patch("confiture.core.live_catalog.routines"),
            patch(
                "confiture.core.function_signature_drift.FunctionSignatureDriftDetector.compare",
                return_value=_DRIFT_REPORT,
            ),
        ):
            return runner.invoke(
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
                    *extra,
                ],
            )

    def test_an_auto_build_that_fails_writes_the_error_envelope(self, tmp_path):
        from confiture.exceptions import SchemaError

        config = tmp_path / "confiture.yaml"
        config.write_text("name: local\n")
        with (
            patch(
                "confiture.cli.commands.migrate.fix_signatures.load_config",
                return_value={"name": "local"},
            ),
            patch(
                "confiture.cli.commands.migrate.fix_signatures._core_builder.SchemaBuilder",
                autospec=True,
                side_effect=SchemaError(
                    "Schema directory not found: db/schema", error_code="SCHEMA_201"
                ),
            ),
        ):
            result = runner.invoke(
                app,
                ["migrate", "fix-signatures", "--config", str(config), "--format", "json"],
            )

        payload = json.loads(result.stdout)
        assert (result.exit_code, payload["ok"], payload["error"]["code"]) == (
            4,
            False,
            "SCHEMA_201",
        )
        assert "--schema" in payload["error"]["actionable"]

    def test_no_stale_overload_with_a_source_is_a_report_at_exit_1(self, tmp_path):
        result = self._invoke(tmp_path, self._NO_SOURCE_SQL)

        payload = json.loads(result.stdout)
        assert (result.exit_code, payload["status"], payload["missing_source"]) == (
            1,
            "unfixable",
            ["public.get_user(integer)"],
        )

    def test_check_body_does_not_call_unfixable_drift_clean(self, tmp_path):
        result = self._invoke(tmp_path, self._NO_SOURCE_SQL, "--check-body")

        payload = json.loads(result.stdout)
        assert (result.exit_code, payload["status"]) == (1, "unfixable")

    def test_an_apply_rolled_back_writes_the_error_envelope(self, tmp_path):
        failing_conn = MagicMock()
        failing_conn.cursor.return_value.__enter__ = MagicMock(
            side_effect=psycopg.OperationalError("db error")
        )
        failing_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        cm = MagicMock()
        cm.__enter__ = MagicMock(return_value=failing_conn)
        cm.__exit__ = MagicMock(return_value=False)

        result = self._invoke(
            tmp_path, _SCHEMA_SQL, "--mode", "apply", conn=MagicMock(return_value=cm)
        )

        payload = json.loads(result.stdout)
        assert (result.exit_code, payload["ok"], payload["error"]["code"]) == (
            1,
            False,
            "SQL_001",
        )
        assert "rolled back" in payload["error"]["message"]
        failing_conn.commit.assert_not_called()

    def test_the_unfixable_report_is_the_published_shape(self, tmp_path):
        """No real capture reaches it (declared and defined come from one source): validate here."""
        from jsonschema import Draft202012Validator
        from referencing import Registry, Resource
        from referencing.jsonschema import DRAFT202012

        from confiture.core.schema_exporter import load_schema

        registry = Registry().with_resource(
            "_common.schema.json",
            Resource.from_contents(load_schema("_common.schema.json"), DRAFT202012),
        )
        validator = Draft202012Validator(
            load_schema("migrate-fix-signatures.schema.json"), registry=registry
        )
        for extra in ((), ("--check-body",)):
            payload = json.loads(self._invoke(tmp_path, self._NO_SOURCE_SQL, *extra).stdout)
            assert [e.message for e in validator.iter_errors(payload)] == []
