"""No ``ALTER TABLE`` subcommand may be silently absent from the expected schema (#301).

A build-from-DDL tree may append an ``ALTER TABLE`` rather than edit the
``CREATE TABLE``, so the expected schema is the two together. Which subcommands
it is built from was, until #301, whatever each of the two readers happened to
need: the differ folded three of the 66 ``AlterTableType`` members, the lint
inventory two, and a column the tree itself dropped was reported as **critical**
drift against a database applied verbatim from that tree.

This is ``test_ddl_objects_are_exhaustive.py``'s lesson one module over. #288's
sixteen invisible statement kinds "were not sixteen oversights but one: nothing
said which statements the differ answered for, so a kind never considered looked
exactly like a kind deliberately skipped."

So every member of pglast's own enum must be in exactly one of

- ``FOLDED`` — read by ``ddl_walk.column_edit`` into a ``ColumnEdit``
- ``MODELLED_ELSEWHERE`` — an expected-schema fact reached another way, with where
- ``NOT_AN_EXPECTED_SCHEMA_FACT`` — declined, with the reason written down

and the tables live in the module, not here: a table in a test is documentation,
a table in the module is a decision the code is made of. Enumerating pglast's
enum rather than iterating the tables is what catches a member a future
PostgreSQL adds; ``_pglast_enums.enums_are_usable`` covers the other direction,
a member that goes away.
"""

from __future__ import annotations

import pglast.enums
import pytest

from confiture.core.ddl_walk import (
    FOLDED,
    MODELLED_ELSEWHERE,
    NOT_AN_EXPECTED_SCHEMA_FACT,
)

MEMBERS = sorted(member.name for member in pglast.enums.AlterTableType)

TABLES = (
    ("FOLDED", FOLDED),
    ("MODELLED_ELSEWHERE", MODELLED_ELSEWHERE),
    ("NOT_AN_EXPECTED_SCHEMA_FACT", NOT_AN_EXPECTED_SCHEMA_FACT),
)


def test_the_enum_has_not_moved_under_us() -> None:
    """A floor: if this is tiny, the enumeration above stopped working."""
    assert len(MEMBERS) > 50


@pytest.mark.parametrize("member", MEMBERS)
def test_every_subtype_is_accounted_for(member: str) -> None:
    homes = [name for name, table in TABLES if member in table]
    assert homes, (
        f"{member} changes something and no one says what happens to it. "
        f"Fold it in ddl_walk.column_edit, or decline it in "
        f"NOT_AN_EXPECTED_SCHEMA_FACT with the reason."
    )
    assert len(homes) == 1, f"{member} is claimed by {homes}; it can only have one home"


def test_no_listed_subtype_has_gone_away() -> None:
    """An entry pglast no longer defines is a reason with nothing to explain."""
    listed = {member for _name, table in TABLES for member in table}
    assert sorted(listed - set(MEMBERS)) == []


def test_every_declined_subtype_states_a_reason() -> None:
    unreasoned = sorted(
        member for member, reason in NOT_AN_EXPECTED_SCHEMA_FACT.items() if not reason.strip()
    )
    assert unreasoned == []


def test_every_reason_says_something() -> None:
    """A table of reasons whose reasons are all one word is a list.

    Not a style check: "not relevant" as a reason is how a member nobody thought
    about comes to look like one that was decided.
    """
    thin = sorted(
        member
        for table in (MODELLED_ELSEWHERE, NOT_AN_EXPECTED_SCHEMA_FACT)
        for member, reason in table.items()
        if len(reason.split()) < 8
    )
    assert thin == [], f"reasons too thin to be reasons: {thin}"
