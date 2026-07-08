"""CLI tests for `migrate validate --check-body-replay` (#179).

The DB-backed detector is covered in tests/integration/test_replay_drift.py;
here we patch ``check_replay_drift`` to exercise the CLI wiring: exit codes,
JSON shape, --show-diff gate, and the broken-migration error path.
"""

import json
import re
from unittest.mock import patch

from typer.testing import CliRunner

from confiture.cli.main import app
from confiture.core.function_body_drift import FunctionBodyDrift, FunctionBodyDriftReport
from confiture.core.validation.replay_drift import ReplayDriftResult
from confiture.exceptions import SchemaError

runner = CliRunner()


def _strip_ansi(text: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


def _clean() -> ReplayDriftResult:
    return ReplayDriftResult(
        body_report=FunctionBodyDriftReport(
            body_drifts=[], functions_checked=7, has_drift=False, detection_time_ms=6.0
        ),
        ssh_target=None,
    )


def _drift() -> ReplayDriftResult:
    return ReplayDriftResult(
        body_report=FunctionBodyDriftReport(
            body_drifts=[
                FunctionBodyDrift(
                    schema="public",
                    name="total",
                    signature_key="public.total()",
                    source_hash="1111aaaa2222",
                    db_hash="3333bbbb4444",
                    expected_body="SELECT sum(price) FROM widgets;",
                    live_body="SELECT sum(price) * 1.2 FROM widgets;",
                    unified_diff=(
                        "--- public.total() (expected)\n"
                        "+++ public.total() (live)\n"
                        "@@ -1 +1 @@\n"
                        "-select sum(price) from widgets;\n"
                        "+select sum(price) * 1.2 from widgets;"
                    ),
                )
            ],
            functions_checked=7,
            has_drift=True,
            detection_time_ms=11.0,
        ),
        ssh_target=None,
    )


def _invoke(tmp_path, result_or_exc, extra_args):
    config = tmp_path / "confiture.yaml"
    config.write_text("name: x\ndatabase_url: postgresql://localhost/test\n")
    kwargs = (
        {"side_effect": result_or_exc}
        if isinstance(result_or_exc, BaseException)
        else {"return_value": result_or_exc}
    )
    with patch("confiture.core.validation.replay_drift.check_replay_drift", **kwargs):
        return runner.invoke(
            app,
            [
                "migrate",
                "validate",
                "--check-body-replay",
                *extra_args,
                "--config",
                str(config),
            ],
        )


def test_clean_exits_0(tmp_path):
    result = _invoke(tmp_path, _clean(), [])
    assert result.exit_code == 0
    assert "hot-patch" in _strip_ansi(result.output).lower()


def test_drift_exits_1(tmp_path):
    result = _invoke(tmp_path, _drift(), [])
    assert result.exit_code == 1
    out = _strip_ansi(result.output)
    assert "public.total()" in out
    assert "1111aaaa2222" in out


def test_json_hash_only_by_default(tmp_path):
    result = _invoke(tmp_path, _drift(), ["--format", "json"])
    assert result.exit_code == 1
    data = json.loads(result.output)
    assert data["check"] == "replay_body_drift"
    assert data["has_drift"] is True
    entry = data["body_drifts"][0]
    assert set(entry) == {"schema", "name", "signature_key", "source_hash", "db_hash"}
    assert "expected_body" not in entry


def test_json_show_diff_includes_bodies(tmp_path):
    result = _invoke(tmp_path, _drift(), ["--show-diff", "--format", "json"])
    assert result.exit_code == 1
    entry = json.loads(result.output)["body_drifts"][0]
    assert entry["expected_body"].startswith("SELECT sum(price)")
    assert "* 1.2" in entry["live_body"]
    assert "+select sum(price) * 1.2 from widgets;" in entry["unified_diff"]


def test_broken_migration_surfaces_error_not_drift(tmp_path):
    """A SchemaError from a broken replay routes through fail() (not false drift)."""
    exc = SchemaError("Migration replay into the scratch database failed: [...]")
    result = _invoke(tmp_path, exc, ["--format", "json"])
    assert result.exit_code != 0
    data = json.loads(result.output)
    assert data["ok"] is False
    assert "replay" in data["error"]["message"].lower()
