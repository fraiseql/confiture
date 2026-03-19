"""Unit tests for migrate validate --check-signatures and --check-body CLI flags."""

import re
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from confiture.cli.main import app
from confiture.core.function_body_drift import FunctionBodyDrift, FunctionBodyDriftReport
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


def _empty_body_report() -> FunctionBodyDriftReport:
    return FunctionBodyDriftReport(
        body_drifts=[],
        functions_checked=3,
        has_drift=False,
        detection_time_ms=5.0,
    )


def _drift_body_report() -> FunctionBodyDriftReport:
    return FunctionBodyDriftReport(
        body_drifts=[
            FunctionBodyDrift(
                schema="public",
                name="my_function",
                signature_key="public.my_function(uuid,bigint)",
                source_hash="a3f8c1d2e4f9",
                db_hash="7b2e09f1c3a8",
            )
        ],
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


class TestCheckBodyFlag:
    """Tests for --check-body flag on migrate validate."""

    def _make_open_conn_mock(self) -> MagicMock:
        fake_conn = MagicMock()
        cm = MagicMock()
        cm.__enter__ = MagicMock(return_value=fake_conn)
        cm.__exit__ = MagicMock(return_value=False)
        return MagicMock(return_value=cm)

    # ------------------------------------------------------------------
    # Cycle 1: Guard — --check-body requires --check-signatures
    # ------------------------------------------------------------------

    def test_check_body_without_check_signatures_exits_2(self, tmp_path):
        config = tmp_path / "confiture.yaml"
        config.write_text("database:\n  url: postgresql://localhost/test\n")
        result = runner.invoke(
            app,
            ["migrate", "validate", "--check-body", "--config", str(config)],
        )
        # Guard triggers before any DB access; message goes to stderr (error_console)
        assert result.exit_code == 2

    # ------------------------------------------------------------------
    # Cycle 2 & 3: Clean run and drift detection
    # ------------------------------------------------------------------

    def test_check_body_clean_run_exits_0(self, tmp_path):
        config = tmp_path / "confiture.yaml"
        config.write_text("database:\n  url: postgresql://localhost/test\n")
        schema = tmp_path / "schema.sql"
        schema.write_text("-- no functions")

        with (
            patch(
                "confiture.cli.commands.migrate_analysis.load_config",
                return_value=MagicMock(),
            ),
            patch(
                "confiture.cli.commands.migrate_analysis.open_connection",
                self._make_open_conn_mock(),
            ),
            patch("confiture.core.live_function_catalog.FunctionIntrospector") as MockIntr,
            patch(
                "confiture.core.function_signature_drift.FunctionSignatureDriftDetector.compare",
                return_value=_empty_report(),
            ),
            patch(
                "confiture.core.function_body_drift.FunctionBodyDriftDetector.compare",
                return_value=_empty_body_report(),
            ),
        ):
            MockIntr.return_value.introspect.return_value = MagicMock(functions=[])
            result = runner.invoke(
                app,
                [
                    "migrate",
                    "validate",
                    "--check-signatures",
                    "--check-body",
                    "--config",
                    str(config),
                    "--schema",
                    str(schema),
                ],
            )

        assert result.exit_code == 0
        assert "body drift" in _strip_ansi(result.output).lower()

    def test_check_body_drift_detected_exits_1(self, tmp_path):
        config = tmp_path / "confiture.yaml"
        config.write_text("database:\n  url: postgresql://localhost/test\n")
        schema = tmp_path / "schema.sql"
        schema.write_text("-- no functions")

        with (
            patch(
                "confiture.cli.commands.migrate_analysis.load_config",
                return_value=MagicMock(),
            ),
            patch(
                "confiture.cli.commands.migrate_analysis.open_connection",
                self._make_open_conn_mock(),
            ),
            patch("confiture.core.live_function_catalog.FunctionIntrospector") as MockIntr,
            patch(
                "confiture.core.function_signature_drift.FunctionSignatureDriftDetector.compare",
                return_value=_empty_report(),
            ),
            patch(
                "confiture.core.function_body_drift.FunctionBodyDriftDetector.compare",
                return_value=_drift_body_report(),
            ),
        ):
            MockIntr.return_value.introspect.return_value = MagicMock(functions=[])
            result = runner.invoke(
                app,
                [
                    "migrate",
                    "validate",
                    "--check-signatures",
                    "--check-body",
                    "--config",
                    str(config),
                    "--schema",
                    str(schema),
                ],
            )

        assert result.exit_code == 1
        output = _strip_ansi(result.output)
        assert "my_function" in output
        assert "a3f8c1d2e4f9" in output
        assert "7b2e09f1c3a8" in output

    # ------------------------------------------------------------------
    # Cycle 4: JSON output includes body_drift key
    # ------------------------------------------------------------------

    def test_check_body_json_output_includes_body_drift(self, tmp_path):
        import json

        config = tmp_path / "confiture.yaml"
        config.write_text("database:\n  url: postgresql://localhost/test\n")
        schema = tmp_path / "schema.sql"
        schema.write_text("-- no functions")

        with (
            patch(
                "confiture.cli.commands.migrate_analysis.load_config",
                return_value=MagicMock(),
            ),
            patch(
                "confiture.cli.commands.migrate_analysis.open_connection",
                self._make_open_conn_mock(),
            ),
            patch("confiture.core.live_function_catalog.FunctionIntrospector") as MockIntr,
            patch(
                "confiture.core.function_signature_drift.FunctionSignatureDriftDetector.compare",
                return_value=_empty_report(),
            ),
            patch(
                "confiture.core.function_body_drift.FunctionBodyDriftDetector.compare",
                return_value=_drift_body_report(),
            ),
        ):
            MockIntr.return_value.introspect.return_value = MagicMock(functions=[])
            result = runner.invoke(
                app,
                [
                    "migrate",
                    "validate",
                    "--check-signatures",
                    "--check-body",
                    "--format",
                    "json",
                    "--config",
                    str(config),
                    "--schema",
                    str(schema),
                ],
            )

        assert result.exit_code == 1
        data = json.loads(result.output)
        assert "body_drift" in data
        assert data["body_drift"]["has_drift"] is True
        assert len(data["body_drift"]["body_drifts"]) == 1
        drift_entry = data["body_drift"]["body_drifts"][0]
        assert drift_entry["signature_key"] == "public.my_function(uuid,bigint)"
        assert drift_entry["source_hash"] == "a3f8c1d2e4f9"
        assert drift_entry["db_hash"] == "7b2e09f1c3a8"

    # ------------------------------------------------------------------
    # Cycle 5: Exit code matrix
    # ------------------------------------------------------------------

    @pytest.mark.parametrize(
        "sig_has_drift,body_has_drift,expected_exit",
        [
            (False, False, 0),
            (True, False, 1),
            (False, True, 1),
            (True, True, 1),
        ],
    )
    def test_check_body_exit_codes(
        self, tmp_path, sig_has_drift: bool, body_has_drift: bool, expected_exit: int
    ):
        config = tmp_path / "confiture.yaml"
        config.write_text("database:\n  url: postgresql://localhost/test\n")
        schema = tmp_path / "schema.sql"
        schema.write_text("-- no functions")

        sig_report = _drift_report() if sig_has_drift else _empty_report()
        body_rpt = _drift_body_report() if body_has_drift else _empty_body_report()

        with (
            patch(
                "confiture.cli.commands.migrate_analysis.load_config",
                return_value=MagicMock(),
            ),
            patch(
                "confiture.cli.commands.migrate_analysis.open_connection",
                self._make_open_conn_mock(),
            ),
            patch("confiture.core.live_function_catalog.FunctionIntrospector") as MockIntr,
            patch(
                "confiture.core.function_signature_drift.FunctionSignatureDriftDetector.compare",
                return_value=sig_report,
            ),
            patch(
                "confiture.core.function_body_drift.FunctionBodyDriftDetector.compare",
                return_value=body_rpt,
            ),
        ):
            MockIntr.return_value.introspect.return_value = MagicMock(functions=[])
            result = runner.invoke(
                app,
                [
                    "migrate",
                    "validate",
                    "--check-signatures",
                    "--check-body",
                    "--config",
                    str(config),
                    "--schema",
                    str(schema),
                ],
            )

        assert result.exit_code == expected_exit
