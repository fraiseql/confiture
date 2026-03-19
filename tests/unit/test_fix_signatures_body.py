"""Unit tests for fix-signatures --check-body body drift remediation."""

import json
import re
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from confiture.cli.main import app
from confiture.core.function_body_drift import FunctionBodyDrift, FunctionBodyDriftReport
from confiture.core.function_signature_drift import FunctionSignatureDriftReport

runner = CliRunner()

SCHEMA_WITH_FN = (
    "CREATE OR REPLACE FUNCTION public.my_fn(y text) RETURNS text"
    " LANGUAGE sql AS $$ SELECT upper(y); $$;"
)


def _strip_ansi(text: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


def _clean_sig_report() -> FunctionSignatureDriftReport:
    return FunctionSignatureDriftReport(
        stale_overloads=[],
        missing_from_db=[],
        schemas_checked=["public"],
        functions_checked=2,
        has_drift=False,
        detection_time_ms=5.0,
    )


def _clean_body_report() -> FunctionBodyDriftReport:
    return FunctionBodyDriftReport(
        body_drifts=[],
        functions_checked=2,
        has_drift=False,
        detection_time_ms=3.0,
    )


def _drift_body_report() -> FunctionBodyDriftReport:
    return FunctionBodyDriftReport(
        body_drifts=[
            FunctionBodyDrift(
                schema="public",
                name="my_fn",
                signature_key="public.my_fn(text)",
                source_hash="aabbccddeeff",
                db_hash="112233445566",
            )
        ],
        functions_checked=2,
        has_drift=True,
        detection_time_ms=3.0,
    )


def _make_conn_cm(fake_conn: MagicMock | None = None) -> MagicMock:
    """Return a context-manager mock for open_connection."""
    conn = fake_conn or MagicMock()
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=conn)
    cm.__exit__ = MagicMock(return_value=False)
    return MagicMock(return_value=cm)


def _make_cursor_conn() -> tuple[MagicMock, MagicMock]:
    """Return (fake_cursor, fake_conn) with cursor() context-manager wired."""
    fake_cursor = MagicMock()
    fake_cursor.__enter__ = MagicMock(return_value=fake_cursor)
    fake_cursor.__exit__ = MagicMock(return_value=False)
    fake_conn = MagicMock()
    fake_conn.autocommit = True
    fake_conn.cursor.return_value = fake_cursor
    return fake_cursor, fake_conn


# ---------------------------------------------------------------------------
# Phase 01 — Cycle 1: flag exists, no regression
# ---------------------------------------------------------------------------


def test_check_body_flag_exists():
    result = runner.invoke(app, ["migrate", "fix-signatures", "--help"])
    assert "--check-body" in _strip_ansi(result.output)


def test_without_check_body_no_regression(tmp_path):
    """Existing behaviour unchanged when --check-body is absent."""
    config = tmp_path / "confiture.yaml"
    config.write_text("database:\n  url: postgresql://localhost/test\n")
    schema = tmp_path / "schema.sql"
    schema.write_text("-- no functions")

    with (
        patch("confiture.cli.commands.migrate_analysis.load_config", return_value=MagicMock()),
        patch("confiture.cli.commands.migrate_analysis.open_connection", _make_conn_cm()),
        patch("confiture.core.live_function_catalog.FunctionIntrospector") as MockIntr,
        patch(
            "confiture.core.function_signature_drift.FunctionSignatureDriftDetector.compare",
            return_value=_clean_sig_report(),
        ),
    ):
        MockIntr.return_value.introspect.return_value = MagicMock(functions=[])
        result = runner.invoke(
            app,
            ["migrate", "fix-signatures", "--config", str(config), "--schema", str(schema)],
        )
    assert result.exit_code == 0


# ---------------------------------------------------------------------------
# Phase 01 — Cycle 2: body-only path (sig clean, body dirty)
# ---------------------------------------------------------------------------


