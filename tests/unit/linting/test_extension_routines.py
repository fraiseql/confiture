"""``build_003`` and the extensions the build itself creates (#741).

A ``CREATE EXTENSION … SCHEMA public`` in the tree creates routines no file
spells out. The rule must not report a call to one of them as "no file in the
build creates it" when a file in the build does, through the extension.
"""

import json
import os
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from typer.testing import CliRunner

from confiture.cli.main import app
from confiture.core.expected_db import ExpectedSchemaDB
from confiture.core.linting import unresolved
from confiture.core.linting.extensions import BuiltExtension
from confiture.core.linting.references import RELATION, ROUTINE, Reference
from confiture.core.linting.schema_linter import SchemaLinter
from confiture.core.linting.unresolved import LiveCatalogue, split_by_extension
from confiture.core.schema_identity import DEFAULT_SCHEMA
from confiture.core.temp_database import TempDatabase
from confiture.exceptions import SchemaError

runner = CliRunner()

#: Nothing listens on port 1: the live tier cannot answer. No ``scratch_url``,
#: so no server is asked whatever the run would otherwise build a scratch on.
_ENV = (
    "database_url: postgresql://127.0.0.1:1/confiture_no_such_server\n"
    "include_dirs:\n  - path: db/schema\n"
)

#: The tree from #741, plus the ``CREATE SCHEMA`` the issue's snippet leaves out.
ISSUE_741 = {
    "001_extensions.sql": (
        "CREATE EXTENSION IF NOT EXISTS ltree SCHEMA public;\n"
        "CREATE EXTENSION IF NOT EXISTS unaccent SCHEMA public;\n"
    ),
    "002_fn.sql": (
        "CREATE SCHEMA IF NOT EXISTS app;\n"
        "CREATE FUNCTION app.label(p_name TEXT) RETURNS public.ltree\n"
        "LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$\n"
        "BEGIN\n"
        "    RETURN public.text2ltree(public.unaccent('public.unaccent'::regdictionary, p_name));\n"
        "END;\n"
        "$$;\n"
    ),
}


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


def _payload(*args: str) -> dict:
    result = runner.invoke(
        app, ["lint", "--select", "build_003", "--format", "json", "--fail-on", "never", *args]
    )
    assert result.exit_code == 0, result.output
    return json.loads(result.stdout)


def _locations(payload: dict) -> list[str]:
    return [i["location"] for i in payload["violations"]["items"] if i["rule_id"] == "build_003"]


def test_issue_741_repro_without_server(in_tmp: Path) -> None:
    """The issue's tree, no server to ask: neither extension routine is a finding."""
    _project(in_tmp, ISSUE_741)

    locations = _locations(_payload())

    assert not [loc for loc in locations if "public.text2ltree" in loc or "public.unaccent" in loc]


# The split: which outstanding references an extension the build creates may answer.


def _ext(name: str, schema: str | None, *, line: int = 1) -> BuiltExtension:
    return BuiltExtension(
        name=name,
        schema=schema or DEFAULT_SCHEMA,
        schema_written=schema is not None,
        file="db/schema/001_extensions.sql",
        line=line,
        create_sql=f"CREATE EXTENSION IF NOT EXISTS {name}",
    )


def _ref(schema: str | None, name: str, kind: str = ROUTINE) -> tuple[str | None, Reference]:
    return (
        "db/schema/002_fn.sql",
        Reference(
            schema=schema,
            name=name,
            kind=kind,
            line=3,
            referrer="app.f()",
            referrer_kind="function",
        ),
    )


def _written(extensions: list[BuiltExtension]) -> list[BuiltExtension]:
    """What may loosen a verdict with no server to ask."""
    return [e for e in extensions if e.schema_written]


