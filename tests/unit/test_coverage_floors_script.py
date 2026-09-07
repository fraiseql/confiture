"""``scripts/coverage_floors.py`` reads a coverage JSON report and enforces per-file floors.

The floors file is the committed contract; this test checks the script's reading of
a report (below / at / missing file) and that the committed floors name real modules.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
FLOORS = REPO_ROOT / "tests" / "coverage_floors.json"


@pytest.fixture(scope="module")
def floors_module():
    script = REPO_ROOT / "scripts" / "coverage_floors.py"
    spec = importlib.util.spec_from_file_location("coverage_floors", script)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _report(tmp_path: Path, percents: dict[str, float]) -> Path:
    files = {
        f"/ci/python/confiture/{rel}": {"summary": {"percent_covered": pct}}
        for rel, pct in percents.items()
    }
    path = tmp_path / "coverage.json"
    path.write_text(json.dumps({"files": files, "totals": {"percent_covered": 90.0}}))
    return path


def test_every_floor_names_an_existing_module() -> None:
    floors = json.loads(FLOORS.read_text(encoding="utf-8"))["files"]
    missing = [rel for rel in floors if not (REPO_ROOT / "python" / "confiture" / rel).exists()]
    assert missing == [], f"floors for modules that do not exist: {missing}"
    assert all(50 <= floor <= 100 for floor in floors.values())


def test_check_reports_files_below_their_floor(floors_module, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(floors_module, "load_floors", lambda: {"a/b.py": 70.0, "c.py": 70.0})
    failures = floors_module.check(_report(tmp_path, {"a/b.py": 69.9, "c.py": 70.0}))
    assert failures == ["a/b.py: 69.9% < floor 70%"]


def test_check_flags_a_floor_whose_module_left_the_report(
    floors_module, tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(floors_module, "load_floors", lambda: {"gone.py": 70.0})
    failures = floors_module.check(_report(tmp_path, {"other.py": 99.0}))
    assert failures and failures[0].startswith("gone.py: not in the coverage report")
