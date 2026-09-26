"""``seed validate --fix --format json`` writes one JSON document to stdout, and says what it fixed."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from confiture.cli.main import app
from confiture.core.schema_exporter import load_schema
from confiture.core.seed.validation.models import SeedValidationPattern
from confiture.core.seed.validation.prep_seed.models import PrepSeedPattern, ViolationSeverity

_UNGUARDED = "INSERT INTO t (id) VALUES (1);\n"


@pytest.fixture
def seeds_dir(tmp_path: Path) -> Path:
    seeds = tmp_path / "seeds"
    seeds.mkdir()
    (seeds / "01_t.sql").write_text(_UNGUARDED)
    return seeds


def _run(seeds: Path, *flags: str) -> dict:
    result = CliRunner().invoke(
        app, ["seed", "validate", "--seeds-dir", str(seeds), "--format", "json", *flags]
    )
    return json.loads(result.stdout)


def test_fix_dry_run_reports_the_fix_in_the_payload_and_changes_nothing(seeds_dir: Path) -> None:
    payload = _run(seeds_dir, "--fix", "--dry-run")

    assert payload["fixes"] == [
        {"file": str(seeds_dir / "01_t.sql"), "fixes_applied": 1, "written": False}
    ]
    assert (seeds_dir / "01_t.sql").read_text() == _UNGUARDED


def test_fix_reports_the_file_it_rewrote(seeds_dir: Path) -> None:
    payload = _run(seeds_dir, "--fix")

    assert payload["fixes"] == [
        {"file": str(seeds_dir / "01_t.sql"), "fixes_applied": 1, "written": True}
    ]
    assert "ON CONFLICT DO NOTHING" in (seeds_dir / "01_t.sql").read_text()


def test_without_fix_the_payload_has_no_fixes_key(seeds_dir: Path) -> None:
    assert "fixes" not in _run(seeds_dir)


def test_the_schema_names_every_pattern_and_severity() -> None:
    defs = load_schema("seed-validate.schema.json")["$defs"]

    assert defs["SeedViolation"]["properties"]["pattern"]["enum"] == [
        p.name for p in SeedValidationPattern
    ]
    assert defs["PrepSeedViolation"]["properties"]["pattern"]["enum"] == [
        p.name for p in PrepSeedPattern
    ]
    assert defs["PrepSeedViolation"]["properties"]["severity"]["enum"] == [
        s.name for s in ViolationSeverity
    ]
