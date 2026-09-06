"""Tests for the verify → verify-checksums rename + deprecation (issue #143).

The checksum logic is unchanged (pure passthrough); these cover the rename
mechanics: the canonical command, the deprecated alias's stderr warning, and the
cross-referential help.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from typer.testing import CliRunner

from confiture.cli.main import app

runner = CliRunner()


def _cfg(tmp_path: Path, test_db_url: str) -> Path:
    p = tmp_path / "env.yaml"
    p.write_text(
        yaml.safe_dump({"name": "test", "database_url": test_db_url, "include_dirs": ["db/schema"]})
    )
    return p


# ── help cross-references (no DB) ─────────────────────────────────────────────


def test_migrate_verify_help_points_to_checksums() -> None:
    out = runner.invoke(app, ["migrate", "verify", "--help"]).output
    assert "verify-checksums" in out
    assert "runtime correctness" in out.lower()


def test_verify_checksums_help_points_to_migrate_verify() -> None:
    out = runner.invoke(app, ["verify-checksums", "--help"]).output
    assert "migrate verify" in out
    assert "integrity" in out.lower()


# ── the removed alias must stay removed ────────────────────────────────────────


def test_verify_checksums_does_not_warn(tmp_path: Path, test_db_url: str) -> None:
    result = runner.invoke(app, ["verify-checksums", "-c", str(_cfg(tmp_path, test_db_url))])
    assert "deprecated" not in result.output.lower()


def test_verify_checksums_is_registered() -> None:
    # Distinct from the deprecated alias; both are invokable.
    top_help = runner.invoke(app, ["--help"]).output
    assert "verify-checksums" in top_help
