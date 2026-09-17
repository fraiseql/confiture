"""No statement that changes a declared object may be silently absent (#301).

`tests/unit/test_alter_subtypes_are_exhaustive.py` accounts for every
``AlterTableType`` member. That guard is worth less than it looks if the
statement *kinds* around it are unaccounted for, which they were:
``DROP TABLE``, ``ALTER TABLE … RENAME COLUMN``, ``ALTER TABLE … RENAME TO`` and
``ALTER TABLE … SET SCHEMA`` are a ``DropStmt``, two ``RenameStmt`` and an
``AlterObjectSchemaStmt``. A tree that dropped a table still expected it — one
critical ``missing_table`` against a database matching the tree exactly — and a
subtype guard would have called the surface complete.

So every statement in pglast's grammar that *changes or removes* something
already declared must be in exactly one of

- ``FOLDED_STATEMENTS`` — read by ``ddl_walk.object_edits``
- ``MODELLED_STATEMENTS`` — reached another way, with where
- ``NOT_AN_EXPECTED_SCHEMA_STATEMENT`` — declined, with the reason written down

The enumeration is mechanical: every ``Alter…Stmt``, ``Drop…Stmt`` and
``Rename…Stmt`` pglast defines. Creating statements are
``test_ddl_objects_are_exhaustive.py``'s subject and are not repeated here.
"""

from __future__ import annotations

import pglast.ast
import pytest

from confiture.core.ddl_walk import (
    FOLDED_STATEMENTS,
    MODELLED_STATEMENTS,
    NOT_AN_EXPECTED_SCHEMA_STATEMENT,
)

#: Every statement node that alters, drops or renames. Mechanical on purpose: a
#: hand-written list is the thing this guard exists to replace.
MUTATING_NODES = frozenset(
    name
    for name in dir(pglast.ast)
    if name.endswith("Stmt")
    and name.startswith(("Alter", "Drop", "Rename"))
    and isinstance(getattr(pglast.ast, name), type)
)

TABLES = (
    ("FOLDED_STATEMENTS", FOLDED_STATEMENTS),
    ("MODELLED_STATEMENTS", MODELLED_STATEMENTS),
    ("NOT_AN_EXPECTED_SCHEMA_STATEMENT", NOT_AN_EXPECTED_SCHEMA_STATEMENT),
)


def test_the_grammar_has_not_moved_under_us() -> None:
    """A floor: if this is tiny, the enumeration above stopped working."""
    assert len(MUTATING_NODES) > 30


@pytest.mark.parametrize("node", sorted(MUTATING_NODES))
def test_every_mutating_statement_is_accounted_for(node: str) -> None:
    homes = [name for name, table in TABLES if node in table]
    assert homes, (
        f"{node} changes something already declared and no one says what happens "
        f"to it. Fold it in ddl_walk.object_edits, or decline it in "
        f"NOT_AN_EXPECTED_SCHEMA_STATEMENT with the reason."
    )
    assert len(homes) == 1, f"{node} is claimed by {homes}; it can only have one home"


def test_no_listed_statement_has_gone_away() -> None:
    """An entry pglast no longer defines is a reason with nothing to explain."""
    listed = {node for _name, table in TABLES for node in table}
    assert sorted(listed - MUTATING_NODES) == []


def test_every_declined_statement_states_a_reason() -> None:
    unreasoned = sorted(
        node for node, reason in NOT_AN_EXPECTED_SCHEMA_STATEMENT.items() if len(reason.split()) < 8
    )
    assert unreasoned == [], f"reasons too thin to be reasons: {unreasoned}"


def test_the_four_statements_this_guard_exists_for_are_folded() -> None:
    """The three node types behind #301's second half, named."""
    assert {"DropStmt", "RenameStmt", "AlterObjectSchemaStmt"} <= FOLDED_STATEMENTS