class TestTheSplit:
    def test_a_qualified_name_into_an_extension_schema_may_be_the_extension_s(self) -> None:
        candidate = _ref("public", "text2ltree")

        maybe, missing = split_by_extension([candidate], [_ext("ltree", "public")], ())

        assert (maybe, missing) == ([candidate], [])

    def test_a_qualified_name_elsewhere_is_missing(self) -> None:
        candidate = _ref("app", "nope")

        maybe, missing = split_by_extension([candidate], [_ext("ltree", "public")], ())

        assert (maybe, missing) == ([], [candidate])

    def test_an_unqualified_relation_through_the_search_path(self) -> None:
        candidate = _ref(None, "some_table", RELATION)

        maybe, _missing = split_by_extension(
            [candidate], [_ext("ltree", "public")], ("app", "public")
        )

        assert maybe == [candidate]

    def test_an_unqualified_routine_is_never_a_candidate(self) -> None:
        candidate = _ref(None, "text2ltree")

        maybe, missing = split_by_extension(
            [candidate], [_ext("ltree", "public")], ("app", "public")
        )

        assert (maybe, missing) == ([], [candidate])

    def test_schemas_compare_in_the_parser_s_spelling(self) -> None:
        candidate = _ref("ext", "x")

        maybe, _missing = split_by_extension([candidate], [_ext("x", "Ext")], ())

        assert maybe == []

    def test_an_extension_with_no_schema_clause_does_not_loosen_without_a_server(self) -> None:
        candidate = _ref("public", "gen_random_uuid")

        maybe, missing = split_by_extension([candidate], _written([_ext("pgcrypto", None)]), ())

        assert (maybe, missing) == ([], [candidate])

    def test_a_parameterless_language_does_not_loosen_without_a_server(self) -> None:
        candidate = _ref("public", "nope")

        maybe, missing = split_by_extension([candidate], _written([_ext("plpgsql", None)]), ())

        assert (maybe, missing) == ([], [candidate])

    def test_one_written_extension_in_the_schema_is_enough(self) -> None:
        candidate = _ref("public", "x")
        extensions = [_ext("ltree", "public"), _ext("pgcrypto", None)]

        maybe, _missing = split_by_extension([candidate], _written(extensions), ())

        assert maybe == [candidate]


# Through the CLI: one degraded entry, not findings.

_TIER_B = "no database answered"


def _extension_entries(payload: dict) -> list[dict]:
    return [
        d
        for d in payload.get("degraded", [])
        if d["code"] == "build_003" and "where the build creates" in d["reason"]
    ]


def test_the_issue_s_references_are_one_unchecked_entry(in_tmp: Path) -> None:
    _project(in_tmp, ISSUE_741)

    payload = _payload()

    assert _locations(payload) == []
    [entry] = _extension_entries(payload)
    assert "2 references into public" in entry["reason"]
    assert "ltree (db/schema/001_extensions.sql:1)" in entry["reason"]
    assert "unaccent (db/schema/001_extensions.sql:2)" in entry["reason"]
    assert "no scratch server is configured" in entry["reason"]


def test_the_live_tier_s_entry_stays_beside_it(in_tmp: Path) -> None:
    """Two facts, two entries: neither swallows the other into something vaguer."""
    _project(in_tmp, ISSUE_741)

    reasons = [d["reason"] for d in _payload()["degraded"] if d["code"] == "build_003"]

    assert len([r for r in reasons if _TIER_B in r]) == 1
    assert len(reasons) == 2


def test_several_extension_schemas_are_still_one_entry(in_tmp: Path) -> None:
    _project(
        in_tmp,
        {
            "001_extensions.sql": (
                "CREATE SCHEMA IF NOT EXISTS ext;\n"
                "CREATE EXTENSION IF NOT EXISTS ltree SCHEMA public;\n"
                "CREATE EXTENSION IF NOT EXISTS unaccent SCHEMA ext;\n"
            ),
            "002_fn.sql": (
                "CREATE SCHEMA IF NOT EXISTS app;\n"
                "CREATE FUNCTION app.f(p text) RETURNS text LANGUAGE plpgsql AS $$\n"
                "BEGIN\n"
                "    RETURN ext.unaccent(public.text2ltree(p)::text);\n"
                "END;\n"
                "$$;\n"
            ),
        },
    )

    [entry] = _extension_entries(_payload())

    assert "1 reference into public" in entry["reason"]
    assert "1 reference into ext" in entry["reason"]


