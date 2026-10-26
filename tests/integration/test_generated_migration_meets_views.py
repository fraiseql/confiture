"""A generated migration passes a column change under the views that read it (#765).

PostgreSQL refuses ``ALTER COLUMN … TYPE`` and ``DROP COLUMN`` on a column a view
reads. Each case builds the old tree into a throwaway database holding rows,
generates the migration ``migrate diff --generate`` writes, and applies it: the
views are dropped before the change and created again after it, the views return
the same rows, and the down brings the old tree back.
"""

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import psycopg
import pytest
from tests.conftest import create_supported_pg_tviews, drop_roles
from typer.testing import CliRunner

from confiture.cli.main import app
from confiture.core.migration_generator import MigrationGenerator
from confiture.platform import diff

pytestmark = pytest.mark.integration

runner = CliRunner()

_TABLE = "CREATE TABLE tb_user (pk_user bigint PRIMARY KEY, id uuid NOT NULL, name text, age {age}{extra});\n"
_SEED = (
    "INSERT INTO tb_user VALUES (1, gen_random_uuid(), 'ada', 36), "
    "(2, gen_random_uuid(), 'alan', 41);\n"
)


@dataclass(frozen=True)
class Case:
    """An old tree and a new one around a column change, and what to read before and after."""

    old: str
    new: str
    reads: str


_RETYPED = _TABLE.format(age="bigint", extra="")
_KEPT = _TABLE.format(age="integer", extra="")
_DROPPED = "CREATE TABLE tb_user (pk_user bigint PRIMARY KEY, id uuid NOT NULL, name text);\n"
_VIEW = "CREATE VIEW v_user AS SELECT pk_user, name, age FROM tb_user;\n"
_ON_VIEW = "CREATE VIEW v_user_age AS SELECT pk_user, age * 2 AS twice FROM v_user;\n"
_MATVIEW = (
    "CREATE MATERIALIZED VIEW mv_user AS SELECT pk_user, age FROM tb_user;\n"
    "CREATE UNIQUE INDEX ux_mv_user ON mv_user (pk_user);\n"
    "GRANT SELECT ON mv_user TO PUBLIC;\n"
    "COMMENT ON MATERIALIZED VIEW mv_user IS 'ages';\n"
)

CASES = {
    "retype_under_a_view": Case(_KEPT + _VIEW, _RETYPED + _VIEW, "SELECT * FROM v_user"),
    "drop_under_a_view": Case(
        _KEPT + _VIEW,
        _DROPPED + "CREATE VIEW v_user AS SELECT pk_user, name FROM tb_user;\n",
        "SELECT pk_user, name FROM v_user",
    ),
    "retype_under_a_view_on_a_view": Case(
        _KEPT + _VIEW + _ON_VIEW, _RETYPED + _VIEW + _ON_VIEW, "SELECT * FROM v_user_age"
    ),
    "retype_under_a_matview": Case(_KEPT + _MATVIEW, _RETYPED + _MATVIEW, "SELECT * FROM mv_user"),
    "retype_under_a_view_reading_an_added_view": Case(
        _KEPT + _VIEW,
        _RETYPED
        + "CREATE VIEW v_age AS SELECT pk_user, age FROM tb_user;\n"
        + "CREATE VIEW v_user AS SELECT u.pk_user, u.name, a.age "
        + "FROM tb_user u JOIN v_age a USING (pk_user);\n",
        "SELECT * FROM v_user",
    ),
}


def _generate(tmp_path: Path, url: str, old: str, new: str) -> tuple[Path, Path]:
    config = tmp_path / "local.yaml"
    config.write_text(f"name: test\ndatabase_url: {url}\n")
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    MigrationGenerator(migrations).generate_sql(
        diff(old, new), "change", version="20260101000000", destructive="allow"
    )
    return config, migrations


def _migrate(command: str, migrations: Path, config: Path) -> tuple[int, dict]:
    args = ["migrate", command, "--migrations-dir", str(migrations), "--config", str(config)]
    if command == "down":
        args += ["--steps", "1"]
    result = runner.invoke(app, [*args, "--format", "json"])
    return result.exit_code, json.loads(result.output)


def _rows(url: str, query: str) -> list[tuple]:
    with psycopg.connect(url) as conn:
        return conn.execute(f"{query} ORDER BY 1").fetchall()  # nosec B608 - test-owned query


