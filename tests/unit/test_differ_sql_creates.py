"""``DifferSQLGenerator.creates`` names exactly the relations the rendering creates plainly.

The generator writes one ``-- confiture:creates`` line per name ``creates``
returns, and ``migrate validate --idempotent`` accepts a plain create only
under a name so declared. A name the rendering creates plainly but ``creates``
omits is a migration that fails its own idempotency check; a name ``creates``
returns that the rendering never creates is a declaration of nothing. So
the two are compared over every change the corpus holds, up and down, in
both modes, by what PostgreSQL's parser reads from the rendering.
"""

from pathlib import Path

import pglast
import pytest

from confiture.core._pglast_enums import member
from confiture.core.created_relations import relation_named
from confiture.core.ddl_objects import DDLObject
from confiture.core.differ import SchemaDiffer
from confiture.core.differ_sql import DifferSQLGenerator
from confiture.core.schema_change import ObjectAdded, ObjectReplaced, SchemaChange
from tests.unit._schema_changes import ref
from tests.unit.test_schema_change_tiers import CHANGES as DEFINITION_CHANGES

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
_MATVIEW = member("ObjectType", "OBJECT_MATVIEW")


def _pair(name: str) -> list[SchemaChange]:
    old = (FIXTURES / name / "old.sql").read_text(encoding="utf-8")
    new = (FIXTURES / name / "new.sql").read_text(encoding="utf-8")
    return list(SchemaDiffer().compare(old, new).changes)


CORPUS: list[SchemaChange] = [
    *_pair("every_change"),
    *_pair("matview_indexes"),
    *DEFINITION_CHANGES,
]


def _plain_creates(sql: str | None) -> list[tuple[str | None, str]]:
    """``(schemaname, relname)`` of every table and matview *sql* creates without IF NOT EXISTS."""
    found = []
    for raw in pglast.parse_sql(sql or ""):
        stmt = raw.stmt
        kind = type(stmt).__name__
        if kind == "CreateStmt" and not stmt.if_not_exists:
            found.append((stmt.relation.schemaname, stmt.relation.relname))
        elif kind == "CreateTableAsStmt" and stmt.objtype == _MATVIEW and not stmt.if_not_exists:
            found.append((stmt.into.rel.schemaname, stmt.into.rel.relname))
    return found


def _label(change: SchemaChange) -> str:
    wire = change.to_wire()
    return f"{wire.type}:{wire.table}"


@pytest.mark.parametrize("plain", [True, False], ids=["plain", "not_plain"])
@pytest.mark.parametrize("down", [False, True], ids=["up", "down"])
@pytest.mark.parametrize("change", CORPUS, ids=_label)
def test_creates_names_every_plain_create(change: SchemaChange, down: bool, plain: bool) -> None:
    gen = DifferSQLGenerator()
    render = gen.generate_down if down else gen.generate_up
    sql = render(change, plain_creates=plain)
    named = [
        relation_named(spelling) for spelling in gen.creates(change, down=down, plain_creates=plain)
    ]
    assert named == _plain_creates(sql)
    if not plain:
        assert named == []


def test_the_corpus_creates_something_plainly() -> None:
    gen = DifferSQLGenerator()
    up = [c for c in CORPUS if gen.creates(c, plain_creates=True)]
    down = [c for c in CORPUS if gen.creates(c, down=True, plain_creates=True)]
    assert {type(c).__name__ for c in up} >= {"TableAdded", "ObjectAdded", "ObjectReplaced"}
    assert {type(c).__name__ for c in down} >= {"TableDropped", "ObjectDropped", "ObjectReplaced"}


def test_creates_spells_the_created_object_not_the_change() -> None:
    old = DDLObject(
        ref=ref("matview", "mv"),
        definition="CREATE MATERIALIZED VIEW mv AS SELECT 1 AS a",
        create_sql="CREATE MATERIALIZED VIEW IF NOT EXISTS mv AS SELECT 1 AS a",
    )
    new = DDLObject(
        ref=ref("matview", "public.mv"),
        definition="CREATE MATERIALIZED VIEW public.mv AS SELECT 2 AS a",
        create_sql="CREATE MATERIALIZED VIEW IF NOT EXISTS public.mv AS SELECT 2 AS a",
    )
    change = ObjectReplaced(old.ref, old, new)
    gen = DifferSQLGenerator()
    assert gen.creates(change, plain_creates=True) == ("public.mv",)
    assert gen.creates(change, down=True, plain_creates=True) == ("mv",)


def test_creates_is_empty_for_an_object_with_no_definition() -> None:
    empty = DDLObject(ref=ref("matview", "mv"), definition="", create_sql="")
    change = ObjectAdded(empty.ref, empty)
    assert DifferSQLGenerator().creates(change, plain_creates=True) == ()


def test_the_wire_keeps_the_reappliable_matview_definition() -> None:
    [change] = [
        c
        for c in SchemaDiffer().compare("", "CREATE MATERIALIZED VIEW mv AS SELECT 1 AS a;").changes
        if isinstance(c, ObjectAdded)
    ]
    assert "IF NOT EXISTS" in (change.to_wire().new_value or "")
