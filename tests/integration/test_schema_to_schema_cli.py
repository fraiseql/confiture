"""``confiture migrate schema-to-schema``, run by its command line against two real databases.

Medium 4 moves rows from an old database into a new one whose schema differs: the
target imports the source's ``public`` schema as a postgres_fdw foreign schema
(``old_schema``) and copies across it. Every test owns a pair of throwaway databases —
a source holding ``users`` and ``posts`` with rows, and a target declaring the same
tables with renamed columns (``full_name`` → ``display_name``, ``author_id`` →
``user_id``, ``post_title`` → ``title``) — and types the commands
``docs/guides/04-schema-to-schema.md`` types: setup → analyze → migrate (or
migrate-table) → verify → cleanup.

What is pinned is read back from the databases, not from the exit code alone: the
foreign server and the imported foreign tables in the target's catalogs, the rows the
target holds under their new column names, a source left exactly as it was, and — after
cleanup — a target with no FDW left in it and its migrated rows still there.
``--source`` / ``--target`` are spelled all three ways the command resolves them: an
environment name (``db/environments/{name}.yaml``), a config path, and a DSN.

postgres_fdw is not a trusted extension, and ``setup`` maps the connecting role with an
empty password, which only a superuser may use: without one the tests skip.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import psycopg
import pytest
import yaml
from typer.testing import CliRunner

from confiture.cli.main import app
from confiture.error_codes import exit_code_of

pytestmark = pytest.mark.integration

runner = CliRunner()

_SOURCE_DDL = """
CREATE TABLE users (id BIGINT PRIMARY KEY, full_name TEXT NOT NULL, email TEXT);
CREATE TABLE posts (
    id BIGINT PRIMARY KEY,
    author_id BIGINT NOT NULL REFERENCES users (id),
    post_title TEXT NOT NULL
);
INSERT INTO users VALUES
    (1, 'Ada Lovelace', 'ada@example.com'),
    (2, 'Alan Turing', 'alan@example.com'),
    (3, 'Grace Hopper', NULL);
INSERT INTO posts VALUES (10, 1, 'Notes on the Engine'), (11, 3, 'Compilers');
"""

_TARGET_DDL = """
CREATE TABLE users (id BIGINT PRIMARY KEY, display_name TEXT NOT NULL, email TEXT);
CREATE TABLE posts (
    id BIGINT PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users (id),
    title TEXT NOT NULL
);
"""

_USERS = [
    (1, "Ada Lovelace", "ada@example.com"),
    (2, "Alan Turing", "alan@example.com"),
    (3, "Grace Hopper", None),
]
_POSTS = [(10, 1, "Notes on the Engine"), (11, 3, "Compilers")]

_USER_COLUMNS = {"id": "id", "full_name": "display_name", "email": "email"}

#: The guide's column-mapping YAML for this pair, in foreign-key order.
_MAPPING = {
    "users": {"columns": _USER_COLUMNS},
    "posts": {"columns": {"id": "id", "author_id": "user_id", "post_title": "title"}},
}

_SERVER = "confiture_source_server"


@pytest.fixture
def source(superuser_db_url: str, fresh_database_factory: Callable[[str], str]) -> str:
    """The old database: ``users`` and ``posts`` under their old column names, with rows."""
    url = fresh_database_factory("confiture_t")
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(_SOURCE_DDL)
    return url


@pytest.fixture
def target(superuser_db_url: str, fresh_database_factory: Callable[[str], str]) -> str:
    """The new database: the same tables under their new column names, empty."""
    url = fresh_database_factory("confiture_t")
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(_TARGET_DDL)
    return url


@pytest.fixture
def mapping(tmp_path: Path) -> Path:
    path = tmp_path / "column_mapping.yaml"
    path.write_text(yaml.safe_dump(_MAPPING, sort_keys=False))
    return path


@pytest.fixture
def renamed(source: str, tmp_path: Path) -> Path:
    """The guide's own mapping shape: the source's table is ``old_users``, the target's ``users``."""
    with psycopg.connect(source, autocommit=True) as conn:
        conn.execute("ALTER TABLE users RENAME TO old_users")
    path = tmp_path / "column_mapping.yaml"
    entry = {"source_table": "old_users", "target_table": "users", "columns": _USER_COLUMNS}
    path.write_text(yaml.safe_dump({"users": entry}, sort_keys=False))
    return path


