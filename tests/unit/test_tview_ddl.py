"""The DDL side reads a TVIEW: ``CREATE TABLE tv_<entity> AS SELECT`` (#504).

pg_tviews intercepts a ``CREATE TABLE … AS`` whose target is named ``tv_*``,
and only that one, so the reader applies the same rule. Until #504 the
statement was invisible: neither a table nor a view.
"""

from __future__ import annotations

import pglast
import pytest
from pglast.stream import RawStream

from confiture.core.linting.inventory import build_model
from confiture.core.schema_model import TView, ref_for

SELECT = "SELECT p.pk_post, p.id FROM tb_post p"
TABLES = "CREATE TABLE tb_post (pk_post bigint PRIMARY KEY, id uuid);\n"


def _rendered(select: str) -> str:
    return RawStream()(pglast.parse_sql(select)[0].stmt)


@pytest.mark.parametrize(
    ("target", "schema"), [("tv_post", None), ("app.tv_post", "app")], ids=["bare", "qualified"]
)
def test_a_create_table_as_into_tv_is_a_tview(target: str, schema: str | None) -> None:
    model = build_model(f"{TABLES}CREATE TABLE {target} AS {SELECT};\n")

    assert model.tviews == {
        ref_for("tview", schema, "tv_post"): TView(
            name="tv_post", schema=schema, definition=_rendered(SELECT)
        )
    }
    assert ref_for("table", schema, "tv_post") not in model.tables


def test_a_create_table_as_into_another_name_is_no_tview() -> None:
    model = build_model(f"{TABLES}CREATE TABLE post_copy AS {SELECT};\n")

    assert model.tviews == {}


def test_a_materialized_view_is_still_a_view() -> None:
    model = build_model(f"{TABLES}CREATE MATERIALIZED VIEW tv_post AS {SELECT};\n")

    assert model.tviews == {}
    assert ref_for("matview", None, "tv_post") in model.views


def test_drop_table_drops_the_tview() -> None:
    model = build_model(f"{TABLES}CREATE TABLE tv_post AS {SELECT};\nDROP TABLE tv_post;\n")

    assert model.tviews == {}


def test_a_changed_tview_is_an_object_that_changed() -> None:
    """``migrate validate --require-migration`` compares tracked objects by definition."""
    from confiture.core.ddl_objects import objects_in

    def tracked(select: str) -> dict:
        sql = f"{TABLES}CREATE TABLE tv_post AS {select};\n"
        return objects_in(sql, list(pglast.parse_sql(sql)))

    before, after = tracked(SELECT), tracked("SELECT p.pk_post FROM tb_post p")
    ref = ref_for("tview", None, "tv_post")
    assert before.keys() == after.keys() == {ref}
    assert before[ref][0].definition != after[ref][0].definition


def test_a_table_named_tv_with_columns_is_a_table() -> None:
    """``tv_`` is a common naming convention with no pg_tviews anywhere: the shape decides.

    A production project fraisier deploys holds ten ``CREATE TABLE public.tv_x (…)``
    and no pg_tviews. Read by the prefix, each would be a TVIEW the database lacks —
    ten critical ``missing_tview`` on a clean deploy.
    """
    model = build_model("CREATE TABLE public.tv_order (id bigint PRIMARY KEY, data jsonb);\n")

    assert model.tviews == {}
    assert ref_for("table", "public", "tv_order") in model.tables


def test_a_tview_carries_the_storage_its_statement_pins() -> None:
    """``UNLOGGED`` and ``WITH (fillfactor = n)`` are pg_tviews' ``logged`` and ``fillfactor``."""
    model = build_model(
        f"{TABLES}CREATE UNLOGGED TABLE tv_post WITH (fillfactor = 70) AS {SELECT};\n"
    )

    (tview,) = model.tviews.values()
    assert (tview.logged, tview.fillfactor) == (False, 70)


def test_a_tview_that_pins_nothing_carries_no_storage() -> None:
    """An unpinned key is pg_tviews' to choose, and the tree's to leave alone."""
    (tview,) = build_model(f"{TABLES}CREATE TABLE tv_post AS {SELECT};\n").tviews.values()

    assert (tview.logged, tview.fillfactor) == (None, None)
