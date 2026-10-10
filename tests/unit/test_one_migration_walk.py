"""One migration walk: a classifier reads a migration's statements through ``migration_scope.walk``.

Each classifier that judges a migration's statements — the replica verdict, the
change set, the TVIEW preflight — used to loop over them itself and keep its own
fold of what earlier statements did; a fold in one and not another let two
verdicts on one file disagree (ARCHITECTURE Decision 9, as amended). This fails
on such a module calling the lexer's statement entry points itself.
"""

import ast
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PACKAGE = REPO / "python" / "confiture"

#: The lexer's ways to a migration's statements.
ENTRIES = frozenset({"parse_file", "parse", "split_statements"})

#: The modules that judge a migration statement by statement.
CLASSIFIERS = (
    "core/replica/classifier.py",
    "core/change_set/walker.py",
    "core/tview_preflight.py",
)


def _lexer_calls(path: Path) -> list[int]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported = {
        alias.asname or alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and (node.module or "").endswith("sql_lexer")
        for alias in node.names
        if alias.name in ENTRIES
    }
    return [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and (
            (isinstance(node.func, ast.Name) and node.func.id in imported)
            or (
                isinstance(node.func, ast.Attribute)
                and node.func.attr in ENTRIES
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "sql_lexer"
            )
        )
    ]


def test_every_classifier_walks_through_the_scope() -> None:
    found = {module: _lexer_calls(PACKAGE / module) for module in CLASSIFIERS}

    assert {m: lines for m, lines in found.items() if lines} == {}, (
        "read a migration's statements through migration_scope.walk"
    )


def test_every_classifier_imports_the_walk() -> None:
    missing = [
        module
        for module in CLASSIFIERS
        if "migration_scope" not in (PACKAGE / module).read_text(encoding="utf-8")
    ]

    assert missing == []
