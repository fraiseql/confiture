"""``build_003`` and the extensions the build itself creates (#741).

A ``CREATE EXTENSION … SCHEMA public`` in the tree creates routines no file
spells out. The rule must not report a call to one of them as "no file in the
build creates it" when a file in the build does, through the extension.
"""

import json
import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from typer.testing import CliRunner

from confiture.cli.main import app

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


@pytest.mark.xfail(strict=True, reason="#741: tier (a) reads CREATE EXTENSION as creating nothing")
def test_issue_741_repro_without_server(in_tmp: Path) -> None:
    """The issue's tree, no server to ask: neither extension routine is a finding."""
    _project(in_tmp, ISSUE_741)

    locations = _locations(_payload())

    assert not [loc for loc in locations if "public.text2ltree" in loc or "public.unaccent" in loc]