_CALLS_NOPE = (
    "CREATE SCHEMA IF NOT EXISTS app;\n"
    "CREATE FUNCTION app.f() RETURNS void LANGUAGE plpgsql AS $$\n"
    "BEGIN\n"
    "    PERFORM {target}();\n"
    "END;\n"
    "$$;\n"
)


def test_a_reference_into_a_schema_with_no_extension_still_reports(in_tmp: Path) -> None:
    _project(
        in_tmp,
        {
            "001_extensions.sql": "CREATE EXTENSION IF NOT EXISTS ltree SCHEMA public;\n",
            "002_fn.sql": _CALLS_NOPE.format(target="app.nope"),
        },
    )

    payload = _payload()

    assert _locations(payload) == ["app.f() -> app.nope"]
    assert _extension_entries(payload) == []


def test_public_still_reports_when_the_only_extension_is_elsewhere(in_tmp: Path) -> None:
    _project(
        in_tmp,
        {
            "001_extensions.sql": (
                "CREATE SCHEMA IF NOT EXISTS ext;\n"
                "CREATE EXTENSION IF NOT EXISTS ltree SCHEMA ext;\n"
            ),
            "002_fn.sql": _CALLS_NOPE.format(target="public.nope"),
        },
    )

    assert _locations(_payload()) == ["app.f() -> public.nope"]


def test_an_extension_with_no_schema_clause_keeps_the_finding_and_says_how_to_clear_it(
    in_tmp: Path,
) -> None:
    """Where an unwritten schema lands is not a fact the tree states."""
    _project(
        in_tmp,
        {
            "001_extensions.sql": "CREATE EXTENSION IF NOT EXISTS pgcrypto;\n",
            "002_fn.sql": (
                "CREATE SCHEMA IF NOT EXISTS app;\n"
                "CREATE FUNCTION app.fn_id() RETURNS uuid LANGUAGE sql AS $$\n"
                "    SELECT public.gen_random_uuid()\n"
                "$$;\n"
            ),
        },
    )

    payload = _payload()

    [finding] = [i for i in payload["violations"]["items"] if i["rule_id"] == "build_003"]
    assert finding["location"] == "app.fn_id() -> public.gen_random_uuid"
    assert "no file in the build creates it" in finding["message"]
    assert "pgcrypto (db/schema/001_extensions.sql:1) with no SCHEMA clause" in finding["message"]
    assert "--server-url, or scratch_url" in finding["message"]
    assert finding["suggested_fix"].startswith("If an extension provides it:")
    assert _extension_entries(payload) == []


def test_the_hint_is_only_for_a_name_the_unwritten_extension_could_hold(in_tmp: Path) -> None:
    _project(
        in_tmp,
        {
            "001_extensions.sql": "CREATE EXTENSION IF NOT EXISTS pgcrypto;\n",
            "002_fn.sql": _CALLS_NOPE.format(target="app.nope"),
        },
    )

    [finding] = [i for i in _payload()["violations"]["items"] if i["rule_id"] == "build_003"]

    assert finding["message"] == (
        "Function 'app.f()' references routine 'app.nope', and no file in the build creates it"
    )


# The gate and the baseline.


def test_fail_on_warning_passes_over_the_issue_s_tree(in_tmp: Path) -> None:
    _project(in_tmp, ISSUE_741)

    result = runner.invoke(app, ["lint", "--select", "build_003", "--fail-on", "warning"])

    assert result.exit_code == 0, result.output


def test_a_baseline_of_the_old_findings_lists_them_as_fixed(in_tmp: Path) -> None:
    _project(in_tmp, ISSUE_741)
    baseline = in_tmp / "baseline.json"
    baseline.write_text(
        json.dumps(
            {
                "version": 1,
                "rules": {
                    "build_003": [
                        "build_003:function:app.label(text) -> public.text2ltree",
                        "build_003:function:app.label(text) -> public.unaccent",
                    ]
                },
            }
        )
    )

    payload = _payload("--baseline", str(baseline))

    assert sorted(payload["baseline"]["fixed"]) == [
        "build_003:function:app.label(text) -> public.text2ltree",
        "build_003:function:app.label(text) -> public.unaccent",
    ]