def _json(stdout: str) -> dict:
    """The payload, which must be all of stdout: a consumer parses the stream."""
    return json.loads(stdout)


def _rows(url: str, query: str) -> list[tuple]:
    with psycopg.connect(url) as conn:
        return conn.execute(query).fetchall()


def _db_name(url: str) -> str:
    return urlparse(url).path.lstrip("/")


def _with_host(url: str, host: str) -> str:
    """*url* with its host replaced, credentials and port kept."""
    parsed = urlparse(url)
    userinfo = parsed.netloc.rpartition("@")[0]
    port = f":{parsed.port}" if parsed.port else ""
    netloc = f"{userinfo}@{host}{port}" if userinfo else f"{host}{port}"
    return urlunparse(parsed._replace(netloc=netloc))


def _foreign_servers(url: str) -> dict[str, dict[str, str]]:
    """Every foreign server in *url*'s database, with its options."""
    rows = _rows(url, "SELECT srvname, srvoptions FROM pg_foreign_server")
    return {name: dict(opt.split("=", 1) for opt in options or []) for name, options in rows}


def _foreign_tables(url: str) -> list[str]:
    rows = _rows(
        url,
        "SELECT c.relname FROM pg_foreign_table f JOIN pg_class c ON c.oid = f.ftrelid "
        "JOIN pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname = 'old_schema' "
        "ORDER BY c.relname",
    )
    return [row[0] for row in rows]


def _schemas(url: str) -> set[str]:
    return {row[0] for row in _rows(url, "SELECT nspname FROM pg_namespace")}


def _user_mappings(url: str) -> list[str]:
    return [row[0] for row in _rows(url, "SELECT srvname FROM pg_user_mappings")]


def _setup(source: str, target: str) -> None:
    result = runner.invoke(
        app, ["migrate", "schema-to-schema", "setup", "--source", source, "--target", target]
    )
    assert result.exit_code == 0, result.output


def _migrate(source: str, target: str, mapping: Path) -> dict:
    result = runner.invoke(
        app,
        [
            "migrate",
            "schema-to-schema",
            "migrate",
            "--source",
            source,
            "--target",
            target,
            "--mapping",
            str(mapping),
            "--format",
            "json",
        ],
    )
    assert result.exit_code == 0, result.output
    return _json(result.stdout)


# -- the guide, end to end ---------------------------------------------------------------


