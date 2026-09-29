"""A pg_tviews TVIEW is compared as one object: missing is critical, extra is info (#504).

Until #504 the DDL side dropped ``CREATE TABLE tv_post AS SELECT …`` and the live
side read ``tv_post`` as a table, so every TVIEW project reported
``extra_table warning public.tv_post`` (measured on 1.26.0) — failing
``--fail-on-warning`` on a database built from its own DDL.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from confiture.core.drift import DriftType, SchemaDriftDetector, parse_expected_schema
from confiture.core.schema_model import SchemaModel, Table, TView, ref_for, tview_ref

DECLARED = """
CREATE TABLE tb_post (pk_post bigint PRIMARY KEY);
CREATE TABLE tv_post AS SELECT pk_post FROM tb_post;
"""

POST = Table(name="tb_post", schema="public")


def live(*tviews: TView) -> SchemaModel:
    expected_table = parse_expected_schema(DECLARED).model.tables
    return SchemaModel(tables=expected_table, tviews={tview_ref(t): t for t in tviews})


def compare(live_model: SchemaModel):
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value.fetchone.return_value = ("db",)
    expected = parse_expected_schema(DECLARED).model
    return SchemaDriftDetector(conn).compare_schemas(expected, live_model, objects=True).drift_items


def keys(items) -> list[tuple[str, str, str]]:
    return sorted((i.drift_type.value, i.severity.value, i.object_name) for i in items)


def test_the_expected_side_holds_the_tview_and_no_table_for_it() -> None:
    model = parse_expected_schema(DECLARED).model
    assert list(model.tviews) == [ref_for("tview", "public", "tv_post")]
    assert ref_for("table", "public", "tv_post") not in model.tables


def test_a_database_holding_the_tview_reports_nothing() -> None:
    assert compare(live(TView(name="tv_post", schema="public"))) == []


def test_a_missing_tview_is_critical() -> None:
    assert keys(compare(live())) == [("missing_tview", "critical", "tv_post")]


def test_an_extra_tview_is_info() -> None:
    found = compare(
        live(TView(name="tv_post", schema="public"), TView(name="tv_user", schema="public"))
    )
    assert keys(found) == [("extra_tview", "info", "public.tv_user")]


def test_the_kinds_are_published() -> None:
    assert (DriftType.MISSING_TVIEW.value, DriftType.EXTRA_TVIEW.value) == (
        "missing_tview",
        "extra_tview",
    )
