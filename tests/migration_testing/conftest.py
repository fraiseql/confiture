"""Test configuration and fixtures for Confiture migration testing.

This module provides fixtures for mutation testing, performance profiling,
and comprehensive migration validation.
"""

import os
import tempfile
from collections.abc import Generator
from pathlib import Path

import psycopg
import pytest


@pytest.fixture
def test_db_connection() -> Generator:
    """Provide a PostgreSQL connection for migration tests.

    Uses DATABASE_URL environment variable or creates a test connection.
    Yields the connection for use in tests.
    """
    db_url = os.environ.get(
        "DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/confiture_test"
    )

    conn = psycopg.connect(db_url)
    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture
def temp_project_dir() -> Generator[Path, None, None]:
    """Create a temporary project directory with db/ structure for testing.

    Yields:
        Path to temporary project directory with Confiture-standard structure:
        - db/schema/00_common/
        - db/schema/10_tables/
        - db/schema/20_views/
        - db/migrations/
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir)

        # Create Confiture-standard directory structure
        (project_dir / "db" / "schema" / "00_common").mkdir(parents=True)
        (project_dir / "db" / "schema" / "10_tables").mkdir(parents=True)
        (project_dir / "db" / "schema" / "20_views").mkdir(parents=True)
        (project_dir / "db" / "migrations").mkdir(parents=True)

        yield project_dir


@pytest.fixture
def sample_confiture_schema(temp_project_dir: Path) -> dict[str, Path]:
    """Create sample DDL files in PostgreSQL-idiomatic format.

    Returns:
        Dictionary mapping file names to their paths
    """
    schema_dir = temp_project_dir / "db" / "schema"

    # 00_common/extensions.sql
    extensions_sql = schema_dir / "00_common" / "extensions.sql"
    extensions_sql.write_text("""-- PostgreSQL Extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";
""")

    # 10_tables/users.sql
    users_sql = schema_dir / "10_tables" / "users.sql"
    users_sql.write_text("""-- Users table
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    username VARCHAR(255) NOT NULL UNIQUE,
    email VARCHAR(255) NOT NULL UNIQUE,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_users_username ON users(username);
CREATE INDEX idx_users_email ON users(email);
""")

    # 10_tables/posts.sql
    posts_sql = schema_dir / "10_tables" / "posts.sql"
    posts_sql.write_text("""-- Posts table
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
""")

    # 20_views/user_stats.sql
    user_stats_sql = schema_dir / "20_views" / "user_stats.sql"
    user_stats_sql.write_text("""-- User statistics view
CREATE VIEW user_stats AS
SELECT
    u.id,
    u.username,
    COUNT(p.id) AS post_count,
    MAX(p.created_at) AS last_post_date
FROM users u
LEFT JOIN posts p ON p.user_id = u.id
GROUP BY u.id, u.username;
""")

    return {
        "extensions": extensions_sql,
        "users": users_sql,
        "posts": posts_sql,
        "user_stats": user_stats_sql,
    }


@pytest.fixture
def mutation_registry():
    """Provide mutation registry for mutation testing.

    Uses the mutation framework from confiture.testing.frameworks.
    """
    from confiture.testing.frameworks.mutation import MutationRegistry

    return MutationRegistry()


@pytest.fixture
def performance_profiler(test_db_connection):
    """Provide performance profiler for performance testing.

    Uses the performance framework from confiture.testing.frameworks.
    Requires database connection for profiling actual migrations.
    """
    from confiture.testing.frameworks.performance import MigrationPerformanceProfiler

    return MigrationPerformanceProfiler(test_db_connection)