def test_the_guides_sequence_moves_the_rows_and_leaves_no_fdw_behind(
    source: str, target: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """setup → analyze → migrate → verify → cleanup, by environment name, as the guide types it."""
    environments = tmp_path / "db" / "environments"
    environments.mkdir(parents=True)
    for name, url in (("old_production", source), ("new_production", target)):
        config = {"name": name, "database_url": url, "include_dirs": ["db/schema"]}
        (environments / f"{name}.yaml").write_text(yaml.safe_dump(config))
    (tmp_path / "db" / "migration").mkdir()
    (tmp_path / "db" / "migration" / "column_mapping.yaml").write_text(
        yaml.safe_dump(_MAPPING, sort_keys=False)
    )
    monkeypatch.chdir(tmp_path)

    setup = runner.invoke(
        app,
        [
            "migrate",
            "schema-to-schema",
            "setup",
            "--source",
            "old_production",
            "--target",
            "new_production",
        ],
    )
    assert setup.exit_code == 0, setup.output
    assert "FDW configured" in setup.stdout
    assert _foreign_tables(target) == ["posts", "users"]

    analyze = runner.invoke(
        app,
        [
            "migrate",
            "schema-to-schema",
            "analyze",
            "--source",
            "old_production",
            "--target",
            "new_production",
        ],
    )
    assert analyze.exit_code == 0, analyze.output
    assert "users: fdw" in analyze.stdout
    assert "posts: fdw" in analyze.stdout

    migrate = runner.invoke(
        app,
        [
            "migrate",
            "schema-to-schema",
            "migrate",
            "--source",
            "old_production",
            "--target",
            "new_production",
            "--mapping",
            "db/migration/column_mapping.yaml",
        ],
    )
    assert migrate.exit_code == 0, migrate.output
    assert "users: 3 rows migrated" in migrate.stdout
    assert "posts: 2 rows migrated" in migrate.stdout
    assert "Migrated 2 table(s) via fdw" in migrate.stdout
    assert _rows(target, "SELECT id, display_name, email FROM users ORDER BY id") == _USERS
    assert _rows(target, "SELECT id, user_id, title FROM posts ORDER BY id") == _POSTS

    verify = runner.invoke(
        app,
        [
            "migrate",
            "schema-to-schema",
            "verify",
            "--source",
            "old_production",
            "--target",
            "new_production",
            "--tables",
            "users,posts",
        ],
    )
    assert verify.exit_code == 0, verify.output
    assert "users: source=3 target=3" in verify.stdout
    assert "posts: source=2 target=2" in verify.stdout
    assert "All tables match" in verify.stdout

    cleanup = runner.invoke(
        app,
        [
            "migrate",
            "schema-to-schema",
            "cleanup",
            "--source",
            "old_production",
            "--target",
            "new_production",
        ],
    )
    assert cleanup.exit_code == 0, cleanup.output
    assert "FDW removed from target" in cleanup.stdout
    assert _foreign_servers(target) == {}
    assert _rows(target, "SELECT id, display_name, email FROM users ORDER BY id") == _USERS
    assert _rows(source, "SELECT id, full_name, email FROM users ORDER BY id") == _USERS


# -- setup -------------------------------------------------------------------------------


def test_setup_imports_the_source_schema_into_the_target(source: str, target: str) -> None:
    result = runner.invoke(
        app,
        [
            "migrate",
            "schema-to-schema",
            "setup",
            "--source",
            source,
            "--target",
            target,
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = _json(result.stdout)
    assert set(payload.pop("parser")) == {"pglast", "pg_major"}
    assert payload == {"ok": True, "command": "setup", "skip_import": False}
    servers = _foreign_servers(target)
    assert list(servers) == [_SERVER]
    assert servers[_SERVER]["dbname"] == _db_name(source)
    assert _user_mappings(target) == [_SERVER]
    assert _foreign_tables(target) == ["posts", "users"]
    # The foreign tables read the source's rows, under the source's column names.
    assert _rows(target, "SELECT id, full_name, email FROM old_schema.users ORDER BY id") == _USERS


def test_setup_skip_import_creates_the_server_and_an_empty_foreign_schema(
    source: str, target: str
) -> None:
    result = runner.invoke(
        app,
        [
            "migrate",
            "schema-to-schema",
            "setup",
            "--source",
            source,
            "--target",
            target,
            "--skip-import",
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0, result.output
    assert _json(result.stdout)["skip_import"] is True
    assert list(_foreign_servers(target)) == [_SERVER]
    assert "old_schema" in _schemas(target)
    assert _foreign_tables(target) == []


def test_setup_run_twice_leaves_one_fdw(source: str, target: str) -> None:
    _setup(source, target)

    result = runner.invoke(
        app, ["migrate", "schema-to-schema", "setup", "--source", source, "--target", target]
    )

    assert result.exit_code == 0, result.output
    assert list(_foreign_servers(target)) == [_SERVER]
    assert _foreign_tables(target) == ["posts", "users"]


def test_setup_points_the_foreign_server_where_source_points(source: str, target: str) -> None:
    result = runner.invoke(
        app,
        [
            "migrate",
            "schema-to-schema",
            "setup",
            "--source",
            _with_host(source, "127.0.0.1"),
            "--target",
            target,
        ],
    )

    assert result.exit_code == 0, result.output
    options = _foreign_servers(target)[_SERVER]
    assert (options["host"], options["dbname"]) == ("127.0.0.1", _db_name(source))


def test_a_source_that_resolves_to_nothing_is_a_configuration_error(
    target: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(
        app,
        [
            "migrate",
            "schema-to-schema",
            "setup",
            "--source",
            "old_production",
            "--target",
            target,
            "--format",
            "json",
        ],
    )

    assert result.exit_code == exit_code_of("CONFIG_004"), result.output
    payload = _json(result.stdout)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "CONFIG_004"
    assert "db/environments/old_production.yaml" in payload["error"]["message"]
    assert _foreign_servers(target) == {}


# -- analyze -----------------------------------------------------------------------------


def test_analyze_recommends_a_strategy_for_every_table(source: str, target: str) -> None:
    _setup(source, target)

    result = runner.invoke(
        app,
        [
            "migrate",
            "schema-to-schema",
            "analyze",
            "--source",
            source,
            "--target",
            target,
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = _json(result.stdout)
    assert payload["command"] == "analyze"
    assert sorted(payload["tables"]) == ["posts", "users"]
    assert {info["strategy"] for info in payload["tables"].values()} == {"fdw"}


def test_analyze_sizes_the_rows_it_is_about_to_migrate(source: str, target: str) -> None:
    _setup(source, target)

    result = runner.invoke(
        app,
        [
            "migrate",
            "schema-to-schema",
            "analyze",
            "--source",
            source,
            "--target",
            target,
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0, result.output
    tables = _json(result.stdout)["tables"]
    assert (tables["users"]["row_count"], tables["posts"]["row_count"]) == (3, 2)


# -- migrate -----------------------------------------------------------------------------


@pytest.mark.parametrize("strategy", ["fdw", "copy"])
def test_migrate_moves_every_mapped_table_into_its_renamed_columns(
    source: str, target: str, mapping: Path, strategy: str
) -> None:
    _setup(source, target)

    result = runner.invoke(
        app,
        [
            "migrate",
            "schema-to-schema",
            "migrate",
            "--source",
            source,
            "--target",
            target,
            "--mapping",
            str(mapping),
            "--strategy",
            strategy,
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = _json(result.stdout)
    assert (payload["command"], payload["strategy"]) == ("migrate", strategy)
    assert payload["migrated"] == {"users": 3, "posts": 2}
    assert _rows(target, "SELECT id, display_name, email FROM users ORDER BY id") == _USERS
    assert _rows(target, "SELECT id, user_id, title FROM posts ORDER BY id") == _POSTS
    # Reading is all the migration does to the source.
    assert _rows(source, "SELECT id, full_name, email FROM users ORDER BY id") == _USERS


def test_migrate_reads_a_renamed_table_from_its_source_table(
    source: str, target: str, renamed: Path
) -> None:
    _setup(source, target)

    payload = _migrate(source, target, renamed)

    assert payload["migrated"] == {"users": 3}
    assert _rows(target, "SELECT id, display_name, email FROM users ORDER BY id") == _USERS


def test_migrate_before_setup_fails_and_writes_nothing(
    source: str, target: str, mapping: Path
) -> None:
    result = runner.invoke(
        app,
        [
            "migrate",
            "schema-to-schema",
            "migrate",
            "--source",
            source,
            "--target",
            target,
            "--mapping",
            str(mapping),
            "--format",
            "json",
        ],
    )

    assert result.exit_code == exit_code_of("MIGR_001"), result.output
    payload = _json(result.stdout)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "MIGR_001"
    assert "old_schema" in payload["error"]["message"]
    assert _rows(target, "SELECT count(*) FROM users") == [(0,)]


# -- migrate-table -----------------------------------------------------------------------


@pytest.mark.parametrize("strategy", ["fdw", "copy"])
def test_migrate_table_reports_the_rows_it_moved(
    source: str, target: str, tmp_path: Path, strategy: str
) -> None:
    """The new schema seeds a system user; migrating three users in reports three."""
    with psycopg.connect(target, autocommit=True) as conn:
        conn.execute("INSERT INTO users VALUES (0, 'system', NULL)")
    _setup(source, target)
    old, new = tmp_path / "old.yaml", tmp_path / "new.yaml"
    old.write_text(yaml.safe_dump({"database_url": source}))
    new.write_text(yaml.safe_dump({"database_url": target}))

    result = runner.invoke(
        app,
        [
            "migrate",
            "schema-to-schema",
            "migrate-table",
            "--source",
            str(old),
            "--target",
            str(new),
            "--source-table",
            "users",
            "--target-table",
            "users",
            "--mapping",
            "id:id, full_name:display_name, email:email",
            "--strategy",
            strategy,
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0, result.output
    migrated = _rows(target, "SELECT id, display_name, email FROM users WHERE id > 0 ORDER BY id")
    assert migrated == _USERS
    payload = _json(result.stdout)
    assert (payload["command"], payload["target_table"]) == ("migrate-table", "users")
    assert payload["rows"] == 3


# -- verify ------------------------------------------------------------------------------


def test_verify_before_migrating_reports_the_missing_rows_and_exits_1(
    source: str, target: str
) -> None:
    _setup(source, target)

    result = runner.invoke(
        app,
        [
            "migrate",
            "schema-to-schema",
            "verify",
            "--source",
            source,
            "--target",
            target,
            "--tables",
            "users,posts",
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 1, result.output
    payload = _json(result.stdout)
    assert payload["matched"] is False
    assert payload["tables"] == {
        "users": {"source_count": 3, "target_count": 0, "match": False, "difference": -3},
        "posts": {"source_count": 2, "target_count": 0, "match": False, "difference": -2},
    }


def test_verify_counts_a_renamed_table_against_its_source_table(
    source: str, target: str, renamed: Path
) -> None:
    """The mapping ``migrate`` read says where each table came from (#359)."""
    _setup(source, target)
    _migrate(source, target, renamed)

    result = runner.invoke(
        app,
        [
            "migrate",
            "schema-to-schema",
            "verify",
            "--source",
            source,
            "--target",
            target,
            "--mapping",
            str(renamed),
            "--tables",
            "users",
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = _json(result.stdout)
    assert payload["tables"]["users"]["source_count"] == 3
    assert payload["matched"] is True


def test_verify_with_a_mapping_verifies_every_table_it_maps(
    source: str, target: str, renamed: Path
) -> None:
    _setup(source, target)
    _migrate(source, target, renamed)

    result = runner.invoke(
        app,
        [
            "migrate",
            "schema-to-schema",
            "verify",
            "--source",
            source,
            "--target",
            target,
            "--mapping",
            str(renamed),
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0, result.output
    assert list(_json(result.stdout)["tables"]) == ["users"]


def test_verify_needs_tables_or_a_mapping(source: str, target: str) -> None:
    result = runner.invoke(
        app,
        [
            "migrate",
            "schema-to-schema",
            "verify",
            "--source",
            source,
            "--target",
            target,
            "--format",
            "json",
        ],
    )

    assert result.exit_code == exit_code_of("CONFIG_001"), result.output


# -- cleanup -----------------------------------------------------------------------------


def test_cleanup_removes_the_fdw_and_keeps_the_migrated_rows(
    source: str, target: str, mapping: Path
) -> None:
    _setup(source, target)
    _migrate(source, target, mapping)

    result = runner.invoke(
        app,
        [
            "migrate",
            "schema-to-schema",
            "cleanup",
            "--source",
            source,
            "--target",
            target,
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = _json(result.stdout)
    assert (payload["ok"], payload["command"]) == (True, "cleanup")
    assert _foreign_servers(target) == {}
    assert _user_mappings(target) == []
    assert "old_schema" not in _schemas(target)
    assert _rows(target, "SELECT id, display_name, email FROM users ORDER BY id") == _USERS
    assert _rows(target, "SELECT id, user_id, title FROM posts ORDER BY id") == _POSTS
    assert _rows(source, "SELECT count(*) FROM users") == [(3,)]