def test_check_body_body_only_dry_run(tmp_path):
    """Sig clean + body dirty: body CORF shown in dry-run; exits 0."""
    config = tmp_path / "confiture.yaml"
    config.write_text("database:\n  url: postgresql://localhost/test\n")
    schema = tmp_path / "schema.sql"
    schema.write_text(SCHEMA_WITH_FN)

    with (
        patch("confiture.cli.commands.migrate_analysis.load_config", return_value=MagicMock()),
        patch("confiture.cli.commands.migrate_analysis.open_connection", _make_conn_cm()),
        patch("confiture.core.live_function_catalog.FunctionIntrospector") as MockIntr,
        patch(
            "confiture.core.function_signature_drift.FunctionSignatureDriftDetector.compare",
            return_value=_clean_sig_report(),
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
                "fix-signatures",
                "--check-body",
                "--config",
                str(config),
                "--schema",
                str(schema),
            ],
        )

    assert result.exit_code == 0
    output = _strip_ansi(result.output)
    assert "CREATE OR REPLACE" in output
    assert "my_fn" in output


# ---------------------------------------------------------------------------
# Phase 01 — Cycle 3: both checks clean with --check-body
# ---------------------------------------------------------------------------


def test_check_body_both_clean_exits_0(tmp_path):
    config = tmp_path / "confiture.yaml"
    config.write_text("database:\n  url: postgresql://localhost/test\n")
    schema = tmp_path / "schema.sql"
    schema.write_text("-- no functions")

    with (
        patch("confiture.cli.commands.migrate_analysis.load_config", return_value=MagicMock()),
        patch("confiture.cli.commands.migrate_analysis.open_connection", _make_conn_cm()),
        patch("confiture.core.live_function_catalog.FunctionIntrospector") as MockIntr,
        patch(
            "confiture.core.function_signature_drift.FunctionSignatureDriftDetector.compare",
            return_value=_clean_sig_report(),
        ),
        patch(
            "confiture.core.function_body_drift.FunctionBodyDriftDetector.compare",
            return_value=_clean_body_report(),
        ),
    ):
        MockIntr.return_value.introspect.return_value = MagicMock(functions=[])
        result = runner.invoke(
            app,
            [
                "migrate",
                "fix-signatures",
                "--check-body",
                "--config",
                str(config),
                "--schema",
                str(schema),
            ],
        )

    assert result.exit_code == 0
    assert "drift" in _strip_ansi(result.output).lower()


# ---------------------------------------------------------------------------
# Phase 01 — Cycle 4: no fixable overloads + body drift — body still detected
# ---------------------------------------------------------------------------


def test_check_body_no_fixable_overloads_body_still_detected(tmp_path):
    """When all stale overloads have no source, body fixes still run."""
    from confiture.core.function_signature_drift import StaleOverload

    config = tmp_path / "confiture.yaml"
    config.write_text("database:\n  url: postgresql://localhost/test\n")
    schema = tmp_path / "schema.sql"
    schema.write_text(SCHEMA_WITH_FN)

    stale = MagicMock(spec=StaleOverload)
    stale.schema = "public"
    stale.name = "old_fn"
    stale.stale_signature = "public.old_fn(integer)"
    stale.drop_sql = "DROP FUNCTION public.old_fn(integer);"

    sig_report_with_drift = FunctionSignatureDriftReport(
        stale_overloads=[stale],
        missing_from_db=[],
        schemas_checked=["public"],
        functions_checked=2,
        has_drift=True,
        detection_time_ms=5.0,
    )

    with (
        patch("confiture.cli.commands.migrate_analysis.load_config", return_value=MagicMock()),
        patch("confiture.cli.commands.migrate_analysis.open_connection", _make_conn_cm()),
        patch("confiture.core.live_function_catalog.FunctionIntrospector") as MockIntr,
        patch(
            "confiture.core.function_signature_drift.FunctionSignatureDriftDetector.compare",
            return_value=sig_report_with_drift,
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
                "fix-signatures",
                "--check-body",
                "--config",
                str(config),
                "--schema",
                str(schema),
            ],
        )

    assert result.exit_code == 0
    output = _strip_ansi(result.output)
    assert "CREATE OR REPLACE" in output
    assert "my_fn" in output


# ---------------------------------------------------------------------------
# Phase 01 — Cycle 5: dry-run JSON includes body fields
# ---------------------------------------------------------------------------


