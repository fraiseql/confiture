"""Pytest configuration and shared fixtures for Confiture tests

This module provides fixtures for:
- Temporary directories for schema files
- Test database setup/teardown
- Mock configurations
- Sample DDL files
"""

import os
import tempfile
from collections.abc import Generator
from pathlib import Path

import psycopg
import pytest
import yaml


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
def local_env_config(temp_project_dir: Path) -> Path:
    """Create a local environment configuration file

    Returns:
        Path to local.yaml config file
    """
    env_dir = temp_project_dir / "db" / "environments"
    local_config = env_dir / "local.yaml"

    config_data = {
        "name": "local",
        "database_url": os.getenv(
            "CONFITURE_TEST_DB_URL",
            "postgresql://localhost/confiture_test",
        ),
        "include_dirs": ["db/schema"],
        "exclude_dirs": ["db/schema/99_deprecated"],
        "migration_table": "confiture_migrations",
        "auto_backup": True,
        "require_confirmation": False,
    }

    local_config.write_text(yaml.dump(config_data))
    return local_config


@pytest.fixture
def test_db_url() -> str:
    """Get test database URL from environment

    Returns:
        Database connection URL for testing
    """
    return os.getenv(
        "CONFITURE_TEST_DB_URL",
        "postgresql://localhost/confiture_test",
    )


@pytest.fixture
def test_db_connection(test_db_url: str) -> Generator[psycopg.Connection, None, None]:
    """Create a test database connection

    Yields:
        psycopg Connection to test database

    Note:
        This fixture requires a PostgreSQL server to be running
        and accessible at CONFITURE_TEST_DB_URL.
    """
    try:
        conn = psycopg.connect(test_db_url, autocommit=False)
        yield conn
    except psycopg.OperationalError as e:
        pytest.skip(f"PostgreSQL not available: {e}")
    finally:
        if "conn" in locals():
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
        """Drop all objects in public schema"""
        with conn.cursor() as cur:
            # Drop all views
            cur.execute("""
                SELECT tablename FROM pg_views
                WHERE schemaname = 'public'
            """)
            for (view_name,) in cur.fetchall():
                cur.execute(f'DROP VIEW IF EXISTS "{view_name}" CASCADE')

            # Drop all tables
            cur.execute("""
                SELECT tablename FROM pg_tables
                WHERE schemaname = 'public'
            """)
            for (table_name,) in cur.fetchall():
                cur.execute(f'DROP TABLE IF EXISTS "{table_name}" CASCADE')

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


@pytest.fixture
def source_db_url() -> str:
    """Get source test database URL from environment.

    Returns:
        Database connection URL for source database
    """
    return os.getenv(
        "CONFITURE_SOURCE_DB_URL",
        "postgresql://localhost/confiture_source_test",
    )


@pytest.fixture
def target_db_url() -> str:
    """Get target test database URL from environment.

    Returns:
        Database connection URL for target database
    """
    return os.getenv(
        "CONFITURE_TARGET_DB_URL",
        "postgresql://localhost/confiture_target_test",
    )


@pytest.fixture
def source_db(source_db_url: str) -> Generator[psycopg.Connection, None, None]:
    """Create source database connection.

    Yields:
        psycopg Connection to source database
    """
    try:
        conn = psycopg.connect(source_db_url, autocommit=True)

        # Clean before test
        _sync_clean_database(conn)

        yield conn

        # Clean after test
        _sync_clean_database(conn)
        conn.close()
    except psycopg.OperationalError as e:
        pytest.skip(f"PostgreSQL not available for source database: {e}")


@pytest.fixture
def target_db(target_db_url: str) -> Generator[psycopg.Connection, None, None]:
    """Create target database connection.

    Yields:
        psycopg Connection to target database
    """
    try:
        conn = psycopg.connect(target_db_url, autocommit=True)

        # Clean before test
        _sync_clean_database(conn)

        yield conn

        # Clean after test
        _sync_clean_database(conn)
        conn.close()
    except psycopg.OperationalError as e:
        pytest.skip(f"PostgreSQL not available for target database: {e}")


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
