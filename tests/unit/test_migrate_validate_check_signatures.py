"""Unit tests for migrate validate --check-signatures CLI flag."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from confiture.cli.main import app
from confiture.core.function_signature_drift import FunctionSignatureDriftReport
from confiture.core.function_signature_parser import FunctionSignature


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
        assert "--check-signatures" in result.output

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

    def test_check_signatures_exits_0_on_clean(self, tmp_path):
        config = tmp_path / "confiture.yaml"
        config.write_text("database:\n  url: postgresql://localhost/test\n")
        schema = tmp_path / "schema.sql"
        schema.write_text("-- no functions")

        with (
            patch("confiture.cli.commands.migrate_analysis.load_config", return_value=MagicMock()),
            patch("confiture.cli.commands.migrate_analysis.create_connection") as mock_conn,
            patch(
                "confiture.core.live_function_catalog.FunctionIntrospector"
            ) as MockIntrospector,
        ):
            mock_conn.return_value.__enter__ = MagicMock()
            mock_conn.return_value.close = MagicMock()
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
            patch("confiture.cli.commands.migrate_analysis.create_connection") as mock_conn,
            patch(
                "confiture.core.live_function_catalog.FunctionIntrospector"
            ) as MockIntrospector,
        ):
            mock_conn.return_value.__enter__ = MagicMock()
            mock_conn.return_value.close = MagicMock()
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
            patch("confiture.cli.commands.migrate_analysis.create_connection") as mock_conn,
            patch(
                "confiture.core.live_function_catalog.FunctionIntrospector"
            ) as MockIntrospector,
        ):
            mock_conn.return_value.__enter__ = MagicMock()
            mock_conn.return_value.close = MagicMock()
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
