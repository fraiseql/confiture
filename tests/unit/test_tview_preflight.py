"""Preflight names the migration shapes that turn a pg_tviews TVIEW into a plain table or an error.

``PFLIGHT_TVIEW_SAME_BATCH`` and ``PFLIGHT_TVIEW_IF_NOT_EXISTS`` exist only because of
fraiseql/pg_tviews#80 and #79: delete each with its issue. ``PFLIGHT_TVIEW_BASE_COLUMN`` is
PostgreSQL's own dependency on the TVIEW's backing view, and stays.
"""

from __future__ import annotations

from pathlib import Path

from confiture.core.preflight import run_preflight
from confiture.core.tview_preflight import live_issues
from confiture.models.results import PFLIGHT_CODES, PreflightIssue

CTAS = "CREATE TABLE tv_post AS SELECT 1 AS id;"
TVIEWS = {"public.tv_post": "SELECT p.id, p.title FROM public.tb_post p"}


def _static(tmp_path: Path, sql: str, code: str) -> list[PreflightIssue]:
    (tmp_path / "20260929000001_m.up.sql").write_text(sql)
    (tmp_path / "20260929000001_m.down.sql").write_text("SELECT 1;")
    return [i for i in run_preflight(tmp_path).issues if i.code == code]


def _live(tmp_path: Path, sql: str) -> list[PreflightIssue]:
    (tmp_path / "20260929000002_m.up.sql").write_text(sql)
    return live_issues([tmp_path / "20260929000002_m.up.sql"], TVIEWS)


def test_an_extension_and_a_tview_in_one_transactional_script_is_an_error(tmp_path: Path) -> None:
    (issue,) = _static(
        tmp_path, f"CREATE EXTENSION IF NOT EXISTS pg_tviews;\n{CTAS}", "PFLIGHT_TVIEW_SAME_BATCH"
    )

    assert (issue.severity, issue.line, issue.file) == (
        "error",
        2,
        "20260929000001_m.up.sql",
    )


def test_a_tview_without_the_extension_in_the_script_is_not_a_same_batch(tmp_path: Path) -> None:
    assert _static(tmp_path, CTAS, "PFLIGHT_TVIEW_SAME_BATCH") == []


def test_the_extension_without_a_tview_is_not_a_same_batch(tmp_path: Path) -> None:
    assert _static(tmp_path, "CREATE EXTENSION pg_tviews;", "PFLIGHT_TVIEW_SAME_BATCH") == []


def test_a_non_transactional_script_is_sent_statement_by_statement(tmp_path: Path) -> None:
    sql = f"CREATE EXTENSION pg_tviews;\n{CTAS}\nCREATE INDEX CONCURRENTLY i ON t (c);"

    assert _static(tmp_path, sql, "PFLIGHT_TVIEW_SAME_BATCH") == []


def test_create_table_if_not_exists_a_tview_is_an_error(tmp_path: Path) -> None:
    (issue,) = _static(
        tmp_path,
        "CREATE TABLE IF NOT EXISTS tv_post AS SELECT 1 AS id;",
        "PFLIGHT_TVIEW_IF_NOT_EXISTS",
    )

    assert (issue.severity, issue.line) == ("error", 1)


def test_create_table_if_not_exists_a_plain_table_is_fine(tmp_path: Path) -> None:
    sql = "CREATE TABLE IF NOT EXISTS tb_post AS SELECT 1 AS id;"

    assert _static(tmp_path, sql, "PFLIGHT_TVIEW_IF_NOT_EXISTS") == []


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


def test_every_tview_code_has_a_severity_and_an_actionable() -> None:
    for code in (
        "PFLIGHT_TVIEW_SAME_BATCH",
        "PFLIGHT_TVIEW_IF_NOT_EXISTS",
        "PFLIGHT_TVIEW_BASE_COLUMN",
    ):
        assert PFLIGHT_CODES[code][0] == "error"
