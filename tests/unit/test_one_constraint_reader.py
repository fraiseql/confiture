"""One foreign-key reader: ``core/ddl_walk.read_constraint`` (#511).

A foreign key is read once, from pglast's ``Constraint`` node, into
``schema_model.Constraint``. The regexes ``build.two_pass`` used instead read a
string literal as a key, wrote the source column as the referenced one and left
``MATCH FULL`` in the table, and ``migrate`` dry-run analysis and the replica
classifier each held a reader of their own. A module that takes a foreign key's
fields off the node itself, or matches one in text with a regex, is a second
reader and fails here.

Each entry below is ``module`` → the different question it asks. An entry that
matches nothing fails, so the table is an edit, never an escape.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
# The source tree, not the imported package: the Publish workflow runs this suite
# against the built wheel, where ``confiture.__file__`` lives in the virtualenv.
PACKAGE = REPO / "python" / "confiture"
READER = PACKAGE / "core" / "ddl_walk.py"

#: What a foreign key says, as pglast's ``Constraint`` node holds it.
FOREIGN_KEY_FIELDS = frozenset(
    {
        "pktable",
        "fk_attrs",
        "pk_attrs",
        "fk_matchtype",
        "fk_upd_action",
        "fk_del_action",
        "fk_del_set_cols",
    }
)

#: A pattern over SQL text that spells a foreign key's keywords.
_KEY_PATTERN = re.compile(r"(?:REFERENCES|FOREIGN)(?:\\s|\s*\\\()", re.IGNORECASE)

ALLOWED: dict[str, str] = {
    "core/linting/references.py": (
        "labels each relation a statement names with the clause that names it, so a "
        "forward reference reads 'FOREIGN KEY'; it takes the node, never what the key declares"
    ),
}


def _prose(tree: ast.AST) -> set[int]:
    return {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef)
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
    }


def _reads_a_key(node: ast.AST, prose: set[int]) -> bool:
    if isinstance(node, ast.Attribute):
        return node.attr in FOREIGN_KEY_FIELDS
    return (
        isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in prose
        and (node.value in FOREIGN_KEY_FIELDS or bool(_KEY_PATTERN.search(node.value)))
    )


def _second_readers(path: Path) -> list[int]:
    """Lines where *path* reads a foreign key by itself: a node's key fields, or a key regex."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    prose = _prose(tree)
    return sorted({node.lineno for node in ast.walk(tree) if _reads_a_key(node, prose)})


def _by_module() -> dict[str, list[int]]:
    found: dict[str, list[int]] = {}
    for path in sorted(PACKAGE.rglob("*.py")):
        if path == READER:
            continue
        lines = _second_readers(path)
        if lines:
            found[path.relative_to(PACKAGE).as_posix()] = lines
    return found


def test_no_module_reads_a_foreign_key_by_itself() -> None:
    offenders = [
        f"{module} (lines {lines})"
        for module, lines in _by_module().items()
        if module not in ALLOWED
    ]
    assert offenders == [], (
        "a second foreign-key reader — read the node with ddl_walk.read_constraint and "
        "write it with ddl_clauses.constraint_body:\n  " + "\n  ".join(offenders)
    )


def test_allow_list_is_current() -> None:
    stale = sorted(module for module in ALLOWED if module not in _by_module())
    assert stale == [], f"allow-list entries with nothing left to allow: {stale}"


def test_the_guard_sees_each_shape_of_read(tmp_path: Path) -> None:
    probe = tmp_path / "probe.py"
    probe.write_text(
        'r"""Mentions REFERENCES\\s+ in prose only."""\n'
        "a = node.pktable\n"
        "b = getattr(node, 'fk_attrs', None)\n"
        "c = re.compile(r'\\s+REFERENCES\\s+(\\w+)')\n"
        "d = r'FOREIGN\\s+KEY\\s*\\(([^)]+)\\)'\n"
        "e = 'the key REFERENCES a table'\n",
        encoding="utf-8",
    )

    assert _second_readers(probe) == [2, 3, 4, 5]


def test_the_reader_is_where_the_guard_points() -> None:
    assert _second_readers(READER), "the reader no longer reads a key: the guard is stale"
