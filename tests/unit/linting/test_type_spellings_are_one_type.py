"""Two spellings of one PostgreSQL type are one type (#275).

`doc_002` matched a `COMMENT ON FUNCTION` to its `CREATE` on the *rendered*
argument types, and pglast renders a type according to how it was written: the
SQL-standard keyword forms come back `pg_catalog`-qualified, the internal names
come back bare. So `timestamptz` and `timestamp with time zone` were two
signatures, and the `COMMENT` written one way did not document the `CREATE`
written the other.

Ten pairs split, not one. `numeric`/`decimal`, `varchar`/`character varying` and
`timestamp`/`timestamp without time zone` do not — both arrive `pg_catalog`-
qualified — which is why the reporter's controls passed and made the bug look
specific to `timestamptz`.

It runs in the other direction too, and that half is worse: the same string is
the routine half of `object_key`, so `build_001` — an `error`, on by default —
reported no duplicate for two `CREATE`s PostgreSQL rejects as the same function.
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

_ENV = "database_url: postgresql://localhost/test\ninclude_dirs:\n  - db/schema\n"

#: The ten spellings whose two forms rendered differently, measured on pglast
#: 8.4. Each row is (keyword form, internal name).
SPLIT_PAIRS = [
    ("smallint", "int2"),
    ("integer", "int4"),
    ("bigint", "int8"),
    ("real", "float4"),
    ("double precision", "float8"),
    ("boolean", "bool"),
    ("char", "bpchar"),
    ("timestamp with time zone", "timestamptz"),
    ("time with time zone", "timetz"),
    ("bit varying", "varbit"),
]

#: Pairs that already matched: both spellings arrive `pg_catalog`-qualified.
JOINED_PAIRS = [
    ("numeric", "decimal"),
    ("varchar", "character varying"),
    ("timestamp", "timestamp without time zone"),
    ("int", "integer"),
]


@pytest.fixture
def project(tmp_path: Path) -> Iterator[Path]:
    (tmp_path / "db" / "schema").mkdir(parents=True)
    (tmp_path / "db" / "environments").mkdir(parents=True)
    (tmp_path / "db" / "environments" / "local.yaml").write_text(_ENV)
    old_cwd = Path.cwd()
    os.chdir(tmp_path)
    try:
        yield tmp_path
    finally:
        os.chdir(old_cwd)


def _write(project: Path, sql: str) -> None:
    (project / "db" / "schema" / "010.sql").write_text(sql)


def _lint(*extra: str) -> dict:
    result = runner.invoke(
        app, ["lint", "--env", "local", "--fail-on", "never", "--format", "json", *extra]
    )
    assert result.exit_code == 0, result.output
    return json.loads(result.stdout)


def _undocumented(payload: dict) -> list[str]:
    return [i["location"] for i in payload["violations"]["items"] if i["rule_id"] == "doc_002"]


class TestACommentResolvesWhicheverWayEachSideIsSpelled:
    @pytest.mark.parametrize(
        ("keyword", "internal"), SPLIT_PAIRS, ids=lambda p: p.replace(" ", "_")
    )
    def test_created_internal_commented_keyword(
        self, project: Path, keyword: str, internal: str
    ) -> None:
        _write(
            project,
            f"CREATE FUNCTION fn_f(p {internal}) RETURNS int LANGUAGE sql AS $$ SELECT 1 $$;\n"
            f"COMMENT ON FUNCTION fn_f({keyword}) IS 'documented';\n",
        )

        assert _undocumented(_lint("--select", "doc_002")) == []

    @pytest.mark.parametrize(
        ("keyword", "internal"), SPLIT_PAIRS, ids=lambda p: p.replace(" ", "_")
    )
    def test_created_keyword_commented_internal(
        self, project: Path, keyword: str, internal: str
    ) -> None:
        _write(
            project,
            f"CREATE FUNCTION fn_f(p {keyword}) RETURNS int LANGUAGE sql AS $$ SELECT 1 $$;\n"
            f"COMMENT ON FUNCTION fn_f({internal}) IS 'documented';\n",
        )

        assert _undocumented(_lint("--select", "doc_002")) == []

    @pytest.mark.parametrize(("a", "b"), JOINED_PAIRS, ids=lambda p: p.replace(" ", "_"))
    def test_the_pairs_that_already_matched_still_do(self, project: Path, a: str, b: str) -> None:
        _write(
            project,
            f"CREATE FUNCTION fn_f(p {a}) RETURNS int LANGUAGE sql AS $$ SELECT 1 $$;\n"
            f"COMMENT ON FUNCTION fn_f({b}) IS 'documented';\n",
        )

        assert _undocumented(_lint("--select", "doc_002")) == []


class TestTheReportedReproduction:
    """#275's five functions, verbatim. Reported: documented 3, undocumented 2."""

    REPRO = """CREATE SCHEMA app;

CREATE OR REPLACE FUNCTION app.fn_a(p_at TIMESTAMPTZ) RETURNS INT AS $$ SELECT 1 $$ LANGUAGE sql;
COMMENT ON FUNCTION app.fn_a(p_at timestamp with time zone) IS 'Returns one for any instant.';

CREATE OR REPLACE FUNCTION app.fn_b(p_at TIMESTAMPTZ) RETURNS INT AS $$ SELECT 1 $$ LANGUAGE sql;
COMMENT ON FUNCTION app.fn_b(p_at timestamptz) IS 'Returns one for any instant.';

CREATE OR REPLACE FUNCTION app.fn_c(p_n INT) RETURNS INT AS $$ SELECT p_n $$ LANGUAGE sql;
COMMENT ON FUNCTION app.fn_c(p_n integer) IS 'Returns its argument.';

CREATE OR REPLACE FUNCTION app.fn_d(p_s VARCHAR) RETURNS INT AS $$ SELECT 1 $$ LANGUAGE sql;
COMMENT ON FUNCTION app.fn_d(p_s character varying) IS 'Returns one for any string.';

CREATE OR REPLACE FUNCTION app.fn_e(p_at TIMESTAMP WITH TIME ZONE) RETURNS INT AS $$ SELECT 1 $$ LANGUAGE sql;
COMMENT ON FUNCTION app.fn_e(p_at timestamptz) IS 'Returns one for any instant.';
"""

    def test_all_five_are_documented(self, project: Path) -> None:
        _write(project, self.REPRO)

        payload = _lint("--select", "doc_002")

        assert _undocumented(payload) == []
        doc_002 = next(r for r in payload["documentation"]["rules"] if r["code"] == "doc_002")
        assert (doc_002["documented"], doc_002["undocumented"]) == (5, 0)


