"""A ``tviews.registry`` row, read under contract 2: every option is a key of ``options``.

The rows are what pg_tviews answered for each tree in ``tests/fixtures/pg_tviews_registry/``
(``scripts/capture_pg_tviews_registry.py``), never rows written by hand.
"""

import json
from pathlib import Path
from typing import Any

import pytest

from confiture.core import live_catalog
from confiture.core.schema_model import FunctionRead, UncascadedTable

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "pg_tviews_registry"


def _captured(case: str) -> dict[str, Any]:
    return json.loads((FIXTURES / f"{case}.json").read_text())


def _row(case: str, name: str) -> dict[str, Any]:
    return next(row for row in _captured(case)["registry"] if row["name"] == name)


@pytest.mark.parametrize("case", ["defaults", "unlogged", "declared", "aggregate"])
def test_every_fixture_was_captured_from_the_contract_confiture_reads(case: str) -> None:
    assert _captured(case)["captured_from"]["contract"] == live_catalog.CONTRACT_VERSION


def test_a_tview_that_declares_nothing_reads_every_default() -> None:
    """pg_tviews fills every key: LOGGED, fillfactor 85, policy ``error``, nothing declared."""
    tview = live_catalog.registry_tview(_row("defaults", "tv_post"))

    assert (tview.schema, tview.name) == ("public", "tv_post")
    assert tview.logged is True
    assert tview.fillfactor == 85
    assert tview.uncascaded_policy == "error"
    assert tview.time_refresh is None
    assert tview.function_reads == ()
    assert tview.uncascaded_tables == ()


def test_the_storage_a_create_table_as_says_is_read() -> None:
    tview = live_catalog.registry_tview(_row("unlogged", "tv_post"))

    assert (tview.logged, tview.fillfactor) == (False, 70)


def test_every_option_a_call_declares_is_read_from_options() -> None:
    tview = live_catalog.registry_tview(_row("declared", "tv_user"))

    assert (tview.logged, tview.fillfactor) == (False, 90)
    assert tview.uncascaded_policy == "full_refresh"
    assert tview.uncascaded_tables == (UncascadedTable("tb_label", "warn"),)
    assert tview.function_reads == (FunctionRead("public.label_of(bigint)", ("tb_setting",)),)


def test_time_refresh_is_read_from_options() -> None:
    assert live_catalog.registry_tview(_row("declared", "tv_visit")).time_refresh == "external"


def test_the_query_is_held_as_the_tree_s_is() -> None:
    """One deparser on both sides: ``rendered_query`` of the registry's ``query``."""
    from confiture.core.ddl_walk import rendered_query

    row = _row("defaults", "tv_post")

    assert live_catalog.registry_tview(row).definition == rendered_query(row["query"])


def test_a_column_or_key_appended_later_is_ignored() -> None:
    """Additive changes do not bump the contract: read by name, ignore what is unknown."""
    row = _row("declared", "tv_user")
    later = {
        **row,
        "a_later_column": [1],
        "options": {**row["options"], "a_later_option": True},
    }

    assert live_catalog.registry_tview(later) == live_catalog.registry_tview(row)


def test_the_options_confiture_does_not_model_are_carried_as_the_registry_holds_them() -> None:
    """Every key, so the call written from a database passes back what it holds (the round trip)."""
    tview = live_catalog.registry_tview(_row("declared", "tv_user"))

    assert tview.other_options["data_gin_index"] is True
    assert tview.other_options["typename"] == "Member"
    assert tview.other_options["indexes"] == [["name"]]
    assert tview.other_options["data_storage"] == "extended"
    assert "logged" not in tview.other_options
    assert "function_reads" not in tview.other_options


def test_the_aggregate_s_group_keys_are_carried() -> None:
    tview = live_catalog.registry_tview(_row("aggregate", "tv_user_summary"))

    assert tview.other_options["group_keys"] == {"tb_order": "fk_user", "tb_user": "pk_user"}


def test_carried_options_are_never_compared() -> None:
    """The model compares the keys it models; the rest are the database's, carried for the call."""
    from dataclasses import replace

    tview = live_catalog.registry_tview(_row("declared", "tv_user"))

    assert replace(tview, other_options={}) == tview
