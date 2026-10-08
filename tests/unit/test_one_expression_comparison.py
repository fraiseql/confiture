"""One comparison of two expressions: ``ddl_walk.same_value``.

A default, a CHECK, a generation expression, an index key and a partial index's
predicate are each text one side wrote and the other may hold re-spelled —
PostgreSQL stores them analysed and prints constants its own way (#564). Before,
the differ compared a default with ``!=`` and drift ran a canonicaliser of its own
over index keys, so the two disagreed about one database. This test fails on a
module that compares one of those fields with ``==`` or ``!=``, and on a field
the engine compares by name that :data:`NAMED` does not answer for.
"""

import ast
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PACKAGE = REPO / "python" / "confiture"

#: The model's expression fields.
EXPRESSIONS = frozenset({"default", "generated", "expression", "where", "predicate"})

#: The engine modules whose comparisons name fields as strings.
ENGINE = ("core/differ.py", "core/drift.py")

#: Each expression field the engine compares by name, and why it is not a value
#: comparison. Both sides have been through ``parity_constraint`` / ``parity_indexes``
#: first: between two trees or two databases the text is one writer's spelling, and
#: between a tree and a database ``analysed_expressions`` reduces it to that it
#: exists — the stored text is PostgreSQL's analysis, which only a database built
#: from the tree can be compared with, and the materialised tier builds one.
NAMED: dict[str, str] = {
    "core/differ.py:expression": (
        "a CHECK paired and compared by its parity rendering: as written, existence, or "
        "— materialised — as stored on both sides"
    ),
    "core/differ.py:where": (
        "an EXCLUDE constraint's or a partial index's predicate, compared by its parity "
        "rendering: as written, existence, or — materialised — as stored on both sides"
    ),
}


def _compared(tree: ast.AST) -> list[int]:
    """Lines comparing an expression field with ``==``/``!=`` to anything but ``None``."""
    lines = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare):
            continue
        if not any(isinstance(op, (ast.Eq, ast.NotEq)) for op in node.ops):
            continue
        operands = [node.left, *node.comparators]
        if any(isinstance(o, ast.Constant) for o in operands):
            continue
        if any(isinstance(o, ast.Attribute) and o.attr in EXPRESSIONS for o in operands):
            lines.append(node.lineno)
    return lines


def _named(tree: ast.AST) -> set[str]:
    """Expression fields a tuple of field names holds."""
    return {
        element.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Tuple)
        and node.elts
        and all(isinstance(e, ast.Constant) and isinstance(e.value, str) for e in node.elts)
        for element in node.elts
        if isinstance(element, ast.Constant) and element.value in EXPRESSIONS
    }


def test_no_module_compares_an_expression_field_itself() -> None:
    found = [
        f"{path.relative_to(PACKAGE)}:{line}"
        for path in sorted(PACKAGE.rglob("*.py"))
        for line in _compared(ast.parse(path.read_text(encoding="utf-8")))
    ]
    assert found == [], "compare an expression through ddl_walk.same_value"


def test_every_field_the_engine_names_is_answered_for() -> None:
    named = {
        f"{module}:{field}"
        for module in ENGINE
        for field in _named(ast.parse((PACKAGE / module).read_text(encoding="utf-8")))
    }
    assert named == set(NAMED)


def test_the_detector_sees_a_comparison_and_not_a_presence_check() -> None:
    assert _compared(ast.parse("old.default != new.default")) == [1]
    assert _compared(ast.parse("x = a.where == b.where")) == [1]
    assert _compared(ast.parse("c.default is None or c.default == None")) == []
    assert _named(ast.parse("f(('columns', 'where'))")) == {"where"}
