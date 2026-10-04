"""Every constraint kind PostgreSQL's grammar has is decided, once (#315).

``core/ddl_walk.py`` reads a ``Constraint`` node in one place, for every model
of a table — the lint inventory's and the differ's alike. What made #315
possible was not that ``CONSTR_FOREIGN`` was forgotten but that nothing said
which kinds the reader answered for — so a kind nobody had considered looked
exactly like a kind deliberately skipped.

This enumerates pglast's own ``ConstrType`` rather than a hand-written list, so
a member PostgreSQL adds fails here instead of falling silently through the
dispatch. Same shape as ``test_ddl_objects_are_exhaustive`` and the
``AlterTableType`` guard in ``test_one_alter_folder``.

Both directions hold: a member pglast defines that nobody decided fails, and so
does a decision about a member pglast no longer defines. confiture supports one
pglast major, so no member is tolerated as defined by only part of a range.
"""

from pglast.enums.parsenodes import ConstrType

from confiture.core._pglast_enums import REQUIRED_MEMBERS
from confiture.core.ddl_walk import (
    CONSTRAINT_READERS,
    MODELLED_CONSTRAINTS,
    NOT_MODELLED_CONSTRAINTS,
)


def _members() -> set[str]:
    return {member.name for member in ConstrType}


def test_the_grammar_has_not_moved_under_us() -> None:
    """A sanity floor: if this is tiny, the enumeration above stopped working."""
    assert len(_members()) > 10


def test_every_constraint_kind_is_decided() -> None:
    undecided = sorted(_members() - set(MODELLED_CONSTRAINTS) - set(NOT_MODELLED_CONSTRAINTS))
    assert undecided == [], (
        f"{undecided} can appear in DDL and nothing says what the model does with it. "
        "Read it in MODELLED_CONSTRAINTS, or decline it in NOT_MODELLED_CONSTRAINTS "
        "with the reason."
    )


def test_no_kind_is_both_read_and_declined() -> None:
    both = sorted(set(MODELLED_CONSTRAINTS) & set(NOT_MODELLED_CONSTRAINTS))
    assert both == [], f"{both} is claimed by both tables; a kind can only have one home"


def test_no_decision_has_gone_stale() -> None:
    """A reason for a member this pglast does not define explains nothing."""
    decided = set(MODELLED_CONSTRAINTS) | set(NOT_MODELLED_CONSTRAINTS)
    stale = sorted(decided - _members())
    assert stale == [], f"decided kinds that pglast no longer defines: {stale}"


def test_every_declined_kind_states_a_reason() -> None:
    unreasoned = sorted(
        kind for kind, reason in NOT_MODELLED_CONSTRAINTS.items() if not reason.strip()
    )
    assert unreasoned == []


def test_the_reader_declares_the_members_it_depends_on() -> None:
    """Every kind the reader dispatches on is in ``_pglast_enums.REQUIRED_MEMBERS``.

    That table is what ``test_pglast_enum_binding`` enumerates, so a kind this
    reader starts depending on joins the CONFIG_011 check automatically rather
    than by being remembered.
    """
    assert set(MODELLED_CONSTRAINTS) == set(REQUIRED_MEMBERS["ConstrType"])


def test_the_dispatch_resolves_every_modelled_kind_by_name() -> None:
    """Resolved through ``_pglast_enums.member``, never against a literal ordinal.

    PostgreSQL 18 renumbered ``AlterTableType``; a hardcoded ordinal then stops
    matching silently, which is the whole of #192.
    """
    assert len(CONSTRAINT_READERS) == len(MODELLED_CONSTRAINTS)
    for name in MODELLED_CONSTRAINTS:
        assert int(getattr(ConstrType, name)) in CONSTRAINT_READERS
