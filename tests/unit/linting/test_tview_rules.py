"""``tview_001`` and ``tview_002``: a TVIEW's storage, read from the tree (#504).

``tview_002`` waits on fraiseql/pg_tviews#75 and is deleted with it.
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


def test_a_tview_as_pg_tviews_creates_it_is_fine() -> None:
    """pg_tviews 0.1.0-beta.18 indexes each ``fk_*`` and sets fillfactor 85 itself."""
    for code in ("tview_001", "tview_002"):
        assert _findings(TVIEW, code) == []


@pytest.mark.parametrize(
    "index",
    [
        "CREATE INDEX ix ON tv_post USING gin (data);",
        "CREATE INDEX ix ON tv_post ((data->>'email'));",
        "CREATE INDEX ix ON tv_post (updated_at);",
    ],
)
def test_an_index_over_a_column_every_refresh_rewrites_blocks_hot(index: str) -> None:
    (finding,) = _findings(TVIEW + index + "\n", "tview_001")

    assert "ix" in finding.message


def test_an_index_on_a_stable_column_is_fine() -> None:
    sql = TVIEW + "CREATE INDEX ix ON tv_post (fk_user, pk_post);\n"

    assert _findings(sql, "tview_001") == []


def test_an_unlogged_tview_with_replicas_is_named() -> None:
    (finding,) = _findings(TVIEW, "tview_002", replicas=True)

    assert finding.object_name == "tv_post"


def test_no_replicas_nothing_to_say() -> None:
    assert _findings(TVIEW, "tview_002", replicas=False) == []


def test_set_logged_satisfies_it() -> None:
    sql = TVIEW + "ALTER TABLE tv_post SET LOGGED;\n"

    assert _findings(sql, "tview_002", replicas=True) == []


def test_set_unlogged_after_set_logged_is_unlogged_again() -> None:
    sql = TVIEW + "ALTER TABLE tv_post SET LOGGED;\nALTER TABLE tv_post SET UNLOGGED;\n"

    assert len(_findings(sql, "tview_002", replicas=True)) == 1


def test_a_plain_table_named_tv_with_a_column_list_is_not_a_tview() -> None:
    sql = (
        "CREATE TABLE tv_note (id int, data jsonb);\nCREATE INDEX ix ON tv_note USING gin (data);\n"
    )

    assert _findings(sql, "tview_001") == []
