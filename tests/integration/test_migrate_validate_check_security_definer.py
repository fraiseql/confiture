"""Integration tests for ``migrate validate --check-security-definer`` (issue #161)."""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest
from typer.testing import CliRunner

from confiture.cli.main import app

pytest.importorskip("pglast")

_UNPINNED_DEFINER = (
    "CREATE FUNCTION public.risky() RETURNS void LANGUAGE plpgsql "
    "SECURITY DEFINER AS $$ BEGIN END $$;\n"
)
_PINNED_DEFINER = (
    "CREATE FUNCTION public.safe() RETURNS void LANGUAGE plpgsql "
    "SECURITY DEFINER SET search_path = pg_catalog, public AS $$ BEGIN END $$;\n"
)
_INVOKER = "CREATE FUNCTION public.invoker() RETURNS void LANGUAGE plpgsql AS $$ BEGIN END $$;\n"


def _write_config(tmp_path: Path, security_lint_body: str = "") -> Path:
    cfg = tmp_path / "confiture.yaml"
    body = textwrap.dedent(
        """\
        name: test
        database_url: postgresql://localhost/nonexistent
        include_dirs: []
        """
    )
    if security_lint_body:
        body += textwrap.dedent(security_lint_body)
    cfg.write_text(body)
    return cfg


def _write_ddl(tmp_path: Path, name: str, sql: str) -> Path:
    d = tmp_path / "db" / "schema"
    d.mkdir(parents=True, exist_ok=True)
    p = d / name
    p.write_text(sql)
    return p


def _invoke(tmp_path: Path, cfg: Path, extra: list[str] | None = None) -> object:
    args = [
        "migrate",
        "validate",
        "--check-security-definer",
        "--config",
        str(cfg),
        "--ddl-dir",
        str(tmp_path / "db" / "schema"),
    ]
    if extra:
        args.extend(extra)
    return CliRunner().invoke(app, args)


# ---------------------------------------------------------------------------
# Clean pass
# ---------------------------------------------------------------------------


def test_no_findings_exits_0(tmp_path: Path) -> None:
    cfg = _write_config(
        tmp_path,
        """
        security_lint:
          enabled: true
        """,
    )
    _write_ddl(tmp_path, "safe.sql", _PINNED_DEFINER)
    result = _invoke(tmp_path, cfg)
    assert result.exit_code == 0, result.output
    assert "No unpinned SECURITY DEFINER" in result.output


def test_invoker_only_exits_0(tmp_path: Path) -> None:
    cfg = _write_config(
        tmp_path,
        """
        security_lint:
          enabled: true
        """,
    )
    _write_ddl(tmp_path, "inv.sql", _INVOKER)
    result = _invoke(tmp_path, cfg)
    assert result.exit_code == 0, result.output


# ---------------------------------------------------------------------------
# Warning severity (advisory — exit 0)
# ---------------------------------------------------------------------------


def test_finding_at_warning_exits_0_but_printed(tmp_path: Path) -> None:
    cfg = _write_config(
        tmp_path,
        """
        security_lint:
          enabled: true
          severity: warning
        """,
    )
    _write_ddl(tmp_path, "risky.sql", _UNPINNED_DEFINER)
    result = _invoke(tmp_path, cfg)
    assert result.exit_code == 0, result.output
    assert "sec_002" in result.output


# ---------------------------------------------------------------------------
# Error severity (hard gate — exit 1)
# ---------------------------------------------------------------------------


def test_finding_at_error_exits_1(tmp_path: Path) -> None:
    cfg = _write_config(
        tmp_path,
        """
        security_lint:
          enabled: true
          severity: error
        """,
    )
    _write_ddl(tmp_path, "risky.sql", _UNPINNED_DEFINER)
    result = _invoke(tmp_path, cfg)
    assert result.exit_code == 1, result.output
    assert "sec_002" in result.output


# ---------------------------------------------------------------------------
# Config-absent no-op
# ---------------------------------------------------------------------------


def test_config_absent_noop_exits_0(tmp_path: Path) -> None:
    cfg = _write_config(tmp_path)  # No security_lint: block
    _write_ddl(tmp_path, "risky.sql", _UNPINNED_DEFINER)
    result = _invoke(tmp_path, cfg)
    assert result.exit_code == 0, result.output


def test_config_disabled_noop_exits_0(tmp_path: Path) -> None:
    cfg = _write_config(
        tmp_path,
        """
        security_lint:
          enabled: false
        """,
    )
    _write_ddl(tmp_path, "risky.sql", _UNPINNED_DEFINER)
    result = _invoke(tmp_path, cfg)
    assert result.exit_code == 0, result.output


# ---------------------------------------------------------------------------
# JSON output
# ---------------------------------------------------------------------------


def test_json_output_shape(tmp_path: Path) -> None:
    cfg = _write_config(
        tmp_path,
        """
        security_lint:
          enabled: true
          severity: error
        """,
    )
    _write_ddl(tmp_path, "risky.sql", _UNPINNED_DEFINER)
    out_file = tmp_path / "report.json"
    result = _invoke(tmp_path, cfg, extra=["--format", "json", "--output", str(out_file)])
    assert result.exit_code == 1, result.output
    payload = json.loads(out_file.read_text())
    assert payload["check"] == "security_definer"
    assert len(payload["violations"]) == 1
    v = payload["violations"][0]
    assert v["rule_id"] == "sec_002"
    assert v["object_name"] == "public.risky"
    assert "line_number" in v
    assert "file_path" in v


# ---------------------------------------------------------------------------
# Ignore pattern
# ---------------------------------------------------------------------------


def test_ignore_pattern_suppresses_finding(tmp_path: Path) -> None:
    cfg = _write_config(
        tmp_path,
        """
        security_lint:
          enabled: true
          severity: error
          ignore: ["public.risky"]
        """,
    )
    _write_ddl(tmp_path, "risky.sql", _UNPINNED_DEFINER)
    result = _invoke(tmp_path, cfg)
    assert result.exit_code == 0, result.output
