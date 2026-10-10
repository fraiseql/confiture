"""A pg_tviews TVIEW is one object in the schema model (#504).

``CREATE TABLE tv_post AS SELECT …`` is turned by pg_tviews into a table, a
backing view in its own ``tviews`` schema and triggers on each base table. The model holds the
TVIEW as one object — the relation's name and the query — so drift and preflight
compare a TVIEW, never its parts.
"""

import json

from confiture.core.schema_model import (
    FunctionRead,
    SchemaModel,
    TView,
    UncascadedTable,
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
