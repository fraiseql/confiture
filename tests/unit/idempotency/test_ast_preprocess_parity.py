"""Preprocessing parity probe between the regex and AST backends.

The AST detector consumes the same preprocessed SQL as the regex
detector (see ``IdempotencyValidator._preprocess_sql``). Three
transformations happen there:

1. ``--`` line comments → spaces.
2. ``/* … */`` block comments → newlines (line count preserved).
3. Dollar-quoted bodies → ``$MASKED$ … $MASKED$``.

``$MASKED$`` is a valid PostgreSQL dollar-quote tag, so pglast parses
the masked output cleanly. This module asserts that empirically against
every ``*.sql`` and ``*.up.sql`` fixture we can find in the repo. If
any fixture breaks, the AST path must fork (consume raw SQL and use
pglast's native location info instead of sharing the preprocessor).

Smoke test: also asserts pglast ≥ 6 is importable. The visitors reference
PostgreSQL enum *names* that are stable across pglast 6.x → 7.x, but
this test catches a downstream environment that pinned a pre-6.0 version.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from confiture.core.idempotency.validator import IdempotencyValidator

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _iter_sql_fixtures() -> list[Path]:
    """Collect representative SQL files from the repo.

    Includes ``db/schema/``, ``db/schema_history/``, ``examples/**``,
    ``scripts/init-databases.sql``, and any other top-level SQL. Skips
    ``.venv`` and ``node_modules``.
    """
    skip_parts = {".venv", "node_modules", "__pycache__"}
    candidates: list[Path] = []
    for path in PROJECT_ROOT.rglob("*.sql"):
        if any(part in skip_parts for part in path.parts):
            continue
        candidates.append(path)
    candidates.sort()
    return candidates


SQL_FIXTURES = _iter_sql_fixtures()


def test_at_least_one_fixture_available():
    """Sanity: the probe is non-trivial only if we have fixtures to scan."""
    assert SQL_FIXTURES, (
        "no SQL fixtures discovered under repo root; the preprocessing "
        "probe would be a no-op. If the repo layout changed, update "
        "_iter_sql_fixtures() in this test module."
    )


@pytest.mark.parametrize("fixture", SQL_FIXTURES, ids=lambda p: str(p.relative_to(PROJECT_ROOT)))
def test_preprocessing_preserves_pglast_parsability(fixture: Path):
    """Preprocessing must not degrade pglast's ability to parse a file.

    Files that pglast cannot parse raw (psql meta-commands like ``\\c``,
    non-PG extensions like ``CREATE ROLE IF NOT EXISTS``, or verification
    snippets that aren't real DDL) are out of scope — they aren't valid
    inputs to the AST backend in the first place, regardless of
    preprocessing. The test fails only when raw parses *and* preprocessed
    does not, which would mean preprocessing introduced corruption.
    """
    pglast = pytest.importorskip("pglast")

    raw = fixture.read_text(encoding="utf-8")
    if not raw.strip():
        pytest.skip(f"{fixture} is empty")

    try:
        pglast.parse_sql(raw)
    except pglast.parser.ParseError:
        pytest.skip(
            f"{fixture.relative_to(PROJECT_ROOT)} is not pglast-parseable raw "
            "(psql meta-commands, non-PG syntax, or partial SQL); "
            "preprocessing parity is undefined for this input."
        )

    validator = IdempotencyValidator()
    masked = validator._preprocess_sql(raw)  # noqa: SLF001 — intentional internals probe

    try:
        pglast.parse_sql(masked)
    except pglast.parser.ParseError as exc:
        pytest.fail(
            f"pglast.parse_sql succeeded on raw {fixture.relative_to(PROJECT_ROOT)} "
            f"but failed after preprocessing: {type(exc).__name__}: {exc}. "
            "Preprocessing corrupted otherwise-valid SQL. The AST path must "
            "fork (consume raw SQL with pglast's native location info) before "
            "Phase 2 visitors land. See /tmp/issue-122-phased-plan.md."
        )


def test_pglast_version_floor_is_six_or_newer():
    """Pin a hard floor: the AST visitors reference pglast 6+ enum names.

    The enum names (``AT_AddColumn``, ``CONSTR_CHECK``, ``OBJECT_TABLE``,
    etc.) are stable across pglast 6.x → 7.x because they come straight
    from PostgreSQL's ``parsenodes.h``. If the floor moves earlier than
    6.0, the imports in :mod:`confiture.core.idempotency.ast_detector`
    would still work, but the AST node shape predates the schema this
    plan was validated against. Better to fail loudly here.
    """
    pglast = pytest.importorskip("pglast")
    version = pglast.__version__.lstrip("v")
    major = int(version.split(".")[0])
    assert major >= 6, (
        f"pglast version {version!r} is older than the supported floor (6.0). "
        "Bump the floor in pyproject.toml or upgrade the installed version."
    )
