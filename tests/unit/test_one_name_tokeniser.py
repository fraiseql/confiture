"""One tokeniser for the words of a name: ``schema_identity.identifier_words``.

A rule that matches a name by what it means — a credential column, a status
word in a file name, a comment that restates its object, a renamed column —
asks for its words. Splitting on ``_`` by hand gets ``stripeApiKey`` wrong, and a
substring test gets ``tokenizer`` wrong; every rule that did either had its own
answer. This test fails on a new ``.split("_")``.

The modules allowed one *write* a name — a class name from a function name — or
read a fixed format (a rule code), never a name's meaning.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PACKAGE = REPO / "python" / "confiture"

ALLOWED: dict[str, str] = {
    "python/confiture/models/stub_models.py": "writes a Python class name from a routine name",
    "python/confiture/core/migration_generator.py": "writes a migration class name from its file",
    "python/confiture/core/linting/rule_registry.py": (
        "reads a rule code's `family_NNN` format, not a name's meaning"
    ),
}


def _splits(path: Path) -> list[int]:
    return sorted(
        node.lineno
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"split", "rsplit"}
        and [ast.unparse(arg) for arg in node.args[:1]] == ["'_'"]
    )


def _splitters() -> dict[str, list[int]]:
    found = {}
    for path in sorted(PACKAGE.rglob("*.py")):
        if lines := _splits(path):
            found[path.relative_to(REPO).as_posix()] = lines
    return found


def test_a_name_s_words_come_from_the_one_tokeniser() -> None:
    unexpected = {m: lines for m, lines in _splitters().items() if m not in ALLOWED}
    assert unexpected == {}, f"use schema_identity.identifier_words: {unexpected}"


def test_every_allowance_is_still_needed() -> None:
    assert sorted(set(ALLOWED) - set(_splitters())) == []
