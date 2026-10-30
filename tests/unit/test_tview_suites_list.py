"""``ci/pg-tviews/suites.txt`` is the one list of TVIEW suites (#782).

The quality gate's ``pg-tviews`` leg reads it, and pg_tviews runs the same file
against a release candidate, so a suite added here reaches both.
"""

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
SUITES = ROOT / "ci" / "pg-tviews" / "suites.txt"
WORKFLOW = ROOT / ".github" / "workflows" / "quality-gate.yml"
#: How a suite asks for the extension (built, so this file does not match itself).
NEEDS_PG_TVIEWS = "create_supported_pg_tviews" + "("


def _listed() -> list[str]:
    lines = (line.strip() for line in SUITES.read_text().splitlines())
    return [line for line in lines if line and not line.startswith("#")]


def _leg_script() -> str:
    job = yaml.safe_load(WORKFLOW.read_text())["jobs"]["pg-tviews"]
    return "\n".join(step.get("run", "") for step in job["steps"])


def test_every_listed_suite_exists_once() -> None:
    listed = _listed()

    assert listed
    assert len(listed) == len(set(listed))
    assert [path for path in listed if not (ROOT / path).is_file()] == []


def test_the_leg_runs_the_list_and_names_no_suite_itself() -> None:
    script = _leg_script()

    assert "ci/pg-tviews/suites.txt" in script
    assert re.findall(r"tests/\S+\.py", script) == []


def test_the_leg_fails_on_a_skip() -> None:
    script = _leg_script()

    assert "--junitxml" in script
    assert "skipped" in script


def test_every_suite_that_creates_pg_tviews_is_listed() -> None:
    """A suite that needs the extension and is left out never runs where it is."""
    needs = {
        str(path.relative_to(ROOT))
        for path in (ROOT / "tests").rglob("test_*.py")
        if NEEDS_PG_TVIEWS in path.read_text()
    }

    assert sorted(needs - set(_listed())) == []