def test_check_body_dry_run_json(tmp_path):
    config = tmp_path / "confiture.yaml"
    config.write_text("database:\n  url: postgresql://localhost/test\n")
    schema = tmp_path / "schema.sql"
    schema.write_text(SCHEMA_WITH_FN)

    with (
        patch("confiture.cli.commands.migrate_analysis.load_config", return_value=MagicMock()),
        patch("confiture.cli.commands.migrate_analysis.open_connection", _make_conn_cm()),
        patch("confiture.core.live_function_catalog.FunctionIntrospector") as MockIntr,
        patch(
            "confiture.core.function_signature_drift.FunctionSignatureDriftDetector.compare",
            return_value=_clean_sig_report(),
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
                "fix-signatures",
                "--check-body",
                "--format",
                "json",
                "--config",
                str(config),
                "--schema",
                str(schema),
            ],
        )

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["status"] == "dry_run"
    assert data["body_drift_fixes_planned"] == 1
    assert len(data["body_drift_blocks"]) == 1
    block = data["body_drift_blocks"][0]
    assert block["signature_key"] == "public.my_fn(text)"
    assert "CREATE OR REPLACE" in block["create_sql"]
    assert "my_fn" in block["create_sql"]


# ---------------------------------------------------------------------------
# Phase 02 — Cycle 1: --apply executes body CORF in transaction
# ---------------------------------------------------------------------------


def test_apply_executes_body_corf(tmp_path):
    """--apply runs CREATE OR REPLACE for body-drifted functions."""
    config = tmp_path / "confiture.yaml"
    config.write_text("database:\n  url: postgresql://localhost/test\n")
    schema = tmp_path / "schema.sql"
    schema.write_text(SCHEMA_WITH_FN)

    fake_cursor, fake_conn = _make_cursor_conn()

    with (
        patch("confiture.cli.commands.migrate_analysis.load_config", return_value=MagicMock()),
        patch(
            "confiture.cli.commands.migrate_analysis.open_connection",
            _make_conn_cm(fake_conn),
        ),
        patch("confiture.core.live_function_catalog.FunctionIntrospector") as MockIntr,
        patch(
            "confiture.core.function_signature_drift.FunctionSignatureDriftDetector.compare",
            return_value=_clean_sig_report(),
        ),
        patch(
            "confiture.core.function_body_drift.FunctionBodyDriftDetector.compare",
            side_effect=[_drift_body_report(), _clean_body_report()],
        ),
    ):
        MockIntr.return_value.introspect.return_value = MagicMock(functions=[])
        runner.invoke(
            app,
            [
                "migrate",
                "fix-signatures",
                "--check-body",
                "--apply",
                "--config",
                str(config),
                "--schema",
                str(schema),
            ],
        )

    executed_sqls = [call.args[0] for call in fake_cursor.execute.call_args_list]
    assert any("CREATE OR REPLACE" in sql for sql in executed_sqls)
    assert any("my_fn" in sql for sql in executed_sqls)
    fake_conn.commit.assert_called_once()


# ---------------------------------------------------------------------------
# Phase 02 — Cycle 2: rollback on body CORF failure
# ---------------------------------------------------------------------------


def test_apply_body_corf_failure_rolls_back(tmp_path):
    """A failing CORF rolls back all changes atomically."""
    config = tmp_path / "confiture.yaml"
    config.write_text("database:\n  url: postgresql://localhost/test\n")
    schema = tmp_path / "schema.sql"
    schema.write_text(SCHEMA_WITH_FN)

    fake_cursor, fake_conn = _make_cursor_conn()
    fake_cursor.execute.side_effect = Exception("syntax error in body")

    with (
        patch("confiture.cli.commands.migrate_analysis.load_config", return_value=MagicMock()),
        patch(
            "confiture.cli.commands.migrate_analysis.open_connection",
            _make_conn_cm(fake_conn),
        ),
        patch("confiture.core.live_function_catalog.FunctionIntrospector") as MockIntr,
        patch(
            "confiture.core.function_signature_drift.FunctionSignatureDriftDetector.compare",
            return_value=_clean_sig_report(),
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
                "fix-signatures",
                "--check-body",
                "--apply",
                "--config",
                str(config),
                "--schema",
                str(schema),
            ],
        )
        assert result.exit_code == 1

    fake_conn.rollback.assert_called_once()
    fake_conn.commit.assert_not_called()


# ---------------------------------------------------------------------------
# Phase 02 — Cycle 3: body-only path (fix_blocks empty)
# ---------------------------------------------------------------------------


