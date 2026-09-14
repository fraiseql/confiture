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

import pglast
import pglast.parser
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


def _body_is_unreadable(statement: str) -> bool:
    """Whether *this* libpg_query refuses the body — probed, not looked up.

    The shapes this file pins are **pglast 8's alone**: 6.16 and 7.18 resolve a
    schema-qualified type and serialise a trigger function's datums as valid
    JSON, and the ``[ast]`` extra accepts all three majors. What `build_003`
    promises on every one of them — that a body it did not read is named — is
    asserted unconditionally; what it degrades *on* differs, and asking is the
    only honest way to know which.
    """
    try:
        pglast.parse_plpgsql(statement)
    except (pglast.parser.ParseError, json.JSONDecodeError):
        return True
    return False


ISSUE_270_TYPES = """CREATE SCHEMA IF NOT EXISTS app;

CREATE TYPE app.type_input AS (nom TEXT);
CREATE TYPE app.mutation_response AS (status TEXT, message TEXT);
"""

ISSUE_270_ROUTINES = """CREATE OR REPLACE FUNCTION app.m_a(input_data app.type_input)
RETURNS VOID LANGUAGE plpgsql AS $$
DECLARE r RECORD;
BEGIN FOR r IN SELECT id FROM public.tv_a LOOP NULL; END LOOP; END; $$;

CREATE OR REPLACE FUNCTION app.m_b()
RETURNS app.mutation_response LANGUAGE plpgsql AS $$
DECLARE r RECORD;
BEGIN FOR r IN SELECT id FROM public.tv_b LOOP NULL; END LOOP; RETURN NULL; END; $$;

CREATE OR REPLACE FUNCTION app.m_c(input_data app.type_input)
RETURNS app.mutation_response LANGUAGE plpgsql AS $$
DECLARE r RECORD;
BEGIN FOR r IN SELECT id FROM public.tv_c LOOP NULL; END LOOP; RETURN NULL; END; $$;

CREATE OR REPLACE FUNCTION app.m_d(p TEXT)
RETURNS TEXT LANGUAGE plpgsql AS $$
DECLARE r RECORD;
BEGIN FOR r IN SELECT id FROM public.tv_d LOOP NULL; END LOOP; RETURN NULL; END; $$;
"""


REFUSED_ROUTINE_ALONE = """CREATE OR REPLACE FUNCTION app.m_z(input_data app.type_input[])
RETURNS VOID LANGUAGE plpgsql AS $$
DECLARE r RECORD;
BEGIN FOR r IN SELECT id FROM public.tv_z LOOP NULL; END LOOP; END; $$;
"""

REFUSED_ROUTINES = (
    REFUSED_ROUTINE_ALONE
    + """
CREATE OR REPLACE FUNCTION app.m_d(p TEXT)
RETURNS TEXT LANGUAGE plpgsql AS $$
DECLARE r RECORD;
BEGIN FOR r IN SELECT id FROM public.tv_d LOOP NULL; END LOOP; RETURN NULL; END; $$;
"""
)


