"""``build_003`` asks a scratch database what the build's extensions provide (#741).

The question is PostgreSQL's to answer: which routines ``CREATE EXTENSION ltree
SCHEMA public`` creates is in the extension's install script, on the server. So
these tests build a real scratch database and ask it, and ``database_url`` is
on a port nothing listens on, so the live tier cannot answer in the scratch's
place: a test that passed through the live tier would pass without the fix.
"""

import json
import os
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import pytest
from typer.testing import CliRunner

from confiture.cli.main import app

runner = CliRunner()

pytestmark = pytest.mark.integration

_UNREACHABLE = "postgresql://127.0.0.1:1/confiture_no_such_server"

_EXTENSIONS = (
    "CREATE EXTENSION IF NOT EXISTS ltree SCHEMA public;\n"
    "CREATE EXTENSION IF NOT EXISTS unaccent SCHEMA public;\n"
)


def _caller(body: str, returns: str = "text") -> str:
    return (
        "CREATE SCHEMA IF NOT EXISTS app;\n"
        f"CREATE FUNCTION app.f(p_name text) RETURNS {returns}\n"
        "LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$\n"
        "BEGIN\n"
        f"    {body}\n"
        "END;\n"
        "$$;\n"
    )


def _project(root: Path, files: dict[str, str]) -> None:
    (root / "db" / "schema").mkdir(parents=True, exist_ok=True)
    (root / "db" / "environments").mkdir(parents=True, exist_ok=True)
    (root / "db" / "environments" / "local.yaml").write_text(
        f"database_url: {_UNREACHABLE}\ninclude_dirs:\n  - path: db/schema\n"
    )
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


def _payload(server_url: str) -> dict:
    result = runner.invoke(
        app,
        [
            "lint",
            "--select",
            "build_003",
            "--format",
            "json",
            "--fail-on",
            "never",
            "--server-url",
            server_url,
        ],
    )
    assert result.exit_code == 0, result.output
    return json.loads(result.stdout)


def _findings(payload: dict) -> list[dict]:
    return [i for i in payload["violations"]["items"] if i["rule_id"] == "build_003"]


def _extension_reasons(payload: dict) -> list[str]:
    return [
        d["reason"]
        for d in payload.get("degraded", [])
        if d["code"] == "build_003" and "no database answered" not in d["reason"]
    ]


class TestTheScratchAnswers:
    def test_a_typo_is_still_a_finding_and_the_real_routines_are_not(
        self, in_tmp: Path, test_db_url: str
    ) -> None:
        _project(
            in_tmp,
            {
                "001_extensions.sql": _EXTENSIONS,
                "002_fn.sql": _caller(
                    "RETURN public.text2ltre(public.unaccent("
                    "'public.unaccent'::regdictionary, p_name))::text;"
                ),
            },
        )

        payload = _payload(test_db_url)

        [finding] = _findings(payload)
        assert finding["location"] == "app.f(text) -> public.text2ltre"
        assert "(not provided by extension(s) ltree, unaccent in public)" in finding["message"]
        assert _extension_reasons(payload) == []
        # The live tier still says it could not answer: that is true, and its own fact.
        assert any("no database answered" in d["reason"] for d in payload["degraded"])

    def test_the_issue_s_tree_is_clean(self, in_tmp: Path, test_db_url: str) -> None:
        _project(
            in_tmp,
            {
                "001_extensions.sql": _EXTENSIONS,
                "002_fn.sql": _caller(
                    "RETURN public.text2ltree(public.unaccent("
                    "'public.unaccent'::regdictionary, p_name));",
                    returns="public.ltree",
                ),
            },
        )

        payload = _payload(test_db_url)

        assert _findings(payload) == []
        # Nothing was left for a live database to answer, so its silence cost nothing.
        assert payload.get("degraded", []) == []

    def test_only_the_server_of_the_scratch_url_is_used(
        self, in_tmp: Path, test_db_url: str
    ) -> None:
        """A scratch URL naming a database that does not exist names a server that does."""
        _project(
            in_tmp,
            {
                "001_extensions.sql": _EXTENSIONS,
                "002_fn.sql": _caller(
                    "RETURN public.text2ltree(public.unaccent("
                    "'public.unaccent'::regdictionary, p_name));",
                    returns="public.ltree",
                ),
            },
        )
        server = test_db_url.rsplit("/", 1)[0] + "/confiture_no_such_database"

        payload = _payload(server)

        assert _findings(payload) == []
        assert _extension_reasons(payload) == []


