"""One ALTER folder: ``core/ddl_walk.py`` decides what an ``ALTER TABLE`` does to a column.

Two readers fold ``ALTER TABLE`` into an expected schema — the lint inventory
and the differ — and before #301 each had its own idea of which subcommands
exist. The differ folded ``ADD COLUMN``, ``DROP COLUMN`` and
``ALTER COLUMN … TYPE``; the inventory folded ``ADD COLUMN`` and a primary-key
flag. So `confiture drift`, which reads the inventory, reported a **critical**
``missing_column`` for a column the tree itself had dropped, on a database
applied verbatim from that tree — while `migrate diff`, reading the differ, saw
it correctly.

The dispatch now lives once, in ``ddl_walk.column_edit``. This guard fails on a
second one: any module that compares a value against an ``AlterTableType``
member, or against a bare integer reached from a ``subtype`` attribute.

The four allow-list entries are not folds. Each asks a *different question* of
the same node — is this observable by an N-1 replica reader, what risk tier is
it, does it carry its own ``IF NOT EXISTS``, which object does a finding name —
and a different question has a different answer. An entry that no longer matches
anything fails too, as in the one-lexer, one-path-matcher and one-canonicaliser
guards: a reason cannot outlive the thing it explains.
"""

from __future__ import annotations

import ast
from pathlib import Path

import confiture

PACKAGE = Path(confiture.__file__).resolve().parent
FOLDER = PACKAGE / "core" / "ddl_walk.py"
RESOLVER = PACKAGE / "core" / "_pglast_enums.py"

#: Modules that read an ``AlterTableType`` member for a question that is not
#: "what does this do to the expected schema", with the question each asks.
ALLOWED: dict[str, str] = {
    "core/replica/classifier.py": (
        "asks whether a subcommand is observable by an N-1 replica reader — a "
        "forward-compatibility verdict about an operation, not a column edit to fold"
    ),
    "core/change_set/walker.py": (
        "asks what risk tier the operation carries, which is a judgement about "
        "applying it rather than a statement about the schema it leaves behind"
    ),
    "core/idempotency/ast_detector.py": (
        "asks whether the statement carries its own `IF NOT EXISTS` guard; the "
        "subtype tells it which guard would even be available"
    ),
    "core/idempotency/_captures.py": (
        "captures the object an idempotency finding names — the module CLAUDE.md "
        "cites for hiding an ordinal *inline*, as `sub_int == 17`"
    ),
}


def _reads_alter_table_type(path: Path) -> list[int]:
    """Lines where a module resolves or compares an ``AlterTableType`` member."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:  # pragma: no cover - the package parses
        return []
    found: list[int] = []
    for node in ast.walk(tree):
        names_the_enum = (
            # `member("AlterTableType", "AT_…")` / `enums.AlterTableType.AT_…`
            (isinstance(node, ast.Constant) and node.value == "AlterTableType")
            or (isinstance(node, ast.Attribute) and node.attr == "AlterTableType")
            # A bare integer compared against something read off `.subtype`,
            # which is how `_captures.py` survived the first #192 sweep: the
            # ordinal was inline, and a grep for `_NAME = <int>` cannot see it.
            or (isinstance(node, ast.Compare) and _is_subtype_ordinal_compare(node))
        )
        if names_the_enum:
            found.append(node.lineno)
    return sorted(set(found))


def _is_subtype_ordinal_compare(node: ast.Compare) -> bool:
    """``x == 17`` where ``x`` is named for, or read from, a ``subtype``."""
    names = [node.left, *node.comparators]
    reads_subtype = any(
        (isinstance(n, ast.Attribute) and n.attr == "subtype")
        or (isinstance(n, ast.Name) and "subtype" in n.id.lower())
        or (isinstance(n, ast.Name) and n.id.lower().startswith(("sub_", "subtype")))
        for n in names
    )
    literal_int = any(isinstance(n, ast.Constant) and isinstance(n.value, int) for n in names)
    return reads_subtype and literal_int


def _readers_outside_the_folder() -> dict[str, list[int]]:
    found: dict[str, list[int]] = {}
    for path in sorted(PACKAGE.rglob("*.py")):
        if path in {FOLDER, RESOLVER}:
            continue
        lines = _reads_alter_table_type(path)
        if lines:
            found[path.relative_to(PACKAGE).as_posix()] = lines
    return found


def test_the_folder_still_holds_the_dispatch() -> None:
    """The guard is worth nothing if its predicate stopped matching the real one."""
    assert _reads_alter_table_type(FOLDER), (
        "core/ddl_walk.py no longer reads an AlterTableType member; the guard's "
        "predicate has drifted off the thing it guards"
    )


def test_no_second_alter_folder() -> None:
    offenders = [
        f"{module}:{line}"
        for module, lines in _readers_outside_the_folder().items()
        if module not in ALLOWED
        for line in lines
    ]
    assert offenders == [], (
        "AlterTableType read outside core/ddl_walk.py:\n  "
        + "\n  ".join(offenders)
        + "\nFold it through `ddl_walk.column_edit`, or allow-list the module "
        "with the question it asks instead."
    )


def test_allow_list_is_current() -> None:
    present = set(_readers_outside_the_folder())
    stale = sorted(module for module in ALLOWED if module not in present)
    assert stale == [], f"allow-list entries with nothing left to allow: {stale}"


def test_every_allow_list_entry_states_a_question() -> None:
    unreasoned = sorted(module for module, reason in ALLOWED.items() if not reason.strip())
    assert unreasoned == []
