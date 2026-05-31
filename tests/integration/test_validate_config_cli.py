"""CLI tests for `confiture validate-config` (issue #144, Phase 2).

Offline — no database. Run as integration only because they exercise the full
CLI; none of them connect.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from confiture.cli.main import app

runner = CliRunner()


def _project(tmp_path: Path, *, n_migrations=3, database_url="postgresql://localhost/app") -> Path:
    (tmp_path / "db" / "schema").mkdir(parents=True)
    migs = tmp_path / "db" / "migrations"
    migs.mkdir(parents=True)
    for i in range(n_migrations):
        v = f"2026010100000{i}"
        (migs / f"{v}_m{i}.up.sql").write_text("SELECT 1;")
        (migs / f"{v}_m{i}.down.sql").write_text("SELECT 1;")
    cfg = tmp_path / "env.yaml"
    cfg.write_text(
        yaml.safe_dump(
            {"name": "test", "database_url": database_url, "include_dirs": ["db/schema"]}
        )
    )
    return cfg


def test_valid_config_exit_0(tmp_path: Path) -> None:
    cfg = _project(tmp_path)
    r = runner.invoke(
        app,
        ["validate-config", "-c", str(cfg), "--migrations-path", str(tmp_path / "db" / "migrations")],
    )
    assert r.exit_code == 0, r.output


def test_invalid_config_exit_5(tmp_path: Path) -> None:
    cfg = tmp_path / "env.yaml"
    cfg.write_text(yaml.safe_dump({"name": "test", "include_dirs": ["db/schema"]}))  # no database_url
    (tmp_path / "db" / "schema").mkdir(parents=True)
    r = runner.invoke(
        app, ["validate-config", "-c", str(cfg), "--migrations-path", str(tmp_path / "none")]
    )
    assert r.exit_code == 5, r.output
    assert "CONFIG_001" in r.output


def test_json_output_shape(tmp_path: Path) -> None:
    cfg = _project(tmp_path)
    r = runner.invoke(
        app,
        ["validate-config", "-c", str(cfg), "--migrations-path",
         str(tmp_path / "db" / "migrations"), "--format", "json"],
    )
    assert r.exit_code == 0, r.output
    p = json.loads(r.stdout)
    assert p["valid"] is True
    assert p["config_source"] == "yaml-file"
    assert p["migration_count"] == 3
    assert p["issues"] == []
    assert set(p.keys()) == {"valid", "config_source", "migrations_path", "migration_count", "issues"}


def test_flags_source_without_yaml(tmp_path: Path) -> None:
    migs = tmp_path / "migrations"
    migs.mkdir()
    r = runner.invoke(
        app,
        ["validate-config", "--database-url", "postgresql://x/y",
         "--migrations-path", str(migs), "--format", "json"],
    )
    assert r.exit_code == 0, r.output
    assert json.loads(r.stdout)["config_source"] == "flags"


def test_flags_bad_dsn_exit_5(tmp_path: Path) -> None:
    migs = tmp_path / "migrations"
    migs.mkdir()
    r = runner.invoke(
        app,
        ["validate-config", "--database-url", "not-a-dsn",
         "--migrations-path", str(migs), "--format", "json"],
    )
    assert r.exit_code == 5, r.output
    assert any(i["code"] == "CONFIG_003" for i in json.loads(r.stdout)["issues"])


def test_never_connects(tmp_path: Path, monkeypatch) -> None:
    cfg = _project(tmp_path)
    monkeypatch.setattr(
        "psycopg.connect", lambda *a, **k: pytest.fail("validate-config must never connect!")
    )
    r = runner.invoke(
        app,
        ["validate-config", "-c", str(cfg), "--migrations-path", str(tmp_path / "db" / "migrations")],
    )
    assert r.exit_code == 0, r.output