def test_require_complete_refuses_a_run_that_could_not_check_an_extension(
    in_tmp: Path,
) -> None:
    """A behaviour change, stated in the CHANGELOG: this used to exit by --fail-on."""
    _project(in_tmp, ISSUE_741)

    result = runner.invoke(
        app, ["lint", "--select", "build_003", "--fail-on", "never", "--require-complete"]
    )

    assert result.exit_code == 2, result.output
    assert "were not checked" in result.output


# The scratch tier: which server it asks, and what it costs. No server is
# reached from here; the integration tests ask a real one.

#: A host the fake ``connect`` below answers for, so the pre-probe succeeds.
_SCRATCH = "postgresql://scratcher:s3cret@scratch.invalid:5432/postgres"


class _Answered:
    """What the pre-probe's ``with psycopg.connect(...)`` gets: a connection it closes."""

    def __enter__(self) -> _Answered:
        return self

    def __exit__(self, *exc: object) -> None:
        return None


def _connect_scratch_only(url: str, **_kwargs: object) -> _Answered:
    if "scratch.invalid" not in url:
        raise psycopg.OperationalError("connection refused")
    return _Answered()


@pytest.fixture
def no_scratch_database(monkeypatch: pytest.MonkeyPatch) -> None:
    """Building a scratch database fails the test: the tier must not have run."""

    def refuse(_self: object) -> str:
        raise AssertionError("a scratch database was built")

    monkeypatch.setattr(psycopg, "connect", _connect_scratch_only)
    monkeypatch.setattr(TempDatabase, "__enter__", refuse)