def _definitions(url: str) -> list[tuple]:
    """Each view and matview's columns and query, as PostgreSQL holds them."""
    with psycopg.connect(url) as conn:
        return conn.execute(
            "SELECT c.relname, c.relkind, pg_get_viewdef(c.oid), "
            "array_agg(format_type(a.atttypid, a.atttypmod) ORDER BY a.attnum) "
            "FROM pg_class c JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum > 0 "
            "WHERE c.relkind IN ('v', 'm') AND c.relnamespace = 'public'::regnamespace "
            "GROUP BY c.oid ORDER BY 1"
        ).fetchall()


def _build(url: str, sql: str, *, seed: bool = True) -> None:
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(sql)
        if seed:
            conn.execute(_SEED)
        if "mv_user" in sql:
            conn.execute("REFRESH MATERIALIZED VIEW mv_user")


@pytest.mark.parametrize("case_name", sorted(CASES))
def test_a_column_change_passes_under_the_views_that_read_it(
    case_name: str, fresh_database_factory: Callable[[str], str], tmp_path: Path
) -> None:
    case = CASES[case_name]
    url, expected_new = fresh_database_factory("confiture_t"), fresh_database_factory("confiture_t")
    _build(url, case.old)
    _build(expected_new, case.new, seed=False)
    before, old_definitions = _rows(url, case.reads), _definitions(url)
    config, migrations = _generate(tmp_path, url, case.old, case.new)

    code, payload = _migrate("up", migrations, config)

    assert code == 0, payload
    assert _rows(url, case.reads) == before
    assert _definitions(url) == _definitions(expected_new)

    code, payload = _migrate("down", migrations, config)

    assert code == 0, payload
    assert _definitions(url) == old_definitions


def test_a_matview_comes_back_with_its_index_grant_and_comment(
    fresh_database: str, tmp_path: Path
) -> None:
    case = CASES["retype_under_a_matview"]
    _build(fresh_database, case.old)
    config, migrations = _generate(tmp_path, fresh_database, case.old, case.new)

    code, payload = _migrate("up", migrations, config)

    assert code == 0, payload
    with psycopg.connect(fresh_database) as conn:
        index, comment, public_reads = conn.execute(
            "SELECT to_regclass('ux_mv_user') IS NOT NULL, "
            "obj_description('mv_user'::regclass, 'pg_class'), "
            "has_table_privilege('public', 'mv_user', 'SELECT')"
        ).fetchone()
    assert (index, comment, public_reads) == (True, "ages", True)


def test_preflight_tiers_the_wrap_as_the_change_it_carries(
    fresh_database: str, tmp_path: Path
) -> None:
    """A view dropped and created again is a replacement, not a destructive drop."""
    case = CASES["retype_under_a_view"]
    _build(fresh_database, case.old)
    config, migrations = _generate(tmp_path, fresh_database, case.old, case.new)

    result = runner.invoke(
        app,
        ["migrate", "preflight", "--migrations-dir", str(migrations), "--config", str(config),
         "--format", "json"],
    )  # fmt: skip

    tiers = {e["kind"]: e.get("tier") for e in json.loads(result.output)["change_set"]["changes"]}
    assert tiers["drop_view"] == "reversible"
    assert "confiture:destructive" not in (migrations / "20260101000000_change.up.sql").read_text()


_ISSUE_OLD = (
    "CREATE TABLE tb_user (pk_user bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, "
    "id uuid NOT NULL, name text, age integer, data jsonb NOT NULL DEFAULT '{}');\n"
    "CREATE VIEW v_user AS SELECT id, jsonb_build_object('id', id, 'name', name, 'age', age) "
    "AS data FROM tb_user;\n"
)
_ISSUE_NEW = (
    "CREATE TABLE tb_user (pk_user bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, "
    "id uuid NOT NULL, full_name text, age bigint, email text NOT NULL, "
    "data jsonb NOT NULL DEFAULT '{}');\n"
    "CREATE VIEW v_user AS SELECT id, jsonb_build_object('id', id, 'name', full_name, "
    "'age', age, 'email', email) AS data FROM tb_user;\n"
)


def test_the_issues_migration_applies_once_its_backfill_is_written(
    fresh_database: str, tmp_path: Path
) -> None:
    """#765's repro, which also adds a NOT NULL column nothing fills (#766)."""
    with psycopg.connect(fresh_database, autocommit=True) as conn:
        conn.execute(_ISSUE_OLD)
        conn.execute("INSERT INTO tb_user (id, name, age) VALUES (gen_random_uuid(), 'ada', 36)")
    config, migrations = _generate(tmp_path, fresh_database, _ISSUE_OLD, _ISSUE_NEW)

    code, payload = _migrate("up", migrations, config)
    assert (code, payload["error"]["code"]) == (5, "VALID_010")

    up = migrations / "20260101000000_change.up.sql"
    up.write_text(
        up.read_text().replace(
            "-- confiture:backfill tb_user.email", "UPDATE tb_user SET email = 'ada@example.com';"
        )
    )
    code, payload = _migrate("up", migrations, config)

    assert code == 0, payload
    assert _rows(
        fresh_database, "SELECT data->>'name', data->>'age', data->>'email' FROM v_user"
    ) == [("ada", "36", "ada@example.com")]