def test_apply_body_only_no_sig_fixes(tmp_path):
    """Body-only path: fix_blocks is empty, only body CORFs execute."""
    config = tmp_path / "confiture.yaml"
    config.write_text("database:\n  url: postgresql://localhost/test\n")
    schema = tmp_path / "schema.sql"
    schema.write_text(SCHEMA_WITH_FN)

    fake_cursor, fake_conn = _make_cursor_conn()

    with (
        patch("confiture.cli.commands.migrate_analysis.load_config", return_value=MagicMock()),
        patch(
            "confiture.cli.commands.migrate_analysis.open_connection",
            _make_conn_cm(fake_conn),
        ),
        patch("confiture.core.live_function_catalog.FunctionIntrospector") as MockIntr,
        patch(
            "confiture.core.function_signature_drift.FunctionSignatureDriftDetector.compare",
            return_value=_clean_sig_report(),
        ),
        patch(
            "confiture.core.function_body_drift.FunctionBodyDriftDetector.compare",
            side_effect=[_drift_body_report(), _clean_body_report()],
        ),
    ):
        MockIntr.return_value.introspect.return_value = MagicMock(functions=[])
        runner.invoke(
            app,
            [
                "migrate",
                "fix-signatures",
                "--check-body",
                "--apply",
                "--config",
                str(config),
                "--schema",
                str(schema),
            ],
        )

    executed_sqls = [call.args[0] for call in fake_cursor.execute.call_args_list]
    assert any("CREATE OR REPLACE" in sql for sql in executed_sqls)
    assert not any("DROP" in sql for sql in executed_sqls)
    fake_conn.commit.assert_called_once()


# ---------------------------------------------------------------------------
# Phase 03 — Cycle 1: post-apply text output lists body fixes applied
# ---------------------------------------------------------------------------


def test_apply_text_output_lists_body_fixes(tmp_path):
    config = tmp_path / "confiture.yaml"
    config.write_text("database:\n  url: postgresql://localhost/test\n")
    schema = tmp_path / "schema.sql"
    schema.write_text(SCHEMA_WITH_FN)

    fake_cursor, fake_conn = _make_cursor_conn()

    with (
        patch("confiture.cli.commands.migrate_analysis.load_config", return_value=MagicMock()),
        patch(
            "confiture.cli.commands.migrate_analysis.open_connection",
            _make_conn_cm(fake_conn),
        ),
        patch("confiture.core.live_function_catalog.FunctionIntrospector") as MockIntr,
        patch(
            "confiture.core.function_signature_drift.FunctionSignatureDriftDetector.compare",
            return_value=_clean_sig_report(),
        ),
        patch(
            "confiture.core.function_body_drift.FunctionBodyDriftDetector.compare",
            # first call: initial detection (drift); second call: re-check (clean)
            side_effect=[_drift_body_report(), _clean_body_report()],
        ),
    ):
        MockIntr.return_value.introspect.return_value = MagicMock(functions=[])
        result = runner.invoke(
            app,
            [
                "migrate",
                "fix-signatures",
                "--check-body",
                "--apply",
                "--config",
                str(config),
                "--schema",
                str(schema),
            ],
        )

    assert result.exit_code == 0
    output = _strip_ansi(result.output)
    assert "my_fn" in output
    assert "body" in output.lower()
    assert "zero drift" in output.lower()


# ---------------------------------------------------------------------------
# Phase 03 — Cycle 2: post-apply JSON includes body drift fields
# ---------------------------------------------------------------------------


def test_apply_json_includes_body_fields(tmp_path):
    config = tmp_path / "confiture.yaml"
    config.write_text("database:\n  url: postgresql://localhost/test\n")
    schema = tmp_path / "schema.sql"
    schema.write_text(SCHEMA_WITH_FN)

    fake_cursor, fake_conn = _make_cursor_conn()

    with (
        patch("confiture.cli.commands.migrate_analysis.load_config", return_value=MagicMock()),
        patch(
            "confiture.cli.commands.migrate_analysis.open_connection",
            _make_conn_cm(fake_conn),
        ),
        patch("confiture.core.live_function_catalog.FunctionIntrospector") as MockIntr,
        patch(
            "confiture.core.function_signature_drift.FunctionSignatureDriftDetector.compare",
            return_value=_clean_sig_report(),
        ),
        patch(
            "confiture.core.function_body_drift.FunctionBodyDriftDetector.compare",
            side_effect=[_drift_body_report(), _clean_body_report()],
        ),
    ):
        MockIntr.return_value.introspect.return_value = MagicMock(functions=[])
        result = runner.invoke(
            app,
            [
                "migrate",
                "fix-signatures",
                "--check-body",
                "--apply",
                "--format",
                "json",
                "--config",
                str(config),
                "--schema",
                str(schema),
            ],
        )

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["status"] == "applied"
    assert data["body_drift_fixes_applied"] == 1
    assert "public.my_fn(text)" in data["body_drift_applied"]
    assert data["remaining_body_drift"] is False