@pytest.mark.skipif(
    not _body_is_unreadable(REFUSED_ROUTINE_ALONE),
    reason="this libpg_query resolves an array of a type it does not know",
)
class TestARoutineTheCompilerRefuses:
    """A body libpg_query will not return is named, whatever stopped it (#270).

    The rule is on by default and trees are full of routines, so a body that
    does not come back must be a degradation to report — not an exception to
    raise, and not a silence to pass off as a clean result. `build_003`'s
    `ParseError` arm did the third of those: the routine contributed no names,
    produced no finding, and reached no degradation either.

    Almost nothing raises here any more. A schema-qualified type is blanked
    before the compiler sees it (#270), and a trigger function's mis-serialised
    datums are repaired before the tree is decoded (#272). What is left is
    refused for a reason no rewrite explains: naming an array type means
    resolving its element type, and an element the stub cannot resolve comes
    back as `record`, which PL/pgSQL declines as `_record`. That happens to
    `public.type_input[]` and to a bare `type_input[]` exactly as it happens
    here, so it is a hole with no catalogue-free bottom — and an audible one.
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

    def _unread_reason(self, payload: dict) -> str:
        (degraded,) = self._unread(payload)
        return degraded["reason"]

    def test_the_refused_routine_does_not_crash_the_lint(self, in_tmp: Path) -> None:
        _project(in_tmp, {"001_types.sql": ISSUE_270_TYPES, "010_fn.sql": REFUSED_ROUTINE_ALONE})

        payload = self._payload()

        assert payload["violations"]["total"] == 0
        assert self._unread(payload)[0]["state"] == "degraded"
        assert self._unread(payload)[0]["code"] == "build_003"

    def test_the_refused_routine_is_named(self, in_tmp: Path) -> None:
        _project(in_tmp, {"001_types.sql": ISSUE_270_TYPES, "010_fn.sql": REFUSED_ROUTINES})

        assert "app.m_z(app.type_input[])" in self._unread_reason(self._payload())

    def test_the_control_in_the_same_file_is_read(self, in_tmp: Path) -> None:
        """The refusal is per routine: it hides nothing beside it."""
        _project(in_tmp, {"001_types.sql": ISSUE_270_TYPES, "010_fn.sql": REFUSED_ROUTINES})

        payload = self._payload()

        assert "app.m_d(text)" not in self._unread_reason(payload)
        assert [i["location"] for i in payload["violations"]["items"]] == [
            "app.m_d(text) -> public.tv_d"
        ]

    def test_a_schema_with_no_unreadable_body_reports_no_degradation(self, in_tmp: Path) -> None:
        _project(in_tmp, {"001_schema.sql": ISSUE_246_SCHEMA, "010_fn.sql": ISSUE_246_ROUTINE})

        assert self._unread(self._payload()) == []


class TestTheRoutinesThatCarryTheWriteLogic:
    """#270's reproduction, four functions in one file, all four read.

    `fn(uuid, app.type_x_input, jsonb) RETURNS app.mutation_response` is the
    convention for every mutation in a FraiseQL schema — 233 of 297 plpgsql
    routines on the one this was filed from, and the 64 that were analysable
    were the ones without write logic in them. The type qualifier is blanked
    before the compiler sees it, so the body is read like any other.
    """

    def _payload(self, *args: str) -> dict:
        result = runner.invoke(
            app, ["lint", "--select", "build_003", "--format", "json", "--fail-on", "never", *args]
        )
        assert result.exit_code == 0, result.output
        return json.loads(result.stdout)

    def test_all_four_report(self, in_tmp: Path) -> None:
        _project(in_tmp, {"001_types.sql": ISSUE_270_TYPES, "010_fn.sql": ISSUE_270_ROUTINES})

        payload = self._payload()

        assert sorted(i["location"] for i in payload["violations"]["items"]) == [
            "app.m_a(app.type_input) -> public.tv_a",
            "app.m_b() -> public.tv_b",
            "app.m_c(app.type_input) -> public.tv_c",
            "app.m_d(text) -> public.tv_d",
        ]

    def test_nothing_is_reported_as_unread(self, in_tmp: Path) -> None:
        """Nothing was skipped, so nothing claims to have been."""
        _project(in_tmp, {"001_types.sql": ISSUE_270_TYPES, "010_fn.sql": ISSUE_270_ROUTINES})

        unread = [
            d for d in self._payload()["degraded"] if d["reason"].startswith("could not read")
        ]

        assert unread == []

    def test_a_reference_keeps_the_qualifier_its_author_wrote(self, in_tmp: Path) -> None:
        """Blanking a type must not reach the names the rule reports."""
        _project(
            in_tmp,
            {
                "001_types.sql": ISSUE_270_TYPES,
                "010_fn.sql": """CREATE OR REPLACE FUNCTION app.m_e(input_data app.type_input)
RETURNS app.mutation_response LANGUAGE plpgsql AS $$
DECLARE
    v_res app.mutation_response;
    v_seq int := app.fn_next();
BEGIN
    SELECT * INTO v_res FROM app.tv_summary;
    PERFORM core.fn_log(v_seq);
    RETURN v_res;
