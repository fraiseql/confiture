"""Integration tests for ``migrate validate --check-ownership-coverage`` (issue #124).

Mirrors :mod:`tests.integration.test_migrate_validate_check_acl_coverage`
on the ownership axis.
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest
from typer.testing import CliRunner

from confiture.cli.main import app

# Skip the suite entirely when pglast is missing — the lint rule is a
# no-op without it, so coverage assertions would all be vacuously true.
pytest.importorskip("pglast")


def _write_config(tmp_path: Path, ownership_body: str = "") -> Path:
    cfg = tmp_path / "confiture.yaml"
    body = textwrap.dedent(
        """\
        name: test
        database_url: postgresql://localhost/nonexistent
        include_dirs: []
        """
    )
    if ownership_body:
        body += textwrap.dedent(ownership_body)
    cfg.write_text(body)
    return cfg


def _write_migration(tmp_path: Path, name: str, sql: str) -> Path:
    migrations = tmp_path / "db" / "migrations"
    migrations.mkdir(parents=True, exist_ok=True)
    p = migrations / name
    p.write_text(sql)
    return p


def test_check_ownership_coverage_exits_1_on_missing_alter_owner(tmp_path: Path) -> None:
    cfg = _write_config(
        tmp_path,
        """
        ownership:
          expected_owner: migrator
          apply_to:
            - schema: public
              relkinds: [r]
        """,
    )
    _write_migration(
        tmp_path,
        "20260527090000_add_foo.up.sql",
        "CREATE TABLE public.foo (id int);\n",
    )

    result = CliRunner().invoke(
        app,
        [
            "migrate",
            "validate",
            "--check-ownership-coverage",
            "--config",
            str(cfg),
            "--migrations-dir",
            str(tmp_path / "db" / "migrations"),
        ],
    )
    assert result.exit_code == 1, result.output
    assert "own_001" in result.output


def test_check_ownership_coverage_exits_0_on_full_coverage(tmp_path: Path) -> None:
    cfg = _write_config(
        tmp_path,
        """
        ownership:
          expected_owner: migrator
          apply_to:
            - schema: public
              relkinds: [r]
        """,
    )
    _write_migration(
        tmp_path,
        "20260527090000_add_foo.up.sql",
        "CREATE TABLE public.foo (id int);\nALTER TABLE public.foo OWNER TO migrator;\n",
    )

    result = CliRunner().invoke(
        app,
        [
            "migrate",
            "validate",
            "--check-ownership-coverage",
            "--config",
            str(cfg),
            "--migrations-dir",
            str(tmp_path / "db" / "migrations"),
        ],
    )
    assert result.exit_code == 0, result.output


def test_check_ownership_coverage_without_block_is_noop(tmp_path: Path) -> None:
    """Missing ``ownership:`` block in config → success (opt-in semantics)."""
    cfg = _write_config(tmp_path)
    _write_migration(
        tmp_path,
        "20260527090000_add_foo.up.sql",
        "CREATE TABLE public.foo (id int);\n",
    )

    result = CliRunner().invoke(
        app,
        [
            "migrate",
            "validate",
            "--check-ownership-coverage",
            "--config",
            str(cfg),
            "--migrations-dir",
            str(tmp_path / "db" / "migrations"),
        ],
    )
    assert result.exit_code == 0, result.output


def test_check_ownership_coverage_json_output(tmp_path: Path) -> None:
    cfg = _write_config(
        tmp_path,
        """
        ownership:
          expected_owner: migrator
          apply_to:
            - schema: public
              relkinds: [r]
        """,
    )
    _write_migration(
        tmp_path,
        "20260527090000_add_foo.up.sql",
        "CREATE TABLE public.foo (id int);\n",
    )

    result = CliRunner().invoke(
        app,
        [
            "migrate",
            "validate",
            "--check-ownership-coverage",
            "--config",
            str(cfg),
            "--migrations-dir",
            str(tmp_path / "db" / "migrations"),
            "--format",
            "json",
        ],
    )
    assert result.exit_code == 1, result.output
    payload = json.loads(result.output)
    assert payload["check"] == "ownership_coverage"
    assert len(payload["violations"]) == 1
    v = payload["violations"][0]
    assert v["rule_id"] == "own_001"
    assert v["object_name"] == "public.foo"
    assert v["severity"] == "error"


def test_check_ownership_coverage_lint_disabled_is_noop(tmp_path: Path) -> None:
    cfg = _write_config(
        tmp_path,
        """
        ownership:
          expected_owner: migrator
          apply_to:
            - schema: public
              relkinds: [r]
          lint_enabled: false
        """,
    )
    _write_migration(
        tmp_path,
        "20260527090000_add_foo.up.sql",
        "CREATE TABLE public.foo (id int);\n",
    )

    result = CliRunner().invoke(
        app,
        [
            "migrate",
            "validate",
            "--check-ownership-coverage",
            "--config",
            str(cfg),
            "--migrations-dir",
            str(tmp_path / "db" / "migrations"),
        ],
    )
    assert result.exit_code == 0, result.output
