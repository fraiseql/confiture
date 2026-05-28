"""Integration tests for ``migrate validate --check-function-uniqueness`` (issue #136).

Mirrors :mod:`tests.integration.test_migrate_validate_check_ownership_coverage`
on the function-uniqueness axis.
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


def _write_config(tmp_path: Path, function_coverage_body: str = "") -> Path:
    cfg = tmp_path / "confiture.yaml"
    body = textwrap.dedent(
        """\
        name: test
        database_url: postgresql://localhost/nonexistent
        include_dirs: []
        """
    )
    if function_coverage_body:
        body += textwrap.dedent(function_coverage_body)
    cfg.write_text(body)
    return cfg


def _write_ddl(tmp_path: Path, name: str, sql: str) -> Path:
    schema_dir = tmp_path / "db" / "schema"
    schema_dir.mkdir(parents=True, exist_ok=True)
    p = schema_dir / name
    p.write_text(sql)
    return p


def test_check_function_uniqueness_exits_1_on_duplicate(tmp_path: Path) -> None:
    cfg = _write_config(
        tmp_path,
        """
        function_coverage:
          enabled: true
          apply_to: ["*"]
        """,
    )
    _write_ddl(
        tmp_path,
        "01_foo.sql",
        "CREATE FUNCTION public.foo() RETURNS void AS $$ BEGIN END $$ LANGUAGE plpgsql;\n",
    )
    _write_ddl(
        tmp_path,
        "02_foo_dup.sql",
        "CREATE OR REPLACE FUNCTION public.foo() RETURNS void AS $$ BEGIN END $$ LANGUAGE plpgsql;\n",
    )

    result = CliRunner().invoke(
        app,
        [
            "migrate",
            "validate",
            "--check-function-uniqueness",
            "--config",
            str(cfg),
            "--ddl-dir",
            str(tmp_path / "db" / "schema"),
        ],
    )
    assert result.exit_code == 1, result.output
    assert "func_001" in result.output


def test_check_function_uniqueness_exits_0_on_no_duplicates(tmp_path: Path) -> None:
    cfg = _write_config(
        tmp_path,
        """
        function_coverage:
          enabled: true
          apply_to: ["*"]
        """,
    )
    _write_ddl(
        tmp_path,
        "01_foo.sql",
        "CREATE FUNCTION public.foo() RETURNS void AS $$ BEGIN END $$ LANGUAGE plpgsql;\n",
    )
    _write_ddl(
        tmp_path,
        "02_bar.sql",
        "CREATE FUNCTION public.bar() RETURNS void AS $$ BEGIN END $$ LANGUAGE plpgsql;\n",
    )

    result = CliRunner().invoke(
        app,
        [
            "migrate",
            "validate",
            "--check-function-uniqueness",
            "--config",
            str(cfg),
            "--ddl-dir",
            str(tmp_path / "db" / "schema"),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "All callables have unique signatures" in result.output


def test_check_function_uniqueness_noop_when_block_absent(tmp_path: Path) -> None:
    cfg = _write_config(tmp_path)  # No function_coverage: block
    _write_ddl(
        tmp_path,
        "01_foo.sql",
        "CREATE FUNCTION public.foo() RETURNS void AS $$ BEGIN END $$ LANGUAGE plpgsql;\n",
    )
    _write_ddl(
        tmp_path,
        "02_foo_dup.sql",
        "CREATE OR REPLACE FUNCTION public.foo() RETURNS void AS $$ BEGIN END $$ LANGUAGE plpgsql;\n",
    )

    result = CliRunner().invoke(
        app,
        [
            "migrate",
            "validate",
            "--check-function-uniqueness",
            "--config",
            str(cfg),
            "--ddl-dir",
            str(tmp_path / "db" / "schema"),
        ],
    )
    # No-op when block absent — even with real duplicates, exit 0.
    assert result.exit_code == 0, result.output


def test_check_function_uniqueness_noop_when_disabled(tmp_path: Path) -> None:
    cfg = _write_config(
        tmp_path,
        """
        function_coverage:
          enabled: false
        """,
    )
    _write_ddl(
        tmp_path,
        "01_foo.sql",
        "CREATE FUNCTION public.foo() RETURNS void AS $$ BEGIN END $$ LANGUAGE plpgsql;\n",
    )
    _write_ddl(
        tmp_path,
        "02_foo_dup.sql",
        "CREATE OR REPLACE FUNCTION public.foo() RETURNS void AS $$ BEGIN END $$ LANGUAGE plpgsql;\n",
    )

    result = CliRunner().invoke(
        app,
        [
            "migrate",
            "validate",
            "--check-function-uniqueness",
            "--config",
            str(cfg),
            "--ddl-dir",
            str(tmp_path / "db" / "schema"),
        ],
    )
    assert result.exit_code == 0, result.output


def test_check_function_uniqueness_json_format(tmp_path: Path) -> None:
    cfg = _write_config(
        tmp_path,
        """
        function_coverage:
          enabled: true
          apply_to: ["*"]
        """,
    )
    _write_ddl(
        tmp_path,
        "01_foo.sql",
        "CREATE FUNCTION public.foo() RETURNS void AS $$ BEGIN END $$ LANGUAGE plpgsql;\n",
    )
    _write_ddl(
        tmp_path,
        "02_foo_dup.sql",
        "CREATE OR REPLACE FUNCTION public.foo() RETURNS void AS $$ BEGIN END $$ LANGUAGE plpgsql;\n",
    )

    out_file = tmp_path / "report.json"
    result = CliRunner().invoke(
        app,
        [
            "migrate",
            "validate",
            "--check-function-uniqueness",
            "--config",
            str(cfg),
            "--ddl-dir",
            str(tmp_path / "db" / "schema"),
            "--format",
            "json",
            "--output",
            str(out_file),
        ],
    )
    assert result.exit_code == 1, result.output
    payload = json.loads(out_file.read_text())
    assert payload["check"] == "function_uniqueness"
    assert len(payload["violations"]) == 1
    assert payload["violations"][0]["rule_id"] == "func_001"
    assert payload["violations"][0]["object_type"] == "function"
