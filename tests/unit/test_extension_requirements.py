"""An extension one side's extension requires is that side's too, between a tree and a database.

``CREATE EXTENSION earthdistance CASCADE`` installs ``cube`` (and, from
0.1.0-beta.35, ``CREATE EXTENSION pg_tviews CASCADE`` installs ``jsonb_delta``):
the database holds an extension the tree never wrote, and holds it because the
tree asked for it. What each extension requires is the server's answer
(``live_catalog.extension_requirements``), stubbed here;
``tests/integration/test_drift_agrees_with_diff.py`` reads it from a server.
"""

from dataclasses import replace

from confiture.core.change_order import apply_order
from confiture.core.differ import EXACT, SchemaDiffer, Side
from confiture.core.differ_sql import DifferSQLGenerator
from confiture.core.schema_change import ObjectAdded, ObjectDropped, SchemaChange
from confiture.core.schema_read import read_text

REQUIRES = {"earthdistance": frozenset({"cube"})}


def _tree(sql: str) -> Side:
    return Side.of(read_text(sql))


def _database(sql: str, requires: dict[str, frozenset[str]] = REQUIRES) -> Side:
    """A database holding what *sql* creates, as its server reads it back: an extension by name."""
    side = Side.of(read_text(sql), held=True)
    others = {ref: replace(o, definition=None) for ref, o in side.model.other_objects.items()}
    model = replace(side.model, source="catalog", other_objects=others)
    return replace(side, model=model, requires=requires)


def _extensions(changes: list[SchemaChange]) -> list[tuple[str, str]]:
    return [
        (type(change).__name__, change.ref.name)
        for change in changes
        if isinstance(change, ObjectAdded | ObjectDropped)
    ]


BOTH = "CREATE EXTENSION earthdistance CASCADE; CREATE EXTENSION cube;"


def test_an_extension_cascade_installed_is_the_trees() -> None:
    diff = SchemaDiffer().compare_sides(
        _database(BOTH), _tree("CREATE EXTENSION earthdistance CASCADE;")
    )

    assert diff.changes == []


def test_the_tree_may_write_it_too() -> None:
    diff = SchemaDiffer().compare_sides(
        _database(BOTH), _tree("CREATE EXTENSION cube; CREATE EXTENSION earthdistance;")
    )

    assert diff.changes == []


def test_it_is_the_trees_whichever_side_the_tree_is() -> None:
    diff = SchemaDiffer().compare_sides(
        _tree("CREATE EXTENSION earthdistance CASCADE;"), _database(BOTH)
    )

    assert diff.changes == []


def test_a_required_extension_the_database_already_holds_is_never_dropped() -> None:
    diff = SchemaDiffer().compare_sides(
        _database("CREATE EXTENSION cube;"), _tree("CREATE EXTENSION earthdistance CASCADE;")
    )

    assert _extensions(diff.changes) == [("ObjectAdded", "earthdistance")]


def test_without_its_requirer_it_is_compared_and_dropped_after_it() -> None:
    """A tree that stops creating earthdistance holds no cube either: both go, requirer first."""
    diff = SchemaDiffer().compare_sides(_database(BOTH), _tree("CREATE TABLE t (id int);"))

    ordered = apply_order(diff.changes)
    assert _extensions(ordered) == [
        ("ObjectDropped", "earthdistance"),
        ("ObjectDropped", "cube"),
    ]
    up = "".join(DifferSQLGenerator().generate_up(c) or "" for c in ordered)
    assert up.index("earthdistance") < up.index("cube")


def test_an_extension_is_created_after_what_it_requires() -> None:
    requires = {"alpha": frozenset({"zeta"})}

    diff = SchemaDiffer().compare_sides(
        _database("CREATE TABLE t (id int);", requires),
        _tree("CREATE TABLE t (id int); CREATE EXTENSION alpha; CREATE EXTENSION zeta;"),
    )

    assert _extensions(apply_order(diff.changes)) == [
        ("ObjectAdded", "zeta"),
        ("ObjectAdded", "alpha"),
    ]


def test_a_requirement_through_another_is_followed() -> None:
    requires = {"top": frozenset({"middle"}), "middle": frozenset({"base"})}
    database = "CREATE EXTENSION top; CREATE EXTENSION middle; CREATE EXTENSION base;"

    diff = SchemaDiffer().compare_sides(
        _database(database, requires), _tree("CREATE EXTENSION top CASCADE;")
    )

    assert diff.changes == []


def test_the_server_is_what_knows_it() -> None:
    """With no requirement read, cube is an extension the tree does not create."""
    diff = SchemaDiffer().compare_sides(
        _database(BOTH, {}), _tree("CREATE EXTENSION earthdistance CASCADE;")
    )

    assert _extensions(diff.changes) == [("ObjectDropped", "cube")]


def test_two_databases_compare_what_each_holds() -> None:
    old = _database(BOTH)
    new = _database("CREATE EXTENSION earthdistance;")

    diff = SchemaDiffer().compare_sides(old, new, EXACT)

    assert _extensions(diff.changes) == [("ObjectDropped", "cube")]
