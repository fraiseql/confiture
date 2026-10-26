"""A pg_tviews TVIEW is one object in the schema model (#504).

``CREATE TABLE tv_post AS SELECT …`` is turned by pg_tviews into a table, a
backing view in its own ``tviews`` schema and triggers on each base table. The model holds the
TVIEW as one object — the relation's name and the query — so drift and preflight
compare a TVIEW, never its parts.
"""

import json
from dataclasses import fields, replace

import pytest

from confiture.core.schema_model import (
    FunctionRead,
    Index,
    RelationName,
    SchemaModel,
    TView,
    UncascadedTable,
    parity_tview,
    ref_for,
    tview_ref,
)

POST = TView(name="tv_post", schema="app", definition="SELECT 1 AS pk_post")


def test_a_tview_is_keyed_by_its_relation() -> None:
    assert tview_ref(POST) == ref_for("tview", "app", "tv_post")


def test_a_tview_names_its_entity() -> None:
    assert POST.entity == "post"


def test_the_wire_carries_tviews_and_reads_them_back() -> None:
    model = SchemaModel(tviews={tview_ref(POST): POST})

    assert json.loads(model.to_json())["tviews"] == [
        {
            "name": "tv_post",
            "schema": "app",
            "definition": "SELECT 1 AS pk_post",
            "logged": None,
            "fillfactor": None,
            "uncascaded_policy": None,
            "time_refresh": None,
            "function_reads": None,
            "uncascaded_tables": None,
            "indexes": [],
            "managed_indexes": [],
            "other_options": {},
        }
    ]
    assert SchemaModel.from_json(model.to_json()) == model


def test_a_wire_written_before_tviews_reads_as_none() -> None:
    wire = json.loads(SchemaModel().to_json())
    del wire["tviews"]

    assert SchemaModel.from_json(json.dumps(wire)).tviews == {}


def test_the_wire_carries_the_storage_a_tview_pins() -> None:
    pinned = TView(
        name="tv_post", schema="app", logged=True, fillfactor=70, uncascaded_policy="full_refresh"
    )
    model = SchemaModel(tviews={tview_ref(pinned): pinned})

    assert SchemaModel.from_json(model.to_json()).tviews[tview_ref(pinned)] == pinned


def test_a_wire_written_before_storage_was_modelled_pins_none() -> None:
    wire = json.loads(SchemaModel(tviews={tview_ref(POST): POST}).to_json())
    for tview in wire["tviews"]:
        del tview["logged"], tview["fillfactor"]

    (read,) = SchemaModel.from_json(json.dumps(wire)).tviews.values()
    assert (read.logged, read.fillfactor) == (None, None)


def test_a_wire_written_before_the_uncascaded_policy_was_modelled_pins_none() -> None:
    wire = json.loads(SchemaModel(tviews={tview_ref(POST): POST}).to_json())
    for tview in wire["tviews"]:
        del tview["uncascaded_policy"]

    (read,) = SchemaModel.from_json(json.dumps(wire)).tviews.values()
    assert read.uncascaded_policy is None


READS = TView(
    name="tv_post",
    schema="app",
    time_refresh="external",
    function_reads=(
        FunctionRead("public.label_suffix()", ("public.tb_setting",)),
        FunctionRead("public.now_utc()", ()),
    ),
)


def test_the_wire_carries_what_a_tview_declares_of_its_reads() -> None:
    """pg_tviews' ``time_refresh`` and ``function_reads`` (fraiseql/pg_tviews#193)."""
    model = SchemaModel(tviews={tview_ref(READS): READS})

    (tview,) = json.loads(model.to_json())["tviews"]
    assert tview["time_refresh"] == "external"
    assert tview["function_reads"] == [
        {"function": "public.label_suffix()", "tables": ["public.tb_setting"]},
        {"function": "public.now_utc()", "tables": []},
    ]
    assert SchemaModel.from_json(model.to_json()).tviews[tview_ref(READS)] == READS


def test_a_wire_written_before_the_declared_reads_were_modelled_pins_none() -> None:
    wire = json.loads(SchemaModel(tviews={tview_ref(READS): READS}).to_json())
    for tview in wire["tviews"]:
        del tview["time_refresh"], tview["function_reads"]

    (read,) = SchemaModel.from_json(json.dumps(wire)).tviews.values()
    assert (read.time_refresh, read.function_reads) == (None, None)


TABLES = TView(
    name="tv_category",
    schema="app",
    uncascaded_tables=(
        UncascadedTable("app.tb_category", "full_refresh"),
        UncascadedTable("tb_setting", "warn"),
    ),
)


def test_the_wire_carries_each_table_s_uncascaded_policy() -> None:
    """pg_tviews' per-table ``uncascaded_tables`` (fraiseql/pg_tviews#195)."""
    model = SchemaModel(tviews={tview_ref(TABLES): TABLES})

    (tview,) = json.loads(model.to_json())["tviews"]
    assert tview["uncascaded_tables"] == [
        {"table": "app.tb_category", "policy": "full_refresh"},
        {"table": "tb_setting", "policy": "warn"},
    ]
    assert SchemaModel.from_json(model.to_json()).tviews[tview_ref(TABLES)] == TABLES


