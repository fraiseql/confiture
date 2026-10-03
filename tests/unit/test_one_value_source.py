"""One answer to "where does this column's value come from": ``Column.value_source``.

The readers classify a default once, from its parse tree, while they hold it
(``ddl_walk.default_kind``); the model derives the rest from the column's own
fields. Before, the seed writer's ``writable_columns``, parity and drift each
decided for themselves — two of them by matching ``nextval(`` in text. This
test fails on a module that decides again: one that names ``SERIAL_TYPES`` or
matches ``nextval(`` in a string.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PACKAGE = REPO / "python" / "confiture"
#: The model, which derives the answer, and the reader that classifies a default.
OWNERS = frozenset({"python/confiture/core/schema_model.py", "python/confiture/core/ddl_walk.py"})


def _deciders(path: Path) -> list[int]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docstrings = {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
    }
    return sorted(
        node.lineno
        for node in ast.walk(tree)
        if (isinstance(node, ast.Name) and node.id == "SERIAL_TYPES")
        or (isinstance(node, ast.Attribute) and node.attr == "SERIAL_TYPES")
        or (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and "nextval(" in node.value
            and id(node) not in docstrings
        )
    )


def test_no_module_decides_where_a_value_comes_from_again() -> None:
    found = {}
    for path in sorted(PACKAGE.rglob("*.py")):
        module = path.relative_to(REPO).as_posix()
        if module not in OWNERS and (lines := _deciders(path)):
            found[module] = lines
    assert found == {}, f"read Column.value_source instead: {found}"
