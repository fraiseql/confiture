"""CLI tests for `migrate validate --check-body-views` (#174).

The DB-backed detector is covered in tests/integration/test_view_body_drift_db.py;
here we patch ``check_view_drift`` to exercise the CLI wiring: exit codes, JSON
shape, and the --show-diff gate on definition output.
"""

import json
import re
from unittest.mock import patch

from typer.testing import CliRunner

from confiture.cli.main import app
from confiture.core.validation.view_drift import ViewDriftResult
from confiture.core.view_body_drift import ViewBodyDrift, ViewBodyDriftReport

runner = CliRunner()


def _strip_ansi(text: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


def _clean_result() -> ViewDriftResult:
    return ViewDriftResult(
        view_report=ViewBodyDriftReport(
            body_drifts=[], views_checked=3, has_drift=False, detection_time_ms=4.0
        ),
        auto_built=False,
        ssh_target=None,
    )


def _drift_result() -> ViewDriftResult:
    return ViewDriftResult(
        view_report=ViewBodyDriftReport(
            body_drifts=[
                ViewBodyDrift(
                    schema="public",
                    name="v_etl_unused_meters",
                    relkind="v",
                    source_hash="aaaa1111bbbb",
                    db_hash="cccc2222dddd",
                    expected_def="SELECT id\nFROM meters\nWHERE meter_at > max_volume_date;",
                    live_def="SELECT id\nFROM meters\nWHERE meter_at > (max_volume_date + 1);",
                    unified_diff=(
                        "--- public.v_etl_unused_meters (expected)\n"
                        "+++ public.v_etl_unused_meters (live)\n"
                        "@@ -1,3 +1,3 @@\n"
                        " SELECT id\n"
                        " FROM meters\n"
                        "-WHERE meter_at > max_volume_date;\n"
                        "+WHERE meter_at > (max_volume_date + 1);"
                    ),
                )
            ],
            views_checked=1,
            has_drift=True,
            detection_time_ms=12.0,
        ),
        auto_built=False,
        ssh_target=None,
    )


def _invoke(tmp_path, result, extra_args):
    config = tmp_path / "confiture.yaml"
    config.write_text("database:\n  url: postgresql://localhost/test\n")
    schema = tmp_path / "schema.sql"
    schema.write_text("-- views")
    with patch(
        "confiture.core.validation.view_drift.check_view_drift",
        return_value=result,
    ):
        return runner.invoke(
            app,
            [
                "migrate",
                "validate",
                "--check-body-views",
                *extra_args,
                "--config",
                str(config),
                "--schema",
                str(schema),
            ],
        )


def test_clean_exits_0(tmp_path):
    result = _invoke(tmp_path, _clean_result(), [])
    assert result.exit_code == 0
    assert "view definition drift" in _strip_ansi(result.output).lower()


def test_drift_exits_1(tmp_path):
    result = _invoke(tmp_path, _drift_result(), [])
    assert result.exit_code == 1
    out = _strip_ansi(result.output)
    assert "v_etl_unused_meters" in out
    assert "aaaa1111bbbb" in out


def test_json_hash_only_by_default(tmp_path):
    result = _invoke(tmp_path, _drift_result(), ["--format", "json"])
    assert result.exit_code == 1
    data = json.loads(result.output)
    assert data["check"] == "view_body_drift"
    assert data["has_drift"] is True
    entry = data["body_drifts"][0]
    assert set(entry) == {"schema", "name", "relkind", "source_hash", "db_hash"}
    assert "expected_def" not in entry


def test_json_show_diff_includes_defs(tmp_path):
    result = _invoke(tmp_path, _drift_result(), ["--show-diff", "--format", "json"])
    assert result.exit_code == 1
    data = json.loads(result.output)
    entry = data["body_drifts"][0]
    assert entry["expected_def"].startswith("SELECT id")
    assert "max_volume_date + 1" in entry["live_def"]
    assert "+WHERE meter_at > (max_volume_date + 1);" in entry["unified_diff"]


def test_text_show_diff_prints_diff(tmp_path):
    result = _invoke(tmp_path, _drift_result(), ["--show-diff"])
    assert result.exit_code == 1
    out = _strip_ansi(result.output)
    assert "-WHERE meter_at > max_volume_date;" in out
    assert "+WHERE meter_at > (max_volume_date + 1);" in out
