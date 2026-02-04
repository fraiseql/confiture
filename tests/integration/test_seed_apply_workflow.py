"""Integration tests for complete sequential seed application workflow.

Phase 9, Cycle 9: Integration Tests

Tests with real PostgreSQL database to verify:
- Multi-file sequential execution
- Transaction isolation
- Error recovery with continue-on-error
- Data persistence and rollback behavior
"""

import pytest

from confiture.core.seed_applier import SeedApplier
from confiture.exceptions import SeedError


@pytest.fixture
def seeds_dir(tmp_path):
    """Create temporary seeds directory with test files."""
    seeds = tmp_path / "db" / "seeds"
    seeds.mkdir(parents=True)
    return seeds


@pytest.fixture
def test_schema(test_db_connection):
    """Create test schema for seed data."""
    # Drop and recreate tables (fresh start)
    with test_db_connection.cursor() as cursor:
        cursor.execute("DROP TABLE IF EXISTS posts CASCADE")
        cursor.execute("DROP TABLE IF EXISTS users CASCADE")
        test_db_connection.commit()

        # Create tables
        cursor.execute("""
            CREATE TABLE users (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL
            )
        """)
        cursor.execute("""
            CREATE TABLE posts (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id),
                title TEXT NOT NULL
            )
        """)
        test_db_connection.commit()

    yield

    # Cleanup
    with test_db_connection.cursor() as cursor:
        cursor.execute("DROP TABLE IF EXISTS posts CASCADE")
        cursor.execute("DROP TABLE IF EXISTS users CASCADE")
        test_db_connection.commit()


def test_seed_apply_single_file(test_db_connection, test_schema, seeds_dir):
    """Test applying a single seed file sequentially."""
    # Create seed file
    seed_file = seeds_dir / "01_users.sql"
    seed_file.write_text("INSERT INTO users (name) VALUES ('Alice');")

    # Apply sequentially
    applier = SeedApplier(
        seeds_dir=seeds_dir,
        connection=test_db_connection,
    )
    result = applier.apply_sequential()

    # Verify result
    assert result.total == 1
    assert result.succeeded == 1
    assert result.failed == 0

    # Verify data inserted
    with test_db_connection.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM users")
        count = cursor.fetchone()[0]
    assert count == 1


def test_seed_apply_multiple_files(test_db_connection, test_schema, seeds_dir):
    """Test applying multiple seed files sequentially."""
    # Create seed files
    (seeds_dir / "01_users.sql").write_text(
        "INSERT INTO users (name) VALUES ('Alice');\nINSERT INTO users (name) VALUES ('Bob');"
    )
    (seeds_dir / "02_posts.sql").write_text(
        "INSERT INTO posts (user_id, title) VALUES (1, 'First Post');\n"
        "INSERT INTO posts (user_id, title) VALUES (2, 'Second Post');"
    )

    # Apply sequentially
    applier = SeedApplier(seeds_dir=seeds_dir, connection=test_db_connection)
    result = applier.apply_sequential()

    # Verify result
    assert result.total == 2
    assert result.succeeded == 2
    assert result.failed == 0

    # Verify data
    with test_db_connection.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM users")
        user_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM posts")
        post_count = cursor.fetchone()[0]

    assert user_count == 2
    assert post_count == 2


def test_seed_apply_file_order(test_db_connection, test_schema, seeds_dir):
    """Test seed files are applied in sorted order."""
    # Create files in specific order (reverse of alphabetical)
    (seeds_dir / "03_final.sql").write_text("INSERT INTO users (name) VALUES ('Charlie');")
    (seeds_dir / "01_first.sql").write_text("INSERT INTO users (name) VALUES ('Alice');")
    (seeds_dir / "02_second.sql").write_text("INSERT INTO users (name) VALUES ('Bob');")

    # Apply sequentially
    applier = SeedApplier(seeds_dir=seeds_dir, connection=test_db_connection)
    result = applier.apply_sequential()

    # All should succeed
    assert result.total == 3
    assert result.succeeded == 3

    # Verify data in correct order
    with test_db_connection.cursor() as cursor:
        cursor.execute("SELECT name FROM users ORDER BY id")
        names = [row[0] for row in cursor.fetchall()]

    assert names == ["Alice", "Bob", "Charlie"]


def test_seed_apply_error_rollback(test_db_connection, test_schema, seeds_dir):
    """Test that failed seed file is rolled back (no partial data)."""
    # Create seed files - second one will fail
    (seeds_dir / "01_users.sql").write_text("INSERT INTO users (name) VALUES ('Alice');")
    (seeds_dir / "02_bad.sql").write_text(
        "INSERT INTO users (name) VALUES ('Bob');\n"
        "INSERT INTO posts (user_id, title) VALUES (999, 'Invalid FK');"  # FK violation
    )

    # Apply sequentially - should fail on second file
    applier = SeedApplier(seeds_dir=seeds_dir, connection=test_db_connection)

    with pytest.raises(SeedError):
        applier.apply_sequential()

    # Verify rollback: second file's data should not be in database
    with test_db_connection.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM users")
        user_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM posts")
        post_count = cursor.fetchone()[0]

    # First file succeeded, second file rolled back
    assert user_count == 1
    assert post_count == 0


