"""``build_003``: a body names an object the build does not create (#246).

The reporter's routine read ``app.tv_summary`` and called
``app.fn_refresh_summary``; no file created either, `confiture build` succeeded
and `confiture lint` said nothing. The inventory that ``build_001`` reads to
know an object is created *twice* is the same inventory that can say it is
created *never* — this exercises it in that direction, through the real CLI.

The inventory is the whole build, not the file, so a routine that reads a table
created three files later resolves: only a name absent from the entire build is
a finding.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from typer.testing import CliRunner

from confiture.cli.main import app

runner = CliRunner()

_ENV = "database_url: postgresql://localhost/lintdemo\ninclude_dirs:\n  - path: db/schema\n"

ISSUE_246_SCHEMA = """CREATE SCHEMA IF NOT EXISTS app;
"""

ISSUE_246_ROUTINE = """CREATE OR REPLACE FUNCTION app.fn_report()
RETURNS VOID LANGUAGE plpgsql AS $$
DECLARE
    r RECORD;
BEGIN
    FOR r IN SELECT id FROM app.tv_summary LOOP
        PERFORM app.fn_refresh_summary(r.id);
    END LOOP;
END;
$$;
"""


def _project(root: Path, files: dict[str, str], env: str = _ENV) -> None:
    (root / "db" / "schema").mkdir(parents=True, exist_ok=True)
    (root / "db" / "environments").mkdir(parents=True, exist_ok=True)
    (root / "db" / "environments" / "local.yaml").write_text(env)
    for name, sql in files.items():
        (root / "db" / "schema" / name).write_text(sql)


@pytest.fixture
def in_tmp(tmp_path: Path) -> Iterator[Path]:
    old = Path.cwd()
    os.chdir(tmp_path)
    try:
        yield tmp_path
    finally:
        os.chdir(old)


def _findings(*args: str) -> list[dict]:
    result = runner.invoke(
        app, ["lint", "--select", "build_003", "--format", "json", "--fail-on", "never", *args]
    )
    assert result.exit_code == 0, result.output
    items = json.loads(result.stdout)["violations"]["items"]
    return [i for i in items if i["rule_id"] == "build_003"]


def test_the_issue_reproduction_reports_both_names(in_tmp: Path) -> None:
    """Two objects nobody ever built, one finding each."""
    _project(in_tmp, {"001_schema.sql": ISSUE_246_SCHEMA, "010_fn.sql": ISSUE_246_ROUTINE})

    findings = _findings()

    assert sorted(f["location"] for f in findings) == [
        "app.fn_report() -> app.fn_refresh_summary",
        "app.fn_report() -> app.tv_summary",
    ]


def test_each_finding_names_the_file_the_reader_opens(in_tmp: Path) -> None:
    """The referencing file, project-relative, on every finding."""
    _project(in_tmp, {"001_schema.sql": ISSUE_246_SCHEMA, "010_fn.sql": ISSUE_246_ROUTINE})

    assert {f["file"] for f in _findings()} == {"db/schema/010_fn.sql"}


def test_the_finding_is_a_warning(in_tmp: Path) -> None:
    _project(in_tmp, {"001_schema.sql": ISSUE_246_SCHEMA, "010_fn.sql": ISSUE_246_ROUTINE})

    assert {f["severity"] for f in _findings()} == {"warning"}


def test_the_message_says_which_object_is_missing(in_tmp: Path) -> None:
    _project(in_tmp, {"001_schema.sql": ISSUE_246_SCHEMA, "010_fn.sql": ISSUE_246_ROUTINE})

    messages = " ".join(f["message"] for f in _findings())

    assert "app.tv_summary" in messages
    assert "no file in the build creates it" in messages


def test_a_forward_reference_within_one_build_resolves(in_tmp: Path) -> None:
    """The inventory is the whole build: file order is not resolution order."""
    _project(
        in_tmp,
        {
            "001_schema.sql": ISSUE_246_SCHEMA,
            "010_fn.sql": (
                "CREATE FUNCTION app.fn_ids() RETURNS SETOF bigint LANGUAGE sql AS $$\n"
                "    SELECT id FROM app.tb_later\n"
                "$$;\n"
            ),
            "040_table.sql": "CREATE TABLE app.tb_later (id bigint PRIMARY KEY);\n",
        },
    )

    assert _findings() == []


def test_a_routine_the_build_creates_resolves(in_tmp: Path) -> None:
    """A call is checked by name, not by overload: the build creates ``app.fn_x``."""
    _project(
        in_tmp,
        {
            "001_schema.sql": ISSUE_246_SCHEMA,
            "010_fn.sql": "CREATE FUNCTION app.fn_x(a int) RETURNS int LANGUAGE sql AS $$ SELECT a $$;\n",
            "020_fn.sql": (
                "CREATE FUNCTION app.fn_y() RETURNS int LANGUAGE sql AS $$ SELECT app.fn_x(1) $$;\n"
            ),
        },
    )

    assert _findings() == []


def test_a_view_over_a_table_nobody_creates_reports(in_tmp: Path) -> None:
    _project(
        in_tmp,
        {
            "001_schema.sql": ISSUE_246_SCHEMA,
            "030_view.sql": "CREATE VIEW app.v_report AS SELECT id FROM app.tb_absent;\n",
        },
    )

    assert [f["location"] for f in _findings()] == ["app.v_report -> app.tb_absent"]


def test_a_dynamic_execute_is_not_a_finding(in_tmp: Path) -> None:
    """The one case #246 rules out: a statement built at run time is not resolvable."""
    _project(
        in_tmp,
        {
            "001_schema.sql": ISSUE_246_SCHEMA,
            "010_fn.sql": (
                "CREATE FUNCTION app.fn_dyn(t text) RETURNS void LANGUAGE plpgsql AS $$\n"
                "BEGIN\n"
                "    EXECUTE 'SELECT 1 FROM ' || quote_ident(t);\n"
                "END;\n"
                "$$;\n"
            ),
        },
    )

    assert _findings() == []


def test_a_pg_catalog_reference_never_reports(in_tmp: Path) -> None:
    """PostgreSQL ships its own catalogue; no build creates it."""
    _project(
        in_tmp,
        {
            "001_schema.sql": ISSUE_246_SCHEMA,
            "010_fn.sql": (
                "CREATE FUNCTION app.fn_now() RETURNS timestamptz LANGUAGE sql AS $$\n"
                "    SELECT pg_catalog.now()\n"
                "$$;\n"
            ),
        },
    )

    assert _findings() == []


def test_the_line_is_the_routine_s_until_the_body_offset_is_known(in_tmp: Path) -> None:
    """Where the finding points today: at the ``CREATE``, not at the statement.

    ``parse_plpgsql`` counts lines from the body's first line, and nothing yet
    converts that to a line in the file — so the honest thing to report is the
    routine's own line rather than a line three short of the truth.
    """
    _project(in_tmp, {"001_schema.sql": ISSUE_246_SCHEMA, "010_fn.sql": ISSUE_246_ROUTINE})

    assert {f["line"] for f in _findings()} == {1}
