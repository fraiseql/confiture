"""``build_004`` and the routines an extension the build creates provides (#747).

``CREATE EXTENSION ltree SCHEMA public`` creates ``public.text2ltree``; no file
spells it out. A ``LANGUAGE sql`` body that calls it, created in a file before
the extension's, fails the build with "function public.text2ltree(text) does not
exist". Only a server knows what an extension creates, so with a scratch server
the scratch is asked after each ``CREATE EXTENSION``, and without one the rule
says what it could not order rather than staying silent.
"""

import json
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from confiture.cli.main import app
from confiture.core.linting import unresolved
from confiture.core.linting.unresolved import LiveCatalogue, ScratchAnswer

runner = CliRunner()

_SCRATCH = "postgresql://127.0.0.1:1/postgres"
_ENV = (
    "database_url: postgresql://127.0.0.1:1/confiture_no_such_server\n"
    "include_dirs:\n  - path: db/schema\n"
)
_SCHEMA = "CREATE SCHEMA IF NOT EXISTS app;\n"
_EXTENSION = "CREATE EXTENSION IF NOT EXISTS ltree SCHEMA public;\n"
_SQL_BODY = (
    "CREATE FUNCTION app.path(p text) RETURNS text LANGUAGE sql\n"
    "AS $$ SELECT public.text2ltree(p)::text $$;\n"
)
_PLPGSQL_BODY = (
    "CREATE FUNCTION app.path(p text) RETURNS text LANGUAGE plpgsql\n"
    "AS $$ BEGIN RETURN public.text2ltree(p)::text; END; $$;\n"
)
_DEFAULT = "CREATE TABLE app.t (p text DEFAULT public.text2ltree('a')::text);\n"


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


def _payload(*args: str, select: str = "build_004") -> dict:
    result = runner.invoke(
        app, ["lint", "--select", select, "--format", "json", "--fail-on", "never", *args]
    )
    assert result.exit_code == 0, result.output
    return json.loads(result.stdout)


def _forward(payload: dict) -> list[dict]:
    return [v for v in payload["violations"]["items"] if v["rule_id"] == "build_004"]


def _degraded(payload: dict) -> list[dict]:
    return [d for d in payload.get("degraded", []) if d["code"] == "build_004"]


@pytest.fixture
def scratch(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    """A scratch whose ltree provides ``public.text2ltree``; records each ask."""
    asked: list[list[str]] = []

    def scratch_names(_server: str, extensions: Any, _schemas: Any, candidates: Any, *_a, **_k):
        asked.append(sorted(ref.qualified for _file, ref in candidates))
        ltree = LiveCatalogue(relations=frozenset(), routines=frozenset({"public.text2ltree"}))
        return ScratchAnswer(ltree, after=tuple(ltree for _ext in extensions))

    monkeypatch.setattr(unresolved, "scratch_names", scratch_names)
    return asked


@pytest.mark.parametrize("caller", [_SQL_BODY, _DEFAULT], ids=["language-sql", "default"])
def test_a_call_before_the_extension_is_a_forward_reference(
    in_tmp: Path, scratch: list[list[str]], caller: str
) -> None:
    _project(in_tmp, {"00_app.sql": _SCHEMA + caller, "10_ext.sql": _EXTENSION})

    [finding] = _forward(_payload("--server-url", _SCRATCH))

    assert finding["file"].endswith("db/schema/00_app.sql")
    assert "'public.text2ltree'" in finding["message"]
    assert "db/schema/10_ext.sql:1" in finding["message"]
    assert "extension ltree" in finding["message"]


def test_a_call_after_the_extension_is_fine(in_tmp: Path, scratch: list[list[str]]) -> None:
    _project(in_tmp, {"00_ext.sql": _EXTENSION, "10_app.sql": _SCHEMA + _SQL_BODY})

    payload = _payload("--server-url", _SCRATCH)

    assert _forward(payload) == []
    assert _degraded(payload) == []
    assert scratch == []  # nothing to order: no scratch is built


def test_a_plpgsql_body_is_resolved_when_it_runs(in_tmp: Path, scratch: list[list[str]]) -> None:
    _project(in_tmp, {"00_app.sql": _SCHEMA + _PLPGSQL_BODY, "10_ext.sql": _EXTENSION})

    assert _forward(_payload("--server-url", _SCRATCH)) == []


def test_without_a_scratch_server_the_rule_says_what_it_could_not_order(in_tmp: Path) -> None:
    _project(in_tmp, {"00_app.sql": _SCHEMA + _SQL_BODY, "10_ext.sql": _EXTENSION})

    payload = _payload()

    assert _forward(payload) == []
    [entry] = _degraded(payload)
    assert "ltree (db/schema/10_ext.sql:1)" in entry["reason"]
    assert "no scratch server is configured" in entry["reason"]
    assert "1 reference" in entry["reason"]


def test_an_unreachable_scratch_server_is_named(in_tmp: Path) -> None:
    _project(in_tmp, {"00_app.sql": _SCHEMA + _SQL_BODY, "10_ext.sql": _EXTENSION})

    [entry] = _degraded(_payload("--server-url", "postgresql://u:hunter2@127.0.0.1:1/postgres"))

    assert "no scratch server answered at" in entry["reason"]
    assert "hunter2" not in entry["reason"]


def test_one_scratch_answers_both_rules(in_tmp: Path, scratch: list[list[str]]) -> None:
    """build_003's outstanding names and build_004's ordering share one scratch build."""
    _project(
        in_tmp,
        {
            "00_app.sql": _SCHEMA + _SQL_BODY,
            "10_ext.sql": _EXTENSION,
            "20_other.sql": (
                "CREATE FUNCTION app.other(p text) RETURNS text LANGUAGE plpgsql\n"
                "AS $$ BEGIN RETURN public.nlevel(p)::text; END; $$;\n"
            ),
        },
    )

    _payload("--server-url", _SCRATCH, select="build_003,build_004")

    assert scratch == [["public.nlevel", "public.text2ltree"]]
