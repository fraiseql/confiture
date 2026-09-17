"""No statement that creates a schema object may be silent (issue #288).

The accompaniment gate's whole value is that a schema change cannot pass it
unseen. Before #288 sixteen kinds of statement did, because the differ modelled
tables, enum types and sequences and nothing else — and nothing said so.

This is the guard against that returning. Every parse node in pglast's grammar
that *creates a named schema object* must be in exactly one of three places:

- ``TRACKED_NODES`` — diffed by ``core.ddl_objects``
- ``MODELLED_ELSEWHERE`` — diffed by ``SchemaDiffer`` some other way
- ``NOT_A_SCHEMA_OBJECT`` — declined, with the reason written down

A node in none of them fails here, which is what makes a pglast upgrade that
adds one a decision rather than a silent hole. The allow-list works the way
``test_one_sql_lexer.py``'s does: an entry that no longer matches anything fails
too, so a reason cannot outlive the thing it explains.
"""

import pglast.ast
import pytest

from confiture.core.ddl_objects import (
    MODELLED_ELSEWHERE,
    NOT_A_SCHEMA_OBJECT,
    TRACKED_NODES,
)

#: The grammar that creates things: every ``Create…Stmt``, plus the five
#: creating statements PostgreSQL does not spell with that prefix. Restricted to
#: *statements* — a schema file holds statements, and ``CreateOpClassItem`` and
#: its like are sub-nodes of one, reached only through the statement that owns
#: them. Every other ``*Stmt`` reads, alters, drops or configures; ``ALTER
#: TABLE`` is the one of those the differ folds in, in ``SchemaDiffer``.
CREATING_NODES = frozenset(
    {
        name
        for name in dir(pglast.ast)
        if name.startswith("Create")
        and name.endswith("Stmt")
        and isinstance(getattr(pglast.ast, name), type)
    }
    | {"ViewStmt", "IndexStmt", "RuleStmt", "DefineStmt", "CompositeTypeStmt"}
)


def test_the_grammar_has_not_moved_under_us():
    """A sanity floor: if this is tiny, the enumeration above stopped working."""
    assert len(CREATING_NODES) > 25


@pytest.mark.parametrize("node", sorted(CREATING_NODES))
def test_every_creating_node_is_accounted_for(node: str):
    homes = [
        home
        for home, names in (
            ("TRACKED_NODES", TRACKED_NODES),
            ("MODELLED_ELSEWHERE", MODELLED_ELSEWHERE),
            ("NOT_A_SCHEMA_OBJECT", NOT_A_SCHEMA_OBJECT),
        )
        if node in names
    ]
    assert homes, (
        f"{node} creates something and no one says what happens to it. "
        f"Track it in core.ddl_objects, or decline it in NOT_A_SCHEMA_OBJECT "
        f"with the reason."
    )
    assert len(homes) == 1, f"{node} is claimed by {homes}; it can only have one home"


def test_no_declined_node_has_gone_away():
    """An entry whose node pglast no longer has is a reason with nothing to explain."""
    stale = sorted(set(NOT_A_SCHEMA_OBJECT) | set(MODELLED_ELSEWHERE) - CREATING_NODES)
    unknown = [name for name in stale if not hasattr(pglast.ast, name)]
    assert unknown == [], f"declined nodes that pglast no longer defines: {unknown}"


def test_every_declined_node_states_a_reason():
    unreasoned = sorted(node for node, reason in NOT_A_SCHEMA_OBJECT.items() if not reason.strip())
    assert unreasoned == []


def test_tracked_nodes_are_creating_nodes():
    """Nothing is tracked that the enumeration above does not consider creating."""
    assert TRACKED_NODES <= CREATING_NODES
