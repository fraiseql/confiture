"""Preflight names a change to what a registered pg_tviews TVIEW reads (#504).

``PFLIGHT_TVIEW_BASE_COLUMN`` is PostgreSQL's own dependency on the TVIEW's backing view.
"""

from __future__ import annotations

from pathlib import Path

from confiture.core.tview_preflight import live_issues
from confiture.models.results import PFLIGHT_CODES, PreflightIssue

TVIEWS = {"public.tv_post": "SELECT p.id, p.title FROM public.tb_post p"}


def _live(tmp_path: Path, sql: str) -> list[PreflightIssue]:
    (tmp_path / "20260929000002_m.up.sql").write_text(sql)
    return live_issues([tmp_path / "20260929000002_m.up.sql"], TVIEWS)


def test_dropping_a_column_a_tview_reads_is_an_error(tmp_path: Path) -> None:
    (issue,) = _live(tmp_path, "ALTER TABLE public.tb_post DROP COLUMN title;")

    assert issue.code == "PFLIGHT_TVIEW_BASE_COLUMN"
    assert issue.severity == "error"
    assert issue.migration == "20260929000002"
    assert issue.details["tview"] == "public.tv_post"
    assert issue.details["column"] == "title"


def test_retyping_a_column_a_tview_reads_is_an_error(tmp_path: Path) -> None:
    (issue,) = _live(tmp_path, "ALTER TABLE tb_post ALTER COLUMN title TYPE text;")

    assert issue.code == "PFLIGHT_TVIEW_BASE_COLUMN"


def test_dropping_a_base_table_is_an_error(tmp_path: Path) -> None:
    (issue,) = _live(tmp_path, "DROP TABLE tb_post;")

    assert issue.details["table"] == "public.tb_post"


def test_dropping_a_column_no_tview_reads_is_fine(tmp_path: Path) -> None:
    assert _live(tmp_path, "ALTER TABLE tb_post DROP COLUMN body;") == []


def test_dropping_the_tview_first_is_fine(tmp_path: Path) -> None:
    sql = "DROP TABLE IF EXISTS tv_post;\nALTER TABLE tb_post DROP COLUMN title;"

    assert _live(tmp_path, sql) == []


def test_dropping_the_tview_after_the_change_is_too_late(tmp_path: Path) -> None:
    sql = "ALTER TABLE tb_post DROP COLUMN title;\nDROP TABLE tv_post;"

    assert len(_live(tmp_path, sql)) == 1


def test_the_tview_code_has_a_severity_and_an_actionable() -> None:
    assert PFLIGHT_CODES["PFLIGHT_TVIEW_BASE_COLUMN"][0] == "error"
