"""Characterization safety net for the ``migrate validate`` god-command.

Phase 03 decomposes ``migrate_validate`` into per-mode ``core/validation``
handlers rendered through ``formatters/validate_formatter.py``. The extraction
must be behaviour-preserving for everything except the deliberately-changed
failure exit codes (config/usage errors → 5, tracked as BREAKING for 0.22.0).

These tests pin the *extraction invariants* that the existing suite left thin:
the success-path human-facing strings (most at risk of silent formatter drift)
and the git "all checks passed" JSON envelope (previously unpinned). They are
DB-free — every mode exercised here is static.
"""

from __future__ import annotations

import json
import subprocess
import textwrap
from pathlib import Path

import pytest
from typer.testing import CliRunner

from confiture.cli.main import app

runner = CliRunner()


# ---------------------------------------------------------------------------
# Static-mode success TEXT strings (formatter-drift guard)
# ---------------------------------------------------------------------------


def _acl_project(tmp_path: Path, migration_body: str) -> tuple[Path, Path]:
    (tmp_path / "db" / "migrations").mkdir(parents=True)
    (tmp_path / "db" / "migrations" / "20260101120000_t.up.sql").write_text(migration_body)
    cfg = tmp_path / "confiture.yaml"
    cfg.write_text(
        textwrap.dedent(
            """\
            name: test
            database_url: postgresql://localhost/test
            include_dirs: []
            acls:
              - schema: public
                apply_to: ALL_TABLES
                grants:
                  - role: my_app
                    privileges: [SELECT]
            """
        )
    )
    return cfg, tmp_path / "db" / "migrations"


def test_check_acls_success_text_is_stable(tmp_path: Path) -> None:
    cfg, migrations_dir = _acl_project(
        tmp_path,
        "CREATE TABLE foo (id int);\nGRANT SELECT ON foo TO my_app;\n",
    )
    result = runner.invoke(
        app,
        [
            "migrate",
            "validate",
            "--check-acls",
            "-c",
            str(cfg),
            "--migrations-dir",
            str(migrations_dir),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "✅ All migrations have ACL coverage" in result.output


def test_check_ownership_coverage_success_text_is_stable(tmp_path: Path) -> None:
    (tmp_path / "db" / "migrations").mkdir(parents=True)
    (tmp_path / "db" / "migrations" / "20260101120000_t.up.sql").write_text(
        "CREATE TABLE public.foo (id int);\nALTER TABLE public.foo OWNER TO migrator;\n"
    )
    cfg = tmp_path / "confiture.yaml"
    cfg.write_text(
        textwrap.dedent(
            """\
            name: test
            database_url: postgresql://localhost/test
            include_dirs: []
            ownership:
              expected_owner: migrator
              lint_enabled: true
              apply_to:
                - schema: public
                  relkinds: [r]
            """
        )
    )
    result = runner.invoke(
        app,
        [
            "migrate",
            "validate",
            "--check-ownership-coverage",
            "-c",
            str(cfg),
            "--migrations-dir",
            str(tmp_path / "db" / "migrations"),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "✅ All migrations have ownership coverage" in result.output


def test_check_imports_success_text_is_stable(tmp_path: Path) -> None:
    migrations_dir = tmp_path / "db" / "migrations"
    migrations_dir.mkdir(parents=True)
    # SQL-only migration → import check is a no-op success.
    (migrations_dir / "20260101120000_t.up.sql").write_text("SELECT 1;")
    result = runner.invoke(
        app,
        ["migrate", "validate", "--check-imports", "--migrations-dir", str(migrations_dir)],
    )
    assert result.exit_code == 0, result.output
    assert "passed import check" in result.output


# ---------------------------------------------------------------------------
# Git "all checks passed" envelope (text + JSON)
# ---------------------------------------------------------------------------


def _git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "t@t.com"], cwd=repo, check=True, capture_output=True
    )
    subprocess.run(["git", "config", "user.name", "T"], cwd=repo, check=True, capture_output=True)
    (repo / "db" / "schema").mkdir(parents=True)
    (repo / "db" / "migrations").mkdir(parents=True)
    (repo / "db" / "environments").mkdir(parents=True)
    (repo / "db" / "environments" / "local.yaml").write_text(
        "database_url: postgresql://localhost/test\ninclude_dirs:\n  - path: db/schema\n"
    )
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True)
    return repo


def test_check_drift_all_passed_text(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _git_repo(tmp_path)
    monkeypatch.chdir(repo)
    result = runner.invoke(
        app,
        ["migrate", "validate", "--check-drift", "--base-ref", "HEAD"],
    )
    assert result.exit_code == 0, result.output
    assert "✅ All git validation checks passed" in result.output


def test_check_drift_all_passed_json_envelope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _git_repo(tmp_path)
    monkeypatch.chdir(repo)
    result = runner.invoke(
        app,
        ["migrate", "validate", "--check-drift", "--base-ref", "HEAD", "--format", "json"],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["status"] == "passed"
    assert payload["checks"] == ["drift"]
