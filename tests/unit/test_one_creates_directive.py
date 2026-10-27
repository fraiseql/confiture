"""One reader and one writer of ``-- confiture:creates``: ``core/created_relations.py``.

The directive tells ``migrate validate --idempotent`` and ``migrate fix
--idempotent`` that a plain ``CREATE`` is meant: the relation is new, and
PostgreSQL proves it so. A second module spelling the directive, or matching a
``Directive`` by the name ``creates``, would be a second answer to which
relations a file declares — and one that could loosen what the first refuses.
This test fails on the literal ``confiture:creates`` outside a docstring, an
f-string joining ``DIRECTIVE_PREFIX`` with ``creates``, or a comparison of a
``.name`` with ``"creates"``, anywhere under ``python/confiture/`` but the owner.
"""

import ast
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PACKAGE = REPO / "python" / "confiture"
OWNER = "python/confiture/core/created_relations.py"
#: Modules allowed to spell or match the directive, and why. Empty.
ALLOWED: dict[str, str] = {}


def _docstrings(tree: ast.AST) -> set[int]:
    return {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
    }


def _is_creates(node: ast.AST) -> bool:
    return isinstance(node, ast.Constant) and node.value == "creates"


def _names_prefix(node: ast.AST) -> bool:
    return (isinstance(node, ast.Name) and node.id == "DIRECTIVE_PREFIX") or (
        isinstance(node, ast.Attribute) and node.attr == "DIRECTIVE_PREFIX"
    )


def _spellings(source: str) -> list[int]:
    tree = ast.parse(source)
    docstrings = _docstrings(tree)
    found: list[int] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and "confiture:creates" in node.value.lower()
            and id(node) not in docstrings
        ):
            found.append(node.lineno)
        elif isinstance(node, ast.JoinedStr):
            parts = [v.value if isinstance(v, ast.FormattedValue) else v for v in node.values]
            text = "".join(
                p.value for p in parts if isinstance(p, ast.Constant) and isinstance(p.value, str)
            )
            if any(_names_prefix(p) for p in parts) and "creates" in text:
                found.append(node.lineno)
        elif isinstance(node, ast.Compare):
            operands = [node.left, *node.comparators]
            if any(isinstance(o, ast.Attribute) and o.attr == "name" for o in operands) and any(
                _is_creates(o) for o in operands
            ):
                found.append(node.lineno)
    return sorted(found)


def test_the_guard_sees_each_spelling() -> None:
    source = (
        'A = "-- confiture:creates t"\n'
        'B = f"-- {DIRECTIVE_PREFIX}creates {x}"\n'
        'C = [d for d in ds if d.name == "creates"]\n'
    )
    assert _spellings(source) == [1, 2, 3]


def test_no_module_spells_the_creates_directive_but_its_owner() -> None:
    found = {}
    for path in sorted(PACKAGE.rglob("*.py")):
        module = path.relative_to(REPO).as_posix()
        if module == OWNER or module in ALLOWED:
            continue
        if lines := _spellings(path.read_text(encoding="utf-8")):
            found[module] = lines
    assert found == {}, f"write and read the directive through created_relations: {found}"


def test_every_allowed_module_still_needs_its_entry() -> None:
    for module in ALLOWED:
        path = REPO / module
        assert path.exists(), module
        assert _spellings(path.read_text(encoding="utf-8")), f"{module} no longer spells it"
