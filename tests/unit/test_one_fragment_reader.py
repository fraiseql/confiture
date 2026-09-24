"""One PL/pgSQL fragment reader: ``core/plpgsql_fragments.py`` (#363).

A compiled PL/pgSQL body holds its SQL as ``PLpgSQL_expr`` strings, and how to
read one depends on the statement it sits in. Two walkers read those strings
each their own way, and both lost the same statements: ``references`` tried two
readings of an assignment and neither parses, ``data_assertions`` read only
``SELECT … INTO`` and passed a fragment pglast rejected off as ``[]``. The
reader is where the statement decides the reading, so a module that picks a
``PLpgSQL_expr`` or its ``query`` out of a compiled tree by itself is a second
reader, and fails here.

Each entry below is ``module`` → why it reads the tree. An entry that matches
nothing fails, so the table is an edit, never an escape. It is empty.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
# The source tree, not the imported package: the Publish workflow runs this suite
# against the built wheel, where ``confiture.__file__`` lives in the virtualenv.
PACKAGE = REPO / "python" / "confiture"
READER = PACKAGE / "core" / "plpgsql_fragments.py"

_EXPR = "PLpgSQL_expr"
_NODE = "PLpgSQL_"

ALLOWED: dict[str, str] = {}


def _constants(tree: ast.AST) -> list[ast.Constant]:
    """Every string constant that is code, not a docstring: prose may name the node."""
    prose = {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef)
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
    }
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in prose
    ]


def _reads_query(tree: ast.AST) -> list[int]:
    """Lines that take ``"query"`` out of a mapping: ``x["query"]`` or ``x.get("query")``."""
    return [
        node.lineno
        for node in ast.walk(tree)
        if (isinstance(node, ast.Subscript) and _is_query(node.slice))
        or (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "get"
            and bool(node.args)
            and _is_query(node.args[0])
        )
    ]


def _is_query(node: ast.AST) -> bool:
    return isinstance(node, ast.Constant) and node.value == "query"


def _second_readers(path: Path) -> list[int]:
    """Lines where *path* reads a fragment out of a compiled PL/pgSQL tree by itself.

    Naming ``PLpgSQL_expr`` is reading one. Taking ``"query"`` out of a mapping
    is reading one only in a module that names a PL/pgSQL node at all — a
    ``"query"`` key is common, and an MCP request carries one too.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    strings = _constants(tree)
    lines = [const.lineno for const in strings if _EXPR in const.value]
    if any(const.value.startswith(_NODE) for const in strings):
        lines += _reads_query(tree)
    return sorted(set(lines))


def _by_module() -> dict[str, list[int]]:
    found: dict[str, list[int]] = {}
    for path in sorted(PACKAGE.rglob("*.py")):
        if path == READER:
            continue
        lines = _second_readers(path)
        if lines:
            found[path.relative_to(PACKAGE).as_posix()] = lines
    return found


def test_no_module_reads_a_fragment_by_itself() -> None:
    offenders = [
        f"{module} (lines {lines})"
        for module, lines in _by_module().items()
        if module not in ALLOWED
    ]
    assert offenders == [], (
        "a second reader of PL/pgSQL fragments — read them through "
        "plpgsql_fragments.fragments():\n  " + "\n  ".join(offenders)
    )


def test_allow_list_is_current() -> None:
    stale = sorted(module for module in ALLOWED if module not in _by_module())
    assert stale == [], f"allow-list entries with nothing left to allow: {stale}"


def test_the_guard_sees_each_shape_of_read(tmp_path: Path) -> None:
    probe = tmp_path / "probe.py"
    probe.write_text(
        '"""Reads PLpgSQL_expr in prose only."""\n'
        "a = node['PLpgSQL_expr']\n"
        "b = stmt.get('PLpgSQL_stmt_if')\n"
        "c = expr.get('query')\n"
        "d = expr['query']\n",
        encoding="utf-8",
    )

    assert _second_readers(probe) == [2, 4, 5]


def test_a_query_key_alone_is_not_a_plpgsql_read(tmp_path: Path) -> None:
    probe = tmp_path / "probe.py"
    probe.write_text("sql = request.get('query')\n", encoding="utf-8")

    assert _second_readers(probe) == []


def test_the_reader_is_where_the_guard_points() -> None:
    assert _second_readers(READER), "the reader no longer reads a fragment: the guard is stale"
