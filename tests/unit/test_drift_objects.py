"""A view, matview, trigger or routine the DDL declares and the database lacks (#303).

`compare_schemas` ran three passes — tables, columns, indexes — so a dropped
view, materialized view, trigger or routine was `has_drift: false`, `exit 0`, on
the gate a deploy is failed by. The three body-drift checks do not cover it
either: each compares only the **intersection** of source and live keys, by
design.

Both sides are the schema model — the expected one read from the DDL (a trigger
through `ddl_objects`, which #288 built), the live one from `live_catalog` — and
the comparison is `compare_schemas`', asked with `objects=True`: there is no
second function, and no second model of a live object.

Two rules decide what is reported, and both exist to keep a pristine database
silent:

* **a missing object is CRITICAL**, by analogy with `missing_column`: the DDL
  declares it and the database has not got it;
* **an extra object is reported only for a kind the DDL declares at least one
  of**, in a schema the DDL declares, because "this project does not manage views
  here" and "this project has lost all its views" are indistinguishable from an
  empty expected set.

A function, a procedure and an aggregate share one pair of drift types
(`missing_routine` / `extra_routine`): the object's own name says which it is,
and three more members of a published enum would say nothing new.
"""

from __future__ import annotations

import importlib
from collections import defaultdict
from unittest.mock import MagicMock

import pytest

from confiture.core.drift import SchemaDriftDetector, parse_expected_schema
from confiture.core.schema_model import (
    Routine,
    SchemaModel,
    Trigger,
    View,
    routine_ref,
    trigger_ref,
    view_ref,
)
from confiture.core.type_lattice import signature_from_type_names

DECLARED = """
CREATE SCHEMA core;
CREATE VIEW core.v_widget AS SELECT 1 AS id;
CREATE MATERIALIZED VIEW core.mv_widget AS SELECT 1 AS n;
CREATE FUNCTION core.fn_touch() RETURNS TRIGGER LANGUAGE plpgsql AS $$ BEGIN RETURN NEW; END $$;
CREATE TRIGGER trg_touch BEFORE UPDATE ON core.tb_widget
    FOR EACH ROW EXECUTE FUNCTION core.fn_touch();
CREATE FUNCTION core.fn_gone(widget_id BIGINT) RETURNS BIGINT LANGUAGE sql AS $$ SELECT 1 $$;
CREATE PROCEDURE core.pr_noop() LANGUAGE plpgsql AS $$ BEGIN NULL; END $$;
"""


def expected(sql: str = DECLARED) -> SchemaModel:
    return parse_expected_schema(sql).model


def live(*objects: View | Routine | Trigger) -> SchemaModel:
    routines: dict = defaultdict(list)
    for obj in objects:
        if isinstance(obj, Routine):
            routines[routine_ref(obj)].append(obj)
    return SchemaModel(
        views={view_ref(o): o for o in objects if isinstance(o, View)},
        routines={ref: tuple(found) for ref, found in routines.items()},
        triggers={trigger_ref(o): o for o in objects if isinstance(o, Trigger)},
    )


def view(schema: str, name: str, *, materialized: bool = False) -> View:
    return View(name=name, schema=schema, materialized=materialized)


def routine(name: str, *types: str, kind: str = "function", schema: str = "core") -> Routine:
    return Routine(
        name=name,
        schema=schema,
        kind=kind,  # type: ignore[arg-type]
        signature=", ".join(types),
        signature_key=signature_from_type_names(types),
    )


def everything() -> tuple[View | Routine | Trigger, ...]:
    return (
        view("core", "v_widget"),
        view("core", "mv_widget", materialized=True),
        Trigger(name="trg_touch", table="tb_widget", schema="core"),
        routine("fn_touch"),
        routine("fn_gone", "bigint"),
        routine("pr_noop", kind="procedure"),
    )


def compare_objects(expected_model: SchemaModel, live_model: SchemaModel, *, objects: bool = True):
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value.fetchone.return_value = ("db",)
    detector = SchemaDriftDetector(conn)
    return detector.compare_schemas(expected_model, live_model, objects=objects).drift_items


def keys(items) -> list[tuple[str, str, str]]:
    return sorted((i.drift_type.value, i.severity.value, i.object_name) for i in items)


def test_the_second_model_of_a_live_object_is_gone() -> None:
    with pytest.raises(ImportError):
        importlib.import_module("confiture.core.live_objects")


def test_a_database_holding_everything_reports_nothing() -> None:
    assert compare_objects(expected(), live(*everything())) == []


def test_the_objects_compared_are_counted() -> None:
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value.fetchone.return_value = ("db",)
    report = SchemaDriftDetector(conn).compare_schemas(
        expected(), live(*everything()), objects=True
    )
    assert report.objects_checked == 6


def test_a_missing_view_is_critical() -> None:
    present = [o for o in everything() if o.name != "v_widget"]
    assert keys(compare_objects(expected(), live(*present))) == [
        ("missing_view", "critical", "core.v_widget")
    ]


def test_a_missing_matview_a_missing_trigger_and_a_missing_routine() -> None:
    assert keys(compare_objects(expected(), live())) == [
        ("missing_matview", "critical", "core.mv_widget"),
        ("missing_routine", "critical", "core.fn_gone(bigint)"),
        ("missing_routine", "critical", "core.fn_touch()"),
        ("missing_routine", "critical", "core.pr_noop()"),
        ("missing_trigger", "critical", "core.tb_widget.trg_touch"),
        ("missing_view", "critical", "core.v_widget"),
    ]


def test_a_routine_respelled_is_the_same_routine() -> None:
    """`fn_gone(bigint)` in the tree and `fn_gone(int8)` live are one routine.

    Keying on the spelling reported a DROP and an ADD for one respelled routine,
    which #288 already paid for once (#275).
    """
    live_model = live(
        view("core", "v_widget"),
        view("core", "mv_widget", materialized=True),
        Trigger(name="trg_touch", table="tb_widget", schema="core"),
        routine("fn_touch"),
        routine("fn_gone", "int8"),
        routine("pr_noop", kind="procedure"),
    )
    assert compare_objects(expected(), live_model) == []


def test_an_extra_object_of_a_declared_kind_is_info() -> None:
    items = compare_objects(expected(), live(*everything(), view("core", "v_surprise")))
    assert keys(items) == [("extra_view", "info", "core.v_surprise")]


def test_an_extra_object_of_a_kind_the_tree_does_not_declare_is_silent() -> None:
    """ "This project does not manage matviews here" and "this project has lost
    all its matviews" are indistinguishable from an empty expected set."""
    tree = "CREATE SCHEMA core;\nCREATE VIEW core.v AS SELECT 1;"
    items = compare_objects(
        expected(tree),
        live(view("core", "v"), view("core", "mv_nobody_declared", materialized=True)),
    )
    assert items == []


def test_an_extra_object_in_a_schema_the_tree_does_not_declare_is_silent() -> None:
    items = compare_objects(expected(), live(*everything(), view("elsewhere", "v_theirs")))
    assert items == []


def test_a_kind_the_catalog_did_not_read_is_never_missing() -> None:
    """Silence from a kind nobody asked about is not evidence of absence."""
    assert compare_objects(expected(), SchemaModel(), objects=False) == []
