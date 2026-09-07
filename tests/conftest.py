"""Pytest configuration and shared fixtures for Confiture tests

This module provides fixtures for:
- Temporary directories for schema files
- Test database setup/teardown
- Mock configurations
- Sample DDL files
"""

import os
import tempfile
import uuid
from collections.abc import Callable, Generator
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import psycopg
import psycopg.sql
import pytest
import yaml

from confiture.testing.worker_db import resolve_worker_db_url

# The pytester fixture runs an inner pytest session in-process, so coverage of the
# confiture pytest plugin's fixtures is measured (a subprocess run is invisible to it).
pytest_plugins = ["pytester"]


@pytest.fixture
def temp_project_dir() -> Generator[Path, None, None]:
    """Create a temporary project directory with db/ structure

    Yields:
        Path to temporary project directory with:
        - db/schema/00_common/
        - db/schema/10_tables/
        - db/schema/20_views/
        - db/migrations/
        - db/environments/
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir)

        # Create directory structure
        (project_dir / "db" / "schema" / "00_common").mkdir(parents=True)
        (project_dir / "db" / "schema" / "10_tables").mkdir(parents=True)
        (project_dir / "db" / "schema" / "20_views").mkdir(parents=True)
        (project_dir / "db" / "migrations").mkdir(parents=True)
        (project_dir / "db" / "environments").mkdir(parents=True)

        yield project_dir


@pytest.fixture
def sample_schema_files(temp_project_dir: Path) -> dict[str, Path]:
    """Create sample DDL files in temporary project

    Returns:
        Dictionary mapping file names to their paths
    """
    schema_dir = temp_project_dir / "db" / "schema"

    # 00_common/extensions.sql
    extensions_sql = schema_dir / "00_common" / "extensions.sql"
    extensions_sql.write_text(
        """-- PostgreSQL Extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";
"""
    )

    # 10_tables/users.sql
    users_sql = schema_dir / "10_tables" / "users.sql"
    users_sql.write_text(
        """-- Users table
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    username VARCHAR(255) NOT NULL UNIQUE,
    email VARCHAR(255) NOT NULL UNIQUE,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_users_username ON users(username);
CREATE INDEX idx_users_email ON users(email);
"""
    )

    # 10_tables/posts.sql
    posts_sql = schema_dir / "10_tables" / "posts.sql"
    posts_sql.write_text(
        """-- Posts table
