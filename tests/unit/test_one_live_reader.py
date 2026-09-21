"""One live reader: a schema fact comes from ``pg_catalog`` through ``core/live_catalog``.

A table, its columns, constraints and indexes, an enum and a sequence, read from
a live database, are ``live_catalog.read``'s answer and nobody else's. Before it,
thirty-eight modules issued catalog SQL of their own, and the same question got
different answers — ``information_schema.table_constraints`` reports a CHECK row
per NOT NULL column; ``information_schema.columns.data_type`` spells an array
``ARRAY`` and drops every typmod; one reader hardcoded ``'public'``.

This fails on a catalog relation named in code — not in a docstring or a comment,
which describe rather than query — in any module but ``live_catalog``. The modules
that ask a *different* question of the catalog are listed with that question; an
entry that matches nothing fails, so the list shrinks as readers move.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import confiture

PACKAGE = Path(confiture.__file__).resolve().parent
READER = PACKAGE / "core" / "live_catalog.py"

CATALOG = re.compile(
    r"\b(?:pg_class|pg_attribute|pg_constraint|pg_index|pg_proc|pg_namespace|pg_type"
    r"|pg_depend|pg_attrdef|pg_enum|pg_sequence|pg_tables|pg_indexes|pg_views|pg_matviews"
    r"|pg_sequences)\b|\binformation_schema\."
)

#: Module -> the question it asks of the catalog that is not a schema fact.
ALLOWED: dict[str, str] = {
    "core/bootstrap.py": (
        "which schemas hold a relation the `postgres` role owns (`relowner`), so "
        "bootstrap can hand them to the application's owner: ownership"
    ),
    "core/dependent_objects.py": (
        "which views and routines depend on an object preflight is about to replace, "
        "through `pg_depend` and `pg_rewrite`: the dependency graph"
    ),
    "core/drift.py": (
        "the ACL and ownership passes: the tables a grant expectation covers, the "
        "privileges each role holds on them, and the role that owns each relation"
    ),
    "core/idempotency/suggestion_templates.py": (
        "guard clauses a finding suggests the user write into a migration: text "
        "confiture prints, never a query it runs"
    ),
    "core/large_tables.py": (
        "whether an index build left the index invalid (`indisvalid`) and the "
        "planner's row estimate (`reltuples`): operational state"
    ),
    "core/ledger.py": (
        "where confiture's own ledger table is, as `search_path` resolves its name: "
        "confiture's bookkeeping, not the project's schema"
    ),
    "core/linting/bodies.py": (
        "plpgsql_check's diagnosis of each routine body, and the schema that extension "
        "is installed in: an analysis engine asked about resolved types (#245)"
    ),
    "core/view_manager.py": (
        "the views that depend on a table's columns, saved whole — definition, "
        "indexes, comment, grants — to drop and recreate around ALTER COLUMN TYPE"
    ),
    "integrations/pggit/client.py": (
        "whether pgGit's own bookkeeping tables are installed: a tool's installation "
        "state, not the project's schema"
    ),
    "integrations/pggit/detection.py": (
        "whether pgGit is installed and initialised, and what it installed: a tool's "
        "installation state, not the project's schema"
    ),
    "testing/fixtures/data_validator.py": (
        "how many foreign keys PostgreSQL has not validated against the rows already "
        "there (`convalidated`): whether the data was checked, not what is declared"
    ),
}


#: What makes a string a query rather than a sentence that names a catalog: SQL's
#: own keywords, which this codebase writes in capitals, or a ``::regclass`` cast.
SQL_SHAPE = re.compile(r"\b(?:SELECT|FROM|JOIN)\b|::regclass")


def _docstrings(tree: ast.AST) -> set[int]:
    """The ``id`` of every docstring node — prose, never a query."""
    found: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                found.add(id(body[0].value))
    return found


def catalog_lines(source: str) -> list[int]:
    """Lines where a string that is a query names a catalog relation.

    Only string literals are looked at — a query is one, and a field called
    ``pg_type`` is not — and a docstring is prose. A literal split across an
    f-string or an implicit concatenation is read part by part, each part a
    ``Constant`` of its own.
    """
    tree = ast.parse(source)
    prose = _docstrings(tree)
    lines: set[int] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in prose
            and CATALOG.search(node.value)
            and SQL_SHAPE.search(node.value)
        ):
            lines.add(node.lineno)
    return sorted(lines)


def _sweep() -> dict[str, list[int]]:
    found: dict[str, list[int]] = {}
    for path in sorted(PACKAGE.rglob("*.py")):
        if path == READER:
            continue
        lines = catalog_lines(path.read_text(encoding="utf-8"))
        if lines:
            found[path.relative_to(PACKAGE).as_posix()] = lines
    return found


def test_the_reader_reads_the_catalog() -> None:
    assert catalog_lines(READER.read_text(encoding="utf-8")), "live_catalog issues no catalog SQL"


def test_the_check_ignores_prose_and_sees_queries() -> None:
    source = '''
def f(conn):
    """Reads pg_class, which the docstring may say."""
    # information_schema.columns in a comment is prose too
    reason = "a column with no pg_attrdef row has no default"
    pg_type: str = "int4"
    return conn.execute("SELECT relname FROM pg_class")
'''
    assert catalog_lines(source) == [7]


def test_no_second_live_reader() -> None:
    offenders = sorted(f"{m}:{lines}" for m, lines in _sweep().items() if m not in ALLOWED)
    assert offenders == [], "catalog SQL outside core/live_catalog.py:\n  " + "\n  ".join(offenders)


def test_the_allow_list_is_current() -> None:
    present = set(_sweep())
    stale = sorted(m for m in ALLOWED if m not in present)
    assert stale == [], f"allow-list entries with nothing left to allow: {stale}"


def test_every_allowed_module_states_its_question() -> None:
    assert all(reason.strip() for reason in ALLOWED.values())
