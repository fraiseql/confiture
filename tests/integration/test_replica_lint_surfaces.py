"""Surface tests: `confiture lint --replica-safe` and `migrate preflight` (#139)."""

from __future__ import annotations

import json
from pathlib import Path

import yaml
from typer.testing import CliRunner

from confiture.cli.main import app

runner = CliRunner()


def _config(tmp_path: Path, *, replicas: list[str] | None = None, bypass: bool = False) -> Path:
    return _write_cfg(tmp_path / "env.yaml", replicas=replicas, bypass=bypass)


def _write_cfg(path: Path, *, replicas=None, bypass=False) -> Path:
    body: dict = {
        "name": "test",
        "database_url": "postgresql://localhost/app",
        "include_dirs": ["db/schema"],
    }
    if replicas:
        body["infrastructure"] = {"replicas": replicas}
    if bypass:
        body["migration"] = {"allow_unsafe_under_replication": True}
    path.write_text(yaml.safe_dump(body))
    return path


# ── preflight surface ─────────────────────────────────────────────────────────


def test_preflight_emits_replica_issue_with_replicas(tmp_path: Path) -> None:
    migs = tmp_path / "migrations"
    migs.mkdir()
    (migs / "20260531_1200_drop.up.sql").write_text("ALTER TABLE t DROP COLUMN c;")
    (migs / "20260531_1200_drop.down.sql").write_text("ALTER TABLE t ADD COLUMN c int;")
    cfg = _config(tmp_path, replicas=["read-1"])

    r = runner.invoke(
        app,
        ["migrate", "preflight", "--migrations-dir", str(migs), "-c", str(cfg), "--format", "json"],
    )
    assert r.exit_code == 7, r.output
    codes = {i["code"] for i in json.loads(r.stdout)["issues"]}
    assert "PFLIGHT_REPLICA_DROP_COLUMN" in codes


def test_preflight_replica_warns_without_replicas(tmp_path: Path) -> None:
    migs = tmp_path / "migrations"
    migs.mkdir()
    (migs / "20260531_1200_drop.up.sql").write_text("ALTER TABLE t DROP COLUMN c;")
    (migs / "20260531_1200_drop.down.sql").write_text("ALTER TABLE t ADD COLUMN c int;")

    r = runner.invoke(
        app, ["migrate", "preflight", "--migrations-dir", str(migs), "--format", "json"]
    )
    # No replicas declared → warning, exit 0; the issue is still reported.
    assert r.exit_code == 0, r.output
    payload = json.loads(r.stdout)
    replica = [i for i in payload["issues"] if i["code"].startswith("PFLIGHT_REPLICA")]
    assert replica and replica[0]["severity"] == "warning"


def test_preflight_replica_bypass_downgrades(tmp_path: Path) -> None:
    migs = tmp_path / "migrations"
    migs.mkdir()
    (migs / "20260531_1200_drop.up.sql").write_text("ALTER TABLE t DROP COLUMN c;")
    (migs / "20260531_1200_drop.down.sql").write_text("ALTER TABLE t ADD COLUMN c int;")
    cfg = _config(tmp_path, replicas=["read-1"], bypass=True)

    r = runner.invoke(
        app,
        ["migrate", "preflight", "--migrations-dir", str(migs), "-c", str(cfg), "--format", "json"],
    )
    assert r.exit_code == 0, r.output  # bypass downgrades to warning


def test_preflight_summary_window_safe_false_when_unsafe(tmp_path: Path) -> None:
    """The typed `window_safe` verdict is False when a replica finding is present (#154)."""
    migs = tmp_path / "migrations"
    migs.mkdir()
    (migs / "20260531_1200_drop.up.sql").write_text("ALTER TABLE t DROP COLUMN c;")
    (migs / "20260531_1200_drop.down.sql").write_text("ALTER TABLE t ADD COLUMN c int;")

    r = runner.invoke(
        app, ["migrate", "preflight", "--migrations-dir", str(migs), "--format", "json"]
    )
    assert r.exit_code == 0, r.output  # warn-by-default, but window-unsafe
    assert json.loads(r.stdout)["summary"]["window_safe"] is False


def test_preflight_summary_window_safe_true_when_clean(tmp_path: Path) -> None:
    """A nullable ADD COLUMN is forward-compatible → window_safe True (#154)."""
    migs = tmp_path / "migrations"
    migs.mkdir()
    (migs / "20260531_1200_add.up.sql").write_text("ALTER TABLE t ADD COLUMN c int;")
    (migs / "20260531_1200_add.down.sql").write_text("ALTER TABLE t DROP COLUMN c;")

    r = runner.invoke(
        app, ["migrate", "preflight", "--migrations-dir", str(migs), "--format", "json"]
    )
    assert r.exit_code == 0, r.output
    assert json.loads(r.stdout)["summary"]["window_safe"] is True


def test_preflight_py_migration_is_window_unsafe(tmp_path: Path) -> None:
    """A `.py` migration the classifier can't read makes the window not certifiable (#154)."""
    migs = tmp_path / "migrations"
    migs.mkdir()
    (migs / "20260531_1200_data.py").write_text("def up(cur):\n    pass\n")

    r = runner.invoke(
        app, ["migrate", "preflight", "--migrations-dir", str(migs), "--format", "json"]
    )
    assert r.exit_code == 0, r.output
    payload = json.loads(r.stdout)
    codes = {i["code"] for i in payload["issues"]}
    assert "PFLIGHT_REPLICA_UNCLASSIFIED" in codes
    assert payload["summary"]["window_safe"] is False


# ── lint surface ──────────────────────────────────────────────────────────────


def _standard_project(tmp_path: Path, *, replicas: list[str]) -> Path:
    (tmp_path / "db" / "schema").mkdir(parents=True)
    (tmp_path / "db" / "schema" / "01_t.sql").write_text("CREATE TABLE t (id int PRIMARY KEY);\n")
    envs = tmp_path / "db" / "environments"
    envs.mkdir(parents=True)
    _write_cfg(envs / "local.yaml", replicas=replicas)
    migs = tmp_path / "db" / "migrations"
    migs.mkdir(parents=True)
    (migs / "20260531_1200_drop.up.sql").write_text("ALTER TABLE t DROP COLUMN c;")
    (migs / "20260531_1200_drop.down.sql").write_text("ALTER TABLE t ADD COLUMN c int;")
    return tmp_path


def test_lint_replica_safe_flag_errors_with_replicas(tmp_path: Path) -> None:
    proj = _standard_project(tmp_path, replicas=["read-1"])
    r = runner.invoke(
        app,
        [
            "lint",
            "--replica-safe",
            "--env",
            "local",
            "--project-dir",
            str(proj),
            "--migrations-dir",
            str(proj / "db" / "migrations"),
        ],
    )
    assert r.exit_code != 0
    assert "replica_001" in r.output
