"""Preflight names a change to what a registered pg_tviews TVIEW reads (#504).

``PFLIGHT_TVIEW_BASE_COLUMN`` is PostgreSQL's own dependency on the TVIEW's backing view.
"""

from __future__ import annotations

from pathlib import Path

import pytest

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


class _Session:
    """A session whose connection is only handed on: ``collect_schema_facts`` is patched."""

    _conn = object()


def test_preflight_refuses_a_pg_tviews_confiture_does_not_support(monkeypatch) -> None:
    """Its facts are advisory, but an unsupported pg_tviews is not a missing fact (#541)."""
    from confiture.cli.commands.migrate import preflight
    from confiture.exceptions import ConfigurationError

    def refuse(_conn: object) -> None:
        raise ConfigurationError("pg_tviews 0.1.0-beta.18 is installed", error_code="CONFIG_014")

    monkeypatch.setattr(preflight, "collect_schema_facts", refuse)

    with pytest.raises(ConfigurationError) as refused:
        preflight._collect_preflight_facts(_Session())  # type: ignore[arg-type]

    assert refused.value.error_code == "CONFIG_014"


def test_any_other_failure_to_read_the_facts_leaves_them_empty(monkeypatch) -> None:
    from confiture.cli.commands.migrate import preflight
    from confiture.core.schema_facts import SchemaFacts

    def fail(_conn: object) -> None:
        raise RuntimeError("the catalog is unreadable")

    monkeypatch.setattr(preflight, "collect_schema_facts", fail)

    assert preflight._collect_preflight_facts(_Session()) == SchemaFacts()  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "sql",
    [
        "CREATE TABLE tv_post AS SELECT p.id FROM tb_post p;",
        "CREATE TABLE IF NOT EXISTS app.tv_post AS SELECT 1 AS id;",
        "DROP TABLE IF EXISTS tv_post;",
        "ALTER TABLE tb_post ADD COLUMN body text; DROP TABLE app.tv_post;",
    ],
)
def test_a_migration_that_creates_or_drops_a_tview_touches_one(sql: str) -> None:
    from confiture.core.tview_preflight import touches_tview

    assert touches_tview(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "CREATE TABLE tv_post (id int);",
        "CREATE TABLE archive AS SELECT * FROM tb_post;",
        "ALTER TABLE tb_post ADD COLUMN body text;",
        "not sql at all (",
    ],
)
def test_anything_else_does_not(sql: str) -> None:
    from confiture.core.tview_preflight import touches_tview

    assert not touches_tview(sql)


def test_dropping_the_tview_through_pg_tviews_first_is_fine(tmp_path: Path) -> None:
    sql = (
        "SELECT tviews.pg_tviews_drop('public.tv_post', if_exists => true);\n"
        "ALTER TABLE tb_post DROP COLUMN title;"
    )

    assert _live(tmp_path, sql) == []


@pytest.mark.parametrize(
    ("sql", "touches"),
    [
        ("SELECT tviews.pg_tviews_create_or_replace('tv_post', 'SELECT 1');", True),
        ("SELECT tviews.pg_tviews_drop('app.tv_post', if_exists => true);", True),
        ("CREATE TABLE tv_post AS SELECT 1 AS pk_post;", True),
        ("SELECT count(*) FROM tb_post;", False),
    ],
)
def test_a_migration_touches_a_tview_through_pg_tviews_calls(sql: str, touches: bool) -> None:
    from confiture.core.tview_preflight import touches_tview

    assert touches_tview(sql) is touches
