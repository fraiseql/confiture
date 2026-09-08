"""``build_003``'s live tier, against a real server (#246, D4).

Tier (a) is the DDL tree, and a project's objects do not all come from it: a
migration creates some, an extension owns others. Both are real, both are
absent from the build, and reporting them is the false positive that would make
the rule unusable on the schema #246 was filed from.

The tier that answers for them needs a database, so it is tested here rather
than with a stub: what is at stake is the SQL — ``to_regclass`` for relations
and ``pg_proc`` for routines, one round trip for every outstanding name — and a
stub would only prove that the code calls itself.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from typer.testing import CliRunner

from confiture.cli.main import app

runner = CliRunner()

pytestmark = pytest.mark.integration

_SCHEMA = "confiture_build003_it"

CALLER = f"""CREATE SCHEMA IF NOT EXISTS app;
CREATE FUNCTION app.fn_report() RETURNS SETOF bigint LANGUAGE sql AS $$
    SELECT id FROM {_SCHEMA}.tb_from_migration
$$;
"""

EXTENSION_CALLER = """CREATE SCHEMA IF NOT EXISTS app;
CREATE FUNCTION app.fn_id() RETURNS uuid LANGUAGE sql AS $$
    SELECT public.gen_random_uuid()
$$;
"""


@pytest.fixture
def live_objects(test_db_url: str) -> Iterator[str]:
    """A schema, a table and a function that exist in the database and in no file."""
    with psycopg.connect(test_db_url, autocommit=True) as conn:
        conn.execute(f"DROP SCHEMA IF EXISTS {_SCHEMA} CASCADE")
        conn.execute(f"CREATE SCHEMA {_SCHEMA}")
        conn.execute(f"CREATE TABLE {_SCHEMA}.tb_from_migration (id bigint PRIMARY KEY)")
        conn.execute(
            f"CREATE FUNCTION {_SCHEMA}.fn_from_migration() RETURNS int "
            "LANGUAGE sql AS $$ SELECT 1 $$"
        )
    try:
        yield test_db_url
    finally:
        with psycopg.connect(test_db_url, autocommit=True) as conn:
            conn.execute(f"DROP SCHEMA IF EXISTS {_SCHEMA} CASCADE")


def _project(root: Path, files: dict[str, str], database_url: str) -> None:
    (root / "db" / "schema").mkdir(parents=True, exist_ok=True)
    (root / "db" / "environments").mkdir(parents=True, exist_ok=True)
    (root / "db" / "environments" / "local.yaml").write_text(
        f"database_url: {database_url}\ninclude_dirs:\n  - path: db/schema\n"
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


def _payload() -> dict:
    result = runner.invoke(
        app, ["lint", "--select", "build_003", "--format", "json", "--fail-on", "never"]
    )
    assert result.exit_code == 0, result.output
    return json.loads(result.stdout)


def _findings(payload: dict) -> list[str]:
    return [i["location"] for i in payload["violations"]["items"] if i["rule_id"] == "build_003"]


def test_a_relation_the_database_has_is_not_a_finding(in_tmp: Path, live_objects: str) -> None:
    """The migration-created case: absent from the tree, present in the database."""
    _project(in_tmp, {"010_fn.sql": CALLER}, live_objects)

    assert _findings(_payload()) == []


def test_a_routine_the_database_has_is_not_a_finding(in_tmp: Path, live_objects: str) -> None:
    _project(
        in_tmp,
        {
            "010_fn.sql": (
                "CREATE SCHEMA IF NOT EXISTS app;\n"
                "CREATE FUNCTION app.fn_call() RETURNS int LANGUAGE sql AS $$\n"
                f"    SELECT {_SCHEMA}.fn_from_migration()\n"
                "$$;\n"
            )
        },
        live_objects,
    )

    assert _findings(_payload()) == []


def test_a_reachable_database_makes_the_run_undegraded(in_tmp: Path, live_objects: str) -> None:
    """The live tier answered, so nothing about this run has to be qualified."""
    _project(in_tmp, {"010_fn.sql": CALLER}, live_objects)

    assert _payload()["degraded"] == []


def test_a_name_the_database_does_not_have_still_reports(in_tmp: Path, live_objects: str) -> None:
    """Tier (b) removes findings; it never invents an answer for one it lacks."""
    _project(
        in_tmp,
        {
            "010_fn.sql": (
                "CREATE SCHEMA IF NOT EXISTS app;\n"
                "CREATE FUNCTION app.fn_x() RETURNS SETOF bigint LANGUAGE sql AS $$\n"
                f"    SELECT id FROM {_SCHEMA}.tb_nobody_has_this\n"
                "$$;\n"
            )
        },
        live_objects,
    )

    assert _findings(_payload()) == [f"app.fn_x() -> {_SCHEMA}.tb_nobody_has_this"]


def test_an_extension_owned_function_resolves_through_the_database(
    in_tmp: Path, test_db_url: str
) -> None:
    """#246's own example of a legitimate reference the tree cannot contain."""
    with psycopg.connect(test_db_url, autocommit=True) as conn:
        available = conn.execute(
            "SELECT 1 FROM pg_available_extensions WHERE name = 'pgcrypto'"
        ).fetchone()
        if not available:
            pytest.skip("pgcrypto is not available on this server: no extension to resolve through")
        try:
            conn.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
        except psycopg.errors.InsufficientPrivilege:
            pytest.skip("this role may not CREATE EXTENSION: no extension to resolve through")

    _project(in_tmp, {"010_fn.sql": EXTENSION_CALLER}, test_db_url)

    assert _findings(_payload()) == []
