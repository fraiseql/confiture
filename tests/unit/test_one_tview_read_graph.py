"""One TVIEW read graph: ``core/linting/tview_reads.py``.

Which views, matviews and TVIEWs a tree declares, the query each holds, and what
each reads next — a plain view through a ``RangeVar``, a routine through a call —
is one graph. ``session_reads`` and ``tree_walks`` each read it their own way
before: the same definition reading twice, each pairing a
``pg_tviews_create_or_replace()`` call with its query and resolving a ``RangeVar``
to an inventory view itself. A module that does either outside the graph is a
second graph, and fails here.

Each entry below is ``module`` → the different question it asks. An entry that
matches nothing fails, so the table is an edit, never an escape.
"""

import ast
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
# The source tree, not the imported package: the Publish workflow runs this suite
# against the built wheel, where ``confiture.__file__`` lives in the virtualenv.
PACKAGE = REPO / "python" / "confiture"
GRAPH = PACKAGE / "core" / "linting" / "tview_reads.py"

ALLOWED: dict[str, str] = {
    "core/tview_preflight.py": (
        "reads a migration's statements against the queries a live pg_tviews registered, "
        "to name what a change takes from a TVIEW: no tree, no chain"
    ),
}


def _names(tree: ast.AST) -> set[str]:
    """Every name the module uses, bare or as an attribute, but the functions it defines."""
    used = {
        node.id if isinstance(node, ast.Name) else node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Name | ast.Attribute)
    }
    return used - {node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}


def _finds_views(tree: ast.AST) -> list[int]:
    """Lines calling ``find_all`` with a kind tuple that holds ``"view"``."""
    return [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "find_all"
        and node.args
        and isinstance(node.args[0], ast.Tuple)
        and any(
            isinstance(kind, ast.Constant) and kind.value == "view" for kind in node.args[0].elts
        )
    ]


def _second_graphs(path: Path) -> list[str]:
    """What makes *path* a second read graph: why, for each shape it has."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = _names(tree)
    found = []
    if {"tview_calls", "tview_query_tree"} <= names:
        found.append("pairs tview_calls() with tview_query_tree()")
    strings = {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    lines = _finds_views(tree)
    if lines and "RangeVar" in strings:
        found.append(f"resolves a RangeVar to a view (lines {lines})")
    return found


def _by_module() -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for path in sorted(PACKAGE.rglob("*.py")):
        if path == GRAPH:
            continue
        shapes = _second_graphs(path)
        if shapes:
            found[path.relative_to(PACKAGE).as_posix()] = shapes
    return found


def test_no_module_reads_tview_chains_by_itself() -> None:
    offenders = [
        f"{module}: {'; '.join(shapes)}"
        for module, shapes in _by_module().items()
        if module not in ALLOWED
    ]
    assert offenders == [], (
        "a second TVIEW read graph — read definitions and chains through "
        "core/linting/tview_reads.py:\n  " + "\n  ".join(offenders)
    )


def test_allow_list_is_current() -> None:
    stale = sorted(module for module in ALLOWED if module not in _by_module())
    assert stale == [], f"allow-list entries with nothing left to allow: {stale}"


def test_the_guard_sees_each_shape(tmp_path: Path) -> None:
    pairs = tmp_path / "pairs.py"
    pairs.write_text(
        "from confiture.core.ddl_walk import tview_calls, tview_query_tree\n"
        "roots = [tview_query_tree(c.written) for c in tview_calls(stmt)]\n",
        encoding="utf-8",
    )
    resolves = tmp_path / "resolves.py"
    resolves.write_text(
        "if type(node).__name__ == 'RangeVar':\n"
        "    views = inventory.find_all(('view',), node.schemaname, node.relname)\n",
        encoding="utf-8",
    )
    tables = tmp_path / "tables.py"
    tables.write_text(
        "if type(node).__name__ == 'RangeVar':\n"
        "    found = inventory.find_all(('table',), node.schemaname, node.relname)\n",
        encoding="utf-8",
    )
    assert _second_graphs(pairs) == ["pairs tview_calls() with tview_query_tree()"]
    assert _second_graphs(resolves) == ["resolves a RangeVar to a view (lines [2])"]
    assert _second_graphs(tables) == []
