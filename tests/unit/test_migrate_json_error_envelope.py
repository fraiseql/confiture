"""Issue #145 Phase 2: migrate-family --format json failure paths emit the envelope.

Per .phases/.../test-conventions.md, these assert stdout *parses* as the
envelope (CliRunner cannot reliably separate stdout/stderr); the boundary's
stream separation is covered by test_cli_fail_boundary.py with capsys.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import psycopg
import yaml
from typer.testing import CliRunner

from confiture.cli.main import app

runner = CliRunner()

_UNREACHABLE = "postgresql://localhost:1/nope"


def _dupe_migrations(tmp_path: Path) -> Path:
    d = tmp_path / "migrations"
    d.mkdir()
    # Two files sharing version 20260101000001 → MIGR_106.
    for name in ("20260101000001_a", "20260101000001_b"):
        (d / f"{name}.up.sql").write_text("SELECT 1;")
        (d / f"{name}.down.sql").write_text("SELECT 1;")
    return d


def test_up_duplicate_version_json_envelope(tmp_path: Path) -> None:
    migrations_dir = _dupe_migrations(tmp_path)
    result = runner.invoke(
        app,
        [
            "migrate",
            "up",
            "--database-url",
            _UNREACHABLE,
            "--migrations-dir",
            str(migrations_dir),
            "--format",
            "json",
        ],
    )
    assert result.exit_code == 3, result.output
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "MIGR_106"
    assert payload["error"]["details"]["conflicting_files"]  # populated


def test_up_connection_refused_json_envelope(tmp_path: Path) -> None:
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    with patch(
        "confiture.core.connection.psycopg.connect",
        side_effect=psycopg.OperationalError("connection refused"),
    ):
        result = runner.invoke(
            app,
            [
                "migrate",
                "up",
                "--database-url",
                _UNREACHABLE,
                "--migrations-dir",
                str(migrations_dir),
                "--format",
                "json",
            ],
        )
    assert result.exit_code == 3, result.output
    payload = json.loads(result.stdout)
    assert payload["error"]["code"] == "CONFIG_006"


def test_up_broken_yaml_json_envelope(tmp_path: Path) -> None:
    cfg = tmp_path / "broken.yaml"
    cfg.write_text("database_url: [unterminated\n  : :")
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    result = runner.invoke(
        app,
        [
            "migrate",
            "up",
            "--config",
            str(cfg),
            "--migrations-dir",
            str(migrations_dir),
            "--format",
            "json",
        ],
    )
    assert result.exit_code == 5, result.output
    payload = json.loads(result.stdout)
    assert payload["error"]["code"] == "CONFIG_002"


def test_down_connection_refused_json_envelope(tmp_path: Path) -> None:
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    with patch(
        "confiture.core.connection.psycopg.connect",
        side_effect=psycopg.OperationalError("connection refused"),
    ):
        result = runner.invoke(
            app,
            [
                "migrate",
                "down",
                "--database-url",
                _UNREACHABLE,
                "--migrations-dir",
                str(migrations_dir),
                "--format",
                "json",
            ],
        )
    assert result.exit_code == 3, result.output
    payload = json.loads(result.stdout)
    assert payload["error"]["code"] == "CONFIG_006"


def test_up_text_mode_does_not_emit_json_envelope(tmp_path: Path) -> None:
    """Human (text) mode is unchanged — no JSON envelope on stdout."""
    cfg = tmp_path / "broken.yaml"
    cfg.write_text("database_url: [unterminated\n  : :")
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    result = runner.invoke(
        app,
        [
            "migrate",
            "up",
            "--config",
            str(cfg),
            "--migrations-dir",
            str(migrations_dir),
            "--format",
            "text",
        ],
    )
    assert result.exit_code == 5, result.output
    assert not result.stdout.strip().startswith("{")  # not the JSON envelope


def test_up_unreachable_json_envelope_has_all_inner_keys(tmp_path: Path) -> None:
    """The inner error object carries every required key (nullable)."""
    cfg = tmp_path / "ok.yaml"
    cfg.write_text(yaml.safe_dump({"name": "t", "database_url": _UNREACHABLE}))
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    with patch(
        "confiture.core.connection.psycopg.connect",
        side_effect=psycopg.OperationalError("refused"),
    ):
        result = runner.invoke(
            app,
            [
                "migrate",
                "up",
                "--config",
                str(cfg),
                "--migrations-dir",
                str(migrations_dir),
                "--format",
                "json",
            ],
        )
    inner = json.loads(result.stdout)["error"]
    for key in (
        "severity",
        "code",
        "message",
        "actionable",
        "details",
        "migration",
        "file",
        "line",
    ):
        assert key in inner
