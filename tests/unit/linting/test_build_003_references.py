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
from confiture.core.linting.references import RELATION, Reference
from confiture.core.linting.unresolved import reference_findings

runner = CliRunner()

_ENV = "database_url: postgresql://127.0.0.1:1/lintdemo\ninclude_dirs:\n  - path: db/schema\n"

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


def test_the_line_is_the_statement_inside_the_body(in_tmp: Path) -> None:
    """The line the reader opens is the ``FOR`` and the ``PERFORM``, not the ``CREATE``.

    ``parse_plpgsql`` counts from the body's first line — the remainder of the
    ``$$`` line — so the two statements are body lines 5 and 6 and file lines 6
    and 7.
    """
    _project(in_tmp, {"001_schema.sql": ISSUE_246_SCHEMA, "010_fn.sql": ISSUE_246_ROUTINE})

    lines = {f["location"].rsplit(" -> ", 1)[1]: f["line"] for f in _findings()}

    assert lines == {"app.tv_summary": 6, "app.fn_refresh_summary": 7}


def test_a_language_sql_body_line_is_the_statement_s_too(in_tmp: Path) -> None:
    _project(
        in_tmp,
        {
            "001_schema.sql": ISSUE_246_SCHEMA,
            "010_fn.sql": (
                "-- a leading comment\n"
                "CREATE FUNCTION app.fn_ids() RETURNS SETOF bigint LANGUAGE sql AS $$\n"
                "    SELECT id\n"
                "      FROM app.tb_absent\n"
                "$$;\n"
            ),
        },
    )

    assert [f["line"] for f in _findings()] == [4]


def test_an_unqualified_name_is_not_judged_without_a_search_path(in_tmp: Path) -> None:
    """``widgets`` could be any schema's; ``now()`` is nobody's to create.

    Judging an unqualified name without knowing what resolves it is how every
    built-in becomes a finding — the failure #246 names in its own scope notes.
    """
    _project(
        in_tmp,
        {
            "001_schema.sql": ISSUE_246_SCHEMA,
            "010_fn.sql": (
                "CREATE FUNCTION app.fn_x() RETURNS SETOF record LANGUAGE sql AS $$\n"
                "    SELECT now() FROM widgets\n"
                "$$;\n"
            ),
        },
    )

    assert _findings() == []


def test_an_unqualified_relation_is_judged_under_a_declared_search_path(in_tmp: Path) -> None:
    """With the schemas named, an unqualified relation has somewhere to be looked for."""
    _project(
        in_tmp,
        {
            "001_schema.sql": ISSUE_246_SCHEMA,
            "010_fn.sql": (
                "CREATE FUNCTION app.fn_x() RETURNS SETOF bigint LANGUAGE sql AS $$\n"
                "    SELECT id FROM widgets\n"
                "$$;\n"
            ),
        },
        env=_ENV + "lint:\n  search_path:\n    - app\n",
    )

    assert [f["location"] for f in _findings()] == ["app.fn_x() -> widgets"]


def test_a_search_path_resolves_an_unqualified_relation_the_build_creates(in_tmp: Path) -> None:
    _project(
        in_tmp,
        {
            "001_schema.sql": ISSUE_246_SCHEMA,
            "005_table.sql": "CREATE TABLE app.widgets (id bigint PRIMARY KEY);\n",
            "010_fn.sql": (
                "CREATE FUNCTION app.fn_x() RETURNS SETOF bigint LANGUAGE sql AS $$\n"
                "    SELECT id FROM widgets\n"
                "$$;\n"
            ),
        },
        env=_ENV + "lint:\n  search_path:\n    - app\n",
    )

    assert _findings() == []


def test_an_unqualified_routine_is_never_judged(in_tmp: Path) -> None:
    """``pg_catalog`` is on every search path and confiture cannot enumerate it.

    A declared search path says where a project's own objects live; it does not
    make ``now()``, ``count()`` or an operator's implementation knowable.
    """
    _project(
        in_tmp,
        {
            "001_schema.sql": ISSUE_246_SCHEMA,
            "010_fn.sql": (
                "CREATE FUNCTION app.fn_x() RETURNS timestamptz LANGUAGE sql AS $$\n"
                "    SELECT now()\n"
                "$$;\n"
            ),
        },
        env=_ENV + "lint:\n  search_path:\n    - app\n",
    )

    assert _findings() == []