@pytest.mark.usefixtures("no_scratch_database")
class TestNothingIsBuiltWithNothingToAsk:
    def test_a_tree_with_no_extension(self, in_tmp: Path) -> None:
        _project(in_tmp, {"010_fn.sql": _CALLS_NOPE.format(target="public.nope")})

        assert _locations(_payload("--server-url", _SCRATCH)) == ["app.f() -> public.nope"]

    def test_references_outside_every_extension_schema(self, in_tmp: Path) -> None:
        _project(
            in_tmp,
            {
                "001_extensions.sql": "CREATE EXTENSION IF NOT EXISTS ltree SCHEMA public;\n",
                "002_fn.sql": _CALLS_NOPE.format(target="app.nope"),
            },
        )

        assert _locations(_payload("--server-url", _SCRATCH)) == ["app.f() -> app.nope"]

    def test_the_live_tier_answered_everything(
        self, in_tmp: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _project(in_tmp, ISSUE_741)
        monkeypatch.setattr(
            SchemaLinter,
            "_probe",
            lambda _self, _c, _p, _s: LiveCatalogue(
                relations=frozenset(),
                routines=frozenset({"public.text2ltree", "public.unaccent"}),
            ),
        )

        payload = _payload("--server-url", _SCRATCH)

        assert _locations(payload) == []
        assert payload.get("degraded", []) == []

    def test_no_scratch_server_configured(self, in_tmp: Path) -> None:
        _project(in_tmp, ISSUE_741)

        [entry] = _extension_entries(_payload())

        assert "no scratch server is configured" in entry["reason"]


def test_database_url_is_never_the_scratch_server(in_tmp: Path) -> None:
    """A lint creates no database on the server it lints against, unless told to."""
    _project(
        in_tmp,
        ISSUE_741,
        env=f"database_url: {_SCRATCH}\ninclude_dirs:\n  - path: db/schema\n",
    )
    asked: list[str] = []

    def scratch_names(server_url: str, *_args: object, **_kwargs: object) -> object:
        asked.append(server_url)
        raise AssertionError("asked a scratch server")

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(unresolved, "scratch_names", scratch_names)
        payload = _payload()

    assert asked == []
    assert "no scratch server is configured" in _extension_entries(payload)[0]["reason"]


def test_scratch_url_in_the_environment_is_the_server(
    in_tmp: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _project(in_tmp, ISSUE_741, env=_ENV + f"scratch_url: {_SCRATCH}\n")
    asked: list[str] = []

    def scratch_names(server_url: str, *_args: object, **_kwargs: object) -> object:
        asked.append(server_url)
        raise unresolved.ScratchUnavailable("stub")

    monkeypatch.setattr(unresolved, "scratch_names", scratch_names)
    _payload()

    assert asked == [_SCRATCH]


def test_server_url_wins_over_scratch_url(in_tmp: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _project(in_tmp, ISSUE_741, env=_ENV + "scratch_url: postgresql://elsewhere/postgres\n")
    asked: list[str] = []

    def scratch_names(server_url: str, *_args: object, **_kwargs: object) -> object:
        asked.append(server_url)
        raise unresolved.ScratchUnavailable("stub")

    monkeypatch.setattr(unresolved, "scratch_names", scratch_names)
    _payload("--server-url", _SCRATCH)

    assert asked == [_SCRATCH]


class TestEachFailureSaysWhatFailed:
    def test_an_unreachable_server(self, in_tmp: Path) -> None:
        _project(in_tmp, ISSUE_741)

        [entry] = _extension_entries(
            _payload("--server-url", "postgresql://u:hunter2@127.0.0.1:1/postgres")
        )

        assert "no scratch server answered at" in entry["reason"]
        assert "127.0.0.1:1" in entry["reason"]
        assert "hunter2" not in entry["reason"]
        assert "2 references into public" in entry["reason"]

    def test_a_server_that_refuses_the_scratch_database(
        self, in_tmp: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def refuse(_self: object) -> str:
            raise SchemaError("permission denied to create database")

        monkeypatch.setattr(psycopg, "connect", _connect_scratch_only)
        monkeypatch.setattr(TempDatabase, "__enter__", refuse)
        _project(in_tmp, ISSUE_741)

        [entry] = _extension_entries(_payload("--server-url", _SCRATCH))

        assert "permission denied to create database" in entry["reason"]
        assert "s3cret" not in entry["reason"]
        assert _locations(_payload("--server-url", _SCRATCH)) == []


def test_an_empty_schema_runs_no_psql(monkeypatch: pytest.MonkeyPatch) -> None:
    """The scratch tier builds nothing from text, so it needs no ``psql`` binary."""
    applied: list[str] = []
    monkeypatch.setattr(TempDatabase, "apply_schema", lambda _self, _url, sql: applied.append(sql))
    db = ExpectedSchemaDB("postgresql://localhost/postgres").from_source(schema_sql="")
    db._td = TempDatabase("postgresql://localhost/postgres")
    db._temp_url = "postgresql://localhost/scratch"

    db._build()

    assert applied == []


def test_a_live_no_is_not_final_when_the_build_creates_the_extension(
    in_tmp: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The live database lacks ``public.text2ltree``: its migration has not run there yet."""
    _project(in_tmp, ISSUE_741, env=_ENV + f"scratch_url: {_SCRATCH}\n")
    monkeypatch.setattr(
        SchemaLinter,
        "_probe",
        lambda _self, _c, _p, _s: LiveCatalogue(relations=frozenset(), routines=frozenset()),
    )
    asked: list[list[str]] = []

    def scratch_names(_server: str, _exts: object, _schemas: object, candidates, *_a, **_k):
        asked.append(sorted(ref.qualified for _file, ref in candidates))
        return unresolved.ScratchAnswer(
            unresolved.LiveCatalogue(
                relations=frozenset(),
                routines=frozenset({"public.text2ltree", "public.unaccent"}),
            )
        )

    monkeypatch.setattr(unresolved, "scratch_names", scratch_names)

    payload = _payload()

    assert asked == [["public.text2ltree", "public.unaccent"]]
    assert _locations(payload) == []
    assert payload.get("degraded", []) == []


def test_a_tree_with_no_extension_never_folds_the_tree_again(
    in_tmp: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One unresolved name must not cost a second pass over every statement (release review)."""
    from confiture.core.linting import extensions

    def refuse(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("declared_objects ran for a tree with no CREATE EXTENSION")

    monkeypatch.setattr(extensions, "declared_objects", refuse)
    _project(in_tmp, {"010_fn.sql": _CALLS_NOPE.format(target="public.nope")})

    assert _locations(_payload("--server-url", _SCRATCH)) == ["app.f() -> public.nope"]