class TestWhereTheExtensionReallyIs:
    def test_a_schema_owned_by_a_role_the_server_has_not_got(
        self, in_tmp: Path, test_db_url: str
    ) -> None:
        """The schema is created by name: the tree's ``AUTHORIZATION`` is not replayed."""
        _project(
            in_tmp,
            {
                "001_extensions.sql": (
                    "CREATE SCHEMA ext AUTHORIZATION confiture_no_such_role;\n"
                    "CREATE EXTENSION unaccent SCHEMA ext;\n"
                ),
                "002_fn.sql": _caller("RETURN ext.unaccent(p_name);"),
            },
        )

        payload = _payload(test_db_url)

        assert _findings(payload) == []
        assert _extension_reasons(payload) == []

    def test_no_schema_clause_is_asked_too(self, in_tmp: Path, test_db_url: str) -> None:
        _project(
            in_tmp,
            {
                "001_extensions.sql": "CREATE EXTENSION IF NOT EXISTS unaccent;\n",
                "002_fn.sql": _caller("RETURN public.unaccent(p_name);"),
            },
        )

        payload = _payload(test_db_url)

        assert _findings(payload) == []

    def test_a_parameterless_language_is_harmless(self, in_tmp: Path, test_db_url: str) -> None:
        _project(
            in_tmp,
            {
                "001_extensions.sql": "CREATE LANGUAGE plpgsql;\n",
                "002_fn.sql": _caller("PERFORM public.nope(); RETURN p_name;"),
            },
        )

        payload = _payload(test_db_url)

        [finding] = _findings(payload)
        assert finding["location"] == "app.f(text) -> public.nope"
        # The scratch was asked, and said no: a hint to configure one would be wrong.
        assert "(not provided by extension(s) plpgsql in public)" in finding["message"]
        assert "with no SCHEMA clause" not in finding["message"]
        assert _extension_reasons(payload) == []

    def test_an_extension_elsewhere_builds_no_scratch(
        self, in_tmp: Path, test_db_url: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from confiture.core.temp_database import TempDatabase

        def refuse(_self: object) -> str:
            raise AssertionError("a scratch database was built")

        monkeypatch.setattr(TempDatabase, "__enter__", refuse)
        _project(
            in_tmp,
            {
                "001_extensions.sql": (
                    "CREATE SCHEMA ext;\nCREATE EXTENSION unaccent SCHEMA ext;\n"
                ),
                "002_fn.sql": _caller("RETURN public.unaccent(p_name);"),
            },
        )

        [finding] = _findings(_payload(test_db_url))

        assert finding["location"] == "app.f(text) -> public.unaccent"

    def test_cascade_installs_what_the_extension_needs_into_its_schema(
        self, in_tmp: Path, test_db_url: str
    ) -> None:
        _project(
            in_tmp,
            {
                "001_extensions.sql": (
                    "CREATE EXTENSION IF NOT EXISTS earthdistance SCHEMA public CASCADE;\n"
                ),
                "002_fn.sql": _caller(
                    "RETURN public.cube_distance(public.cube(1), public.cube(2))::text;"
                ),
            },
        )

        payload = _payload(test_db_url)

        assert _findings(payload) == []
        assert _extension_reasons(payload) == []


class TestEachFailureSaysWhatFailed:
    def test_an_extension_the_server_has_not_got(self, in_tmp: Path, test_db_url: str) -> None:
        """``ltree`` is still asked; a name ``no_such_ext`` might provide is unchecked."""
        _project(
            in_tmp,
            {
                "001_extensions.sql": (
                    "CREATE EXTENSION IF NOT EXISTS ltree SCHEMA public;\n"
                    "CREATE EXTENSION IF NOT EXISTS no_such_ext SCHEMA public;\n"
                ),
                "002_fn.sql": _caller(
                    "RETURN public.text2ltree(public.from_no_such_ext(p_name))::text;"
                ),
            },
        )

        payload = _payload(test_db_url)

        assert _findings(payload) == []
        [reason] = _extension_reasons(payload)
        assert "1 reference into public" in reason
        assert "no_such_ext (db/schema/001_extensions.sql:2)" in reason
        assert "is not available" in reason

    def test_a_version_the_server_has_not_got(self, in_tmp: Path, test_db_url: str) -> None:
        _project(
            in_tmp,
            {
                "001_extensions.sql": "CREATE EXTENSION unaccent SCHEMA public VERSION '0.0';\n",
                "002_fn.sql": _caller("RETURN public.unaccent(p_name);"),
            },
        )

        payload = _payload(test_db_url)

        assert _findings(payload) == []
        [reason] = _extension_reasons(payload)
        assert '"0.0"' in reason

    def test_a_schema_the_tree_never_creates(self, in_tmp: Path, test_db_url: str) -> None:
        _project(
            in_tmp,
            {
                "001_extensions.sql": "CREATE EXTENSION ltree SCHEMA nowhere;\n",
                "002_fn.sql": _caller("RETURN nowhere.text2ltree(p_name)::text;"),
            },
        )

        payload = _payload(test_db_url)

        assert _findings(payload) == []
        [reason] = _extension_reasons(payload)
        assert 'schema "nowhere" does not exist' in reason

    def test_no_reason_carries_the_password(self, in_tmp: Path, test_db_url: str) -> None:
        _project(
            in_tmp,
            {
                "001_extensions.sql": "CREATE EXTENSION ltree SCHEMA nowhere;\n",
                "002_fn.sql": _caller("RETURN nowhere.text2ltree(p_name)::text;"),
            },
        )
        password = "pw-that-must-not-print"
        parsed = urlsplit(test_db_url)
        host = parsed.netloc.rsplit("@", 1)[-1]
        user = parsed.username or "confiture_nobody"
        server = urlunsplit(parsed._replace(netloc=f"{user}:{password}@{host}"))

        payload = _payload(server)

        assert payload.get("degraded")

        assert all(password not in d["reason"] for d in payload.get("degraded", []))
