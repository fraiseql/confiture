"""A view, matview, trigger or routine the DDL declares and the database lacks (#303).

`compare_schemas` ran three passes — tables, columns, indexes — so a dropped
view, materialized view, trigger or routine was `has_drift: false`, `exit 0`, on
the gate a deploy is failed by. The three body-drift checks do not cover it
either: each compares only the **intersection** of source and live keys, by
design.

The expected side is `ddl_objects.objects_in`, which #288 already built and which
models the kinds the lint inventory does not — a trigger among them. This is the
comparison over the two.

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

import pglast

from confiture.core.ddl_objects import objects_in
from confiture.core.drift import compare_objects
from confiture.core.linting.inventory import signature_from_type_names
from confiture.core.live_objects import LiveObject, LiveObjects

KINDS = frozenset({"view", "matview", "trigger", "function", "procedure", "aggregate"})

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


def expected(sql: str = DECLARED):
    return objects_in(sql, list(pglast.parse_sql(sql) or []))


def live(*objects: LiveObject) -> LiveObjects:
    return LiveObjects(objects=list(objects), kinds_read=KINDS)


def routine(name: str, *types: str, kind: str = "function", schema: str = "core") -> LiveObject:
    return LiveObject(
        kind=kind, schema=schema, name=name, signature=signature_from_type_names(types)
    )


def everything_live() -> LiveObjects:
    return live(
        LiveObject("view", "core", "v_widget"),
        LiveObject("matview", "core", "mv_widget"),
        LiveObject("trigger", "core", "tb_widget.trg_touch"),
        routine("fn_touch"),
        routine("fn_gone", "bigint"),
        routine("pr_noop", kind="procedure"),
    )


def keys(items) -> list[tuple[str, str, str]]:
    return sorted((i.drift_type.value, i.severity.value, i.object_name) for i in items)


def test_a_database_holding_everything_reports_nothing() -> None:
    assert compare_objects(expected(), everything_live()) == []


def test_a_missing_view_is_critical() -> None:
    present = [o for o in everything_live().objects if o.name != "v_widget"]
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
    live_objects = live(
        LiveObject("view", "core", "v_widget"),
        LiveObject("matview", "core", "mv_widget"),
        LiveObject("trigger", "core", "tb_widget.trg_touch"),
        routine("fn_touch"),
        routine("fn_gone", "int8"),
        routine("pr_noop", kind="procedure"),
    )
    assert compare_objects(expected(), live_objects) == []


def test_an_extra_object_of_a_declared_kind_is_info() -> None:
    items = compare_objects(
        expected(), live(*everything_live().objects, LiveObject("view", "core", "v_surprise"))
    )
    assert keys(items) == [("extra_view", "info", "core.v_surprise")]


def test_an_extra_object_of_a_kind_the_tree_does_not_declare_is_silent() -> None:
    """ "This project does not manage matviews here" and "this project has lost
    all its matviews" are indistinguishable from an empty expected set."""
    tree = "CREATE SCHEMA core;\nCREATE VIEW core.v AS SELECT 1;"
    items = compare_objects(
        expected(tree),
        live(LiveObject("view", "core", "v"), LiveObject("matview", "core", "mv_nobody_declared")),
    )
    assert items == []


def test_an_extra_object_in_a_schema_the_tree_does_not_declare_is_silent() -> None:
    items = compare_objects(
        expected(), live(*everything_live().objects, LiveObject("view", "elsewhere", "v_theirs"))
    )
    assert items == []


def test_a_kind_the_catalog_did_not_read_is_never_missing() -> None:
    """Silence from a kind nobody asked about is not evidence of absence."""
    read_nothing = LiveObjects(objects=[], kinds_read=frozenset())
    assert compare_objects(expected(), read_nothing) == []