def test_seed_apply_continue_on_error(test_db_connection, test_schema, seeds_dir):
    """Test continue-on-error mode applies valid files and skips failed ones."""
    # Create seed files - second one will fail, third should succeed
    (seeds_dir / "01_users.sql").write_text("INSERT INTO users (name) VALUES ('Alice');")
    (seeds_dir / "02_bad.sql").write_text(
        "INSERT INTO posts (user_id, title) VALUES (999, 'Invalid FK');"  # FK violation
    )
    (seeds_dir / "03_posts.sql").write_text(
        "INSERT INTO posts (user_id, title) VALUES (1, 'Valid Post');"
    )

    # Apply sequentially with continue-on-error
    applier = SeedApplier(seeds_dir=seeds_dir, connection=test_db_connection)
    result = applier.apply_sequential(continue_on_error=True)

    # Verify result
    assert result.total == 3
    assert result.succeeded == 2
    assert result.failed == 1
    assert "02_bad.sql" in result.failed_files

    # Verify data: first and third files should be loaded
    with test_db_connection.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM users")
        user_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM posts")
        post_count = cursor.fetchone()[0]
        cursor.execute("SELECT title FROM posts")
        titles = [row[0] for row in cursor.fetchall()]

    assert user_count == 1
    assert post_count == 1
    assert titles == ["Valid Post"]


def test_seed_apply_empty_directory(test_db_connection, test_schema, seeds_dir):
    """Test applying from empty directory."""
    # seeds_dir is empty
    applier = SeedApplier(seeds_dir=seeds_dir, connection=test_db_connection)
    result = applier.apply_sequential()

    assert result.total == 0
    assert result.succeeded == 0
    assert result.failed == 0


def test_seed_apply_large_batch(test_db_connection, test_schema, seeds_dir):
    """Test applying large seed file (650+ rows - parser limit test)."""
    # Create large seed file with 650 INSERT statements
    rows = "\n".join(f"INSERT INTO users (name) VALUES ('User{i}');" for i in range(1, 651))
    (seeds_dir / "01_large.sql").write_text(rows)

    # Apply sequentially
    applier = SeedApplier(seeds_dir=seeds_dir, connection=test_db_connection)
    result = applier.apply_sequential()

    # Verify result
    assert result.total == 1
    assert result.succeeded == 1
    assert result.failed == 0

    # Verify all data inserted
    with test_db_connection.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM users")
        count = cursor.fetchone()[0]

    assert count == 650


def test_seed_apply_with_complex_sql(test_db_connection, test_schema, seeds_dir):
    """Test seed files with complex SQL (CTEs, subqueries, etc)."""
    # Create seed with CTE
    (seeds_dir / "01_users.sql").write_text(
        "WITH user_data AS (\n"
        "  SELECT 'Alice' as name\n"
        "  UNION ALL\n"
        "  SELECT 'Bob' as name\n"
        ")\n"
        "INSERT INTO users (name) SELECT name FROM user_data;"
    )

    # Apply sequentially
    applier = SeedApplier(seeds_dir=seeds_dir, connection=test_db_connection)
    result = applier.apply_sequential()

    # Verify result
    assert result.total == 1
    assert result.succeeded == 1

    # Verify data
    with test_db_connection.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM users")
        count = cursor.fetchone()[0]

    assert count == 2


def test_seed_apply_transaction_isolation(test_db_connection, test_schema, seeds_dir):
    """Test that each seed file is isolated in its own savepoint."""
    # Create seed files that depend on each other's data
    (seeds_dir / "01_users.sql").write_text(
        "INSERT INTO users (name) VALUES ('Alice');\nINSERT INTO users (name) VALUES ('Bob');"
    )
    (seeds_dir / "02_posts.sql").write_text(
        "INSERT INTO posts (user_id, title) VALUES (1, 'Post1');\n"
        "INSERT INTO posts (user_id, title) VALUES (2, 'Post2');"
    )

    # Apply sequentially
    applier = SeedApplier(seeds_dir=seeds_dir, connection=test_db_connection)
    result = applier.apply_sequential()

    # Verify both files succeeded
    assert result.total == 2
    assert result.succeeded == 2

    # Verify data integrity
    with test_db_connection.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM posts WHERE user_id NOT IN (SELECT id FROM users)")
        orphan_count = cursor.fetchone()[0]

    assert orphan_count == 0, "Should have no orphaned posts"
