"""A pg_tviews TVIEW is one object in the schema model (#504).

``CREATE TABLE tv_post AS SELECT …`` is turned by pg_tviews into a table, a
backing view ``v_post`` and triggers on each base table. The model holds the
TVIEW as one object — the relation's name and the query — so drift and preflight
compare a TVIEW, never its parts.
"""

from __future__ import annotations

import json

from confiture.core.schema_model import SchemaModel, TView, ref_for, tview_ref

POST = TView(name="tv_post", schema="app", definition="SELECT 1 AS pk_post")


def test_a_tview_is_keyed_by_its_relation() -> None:
    assert tview_ref(POST) == ref_for("tview", "app", "tv_post")


def test_a_tview_names_its_entity_and_its_backing_view() -> None:
    assert (POST.entity, POST.backing_view) == ("post", "v_post")


def test_the_wire_carries_tviews_and_reads_them_back() -> None:
    model = SchemaModel(tviews={tview_ref(POST): POST})

    assert json.loads(model.to_json())["tviews"] == [
        {
            "name": "tv_post",
            "schema": "app",
            "definition": "SELECT 1 AS pk_post",
            "logged": None,
            "fillfactor": None,
        }
    ]
    assert SchemaModel.from_json(model.to_json()) == model


def test_a_wire_written_before_tviews_reads_as_none() -> None:
    wire = json.loads(SchemaModel().to_json())
    del wire["tviews"]

    assert SchemaModel.from_json(json.dumps(wire)).tviews == {}


def test_the_wire_carries_the_storage_a_tview_pins() -> None:
    pinned = TView(name="tv_post", schema="app", logged=True, fillfactor=70)
    model = SchemaModel(tviews={tview_ref(pinned): pinned})

    assert SchemaModel.from_json(model.to_json()).tviews[tview_ref(pinned)] == pinned


def test_a_wire_written_before_storage_was_modelled_pins_none() -> None:
    wire = json.loads(SchemaModel(tviews={tview_ref(POST): POST}).to_json())
    for tview in wire["tviews"]:
        del tview["logged"], tview["fillfactor"]

    (read,) = SchemaModel.from_json(json.dumps(wire)).tviews.values()
    assert (read.logged, read.fillfactor) == (None, None)
