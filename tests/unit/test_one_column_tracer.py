"""One column tracer: ``core/linting/tenant/trace.py`` (``tenant_003``).

Where a view's output column comes from is a walk of a ``SELECT``'s target list
through its ``FROM`` — aliases, joins, subqueries, CTEs, ``*``, set operations. A
second walk would be a second answer to that question, and it would disagree with
the first the day one of them learns a shape the other has not. So a module other
than the tracer that reads a ``targetList`` fails here, unless the allow-list names
the *different* question it asks.

Each entry is ``module:function`` → the question. An entry that matches nothing
fails too, so the table is an edit, never an escape.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
# The source tree, not the imported package: the Publish workflow runs this suite
# against the built wheel, where ``confiture.__file__`` lives in the virtualenv.
PACKAGE = REPO / "python" / "confiture"
TRACER = PACKAGE / "core" / "linting" / "tenant" / "trace.py"

_TARGET_LIST = "targetList"

ALLOWED: dict[str, str] = {
    "core.ddl_objects:output_columns": (
        "the *names* a view outputs, so a generated migration knows whether "
        "CREATE OR REPLACE VIEW can keep them — never where a column comes from"
    ),
    "core.ddl_walk:canonical_default": (
        "a default read back as `SELECT <expr>`: the one expression, not a view's output"
    ),
    "core.ddl_walk:expression_columns": (
        "the columns a CHECK's or a default's expression names, read as `SELECT <expr>`"
    ),
    "core.live_catalog:_expression": (
        "a catalog expression parsed as `SELECT <expr>` so it renders the way DDL does"
    ),
    "core.seed.validation.prep_seed.seed_rows:_branches": (
        "the values a seed `INSERT … SELECT` writes, row by row — data, not provenance"
    ),
}


def _readers(path: Path) -> list[str]:
    """``module:function`` for each function in *path* that reads a ``targetList``."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    module = path.relative_to(PACKAGE).with_suffix("").as_posix().replace("/", ".")
    found: list[str] = []
    for function in ast.walk(tree):
        if not isinstance(function, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        for node in ast.walk(function):
            reads = (isinstance(node, ast.Attribute) and node.attr == _TARGET_LIST) or (
                isinstance(node, ast.Constant) and node.value == _TARGET_LIST
            )
            if reads:
                found.append(f"{module}:{function.name}")
                break
    return found


def _all_readers() -> set[str]:
    return {
        reader
        for path in sorted(PACKAGE.rglob("*.py"))
        if path != TRACER
        for reader in _readers(path)
    }


def test_no_module_but_the_tracer_walks_a_target_list() -> None:
    unexplained = sorted(_all_readers() - ALLOWED.keys())
    assert unexplained == [], (
        "these read a SELECT's targetList outside core/linting/tenant/trace.py — "
        "trace a column there, or add an entry naming the different question asked: "
        f"{unexplained}"
    )


def test_every_allow_list_entry_still_matches() -> None:
    stale = sorted(ALLOWED.keys() - _all_readers())
    assert stale == [], f"allow-list entries that match nothing — delete them: {stale}"


def test_the_tracer_itself_is_seen_by_the_scan() -> None:
    assert _readers(TRACER), "the scan no longer recognises a targetList read"