CREATE TABLE posts (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title VARCHAR(500) NOT NULL,
    content TEXT,
    published_at TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_posts_user_id ON posts(user_id);
CREATE INDEX idx_posts_published_at ON posts(published_at);
"""
    )

    # 20_views/user_stats.sql
    user_stats_sql = schema_dir / "20_views" / "user_stats.sql"
    user_stats_sql.write_text(
        """-- User statistics view
CREATE VIEW user_stats AS
SELECT
    u.id,
    u.username,
    COUNT(p.id) AS post_count,
    MAX(p.created_at) AS last_post_at
FROM users u
LEFT JOIN posts p ON p.user_id = u.id
GROUP BY u.id, u.username;
"""
    )

    return {
        "extensions": extensions_sql,
        "users": users_sql,
        "posts": posts_sql,
        "user_stats": user_stats_sql,
    }


@pytest.fixture
def local_env_config(temp_project_dir: Path, test_db_url: str) -> Path:
    """Create a local environment configuration file

    Returns:
        Path to local.yaml config file
    """
    env_dir = temp_project_dir / "db" / "environments"
    local_config = env_dir / "local.yaml"

    config_data = {
        "name": "local",
        "database_url": test_db_url,
        "include_dirs": ["db/schema"],
        "exclude_dirs": ["db/schema/99_deprecated"],
        "migration_table": "tb_confiture",
    }

    local_config.write_text(yaml.dump(config_data))
    return local_config


# ---------------------------------------------------------------------------
# Database routing (TST-02)
#
# Every database test reaches its server through the fixtures below; no test
# module carries its own connection string (tests/unit/test_no_literal_dsn.py
# enforces that). The rule for a server that cannot be reached:
#
#   * `CONFITURE_TEST_DB_URL` (or the SOURCE/TARGET pair) is **set** — the
#     operator asked for that server, so a failed connection is a **failure**.
#     CI sets it; a DB test can no longer skip its way to green there.
#   * it is **unset** — the conventional local default is tried once per
#     session and, if unreachable, the test **skips** with that reason.
# ---------------------------------------------------------------------------

DEFAULT_TEST_DB_URL = "postgresql://localhost/confiture_test"
DEFAULT_SOURCE_DB_URL = "postgresql://localhost/confiture_source_test"
DEFAULT_TARGET_DB_URL = "postgresql://localhost/confiture_target_test"

_REACHABILITY: dict[str, str | None] = {}


def pg_available(url: str) -> str | None:
    """``None`` when *url* accepts a connection, else the error text (probed once)."""
    if url not in _REACHABILITY:
        try:
            with psycopg.connect(url, connect_timeout=5):
                pass
            _REACHABILITY[url] = None
        except psycopg.OperationalError as exc:
            _REACHABILITY[url] = str(exc).strip()
    return _REACHABILITY[url]


_WORKER_DBS_READY: set[str] = set()


def _ensure_worker_database(base_url: str, worker_url: str) -> None:
    """Create the per-worker database behind *worker_url* if it does not exist yet."""
    if worker_url in _WORKER_DBS_READY:
        return
    db_name = urlparse(worker_url).path.lstrip("/")
    admin_url = urlunparse(urlparse(base_url)._replace(path="/postgres"))
    with psycopg.connect(admin_url, autocommit=True) as admin:
        exists = admin.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s", (db_name,)
        ).fetchone()
        if not exists:
            try:
                admin.execute(
                    psycopg.sql.SQL("CREATE DATABASE {}").format(psycopg.sql.Identifier(db_name))
                )
            except psycopg.errors.DuplicateDatabase:
                pass  # another worker of the same name won the race; the database is there
    _WORKER_DBS_READY.add(worker_url)


def resolve_db_url(env_var: str, default: str) -> str:
    """The URL a database fixture should use, applying the fail/skip rule above.

    Under pytest-xdist every worker gets its own database — ``confiture_test``
    becomes ``confiture_test_gw0`` for worker ``gw0`` — resolved through
    ``confiture.testing.worker_db.resolve_worker_db_url`` and created on first
    use. Two workers therefore never share a ledger, an advisory lock or a
    ``DROP SCHEMA``. Without xdist the base database is used unchanged.
    """
    explicit = os.getenv(env_var)
    url = explicit or default
    error = pg_available(url)
    if error is not None:
        if explicit:
            pytest.fail(f"{env_var} is set but the server does not accept connections: {error}")
        pytest.skip(f"{env_var} unset and the local default {default} is unreachable: {error}")
    worker_url = resolve_worker_db_url(url)
    if worker_url != url:
        _ensure_worker_database(url, worker_url)
    return worker_url


@pytest.fixture(scope="session")
def test_db_url() -> str:
    """The test database URL (see the routing rule above)."""
    return resolve_db_url("CONFITURE_TEST_DB_URL", DEFAULT_TEST_DB_URL)


@pytest.fixture(scope="session")
def maintenance_url(test_db_url: str) -> str:
    """Same server and credentials as the test database, database ``postgres``.

    For ``CREATE DATABASE`` / ``DROP DATABASE`` / role cleanup — the things a
    test cannot do from inside the database it is testing.
    """
    parsed = urlparse(test_db_url)
    return urlunparse(parsed._replace(path="/postgres"))


@pytest.fixture
def maintenance_connection(maintenance_url: str) -> Generator[psycopg.Connection, None, None]:
    """An autocommit connection to the maintenance database."""
    conn = psycopg.connect(maintenance_url, autocommit=True)
    try:
        yield conn
    finally:
        conn.close()


def database_url_for(test_db_url: str, db_name: str) -> str:
    """*test_db_url* pointed at *db_name* on the same server, same credentials."""
    parsed = urlparse(test_db_url)
    return urlunparse(parsed._replace(path=f"/{db_name}"))


@pytest.fixture
def fresh_database_factory(
    test_db_url: str, maintenance_connection: psycopg.Connection
) -> Generator[Callable[[str], str], None, None]:
    """``make(prefix) -> url``: a throwaway database per call, all dropped at teardown."""
    created: list[str] = []

    def make(prefix: str = "confiture_t") -> str:
        db_name = f"{prefix}_{uuid.uuid4().hex[:8]}"
        maintenance_connection.execute(
            psycopg.sql.SQL("CREATE DATABASE {}").format(psycopg.sql.Identifier(db_name))
        )
        created.append(db_name)
        return database_url_for(test_db_url, db_name)

    yield make

    for db_name in created:
        maintenance_connection.execute(
            psycopg.sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                psycopg.sql.Identifier(db_name)
            )
        )


@pytest.fixture
def fresh_database(fresh_database_factory: Callable[[str], str]) -> str:
    """URL of one throwaway database, created for this test and dropped after it."""
    return fresh_database_factory("confiture_t")


def drop_roles(conn: psycopg.Connection, *roles: str) -> None:
    """Best-effort ``DROP OWNED BY`` + ``DROP ROLE`` for test roles on *conn*."""
    for role in roles:
        for stmt in (
            psycopg.sql.SQL("DROP OWNED BY {} CASCADE").format(psycopg.sql.Identifier(role)),
            psycopg.sql.SQL("DROP ROLE IF EXISTS {}").format(psycopg.sql.Identifier(role)),
        ):
            try:
                conn.execute(stmt)
            except psycopg.Error:
                pass


@pytest.fixture
def superuser_db_url(test_db_url: str) -> str:
    """The test database URL, or a skip naming the missing capability."""
    with psycopg.connect(test_db_url) as conn:
        row = conn.execute("SELECT rolsuper FROM pg_roles WHERE rolname = current_user").fetchone()
    if not (row and row[0]):
        pytest.skip("the connecting role is not a superuser (needed for this test)")
    return test_db_url


@pytest.fixture
def test_db_connection(test_db_url: str) -> Generator[psycopg.Connection, None, None]:
    """Create a test database connection.

    The ``confiture`` helper schema is dropped first. ``migrate up`` installs
    the view helpers into a schema of that name, and under a connecting role
    *also* named ``confiture`` — what CI uses — PostgreSQL's default
    ``"$user", public`` search_path would send every later unqualified
    ``CREATE TABLE`` into it, so a test asserting on ``public.x`` fails only in
    CI, and only after some other module on the same worker ran a migration.

    Yields:
        psycopg Connection to test database
    """
    with psycopg.connect(test_db_url, autocommit=True) as admin:
        admin.execute("DROP SCHEMA IF EXISTS confiture CASCADE")
    conn = psycopg.connect(test_db_url, autocommit=False)
    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture
def clean_test_db(test_db_connection: psycopg.Connection) -> psycopg.Connection:
    """Clean test database before and after test

    Drops all tables, views, and extensions to ensure clean slate.

    Yields:
        psycopg Connection to clean test database
    """
    conn = test_db_connection

    def cleanup():
        """Reset the database to an empty `public` schema.

        Dropping the schema, not its tables one by one, is what takes functions,
        types, sequences and domains with it — the per-object version left
        those behind between tests. Every other user schema goes too, including
        `confiture`: `migrate up` auto-installs the view helpers into a schema of
        that name (migration.view_helpers: auto), and under a connecting role
        *named* confiture — what CI uses — PostgreSQL's default search_path
        `"$user", public` would make a leaked one the target of every later
        unqualified CREATE TABLE.
        """
        with conn.cursor() as cur:
            cur.execute("""
                SELECT nspname FROM pg_namespace
                WHERE nspname NOT IN ('pg_catalog', 'information_schema', 'pg_toast')
                  AND nspname !~ '^pg_'
            """)
            for (schema_name,) in cur.fetchall():
                cur.execute(
                    psycopg.sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                        psycopg.sql.Identifier(schema_name)
                    )
                )
            cur.execute("CREATE SCHEMA public")
            cur.execute("GRANT USAGE, CREATE ON SCHEMA public TO PUBLIC")
            cur.execute("COMMENT ON SCHEMA public IS 'standard public schema'")
            conn.commit()

    # Clean before test
    cleanup()

    yield conn

    # Clean after test
    cleanup()


@pytest.fixture
def mock_git_repo(temp_project_dir: Path) -> Path:
    """Initialize a mock git repository in temp project

    Returns:
        Path to project directory with .git
    """
    git_dir = temp_project_dir / ".git"
    git_dir.mkdir()
    (git_dir / "HEAD").write_text("ref: refs/heads/main\n")
    (git_dir / "refs" / "heads").mkdir(parents=True)
    (git_dir / "refs" / "heads" / "main").write_text("abc123def456789012345678901234567890abcd\n")

    return temp_project_dir


# Fixtures for syncer tests (source and target databases)


@pytest.fixture(scope="session")
def source_db_url() -> str:
    """The sync source database URL (routing rule: see ``resolve_db_url``)."""
    return resolve_db_url("CONFITURE_SOURCE_DB_URL", DEFAULT_SOURCE_DB_URL)


@pytest.fixture(scope="session")
def target_db_url() -> str:
    """The sync target database URL (routing rule: see ``resolve_db_url``)."""
    return resolve_db_url("CONFITURE_TARGET_DB_URL", DEFAULT_TARGET_DB_URL)


@pytest.fixture
def source_db(source_db_url: str) -> Generator[psycopg.Connection, None, None]:
    """Create source database connection.

    Yields:
        psycopg Connection to source database
    """
    conn = psycopg.connect(source_db_url, autocommit=True)
    try:
        _sync_clean_database(conn)
        yield conn
        _sync_clean_database(conn)
    finally:
        conn.close()


@pytest.fixture
def target_db(target_db_url: str) -> Generator[psycopg.Connection, None, None]:
    """Create target database connection.

    Yields:
        psycopg Connection to target database
    """
    conn = psycopg.connect(target_db_url, autocommit=True)
    try:
        _sync_clean_database(conn)
        yield conn
        _sync_clean_database(conn)
    finally:
        conn.close()


@pytest.fixture
def source_config(source_db_url: str):
    """Create source database configuration.

    Returns:
        DatabaseConfig instance
    """
    from confiture.config.environment import DatabaseConfig

    return DatabaseConfig.from_url(source_db_url)


@pytest.fixture
def target_config(target_db_url: str):
    """Create target database configuration.

    Returns:
        DatabaseConfig instance
    """
    from confiture.config.environment import DatabaseConfig

    return DatabaseConfig.from_url(target_db_url)


def _sync_clean_database(conn: psycopg.Connection) -> None:
    """Drop all objects in public schema synchronously."""
    with conn.cursor() as cur:
        # Drop all views
        cur.execute("""
            SELECT viewname FROM pg_views
            WHERE schemaname = 'public'
        """)
        views = cur.fetchall()
        for (view_name,) in views:
            cur.execute(f'DROP VIEW IF EXISTS "{view_name}" CASCADE')

        # Drop all tables
        cur.execute("""
            SELECT tablename FROM pg_tables
            WHERE schemaname = 'public'
        """)
        tables = cur.fetchall()
        for (table_name,) in tables:
            cur.execute(f'DROP TABLE IF EXISTS "{table_name}" CASCADE')

        # Drop all foreign schemas (for FDW tests)
        cur.execute("""
            SELECT schema_name FROM information_schema.schemata
            WHERE schema_name NOT IN ('public', 'pg_catalog', 'information_schema')
              AND schema_name !~ '^pg_'
        """)
        schemas = cur.fetchall()
        for (schema_name,) in schemas:
            cur.execute(f'DROP SCHEMA IF EXISTS "{schema_name}" CASCADE')

        # Drop all foreign servers (for FDW tests)
        cur.execute("SELECT srvname FROM pg_foreign_server")
        servers = cur.fetchall()
        for (server_name,) in servers:
            cur.execute(f'DROP SERVER IF EXISTS "{server_name}" CASCADE')

        # Drop all extensions (except defaults)
        cur.execute("""
            SELECT extname FROM pg_extension
            WHERE extname NOT IN ('plpgsql')
        """)
        extensions = cur.fetchall()
        for (ext_name,) in extensions:
            cur.execute(f'DROP EXTENSION IF EXISTS "{ext_name}" CASCADE')


# ---------------------------------------------------------------------------
# Layer markers
#
# A test's layer is where it lives. Assigning the marker from the directory
# means `-m integration` selects exactly the integration layer and a test can
# never claim a layer it is not in; tests/unit/test_markers.py checks that every
# collected item ends up with exactly one.
# ---------------------------------------------------------------------------

_TESTS_ROOT = Path(__file__).resolve().parent
_LAYER_MARKERS = frozenset({"unit", "integration", "e2e", "performance", "contract"})


def _layer_for(path: Path) -> str | None:
    try:
        top = path.resolve().relative_to(_TESTS_ROOT).parts[0]
    except (ValueError, IndexError):
        return None
    return top if top in _LAYER_MARKERS else None


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Give every item the layer marker of its directory (if it has none yet)."""
    for item in items:
        if any(m.name in _LAYER_MARKERS for m in item.iter_markers()):
            continue
        layer = _layer_for(Path(str(item.path)))
        if layer is not None:
            item.add_marker(getattr(pytest.mark, layer))