_TVIEW_OLD = _KEPT + (
    "CREATE VIEW v_user AS SELECT pk_user, jsonb_build_object('name', name, 'age', age) AS data "
    "FROM tb_user;\n"
    "CREATE TABLE tv_user AS SELECT pk_user, data FROM v_user;\n"
)
_TVIEW_NEW = _TVIEW_OLD.replace("age integer", "age bigint")


@pytest.fixture
def tview_database(fresh_database_factory: Callable[[str], str]) -> str:
    url = fresh_database_factory("confiture_tv")
    with psycopg.connect(url, autocommit=True) as conn:
        if not conn.execute(
            "SELECT 1 FROM pg_available_extensions WHERE name = 'pg_tviews'"
        ).fetchone():
            pytest.skip("pg_tviews is not installed on this server (the pg-tviews CI leg has it)")
        create_supported_pg_tviews(conn)
        conn.execute(_KEPT)
        conn.execute(_SEED)
        conn.execute(_TVIEW_OLD.removeprefix(_KEPT))
    return url


def test_a_column_change_passes_under_a_tview(tview_database: str, tmp_path: Path) -> None:
    before = _rows(tview_database, "SELECT pk_user, data FROM tv_user")
    config, migrations = _generate(tmp_path, tview_database, _TVIEW_OLD, _TVIEW_NEW)

    code, payload = _migrate("up", migrations, config)

    assert code == 0, payload
    assert _rows(tview_database, "SELECT pk_user, data FROM tv_user") == before
    with psycopg.connect(tview_database) as conn:
        assert conn.execute(
            "SELECT format_type(atttypid, atttypmod) FROM pg_attribute "
            "WHERE attrelid = 'tb_user'::regclass AND attname = 'age'"
        ).fetchone() == ("bigint",)

    code, payload = _migrate("down", migrations, config)

    assert code == 0, payload
    assert _rows(tview_database, "SELECT pk_user, data FROM tv_user") == before


_READER, _OWNER = "confiture_t787_reader", "confiture_t787_owner"


def _attached(url: str) -> tuple:
    with psycopg.connect(url) as conn:
        return conn.execute(
            "SELECT has_table_privilege(%s, 'v_user', 'SELECT'), "
            "obj_description('v_user'::regclass, 'pg_class'), "
            "pg_get_userbyid(relowner) FROM pg_class WHERE oid = 'v_user'::regclass",
            (_READER,),
        ).fetchone()


@pytest.fixture
def roles(maintenance_connection: psycopg.Connection):
    drop_roles(maintenance_connection, _READER, _OWNER)
    for role in (_READER, _OWNER):
        maintenance_connection.execute(
            psycopg.sql.SQL("CREATE ROLE {}").format(psycopg.sql.Identifier(role))
        )
    maintenance_connection.execute(
        psycopg.sql.SQL("GRANT {} TO current_user").format(psycopg.sql.Identifier(_OWNER))
    )
    yield
    drop_roles(maintenance_connection, _READER, _OWNER)


def test_a_view_diffed_from_a_database_keeps_its_grant_comment_and_owner(
    fresh_database: str, tmp_path: Path, roles: None
) -> None:
    """The database side carries what the drop takes; the tree writes none of it (#787)."""
    del roles
    with psycopg.connect(fresh_database, autocommit=True) as conn:
        conn.execute(_KEPT + _VIEW + _SEED)
        conn.execute(f"GRANT CREATE ON SCHEMA public TO {_OWNER}")
        conn.execute(f"GRANT SELECT ON v_user TO {_READER}")
        conn.execute("COMMENT ON VIEW v_user IS 'it''s the users'")
        conn.execute(f"ALTER VIEW v_user OWNER TO {_OWNER}")
    held = _attached(fresh_database)
    assert held == (True, "it's the users", _OWNER)
    config, migrations = _generate(tmp_path, fresh_database, fresh_database, _RETYPED + _VIEW)

    code, payload = _migrate("up", migrations, config)

    assert code == 0, payload
    assert _attached(fresh_database) == held

    code, payload = _migrate("down", migrations, config)

    assert code == 0, payload
    assert _attached(fresh_database) == held