def test_a_wire_written_before_per_table_policies_were_modelled_pins_none() -> None:
    wire = json.loads(SchemaModel(tviews={tview_ref(TABLES): TABLES}).to_json())
    for tview in wire["tviews"]:
        del tview["uncascaded_tables"]

    (read,) = SchemaModel.from_json(json.dumps(wire)).tviews.values()
    assert read.uncascaded_tables is None


# A TVIEW's indexes: every one a tree writes on it, or, read from a database, the
# user's — pg_tviews' own (``tviews.registry.managed_indexes``) held apart.
_ON = RelationName("app", "tv_post")
TITLE = Index(name="ix_tv_post_title", table=_ON, columns=("title",))
MANAGED = Index(name="idx_tv_post_id", table=_ON, columns=("id",))
_FIELDS_BEFORE_INDEXES = (
    "name",
    "schema",
    "definition",
    "logged",
    "fillfactor",
    "uncascaded_policy",
    "time_refresh",
    "function_reads",
    "uncascaded_tables",
)


def _indexed(**given: object) -> TView:
    """``POST`` holding *given*: asserted first, so a missing field fails as an assertion."""
    assert {"indexes", "managed_indexes"} <= {f.name for f in fields(TView)}
    return replace(POST, **given)


def test_a_tview_keeps_its_constructor_shape() -> None:
    """The fields it gains are appended, so a positional caller is unchanged."""
    assert tuple(f.name for f in fields(TView))[: len(_FIELDS_BEFORE_INDEXES)] == (
        _FIELDS_BEFORE_INDEXES
    )
    assert TView("tv_post", "app", "SELECT 1 AS pk_post") == POST


def test_a_tview_holds_no_index_by_default() -> None:
    assert (getattr(POST, "indexes", None), getattr(POST, "managed_indexes", None)) == ((), ())


def test_the_wire_carries_a_tview_s_indexes_and_reads_them_back() -> None:
    indexed = _indexed(indexes=(TITLE,), managed_indexes=(MANAGED,))
    model = SchemaModel(tviews={tview_ref(indexed): indexed})

    (tview,) = json.loads(model.to_json())["tviews"]
    assert [i["name"] for i in tview["indexes"]] == ["ix_tv_post_title"]
    assert [i["name"] for i in tview["managed_indexes"]] == ["idx_tv_post_id"]
    (read,) = SchemaModel.from_json(model.to_json()).tviews.values()
    assert (read.indexes, read.managed_indexes) == ((TITLE,), (MANAGED,))


def test_indexes_not_read_round_trip_as_none() -> None:
    """``None`` is "not read" (``live_catalog.tviews()``), never "has none"."""
    unread = _indexed(indexes=None)
    model = SchemaModel(tviews={tview_ref(unread): unread})

    (read,) = SchemaModel.from_json(model.to_json()).tviews.values()
    assert read.indexes is None


def test_a_wire_written_before_tview_indexes_were_modelled_holds_none() -> None:
    wire = json.loads(SchemaModel(tviews={tview_ref(POST): POST}).to_json())
    for tview in wire["tviews"]:
        tview.pop("indexes", None)
        tview.pop("managed_indexes", None)

    (read,) = SchemaModel.from_json(json.dumps(wire)).tviews.values()
    assert (getattr(read, "indexes", None), getattr(read, "managed_indexes", None)) == ((), ())


def test_pg_tviews_own_indexes_are_not_what_a_tview_is() -> None:
    assert _indexed(managed_indexes=(MANAGED,)) == _indexed(managed_indexes=())
    assert _indexed(indexes=(TITLE,)) != _indexed(indexes=())


def test_parity_compares_a_tview_s_indexes_as_a_table_s_and_drops_pg_tviews_own() -> None:
    """Declaration order is not compared, and pg_tviews' own indexes are not the TVIEW's."""
    other = Index(name="ix_tv_post_author", table=_ON, columns=("author",))
    one = _indexed(indexes=(TITLE, other), managed_indexes=(MANAGED,))
    two = _indexed(indexes=(other, TITLE))

    assert parity_tview(one) == parity_tview(two)
    assert parity_tview(one).managed_indexes == ()
    assert parity_tview(_indexed(indexes=None)).indexes is None


@pytest.mark.parametrize(("logged", "pinned"), [(True, None), (False, False), (None, None)])
def test_a_tview_is_logged_unless_it_says_otherwise(
    logged: bool | None, pinned: bool | None
) -> None:
    """pg_tviews contract 2 creates a TVIEW LOGGED: ``logged: false`` is the only pin."""
    from confiture.core.schema_model import parity_tview

    assert parity_tview(TView(name="tv_post", logged=logged)).logged is pinned