class TestTheHonestFallback:
    """When the body's position is unknown, the message says which line this is.

    The conversion from a body-relative line to a file line needs the body's
    opening delimiter, and a text whose scan failed does not have one. Pointing
    at the routine is then the best available answer — and saying so is what
    stops a reader concluding the rule is simply wrong when they open the line
    and find a ``CREATE`` on it.
    """

    def _reference(self, exact: bool) -> Reference:
        return Reference(
            schema="app",
            name="tv_summary",
            kind=RELATION,
            line=5,
            referrer="app.fn_report()",
            referrer_kind="function",
            referrer_line=1,
            line_is_exact=exact,
        )

    def test_an_inexact_reference_reports_the_routine_s_line(self) -> None:
        (finding,) = reference_findings([("db/schema/010_fn.sql", self._reference(exact=False))])

        assert finding.line_number == 1
        assert "the line given is the routine's" in finding.message

    def test_an_exact_reference_says_nothing_extra(self) -> None:
        (finding,) = reference_findings([("db/schema/010_fn.sql", self._reference(exact=True))])

        assert finding.line_number == 5
        assert "the line given is the routine's" not in finding.message


TRIGGER_ROUTINE = """CREATE OR REPLACE FUNCTION app.fn_touch()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$;
"""


class TestABodyNoParserWillReturn:
    """A trigger function must not take the whole lint down with it.

    `libpg_query` serialises a PL/pgSQL *trigger* function's implicit `TG_`
    datums as `{}}` — malformed JSON — so `pglast.parse_plpgsql` raises
    `json.JSONDecodeError` rather than `ParseError` on every `RETURNS TRIGGER`
    and `RETURNS event_trigger` body. Trigger functions are ordinary, this rule
    is on by default, and the exception reached the CLI's error boundary: a
    plain `confiture lint` died with `INTERNAL_ERROR` on most real schemas.

    A body no parser will return is a body this rule did not read, which is a
    degradation to report, not an exception to raise and not a silence to pass
    off as a clean result.
    """

    def _payload(self, *args: str) -> dict:
        result = runner.invoke(
            app, ["lint", "--select", "build_003", "--format", "json", "--fail-on", "never", *args]
        )
        assert result.exit_code == 0, result.output
        return json.loads(result.stdout)

    @staticmethod
    def _unread(payload: dict) -> list[dict]:
        """Only the "body went unread" degradations.

        The fixture's DSN points at a closed port on purpose, so the live tier
        degrades on every run here; that entry is a different fact.
        """
        return [d for d in payload["degraded"] if d["reason"].startswith("could not read")]

    def test_a_trigger_function_does_not_crash_the_lint(self, in_tmp: Path) -> None:
        _project(in_tmp, {"001_schema.sql": ISSUE_246_SCHEMA, "010_trg.sql": TRIGGER_ROUTINE})

        assert self._payload()["violations"]["total"] == 0

    def test_and_the_report_says_the_body_went_unread(self, in_tmp: Path) -> None:
        _project(in_tmp, {"001_schema.sql": ISSUE_246_SCHEMA, "010_trg.sql": TRIGGER_ROUTINE})

        (degraded,) = self._unread(self._payload())

        assert degraded["code"] == "build_003"
        assert degraded["state"] == "degraded"
        assert "app.fn_touch()" in degraded["reason"]

    def test_a_readable_body_beside_it_is_still_read(self, in_tmp: Path) -> None:
        """The degradation is per body: one unreadable routine hides no other."""
        _project(
            in_tmp,
            {
                "001_schema.sql": ISSUE_246_SCHEMA,
                "010_trg.sql": TRIGGER_ROUTINE,
                "020_fn.sql": ISSUE_246_ROUTINE,
            },
        )

        payload = self._payload()

        assert sorted(i["location"] for i in payload["violations"]["items"]) == [
            "app.fn_report() -> app.fn_refresh_summary",
            "app.fn_report() -> app.tv_summary",
        ]
        assert "app.fn_touch()" in self._unread(payload)[0]["reason"]

    def test_a_schema_with_no_unreadable_body_reports_no_degradation(self, in_tmp: Path) -> None:
        _project(in_tmp, {"001_schema.sql": ISSUE_246_SCHEMA, "010_fn.sql": ISSUE_246_ROUTINE})

        assert self._unread(self._payload()) == []
