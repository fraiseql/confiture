"""CLI tests for the structured preflight report (issue #148, Phase 2).

The no-``--against`` static path needs no database; these run as unit tests.
"""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from confiture.cli.main import app

runner = CliRunner()


def _mig(d: Path, version: str, name: str, *, down: bool = True, body: str = "SELECT 1;") -> None:
    (d / f"{version}_{name}.up.sql").write_text(body)
    if down:
        (d / f"{version}_{name}.down.sql").write_text("SELECT 1;")


def test_preflight_json_shape(tmp_path: Path) -> None:
    _mig(tmp_path, "20260531000001", "add_user_bio", down=False)
    r = runner.invoke(
        app, ["migrate", "preflight", "--migrations-dir", str(tmp_path), "--format", "json"]
    )
    assert r.exit_code == 7, r.output
    p = json.loads(r.stdout)
    assert p["ok"] is False
    assert p["summary"]["errors"] == 1
    assert any(
        i["code"] == "PFLIGHT_MISSING_DOWN" and i["severity"] == "error" for i in p["issues"]
    )
    assert all({"severity", "code", "message"} <= set(i) for i in p["issues"])


def test_preflight_clean_exit_0(tmp_path: Path) -> None:
    _mig(tmp_path, "20260531000001", "a")
    r = runner.invoke(
        app, ["migrate", "preflight", "--migrations-dir", str(tmp_path), "--format", "json"]
    )
    assert r.exit_code == 0, r.output
    assert json.loads(r.stdout)["ok"] is True


def test_warnings_only_exit_0_by_default(tmp_path: Path) -> None:
    _mig(tmp_path, "20260531000002", "idx", body="CREATE INDEX CONCURRENTLY i ON t (c);")
    r = runner.invoke(
        app, ["migrate", "preflight", "--migrations-dir", str(tmp_path), "--format", "json"]
    )
    assert r.exit_code == 0, r.output
    assert json.loads(r.stdout)["summary"]["warnings"] >= 1


def test_strict_promotes_warnings(tmp_path: Path) -> None:
    _mig(tmp_path, "20260531000002", "idx", body="CREATE INDEX CONCURRENTLY i ON t (c);")
    r = runner.invoke(
        app,
        ["migrate", "preflight", "--migrations-dir", str(tmp_path), "--strict", "--format", "json"],
    )
    assert r.exit_code == 7, r.output


def test_table_mode_renders_codes(tmp_path: Path) -> None:
    _mig(tmp_path, "20260531000001", "add_user_bio", down=False)
    r = runner.invoke(app, ["migrate", "preflight", "--migrations-dir", str(tmp_path)])
    assert r.exit_code == 7, r.output
    assert "PFLIGHT_MISSING_DOWN" in r.output


def test_duplicate_version_is_error(tmp_path: Path) -> None:
    # Two files share version 20260531000001.
    (tmp_path / "20260531000001_a.up.sql").write_text("SELECT 1;")
    (tmp_path / "20260531000001_a.down.sql").write_text("SELECT 1;")
    (tmp_path / "20260531000001_b.up.sql").write_text("SELECT 1;")
    (tmp_path / "20260531000001_b.down.sql").write_text("SELECT 1;")
    r = runner.invoke(
        app, ["migrate", "preflight", "--migrations-dir", str(tmp_path), "--format", "json"]
    )
    assert r.exit_code == 7, r.output
    p = json.loads(r.stdout)
    assert any(i["code"] == "PFLIGHT_DUPLICATE_VERSION" for i in p["issues"])