END;
$$;
""",
            },
        )

        assert sorted(i["location"] for i in self._payload()["violations"]["items"]) == [
            "app.m_e(app.type_input) -> app.fn_next",
            "app.m_e(app.type_input) -> app.tv_summary",
            "app.m_e(app.type_input) -> core.fn_log",
        ]

    def test_the_line_is_the_statement_inside_the_body(self, in_tmp: Path) -> None:
        """Blanking is spaces, so a neutralised body's lines are its own."""
        _project(
            in_tmp,
            {
                "001_types.sql": ISSUE_270_TYPES,
                "010_fn.sql": """CREATE OR REPLACE FUNCTION app.m_f(input_data app.type_input)
RETURNS app.mutation_response LANGUAGE plpgsql AS $$
DECLARE
    v_res app.mutation_response;
BEGIN
    SELECT * INTO v_res FROM app.tv_summary;
    RETURN v_res;
END;
$$;
""",
            },
        )

        (finding,) = self._payload()["violations"]["items"]

        assert finding["line"] == 6


ISSUE_272_ROUTINES = """CREATE OR REPLACE FUNCTION app.trg_audit()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE v_x int;
BEGIN
    SELECT id INTO v_x FROM app.tv_audit;
    PERFORM app.fn_missing(NEW.id);
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION app.fn_plain()
RETURNS VOID LANGUAGE plpgsql AS $$
DECLARE v_x int;
BEGIN
    SELECT id INTO v_x FROM app.tv_plain;
END;
$$;
"""


class TestATriggerBodyIsRead:
    """#272's reproduction: a trigger body and a control of the same shape.

    `libpg_query` wrote a trigger function's implicit `TG_*` datums as `{}}`,
    so `parse_plpgsql`'s output did not decode and **every** `RETURNS TRIGGER`
    body was unread — not some of them, all of them, whatever the body held.
    The control beside it, identical but for its return type, reported fine,
    which is what made the blind spot a property of the signature rather than
    of anything a reader would look for in the body.

    Trigger functions are where a schema keeps its audit writes, its
    denormalisation maintenance and its cross-table invariants: bodies that
    reference plenty and are rarely covered by a call path a test exercises.
    They are exactly what this rule is for, so "unread but named" was an honest
    report of a permanent hole, not an acceptable resting place.
    """

    def _payload(self, *args: str) -> dict:
        result = runner.invoke(
            app, ["lint", "--select", "build_003", "--format", "json", "--fail-on", "never", *args]
        )
        assert result.exit_code == 0, result.output
        return json.loads(result.stdout)

    def test_the_trigger_and_the_control_both_report(self, in_tmp: Path) -> None:
        _project(in_tmp, {"001_schema.sql": ISSUE_246_SCHEMA, "010_fn.sql": ISSUE_272_ROUTINES})

        assert sorted(i["location"] for i in self._payload()["violations"]["items"]) == [
            "app.fn_plain() -> app.tv_plain",
            "app.trg_audit() -> app.fn_missing",
            "app.trg_audit() -> app.tv_audit",
        ]

    def test_nothing_is_reported_as_unread(self, in_tmp: Path) -> None:
        """The `degraded` line the trigger used to leave behind is gone."""
        _project(in_tmp, {"001_schema.sql": ISSUE_246_SCHEMA, "010_fn.sql": ISSUE_272_ROUTINES})

        unread = [
            d for d in self._payload()["degraded"] if d["reason"].startswith("could not read")
        ]

        assert unread == []

    def test_the_line_is_the_statement_inside_the_body(self, in_tmp: Path) -> None:
        """The repair edits the serialisation, so the body's own numbering stands."""
        _project(in_tmp, {"001_schema.sql": ISSUE_246_SCHEMA, "010_fn.sql": ISSUE_272_ROUTINES})

        lines = {
            f["location"].rsplit(" -> ", 1)[1]: f["line"]
            for f in self._payload()["violations"]["items"]
        }

        assert lines == {"app.tv_audit": 5, "app.fn_missing": 6, "app.tv_plain": 15}

    def test_an_event_trigger_body_is_read_too(self, in_tmp: Path) -> None:
        """Two stray braces rather than ten, and the same answer."""
        _project(
            in_tmp,
            {
                "001_schema.sql": ISSUE_246_SCHEMA,
                "010_fn.sql": (
                    "CREATE FUNCTION app.evt_guard() RETURNS event_trigger\n"
                    "LANGUAGE plpgsql AS $$\n"
                    "BEGIN\n"
                    "    PERFORM app.fn_audit_ddl();\n"
                    "END;\n"
                    "$$;\n"
                ),
            },
        )

        assert [i["location"] for i in self._payload()["violations"]["items"]] == [
            "app.evt_guard() -> app.fn_audit_ddl"
        ]
