"""A type schema written on one side and left off the other still names one type.

`COMMENT ON FUNCTION app.f(custom_t)` documents `CREATE FUNCTION app.f(x
app.custom_t)`, because PostgreSQL resolves the bare name through
`search_path` and lands on the same type. The lint compared the two spellings
as strings and reported the function undocumented — and the reverse, a bare
`CREATE` with a qualified `COMMENT`, the same way.

It is the rule the inventory already applies to the object's own schema
("a missing schema on either side matches any schema"), lifted one level down
to the argument types. What it must *not* do is match two schemas that are
both present and disagree: `app.custom_t` and `other.custom_t` are two types,
and two routines that differ only there are two routines.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from pathlib import Path

import pglast.parser
import pytest
from typer.testing import CliRunner

from confiture.cli.main import app

runner = CliRunner()

_ENV = "database_url: postgresql://localhost/test\ninclude_dirs:\n  - db/schema\n"

_PREAMBLE = "CREATE SCHEMA app;\nCREATE SCHEMA other;\n"


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
    (project / "db" / "schema" / "010.sql").write_text(_PREAMBLE + sql)


def _lint(*extra: str) -> dict:
    result = runner.invoke(
        app, ["lint", "--env", "local", "--fail-on", "never", "--format", "json", *extra]
    )
    assert result.exit_code == 0, result.output
    return json.loads(result.stdout)


def _undocumented(payload: dict) -> list[str]:
    return [i["location"] for i in payload["violations"]["items"] if i["rule_id"] == "doc_002"]


def _function(name: str, arg: str, body: str = "SELECT 1") -> str:
    return f"CREATE FUNCTION {name}(x {arg}) RETURNS int LANGUAGE sql AS $$ {body} $$;\n"


class TestACommentResolvesWhicheverSideCarriesTheSchema:
    def test_created_qualified_commented_bare(self, project: Path) -> None:
        _write(
            project,
            _function("app.f", "app.custom_t")
            + "COMMENT ON FUNCTION app.f(custom_t) IS 'documented';\n",
        )

        assert _undocumented(_lint("--select", "doc_002")) == []

    def test_created_bare_commented_qualified(self, project: Path) -> None:
        _write(
            project,
            _function("app.g", "custom_t")
            + "COMMENT ON FUNCTION app.g(app.custom_t) IS 'documented';\n",
        )

        assert _undocumented(_lint("--select", "doc_002")) == []

    def test_a_present_schema_that_disagrees_does_not_match(self, project: Path) -> None:
        """The negative: the wildcard is for a *missing* schema, not a different one."""
        _write(
            project,
            _function("app.h", "app.custom_t")
            + "COMMENT ON FUNCTION app.h(other.custom_t) IS 'documented';\n",
        )

        assert _undocumented(_lint("--select", "doc_002")) == ["app.h(app.custom_t)"]

    def test_a_bare_comment_documents_one_overload_and_not_the_other(self, project: Path) -> None:
        """`app.custom_t` and `other.custom_t` are two overloads; a bare comment is ambiguous.

        PostgreSQL resolves the ambiguity through `search_path` and the lint has
        none, so a bare spelling matching both is the honest reading — the
        alternative is to report a documented function undocumented.
        """
        _write(
            project,
            _function("app.k", "app.custom_t")
            + _function("app.k", "other.custom_t", "SELECT 2")
            + "COMMENT ON FUNCTION app.k(custom_t) IS 'documented';\n",
        )

        assert _undocumented(_lint("--select", "doc_002")) == []


class TestBuildOO1GroupsTheMixedQualification:
    def test_qualified_and_bare_are_one_object_defined_twice(self, project: Path) -> None:
        _write(project, _function("app.f", "app.custom_t") + _function("app.f", "custom_t"))

        found = _lint("--select", "build_001")["violations"]["items"]

        assert [i["rule_id"] for i in found] == ["build_001"]
        assert "defined 2 times" in found[0]["message"]

    def test_two_present_schemas_stay_two_objects(self, project: Path) -> None:
        _write(project, _function("app.f", "app.custom_t") + _function("app.f", "other.custom_t"))

        assert _lint("--select", "build_001")["violations"]["items"] == []

    def test_a_bare_definition_between_two_qualified_ones_splits(self, project: Path) -> None:
        """Three definitions, two objects: the bare one joins the schema it can.

        A definition joins a group only when it matches *every* member, so the
        bare spelling cannot chain `app.custom_t` to `other.custom_t` through
        itself and report three definitions of one function where PostgreSQL
        has two of one and one of another.
        """
        _write(
            project,
            _function("app.f", "app.custom_t")
            + _function("app.f", "custom_t", "SELECT 2")
            + _function("app.f", "other.custom_t", "SELECT 3"),
        )

        found = _lint("--select", "build_001")["violations"]["items"]

        assert [i["rule_id"] for i in found] == ["build_001"]
        assert "defined 2 times" in found[0]["message"]


class TestTheMatchIsPinnedAtThePredicate:
    """The rule itself, asserted on `signatures_match` rather than through a lint run."""

    @staticmethod
    def _key(*spellings: str) -> tuple[tuple[str | None, str], ...]:
        from confiture.core.linting.inventory import type_key

        args = ", ".join(f"a{i} {s}" for i, s in enumerate(spellings))
        sql = f"CREATE FUNCTION f({args}) RETURNS int LANGUAGE sql AS $$ SELECT 1 $$;"
        stmt = pglast.parser.parse_sql(sql)[0].stmt
        return tuple(type_key(p.argType) for p in stmt.parameters or ())

    def test_a_missing_schema_matches_a_present_one(self) -> None:
        from confiture.core.linting.inventory import signatures_match

        assert signatures_match(self._key("app.custom_t"), self._key("custom_t"))
        assert signatures_match(self._key("custom_t"), self._key("app.custom_t"))

    def test_two_present_schemas_that_disagree_do_not(self) -> None:
        from confiture.core.linting.inventory import signatures_match

        assert not signatures_match(self._key("app.custom_t"), self._key("other.custom_t"))

    def test_the_type_names_must_still_agree(self) -> None:
        from confiture.core.linting.inventory import signatures_match

        assert not signatures_match(self._key("app.custom_t"), self._key("app.other_t"))
        assert not signatures_match(self._key("custom_t"), self._key("other_t"))

    def test_an_array_is_not_its_element_type(self) -> None:
        from confiture.core.linting.inventory import signatures_match

        assert not signatures_match(self._key("app.custom_t[]"), self._key("custom_t"))
        assert signatures_match(self._key("app.custom_t[]"), self._key("custom_t[]"))

    def test_arity_must_agree(self) -> None:
        from confiture.core.linting.inventory import signatures_match

        assert not signatures_match(self._key("custom_t"), self._key("custom_t", "int"))

    def test_a_routine_signature_never_matches_a_table(self) -> None:
        from confiture.core.linting.inventory import signatures_match

        assert not signatures_match(self._key(), None)
        assert not signatures_match(None, self._key())
        assert signatures_match(None, None)

    @pytest.mark.parametrize(
        "spelling",
        ["integer", "int8", "json", "bit", "timestamptz", "timestamp with time zone", "text[]"],
    )
    def test_a_built_in_carries_no_schema_for_the_wildcard_to_match(self, spelling: str) -> None:
        """The canonicaliser drops `pg_catalog`, so the ten split pairs are untouched."""
        assert self._key(spelling)[0][0] is None
