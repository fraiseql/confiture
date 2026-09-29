"""``tview_001`` … ``tview_004``: a TVIEW's storage, read from the tree (#504).

Each rule waits on a pg_tviews issue (#71, #70, #73, #75) and is deleted with it.
"""

from __future__ import annotations

import pytest

from confiture.core.linting.gate import Threshold
from confiture.core.linting.schema_linter import LintViolation, SchemaLinter
from confiture.core.linting.selection import linter_config

BASE = "CREATE TABLE tb_post (pk_post bigint PRIMARY KEY, id uuid, fk_user bigint, title text);\n"
TVIEW = (
    "CREATE TABLE tv_post AS SELECT p.pk_post, p.id, p.fk_user, "
    "jsonb_build_object('title', p.title) AS data FROM tb_post p;\n"
)


def _findings(sql: str, code: str, *, replicas: bool = False) -> list[LintViolation]:
    config = linter_config(frozenset({code}), Threshold.NEVER, has_replicas=replicas)
    report = SchemaLinter(env="local", config=config).lint(BASE + sql)
    return [v for v in [*report.errors, *report.warnings, *report.info] if v.rule_id == code]


def test_a_foreign_key_column_without_an_index_is_named() -> None:
    (finding,) = _findings(TVIEW, "tview_001")

    assert finding.object_name == "tv_post"
    assert "fk_user" in finding.message
    assert finding.suggested_fix == "CREATE INDEX ON tv_post (fk_user, pk_post);"


def test_an_index_leading_with_the_foreign_key_satisfies_it() -> None:
    sql = TVIEW + "CREATE INDEX ON tv_post (fk_user, pk_post);\n"

    assert _findings(sql, "tview_001") == []


def test_a_tview_without_foreign_keys_has_nothing_to_index() -> None:
    sql = "CREATE TABLE tv_post AS SELECT p.pk_post, p.id, p.title AS data FROM tb_post p;\n"

    assert _findings(sql, "tview_001") == []


@pytest.mark.parametrize(
    "index",
    [
        "CREATE INDEX ix ON tv_post USING gin (data);",
        "CREATE INDEX ix ON tv_post ((data->>'email'));",
        "CREATE INDEX ix ON tv_post (updated_at);",
    ],
)
def test_an_index_over_a_column_every_refresh_rewrites_blocks_hot(index: str) -> None:
    (finding,) = _findings(TVIEW + index + "\n", "tview_002")

    assert "ix" in finding.message


def test_an_index_on_a_stable_column_is_fine() -> None:
    sql = TVIEW + "CREATE INDEX ix ON tv_post (fk_user, pk_post);\n"

    assert _findings(sql, "tview_002") == []


def test_a_tview_left_at_fillfactor_100_is_named() -> None:
    (finding,) = _findings(TVIEW, "tview_003")

    assert finding.object_name == "tv_post"


@pytest.mark.parametrize("value", ["85", "70"])
def test_a_lower_fillfactor_satisfies_it(value: str) -> None:
    sql = TVIEW + f"ALTER TABLE tv_post SET (fillfactor = {value});\n"

    assert _findings(sql, "tview_003") == []


def test_fillfactor_100_is_still_full_pages() -> None:
    sql = TVIEW + "ALTER TABLE tv_post SET (fillfactor = 100);\n"

    assert len(_findings(sql, "tview_003")) == 1


def test_an_unlogged_tview_with_replicas_is_named() -> None:
    (finding,) = _findings(TVIEW, "tview_004", replicas=True)

    assert finding.object_name == "tv_post"


def test_no_replicas_nothing_to_say() -> None:
    assert _findings(TVIEW, "tview_004", replicas=False) == []


def test_set_logged_satisfies_it() -> None:
    sql = TVIEW + "ALTER TABLE tv_post SET LOGGED;\n"

    assert _findings(sql, "tview_004", replicas=True) == []


def test_a_plain_table_named_tv_with_a_column_list_is_not_a_tview() -> None:
    sql = "CREATE TABLE tv_note (id int, fk_x bigint);\n"

    assert _findings(sql, "tview_001") == []
