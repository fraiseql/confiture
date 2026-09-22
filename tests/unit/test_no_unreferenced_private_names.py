"""A private module-level name that nothing reads is dead code, and dead code misleads.

The regex backends went when pglast became the one parser, and their patterns stayed:
a reader meeting ``_RE_ADD_COLUMN`` in the replica classifier reasonably assumes
something matches with it. A name spelled with a leading underscore promises that
its module is its reader — or a sibling that imports it by name — so "nothing reads
it" is decidable from the package alone, with no guess about external callers. It is
decided per module: two modules each defining a private ``_RE_ADD_COLUMN`` do not
keep each other alive. Public names are out of
scope here: a consumer may read those, and the orphan census answers for modules.
"""

from __future__ import annotations

import ast
import re
from collections import Counter
from pathlib import Path

import confiture

PACKAGE = Path(confiture.__file__).resolve().parent


def _defined_private_names(tree: ast.Module) -> list[tuple[str, int]]:
    found: list[tuple[str, int]] = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            names = [node.name]
        elif isinstance(node, ast.Assign):
            names = [t.id for t in node.targets if isinstance(t, ast.Name)]
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names = [node.target.id]
        else:
            continue
        found.extend(
            (name, node.lineno)
            for name in names
            if name.startswith("_") and not name.startswith("__")
        )
    return found


def _read_elsewhere(sources: dict[Path, str]) -> set[str]:
    """Private names another module imports by name or reads as an attribute."""
    names: set[str] = set()
    for text in sources.values():
        for node in ast.walk(ast.parse(text)):
            if isinstance(node, ast.ImportFrom):
                names.update(alias.name for alias in node.names)
            elif isinstance(node, ast.Attribute) and node.attr.startswith("_"):
                names.add(node.attr)
    return names


def test_every_private_module_name_is_read_somewhere() -> None:
    sources = {path: path.read_text(encoding="utf-8") for path in PACKAGE.rglob("*.py")}
    elsewhere = _read_elsewhere(sources)
    unread = [
        f"{path.relative_to(PACKAGE)}:{lineno}: {name}"
        for path, text in sorted(sources.items())
        for name, lineno in _defined_private_names(ast.parse(text))
        if Counter(re.findall(r"\b\w+\b", text))[name] == 1 and name not in elsewhere
    ]
    assert unread == [], "private names nothing reads:\n" + "\n".join(unread)


def test_the_check_sees_an_unread_name() -> None:
    tree = ast.parse("_READ = 1\n_UNREAD = 2\nx = _READ\n")
    assert [n for n, _ in _defined_private_names(tree)] == ["_READ", "_UNREAD"]
