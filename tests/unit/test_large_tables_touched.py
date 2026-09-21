"""Which tables a change set touches are large enough to name, without a database."""

from __future__ import annotations

from confiture.core.large_tables import LARGE_TABLE_THRESHOLD, LargeTable, large_tables, table_of

ESTIMATES = {
    "tenant.tb_stat": LARGE_TABLE_THRESHOLD,
    "public.tb_stat": 3,
    "app.tb_small": LARGE_TABLE_THRESHOLD - 1,
    "app.tb_fresh": None,
}


def test_a_target_names_its_table_whatever_it_names_inside_it() -> None:
    assert table_of("tenant.tb_stat") == "tenant.tb_stat"
    assert table_of("tenant.tb_stat.note") == "tenant.tb_stat"
    assert table_of("unknown") is None


def test_the_large_and_the_unmeasured_are_named_by_schema() -> None:
    targets = ["tenant.tb_stat.note", "app.tb_small.note", "app.tb_fresh", "tenant.tb_stat"]

    assert large_tables(targets, ESTIMATES) == [
        LargeTable("app.tb_fresh", None),
        LargeTable("tenant.tb_stat", LARGE_TABLE_THRESHOLD),
    ]


def test_a_table_the_database_has_not_got_is_not_named() -> None:
    """A table the migration creates, or a function: nothing to weigh."""
    assert large_tables(["app.tb_new", "app.fn"], ESTIMATES) == []


def test_the_same_name_in_another_schema_is_another_table() -> None:
    assert large_tables(["public.tb_stat"], ESTIMATES) == []
