"""Unit tests for migrate validate --check-signatures CLI flag."""

import re
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from confiture.cli.main import app
from confiture.core.function_signature_drift import FunctionSignatureDriftReport


def _strip_ansi(text: str) -> str:
    """Strip ANSI escape codes from text (needed when GITHUB_ACTIONS forces Rich colors)."""
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


def _empty_report() -> FunctionSignatureDriftReport:
    return FunctionSignatureDriftReport(
        stale_overloads=[],
        missing_from_db=[],
        schemas_checked=["public"],
        functions_checked=5,
        has_drift=False,
        detection_time_ms=10.0,
    )


def _drift_report() -> FunctionSignatureDriftReport:
    from confiture.core.function_signature_drift import StaleOverload

    return FunctionSignatureDriftReport(
        stale_overloads=[
            StaleOverload(
                schema="public",
                name="get_user",
                stale_signature="public.get_user(integer)",
                source_signatures=["public.get_user(bigint)"],
            )
        ],
        missing_from_db=[],
        schemas_checked=["public"],
        functions_checked=1,
        has_drift=True,
        detection_time_ms=10.0,
    )


runner = CliRunner()


class TestCheckSignaturesFlag:
    def test_check_signatures_flag_exists(self):
        result = runner.invoke(app, ["migrate", "validate", "--help"])
        assert "--check-signatures" in _strip_ansi(result.output)

    def test_check_signatures_requires_schema_file(self, tmp_path):
        config = tmp_path / "confiture.yaml"
        config.write_text("database:\n  url: postgresql://localhost/test\n")
        result = runner.invoke(
            app,
            ["migrate", "validate", "--check-signatures", "--config", str(config)],
        )
        assert result.exit_code == 2

    def test_check_signatures_requires_config_file(self, tmp_path):
        schema = tmp_path / "schema.sql"
        schema.write_text("-- empty")
        result = runner.invoke(
            app,
            [
                "migrate",
                "validate",
                "--check-signatures",
                "--config",
                str(tmp_path / "missing.yaml"),
                "--schema",
                str(schema),
            ],
        )
        assert result.exit_code == 2

    def _make_open_conn_mock(self) -> MagicMock:
        """Return a context manager mock for open_connection."""

        fake_conn = MagicMock()
        cm = MagicMock()
        cm.__enter__ = MagicMock(return_value=fake_conn)
        cm.__exit__ = MagicMock(return_value=False)
        mock = MagicMock(return_value=cm)
        return mock

    def test_check_signatures_exits_0_on_clean(self, tmp_path):
        config = tmp_path / "confiture.yaml"
        config.write_text("database:\n  url: postgresql://localhost/test\n")
        schema = tmp_path / "schema.sql"
        schema.write_text("-- no functions")

        with (
            patch("confiture.cli.commands.migrate_analysis.load_config", return_value=MagicMock()),
            patch(
                "confiture.cli.commands.migrate_analysis.open_connection",
                self._make_open_conn_mock(),
            ),
            patch("confiture.core.live_function_catalog.FunctionIntrospector") as MockIntrospector,
        ):
            MockIntrospector.return_value.introspect.return_value = MagicMock(functions=[])

            with patch(
                "confiture.core.function_signature_drift.FunctionSignatureDriftDetector.compare",
                return_value=_empty_report(),
            ):
                result = runner.invoke(
                    app,
                    [
                        "migrate",
                        "validate",
                        "--check-signatures",
                        "--config",
                        str(config),
                        "--schema",
                        str(schema),
                    ],
                )
        assert result.exit_code == 0

    def test_check_signatures_exits_1_on_drift(self, tmp_path):
        config = tmp_path / "confiture.yaml"
        config.write_text("database:\n  url: postgresql://localhost/test\n")
        schema = tmp_path / "schema.sql"
        schema.write_text("-- no functions")

        with (
            patch("confiture.cli.commands.migrate_analysis.load_config", return_value=MagicMock()),
            patch(
                "confiture.cli.commands.migrate_analysis.open_connection",
                self._make_open_conn_mock(),
            ),
            patch("confiture.core.live_function_catalog.FunctionIntrospector") as MockIntrospector,
        ):
            MockIntrospector.return_value.introspect.return_value = MagicMock(functions=[])

            with patch(
                "confiture.core.function_signature_drift.FunctionSignatureDriftDetector.compare",
                return_value=_drift_report(),
            ):
                result = runner.invoke(
                    app,
                    [
                        "migrate",
                        "validate",
                        "--check-signatures",
                        "--config",
                        str(config),
                        "--schema",
                        str(schema),
                    ],
                )
        assert result.exit_code == 1

    def test_check_signatures_json_output(self, tmp_path):
        config = tmp_path / "confiture.yaml"
        config.write_text("database:\n  url: postgresql://localhost/test\n")
        schema = tmp_path / "schema.sql"
        schema.write_text("-- no functions")

        with (
            patch("confiture.cli.commands.migrate_analysis.load_config", return_value=MagicMock()),
            patch(
                "confiture.cli.commands.migrate_analysis.open_connection",
                self._make_open_conn_mock(),
            ),
            patch("confiture.core.live_function_catalog.FunctionIntrospector") as MockIntrospector,
        ):
            MockIntrospector.return_value.introspect.return_value = MagicMock(functions=[])

            with patch(
                "confiture.core.function_signature_drift.FunctionSignatureDriftDetector.compare",
                return_value=_empty_report(),
            ):
                result = runner.invoke(
                    app,
                    [
                        "migrate",
                        "validate",
                        "--check-signatures",
                        "--config",
                        str(config),
                        "--schema",
                        str(schema),
                        "--format",
                        "json",
                    ],
                )

        import json

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["check"] == "function_signature_drift"
        assert "has_drift" in data