# ---------------------------------------------------------------------------
# Phase 03 — Cycle 3: residual body drift after apply → exit 1
# ---------------------------------------------------------------------------


def test_apply_residual_body_drift_exits_1(tmp_path):
    """Body drift persists after apply → exit 1."""
    config = tmp_path / "confiture.yaml"
    config.write_text("database:\n  url: postgresql://localhost/test\n")
    schema = tmp_path / "schema.sql"
    schema.write_text(SCHEMA_WITH_FN)

    fake_cursor, fake_conn = _make_cursor_conn()

    with (
        patch("confiture.cli.commands.migrate_analysis.load_config", return_value=MagicMock()),
        patch(
            "confiture.cli.commands.migrate_analysis.open_connection",
            _make_conn_cm(fake_conn),
        ),
        patch("confiture.core.live_function_catalog.FunctionIntrospector") as MockIntr,
        patch(
            "confiture.core.function_signature_drift.FunctionSignatureDriftDetector.compare",
            return_value=_clean_sig_report(),
        ),
        patch(
            "confiture.core.function_body_drift.FunctionBodyDriftDetector.compare",
            # both calls return drift: still drifted after apply
            side_effect=[_drift_body_report(), _drift_body_report()],
        ),
    ):
        MockIntr.return_value.introspect.return_value = MagicMock(functions=[])
        result = runner.invoke(
            app,
            [
                "migrate",
                "fix-signatures",
                "--check-body",
                "--apply",
                "--config",
                str(config),
                "--schema",
                str(schema),
            ],
        )
        assert result.exit_code == 1


# ---------------------------------------------------------------------------
# Phase 03 — Cycle 4: no body fields in JSON without --check-body
# ---------------------------------------------------------------------------


def test_apply_json_no_body_fields_without_flag(tmp_path):
    """Without --check-body, JSON output has no body_drift_* keys."""
    from confiture.core.function_signature_drift import StaleOverload

    config = tmp_path / "confiture.yaml"
    config.write_text("database:\n  url: postgresql://localhost/test\n")
    schema = tmp_path / "schema.sql"
    schema.write_text(SCHEMA_WITH_FN)

    stale = MagicMock(spec=StaleOverload)
    stale.schema = "public"
    stale.name = "my_fn"
    stale.stale_signature = "public.my_fn(integer)"
    stale.drop_sql = "DROP FUNCTION public.my_fn(integer);"

    sig_drift = FunctionSignatureDriftReport(
        stale_overloads=[stale],
        missing_from_db=[],
        schemas_checked=["public"],
        functions_checked=1,
        has_drift=True,
        detection_time_ms=5.0,
    )
    sig_clean = _clean_sig_report()

    fake_cursor, fake_conn = _make_cursor_conn()

    with (
        patch("confiture.cli.commands.migrate_analysis.load_config", return_value=MagicMock()),
        patch(
            "confiture.cli.commands.migrate_analysis.open_connection",
            _make_conn_cm(fake_conn),
        ),
        patch("confiture.core.live_function_catalog.FunctionIntrospector") as MockIntr,
        patch(
            "confiture.core.function_signature_drift.FunctionSignatureDriftDetector.compare",
            side_effect=[sig_drift, sig_clean],
        ),
    ):
        MockIntr.return_value.introspect.return_value = MagicMock(functions=[])
        result = runner.invoke(
            app,
            [
                "migrate",
                "fix-signatures",
                "--apply",
                "--format",
                "json",
                "--config",
                str(config),
                "--schema",
                str(schema),
            ],
        )

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert "body_drift_fixes_applied" not in data
    assert "remaining_body_drift" not in data
