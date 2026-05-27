"""Integration tests for ``confiture migrate fix --ownership`` (issue #124).

These tests exercise the CLI end-to-end against a temp project (no real
DB needed for the non-checksum-guard tests — the helper degrades to "no
applied migrations" when it can't open a connection).
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest
from typer.testing import CliRunner

from confiture.cli.main import app

pytest.importorskip("pglast")


def _write_config(tmp_path: Path, ownership_body: str = "") -> Path:
    cfg = tmp_path / "confiture.yaml"
    body = textwrap.dedent(
        """\
        name: test
        database_url: postgresql://localhost/nonexistent_for_fix_test
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


# ---------------------------------------------------------------------------
# Dry-run
# ---------------------------------------------------------------------------


def test_dry_run_does_not_modify_files(tmp_path: Path) -> None:
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
    path = _write_migration(
        tmp_path,
        "20260527090000_add_foo.up.sql",
        "CREATE TABLE public.foo (id int);\n",
    )
    original = path.read_text()

    result = CliRunner().invoke(
        app,
        [
            "migrate",
            "fix",
            "--ownership",
            "--dry-run",
            "--config",
            str(cfg),
            "--migrations-dir",
            str(tmp_path / "db" / "migrations"),
        ],
    )
    assert result.exit_code == 0, result.output
    assert path.read_text() == original  # unchanged
    assert "Would insert" in result.output


def test_apply_writes_alter_owner_into_file(tmp_path: Path) -> None:
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
    path = _write_migration(
        tmp_path,
        "20260527090000_add_foo.up.sql",
        "CREATE TABLE public.foo (id int);\n",
    )

    result = CliRunner().invoke(
        app,
        [
            "migrate",
            "fix",
            "--ownership",
            "--config",
            str(cfg),
            "--migrations-dir",
            str(tmp_path / "db" / "migrations"),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "ALTER TABLE public.foo OWNER TO migrator;" in path.read_text()


# ---------------------------------------------------------------------------
# No-op when no ownership: block
# ---------------------------------------------------------------------------


def test_no_op_when_no_ownership_block(tmp_path: Path) -> None:
    cfg = _write_config(tmp_path)
    path = _write_migration(
        tmp_path,
        "20260527090000_add_foo.up.sql",
        "CREATE TABLE public.foo (id int);\n",
    )
    original = path.read_text()

    result = CliRunner().invoke(
        app,
        [
            "migrate",
            "fix",
            "--ownership",
            "--config",
            str(cfg),
            "--migrations-dir",
            str(tmp_path / "db" / "migrations"),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "no `ownership:` block" in result.output
    assert path.read_text() == original


# ---------------------------------------------------------------------------
# JSON output
# ---------------------------------------------------------------------------


def test_json_output_shape(tmp_path: Path) -> None:
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
            "fix",
            "--ownership",
            "--dry-run",
            "--config",
            str(cfg),
            "--migrations-dir",
            str(tmp_path / "db" / "migrations"),
            "--format",
            "json",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "preview"
    assert len(payload["previews"]) == 1
    assert "ALTER TABLE public.foo OWNER TO migrator" in payload["previews"][0]["after"]
    assert payload["modified"] == []
    assert payload["refused"] == []


# ---------------------------------------------------------------------------
# Combined --idempotent + --ownership
# ---------------------------------------------------------------------------


def test_combined_idempotent_and_ownership(tmp_path: Path) -> None:
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
    path = _write_migration(
        tmp_path,
        "20260527090000_combo.up.sql",
        "CREATE TABLE public.foo (id int);\n",
    )

    result = CliRunner().invoke(
        app,
        [
            "migrate",
            "fix",
            "--idempotent",
            "--ownership",
            "--config",
            str(cfg),
            "--migrations-dir",
            str(tmp_path / "db" / "migrations"),
        ],
    )
    assert result.exit_code == 0, result.output
    final = path.read_text()
    # Idempotency fix should add IF NOT EXISTS.
    assert "IF NOT EXISTS" in final
    # Ownership fix should add ALTER … OWNER TO.
    assert "ALTER TABLE public.foo OWNER TO migrator;" in final
