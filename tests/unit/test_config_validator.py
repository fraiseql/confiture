"""Unit tests for the connection-free ConfigValidator (issue #144, Phase 1)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from confiture.core.config_validator import ConfigValidator


def _project(
    tmp_path: Path,
    *,
    include="db/schema",
    database_url="postgresql://localhost/app",
    n_migrations=3,
) -> Path:
    (tmp_path / "db" / "schema").mkdir(parents=True)
    migs = tmp_path / "db" / "migrations"
    migs.mkdir(parents=True)
    for i in range(n_migrations):
        v = f"2026010100000{i}"
        (migs / f"{v}_m{i}.up.sql").write_text("SELECT 1;")
        (migs / f"{v}_m{i}.down.sql").write_text("SELECT 1;")
    cfg = tmp_path / "env.yaml"
    cfg.write_text(
        yaml.safe_dump({"name": "test", "database_url": database_url, "include_dirs": [include]})
    )
    return cfg


# ── schema + path ─────────────────────────────────────────────────────────────


def test_valid_config_reports_valid(tmp_path: Path) -> None:
    cfg = _project(tmp_path)
    report = ConfigValidator.from_config(
        cfg, migrations_path=tmp_path / "db" / "migrations"
    ).validate()
    assert report.valid
    assert report.issues == []
    assert report.migration_count == 3
    assert report.config_source == "yaml-file"


def test_missing_required_field(tmp_path: Path) -> None:
    cfg = tmp_path / "env.yaml"
    cfg.write_text(
        yaml.safe_dump({"name": "test", "include_dirs": ["db/schema"]})
    )  # no database_url
    (tmp_path / "db" / "schema").mkdir(parents=True)
    report = ConfigValidator.from_config(cfg, migrations_path=tmp_path / "missing").validate()
    assert not report.valid
    assert any(i.code == "CONFIG_001" for i in report.issues)


def test_nonexistent_include_dir(tmp_path: Path) -> None:
    cfg = tmp_path / "env.yaml"
    cfg.write_text(
        yaml.safe_dump(
            {
                "name": "test",
                "database_url": "postgresql://localhost/app",
                "include_dirs": ["db/nope"],
            }
        )
    )
    report = ConfigValidator.from_config(cfg, migrations_path=tmp_path).validate()
    assert not report.valid
    assert any("does not exist" in i.message for i in report.issues)


def test_missing_config_file(tmp_path: Path) -> None:
    report = ConfigValidator.from_config(
        tmp_path / "nope.yaml", migrations_path=tmp_path
    ).validate()
    assert not report.valid
    assert any(i.code == "CONFIG_004" for i in report.issues)


def test_invalid_yaml(tmp_path: Path) -> None:
    cfg = tmp_path / "broken.yaml"
    cfg.write_text("database_url: [unterminated\n  : :")
    report = ConfigValidator.from_config(cfg, migrations_path=tmp_path).validate()
    assert not report.valid
    assert any(i.code == "CONFIG_002" for i in report.issues)


def test_never_connects(monkeypatch, tmp_path: Path) -> None:
    cfg = _project(tmp_path)
    monkeypatch.setattr(
        "psycopg.connect", lambda *a, **k: pytest.fail("validate-config must never connect!")
    )
    ConfigValidator.from_config(cfg, migrations_path=tmp_path / "db" / "migrations").validate()


# ── migrations tree ───────────────────────────────────────────────────────────


def test_duplicate_version_detected(tmp_path: Path) -> None:
    cfg = _project(tmp_path, n_migrations=0)
    migs = tmp_path / "db" / "migrations"
    for name in ("a", "b"):
        (migs / f"20260101000001_{name}.up.sql").write_text("SELECT 1;")
        (migs / f"20260101000001_{name}.down.sql").write_text("SELECT 1;")
    report = ConfigValidator.from_config(cfg, migrations_path=migs).validate()
    assert not report.valid
    assert any(i.code == "MIGR_106" for i in report.issues)


def test_dsn_format_only_no_connect(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("psycopg.connect", lambda *a, **k: pytest.fail("connected!"))
    migs = tmp_path / "migrations"
    migs.mkdir()
    report = ConfigValidator.from_flags(database_url="not-a-dsn", migrations_path=migs).validate()
    assert not report.valid
    assert any(i.code == "CONFIG_003" for i in report.issues)
    assert report.config_source == "flags"


def test_flags_valid_dsn(tmp_path: Path) -> None:
    migs = tmp_path / "migrations"
    migs.mkdir()
    report = ConfigValidator.from_flags(
        database_url="postgresql://localhost/app", migrations_path=migs
    ).validate()
    assert report.valid
    assert report.config_source == "flags"


def test_report_to_dict_shape(tmp_path: Path) -> None:
    cfg = _project(tmp_path)
    report = ConfigValidator.from_config(
        cfg, migrations_path=tmp_path / "db" / "migrations"
    ).validate()
    d = report.to_dict()
    assert set(d.keys()) == {
        "valid",
        "config_source",
        "migrations_path",
        "migration_count",
        "issues",
    }
    assert d["valid"] is True