class TestAFindingPrintsTheTypeAsWritten:
    """The key is canonical; the prose is what the author wrote."""

    def test_int_prints_as_integer_not_int4(self, project: Path) -> None:
        _write(
            project, "CREATE FUNCTION fn_c(p_n INT) RETURNS int LANGUAGE sql AS $$ SELECT 1 $$;\n"
        )

        assert _undocumented(_lint("--select", "doc_002")) == ["fn_c(integer)"]

    def test_an_internal_spelling_is_printed_as_written(self, project: Path) -> None:
        _write(
            project, "CREATE FUNCTION fn_c(p_n int8) RETURNS int LANGUAGE sql AS $$ SELECT 1 $$;\n"
        )

        assert _undocumented(_lint("--select", "doc_002")) == ["fn_c(int8)"]

    def test_json_does_not_leak_the_pg_catalog_qualifier(self, project: Path) -> None:
        """`RawStream` renders a qualified `json` as `pg_catalog.json` (D7a).

        The author wrote `json`; the message told them to write
        `COMMENT ON FUNCTION fn_j(pg_catalog.json)`. `bit` is the other one.
        """
        _write(
            project, "CREATE FUNCTION fn_j(p json) RETURNS int LANGUAGE sql AS $$ SELECT 1 $$;\n"
        )

        assert _undocumented(_lint("--select", "doc_002")) == ["fn_j(json)"]

    def test_bit_does_not_either(self, project: Path) -> None:
        _write(project, "CREATE FUNCTION fn_b(p bit) RETURNS int LANGUAGE sql AS $$ SELECT 1 $$;\n")

        assert _undocumented(_lint("--select", "doc_002")) == ["fn_b(bit)"]


class TestBuildOOneGroupsTheSpellings:
    """The missed duplicate — the worse half of #275, and the half that is a gate."""

    def test_two_spellings_are_one_object_defined_twice(self, project: Path) -> None:
        _write(
            project,
            "CREATE SCHEMA app;\n"
            "CREATE FUNCTION app.f(p TIMESTAMPTZ) RETURNS int LANGUAGE sql AS $$ SELECT 1 $$;\n"
            "CREATE FUNCTION app.f(p TIMESTAMP WITH TIME ZONE) RETURNS int"
            " LANGUAGE sql AS $$ SELECT 2 $$;\n",
        )

        found = _lint("--select", "build_001")["violations"]["items"]

        assert [i["rule_id"] for i in found] == ["build_001"]
        assert "defined 2 times" in found[0]["message"]

    def test_int8_and_bigint_are_one_object(self, project: Path) -> None:
        _write(
            project,
            "CREATE SCHEMA app;\n"
            "CREATE FUNCTION app.g(p INT8) RETURNS int LANGUAGE sql AS $$ SELECT 1 $$;\n"
            "CREATE FUNCTION app.g(p BIGINT) RETURNS int LANGUAGE sql AS $$ SELECT 2 $$;\n",
        )

        assert [i["rule_id"] for i in _lint("--select", "build_001")["violations"]["items"]] == [
            "build_001"
        ]

    def test_an_array_is_still_a_different_overload(self, project: Path) -> None:
        """The regression the array fix exists to prevent: `f(int[])` is not `f(int)`."""
        _write(
            project,
            "CREATE SCHEMA app;\n"
            "CREATE FUNCTION app.k(p INT[]) RETURNS int LANGUAGE sql AS $$ SELECT 1 $$;\n"
            "CREATE FUNCTION app.k(p INT) RETURNS int LANGUAGE sql AS $$ SELECT 2 $$;\n",
        )

        assert _lint("--select", "build_001")["violations"]["items"] == []
