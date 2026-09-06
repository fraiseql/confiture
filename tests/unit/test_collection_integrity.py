"""The test count means what it says: no test is parametrized over local artefacts (TST-01).

``tests/unit/idempotency/test_ast_preprocess_parity.py`` parametrizes over the
SQL fixtures it finds in the checkout. When that was every ``*.sql`` under the
repo root, a developer machine contributed ~1,600 gitignored
``db/schema_history/`` snapshots (written by the suite itself) and the local
run collected ~3,000 more tests than CI — a gap that was carried for months as
"cause unknown" (#207). A fixture is something the repository tracks; the
parametrization has to be built from ``git ls-files``, so local and CI collect
the same ids.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from tests.unit.idempotency import test_ast_preprocess_parity as parity

REPO_ROOT = parity.PROJECT_ROOT


def _git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode not in (0, 1):  # check-ignore exits 1 when nothing is ignored
        pytest.skip(f"not a git checkout (git {args[0]} failed): {result.stderr.strip()}")
    return result.stdout


@pytest.fixture(scope="module")
def tracked_sql() -> set[Path]:
    out = _git("ls-files", "-z", "--", "*.sql")
    return {REPO_ROOT / p for p in out.split("\0") if p}


@pytest.fixture(scope="module")
def fixtures() -> list[Path]:
    assert parity.SQL_FIXTURES, "the parity probe must have fixtures"
    return list(parity.SQL_FIXTURES)


def test_every_fixture_is_tracked_by_git(fixtures: list[Path], tracked_sql: set[Path]) -> None:
    untracked = sorted(str(p.relative_to(REPO_ROOT)) for p in fixtures if p not in tracked_sql)
    assert untracked == [], (
        f"{len(untracked)} parity fixtures are not tracked by git (first 5: {untracked[:5]}); "
        "build SQL_FIXTURES from `git ls-files`, not from a filesystem glob."
    )


def test_no_fixture_is_gitignored(fixtures: list[Path]) -> None:
    listing = "\n".join(str(p.relative_to(REPO_ROOT)) for p in fixtures)
    result = subprocess.run(
        ["git", "check-ignore", "--stdin"],
        cwd=REPO_ROOT,
        input=listing,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode not in (0, 1):
        pytest.skip(f"git check-ignore unavailable: {result.stderr.strip()}")
    ignored = result.stdout.split()
    assert ignored == [], f"{len(ignored)} parity fixtures are gitignored (first 5: {ignored[:5]})"


def test_no_fixture_comes_from_generated_or_history_dirs(fixtures: list[Path]) -> None:
    offenders = [
        str(p.relative_to(REPO_ROOT))
        for p in fixtures
        if {"generated", "schema_history"} & set(p.relative_to(REPO_ROOT).parts)
    ]
    assert offenders == [], f"{len(offenders)} fixtures come from build output or snapshots"


def test_tracked_sql_files_are_all_fixtures(fixtures: list[Path], tracked_sql: set[Path]) -> None:
    """The other direction: the probe sees every tracked fixture, nothing filtered by accident."""
    missing = sorted(str(p.relative_to(REPO_ROOT)) for p in tracked_sql if p not in set(fixtures))
    assert missing == [], f"tracked SQL files the parity probe skips: {missing}"
