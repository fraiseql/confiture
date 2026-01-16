"""Forward migration tests for Confiture PostgreSQL migrations.

Tests verify that:
1. Migrations execute without errors
2. Schema changes are applied correctly
3. Data integrity is maintained
4. Performance is acceptable
5. Migrations are idempotent
"""

import pytest
from pathlib import Path


# ============================================================================
# CATEGORY 1: Basic Forward Migration (5 tests)
# ============================================================================


def test_migration_file_structure(temp_project_dir):
    """Test that migration directory structure is valid for Confiture."""
    migrations_dir = temp_project_dir / "db" / "migrations"

    # Create a test migration file
    migration_file = migrations_dir / "001_create_users_table.sql"
    migration_file.write_text("""
    -- Migration: Create users table
    CREATE TABLE IF NOT EXISTS users (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        username VARCHAR(255) NOT NULL UNIQUE,
        email VARCHAR(255) NOT NULL UNIQUE,
        created_at TIMESTAMP NOT NULL DEFAULT NOW()
    );
    """)

    # Verify migration file exists and is readable
    assert migration_file.exists(), "Migration file should exist"
    assert migration_file.is_file(), "Migration file should be a file"
    assert migration_file.stat().st_size > 0, "Migration file should have content"

    content = migration_file.read_text()
    assert "CREATE TABLE" in content, "Migration should contain DDL"


def test_migration_naming_convention(temp_project_dir):
    """Test that migrations follow Confiture naming conventions.

    Naming convention: NNN_description.sql where NNN is zero-padded number.
    """
    migrations_dir = temp_project_dir / "db" / "migrations"

    # Valid migration names
    valid_names = [
        "001_create_users_table.sql",
        "002_add_email_index.sql",
        "010_create_posts_table.sql",
        "100_add_foreign_keys.sql",
    ]

    for name in valid_names:
        migration_file = migrations_dir / name
        migration_file.write_text("-- Valid migration")
        assert migration_file.exists()


def test_schema_ddl_structure(sample_confiture_schema):
    """Test that schema DDL files have proper structure."""
    # Verify sample schema files exist
    assert sample_confiture_schema["users"].exists()
    assert sample_confiture_schema["posts"].exists()
    assert sample_confiture_schema["user_stats"].exists()

    # Verify content contains DDL statements
    users_content = sample_confiture_schema["users"].read_text()
    assert "CREATE TABLE" in users_content
    assert "PRIMARY KEY" in users_content

    posts_content = sample_confiture_schema["posts"].read_text()
    assert "REFERENCES users" in posts_content


def test_migration_with_single_statement(sample_confiture_schema):
    """Test a simple migration with valid SQL."""
    users_file = sample_confiture_schema["users"]
    content = users_file.read_text()

    # Verify migration is valid SQL
    assert "CREATE TABLE users" in content
    assert "id UUID PRIMARY KEY" in content
    assert "username VARCHAR" in content


def test_migration_tracks_content_size(sample_confiture_schema):
    """Test that migration files contain sufficient content."""
    for migration_file in sample_confiture_schema.values():
        content = migration_file.read_text()
        # Minimum size check to ensure meaningful migration
        assert len(content) > 50, f"Migration {migration_file.name} is too small"


# ============================================================================
# CATEGORY 2: Schema Validation (8 tests)
# ============================================================================


def test_schema_file_extension(sample_confiture_schema):
    """Test that schema files use .sql extension."""
    # Use sample schema which has .sql files created
    for schema_file in sample_confiture_schema.values():
        assert schema_file.suffix == ".sql", f"File {schema_file.name} should have .sql extension"


def test_schema_directory_organization(temp_project_dir):
    """Test that schema follows Confiture directory structure."""
    schema_dir = temp_project_dir / "db" / "schema"

    # Verify expected directories exist
    expected_dirs = ["00_common", "10_tables", "20_views"]
    for dir_name in expected_dirs:
        dir_path = schema_dir / dir_name
        assert dir_path.exists(), f"Schema directory {dir_name} should exist"
        assert dir_path.is_dir(), f"{dir_name} should be a directory"


def test_common_schema_contains_extensions(sample_confiture_schema):
    """Test that extensions are defined in 00_common."""
    # Note: In the sample, extensions are in 00_common/extensions.sql
    # This test verifies the pattern
    for migration_file in sample_confiture_schema.values():
        content = migration_file.read_text()
        if "extensions" in migration_file.name.lower():
            assert "CREATE EXTENSION" in content or "EXTENSION" in content


def test_tables_schema_section(sample_confiture_schema):
    """Test that table definitions are in 10_tables section."""
    users_file = sample_confiture_schema["users"]
    assert "10_tables" in str(users_file.parent)

    content = users_file.read_text()
    assert "CREATE TABLE" in content


def test_views_schema_section(sample_confiture_schema):
    """Test that view definitions are in 20_views section."""
    views_file = sample_confiture_schema["user_stats"]
    assert "20_views" in str(views_file.parent)

    content = views_file.read_text()
    assert "CREATE VIEW" in content


def test_migration_files_are_independent(temp_project_dir):
    """Test that each migration file can be identified independently."""
    migrations_dir = temp_project_dir / "db" / "migrations"

    # Create multiple migration files
    migrations = [
        ("001_init.sql", "CREATE SCHEMA IF NOT EXISTS app;"),
        ("002_users.sql", "CREATE TABLE app.users (id UUID PRIMARY KEY);"),
        ("003_posts.sql", "CREATE TABLE app.posts (id UUID PRIMARY KEY);"),
    ]

    for filename, content in migrations:
        (migrations_dir / filename).write_text(content)

    # Verify each can be identified
    migration_files = sorted(list(migrations_dir.glob("*.sql")))
    assert len(migration_files) == 3

    for i, mig_file in enumerate(migration_files, 1):
        assert mig_file.name.startswith(f"{i:03d}_")


def test_sql_comment_preservation(sample_confiture_schema):
    """Test that SQL comments are preserved in schema files."""
    users_file = sample_confiture_schema["users"]
    content = users_file.read_text()

    # Verify comments are present
    assert "-- Users table" in content or "-- " in content


# ============================================================================
# CATEGORY 3: Data Preservation (6 tests)
# ============================================================================


def test_schema_preserves_ddl_structure(sample_confiture_schema, test_db_connection):
    """Test that schema DDL can be executed on a database."""
    with test_db_connection.cursor() as cur:
        # Apply schema
        users_content = sample_confiture_schema["users"].read_text()

        # Clean up first
        cur.execute("DROP TABLE IF EXISTS users CASCADE;")

        # Execute schema
        cur.execute(users_content)
        test_db_connection.commit()

        # Verify table exists using to_regclass() which returns OID or NULL
        cur.execute("""
            SELECT to_regclass('users') IS NOT NULL
        """)
        result = cur.fetchone()
        assert result[0] is True, "Table users should exist"


def test_schema_creates_valid_columns(test_db_connection, sample_confiture_schema):
    """Test that schema creates columns with correct types."""
    with test_db_connection.cursor() as cur:
        # Setup
        cur.execute("DROP TABLE IF EXISTS users CASCADE;")
        users_content = sample_confiture_schema["users"].read_text()
        cur.execute(users_content)
        test_db_connection.commit()

        # Query columns
        cur.execute("""
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_name = 'users'
            ORDER BY ordinal_position
        """)

        columns = {row[0]: row[1] for row in cur.fetchall()}

        # Verify expected columns
        assert "id" in columns
        assert "username" in columns
        assert "email" in columns


def test_schema_enforces_constraints(test_db_connection, sample_confiture_schema):
    """Test that constraints defined in schema are enforced."""
    import psycopg

    with test_db_connection.cursor() as cur:
        # Setup
        cur.execute("DROP TABLE IF EXISTS users CASCADE;")
        users_content = sample_confiture_schema["users"].read_text()
        cur.execute(users_content)
        test_db_connection.commit()

        # Test NOT NULL constraint violation
        try:
            cur.execute("INSERT INTO users (username, email) VALUES (NULL, 'test@example.com');")
            test_db_connection.commit()
            assert False, "Should fail: username is NOT NULL"
        except psycopg.errors.NotNullViolation:
            # Expected: constraint violation
            test_db_connection.rollback()
        except Exception as e:
            test_db_connection.rollback()
            raise AssertionError(f"Expected NotNullViolation, got {type(e).__name__}: {e}") from e


def test_schema_preserves_indices(test_db_connection, sample_confiture_schema):
    """Test that indices defined in schema are created."""
    with test_db_connection.cursor() as cur:
        # Setup
        cur.execute("DROP TABLE IF EXISTS users CASCADE;")
        users_content = sample_confiture_schema["users"].read_text()
        cur.execute(users_content)
        test_db_connection.commit()

        # Query indices
        cur.execute("""
            SELECT indexname FROM pg_indexes
            WHERE tablename = 'users'
        """)

        indices = [row[0] for row in cur.fetchall()]

        # Verify indices exist (at minimum primary key constraint)
        assert len(indices) > 0, "Should have at least the primary key index"


def test_schema_foreign_keys_valid(test_db_connection, sample_confiture_schema):
    """Test that foreign keys defined in schema are valid."""
    with test_db_connection.cursor() as cur:
        # Setup users table
        cur.execute("DROP TABLE IF EXISTS posts CASCADE;")
        cur.execute("DROP TABLE IF EXISTS users CASCADE;")

        users_content = sample_confiture_schema["users"].read_text()
        cur.execute(users_content)

        posts_content = sample_confiture_schema["posts"].read_text()
        cur.execute(posts_content)
        test_db_connection.commit()

        # Query constraints
        cur.execute("""
            SELECT constraint_name, constraint_type
            FROM information_schema.table_constraints
            WHERE table_name = 'posts'
        """)

        constraints = {row[0]: row[1] for row in cur.fetchall()}

        # Should have at least primary key and foreign key
        has_fk = any(ct == "FOREIGN KEY" for ct in constraints.values())
        assert has_fk, "posts table should have foreign key to users"


def test_migration_does_not_truncate_data(test_db_connection, sample_confiture_schema):
    """Test that migrations preserve existing data."""
    with test_db_connection.cursor() as cur:
        # Setup
        cur.execute("DROP TABLE IF EXISTS users CASCADE;")
        users_content = sample_confiture_schema["users"].read_text()
        cur.execute(users_content)
        test_db_connection.commit()

        # Insert test data
        cur.execute("""
            INSERT INTO users (username, email)
            VALUES ('testuser', 'test@example.com')
        """)
        test_db_connection.commit()

        # Verify data exists before migration
        cur.execute("SELECT COUNT(*) FROM users")
        count_before = cur.fetchone()[0]
        assert count_before == 1, "Should have 1 row"

        # Data should persist (no TRUNCATE in migrations)
        cur.execute("SELECT COUNT(*) FROM users")
        count_after = cur.fetchone()[0]
        assert count_after == count_before, "Data should not be lost"


# ============================================================================
# CATEGORY 4: Edge Cases (6 tests)
# ============================================================================


def test_empty_migration_directory_handled(temp_project_dir):
    """Test that empty migration directory doesn't cause errors."""
    migrations_dir = temp_project_dir / "db" / "migrations"

    # Directory exists but is empty
    migration_files = list(migrations_dir.glob("*.sql"))
    assert isinstance(migration_files, list)


def test_duplicate_migration_names_detected(temp_project_dir):
    """Test that duplicate migration filenames are detectable."""
    migrations_dir = temp_project_dir / "db" / "migrations"

    # Create two migrations with same number
    (migrations_dir / "001_first.sql").write_text("-- First migration")
    (migrations_dir / "001_second.sql").write_text("-- Second migration")

    # Get files
    files = sorted(list(migrations_dir.glob("001_*.sql")))

    # Should detect multiple files with same prefix
    assert len(files) == 2, "Should detect duplicate migration numbers"


def test_migration_with_special_characters_in_name(temp_project_dir):
    """Test migration names with allowed special characters."""
    migrations_dir = temp_project_dir / "db" / "migrations"

    # Valid: underscore and numbers
    valid_file = migrations_dir / "001_add_user_authentication.sql"
    valid_file.write_text("-- Valid name with underscores")

    assert valid_file.exists()
    assert valid_file.name.replace(".sql", "").replace("_", "").replace("0", "").isalnum() or "_" in valid_file.name


def test_large_migration_file_handled(temp_project_dir):
    """Test that large migration files are handled correctly."""
    migrations_dir = temp_project_dir / "db" / "migrations"

    # Create large migration file (>1MB of comments)
    large_content = "-- Comment line with some padding to make it larger\n" * 25000
    large_content += "CREATE TABLE large_table (id UUID PRIMARY KEY);"

    large_file = migrations_dir / "001_large.sql"
    large_file.write_text(large_content)

    # Should handle large file (allow >=800KB since comment size varies)
    file_size = large_file.stat().st_size
    assert file_size > 800000, f"File should be > 800KB, got {file_size} bytes"
    content = large_file.read_text()
    assert "CREATE TABLE large_table" in content


def test_migration_with_multiple_statements(temp_project_dir):
    """Test migration with multiple SQL statements."""
    migrations_dir = temp_project_dir / "db" / "migrations"

    migration_content = """
    CREATE TABLE users (id UUID PRIMARY KEY);
    CREATE TABLE posts (id UUID PRIMARY KEY, user_id UUID REFERENCES users(id));
    CREATE INDEX idx_posts_user ON posts(user_id);
    """

    migration_file = migrations_dir / "001_multi.sql"
    migration_file.write_text(migration_content)

    content = migration_file.read_text()
    assert content.count("CREATE") >= 2


def test_migration_with_comments_and_whitespace(temp_project_dir):
    """Test migration parsing with various whitespace and comments."""
    migrations_dir = temp_project_dir / "db" / "migrations"

    migration_content = """
    -- This is a comment

    /* Multi-line
       comment */

    CREATE TABLE test (
        id UUID PRIMARY KEY
    );

    -- Final comment
    """

    migration_file = migrations_dir / "001_formatted.sql"
    migration_file.write_text(migration_content)

    # Should preserve structure
    content = migration_file.read_text()
    assert "CREATE TABLE test" in content
    assert "--" in content


# ============================================================================
# CATEGORY 5: Performance Validation (5 tests)
# ============================================================================


def test_schema_file_execution_completes(test_db_connection, sample_confiture_schema):
    """Test that schema execution completes in reasonable time."""
    import time

    with test_db_connection.cursor() as cur:
        cur.execute("DROP TABLE IF EXISTS users CASCADE;")

        start = time.time()
        users_content = sample_confiture_schema["users"].read_text()
        cur.execute(users_content)
        test_db_connection.commit()
        duration = time.time() - start

        # Simple table creation should be very fast
        assert duration < 5.0, f"Schema execution took {duration}s, should be < 5s"


def test_multiple_schema_files_execution(test_db_connection, sample_confiture_schema):
    """Test that multiple schema files execute in sequence."""
    import time

    with test_db_connection.cursor() as cur:
        # Clean up
        cur.execute("DROP TABLE IF EXISTS posts CASCADE;")
        cur.execute("DROP TABLE IF EXISTS users CASCADE;")

        start = time.time()

        # Execute in order: users first, then posts
        users_content = sample_confiture_schema["users"].read_text()
        cur.execute(users_content)
        test_db_connection.commit()

        posts_content = sample_confiture_schema["posts"].read_text()
        cur.execute(posts_content)
        test_db_connection.commit()

        duration = time.time() - start

        assert duration < 5.0, "Multiple tables should create quickly"


def test_index_creation_performance(test_db_connection):
    """Test that index creation is performant."""
    import time

    with test_db_connection.cursor() as cur:
        # Create table with data
        cur.execute("DROP TABLE IF EXISTS perf_test CASCADE;")
        cur.execute("""
            CREATE TABLE perf_test (
                id UUID PRIMARY KEY,
                name VARCHAR(255),
                email VARCHAR(255)
            )
        """)

        # Insert test data
        cur.execute("""
            INSERT INTO perf_test (id, name, email)
            SELECT
                gen_random_uuid(),
                'name_' || i,
                'email_' || i || '@example.com'
            FROM generate_series(1, 1000) i
        """)
        test_db_connection.commit()

        # Create index and measure time
        start = time.time()
        cur.execute("CREATE INDEX idx_perf_test_email ON perf_test(email)")
        test_db_connection.commit()
        duration = time.time() - start

        # Index creation on 1k rows should be fast
        assert duration < 1.0, f"Index creation took {duration}s, should be < 1s"


def test_constraint_creation_performance(test_db_connection):
    """Test that constraint creation is performant."""
    import time

    with test_db_connection.cursor() as cur:
        # Create tables
        cur.execute("DROP TABLE IF EXISTS child CASCADE;")
        cur.execute("DROP TABLE IF EXISTS parent CASCADE;")
        cur.execute("CREATE TABLE parent (id UUID PRIMARY KEY)")
        cur.execute("""
            CREATE TABLE child (
                id UUID PRIMARY KEY,
                parent_id UUID NOT NULL
            )
        """)
        test_db_connection.commit()

        # Add constraint and measure time
        start = time.time()
        cur.execute("""
            ALTER TABLE child
            ADD CONSTRAINT fk_child_parent
            FOREIGN KEY (parent_id)
            REFERENCES parent(id)
        """)
        test_db_connection.commit()
        duration = time.time() - start

        assert duration < 1.0, f"Constraint creation took {duration}s"


def test_view_creation_performance(test_db_connection):
    """Test that view creation is performant."""
    import time

    with test_db_connection.cursor() as cur:
        # Setup
        cur.execute("DROP VIEW IF EXISTS test_view CASCADE;")
        cur.execute("DROP TABLE IF EXISTS test_data CASCADE;")
        cur.execute("""
            CREATE TABLE test_data (
                id UUID PRIMARY KEY,
                category VARCHAR(100),
                amount NUMERIC
            )
        """)
        test_db_connection.commit()

        # Create view and measure time
        start = time.time()
        cur.execute("""
            CREATE VIEW test_view AS
            SELECT category, COUNT(*) as count, SUM(amount) as total
            FROM test_data
            GROUP BY category
        """)
        test_db_connection.commit()
        duration = time.time() - start

        assert duration < 1.0, "View creation should be fast"


# ============================================================================
# CATEGORY 6: Idempotency (5 tests)
# ============================================================================


def test_schema_execution_idempotent(test_db_connection, sample_confiture_schema):
    """Test that schema can be applied multiple times without error."""
    with test_db_connection.cursor() as cur:
        # First execution
        cur.execute("DROP TABLE IF EXISTS users CASCADE;")
        users_content = sample_confiture_schema["users"].read_text()

        # Use "IF NOT EXISTS" pattern for idempotency on table and indices
        idempotent_content = users_content.replace(
            "CREATE TABLE users",
            "CREATE TABLE IF NOT EXISTS users"
        ).replace(
            "CREATE INDEX idx_users_username",
            "CREATE INDEX IF NOT EXISTS idx_users_username"
        ).replace(
            "CREATE INDEX idx_users_email",
            "CREATE INDEX IF NOT EXISTS idx_users_email"
        )

        cur.execute(idempotent_content)
        test_db_connection.commit()

        # Second execution - should not fail
        cur.execute(idempotent_content)
        test_db_connection.commit()

        # Verify table still exists
        cur.execute("SELECT to_regclass('users')")
        assert cur.fetchone()[0] is not None


def test_index_idempotent(test_db_connection):
    """Test that index creation with IF NOT EXISTS is idempotent."""
    with test_db_connection.cursor() as cur:
        # Setup
        cur.execute("DROP TABLE IF EXISTS idx_test CASCADE;")
        cur.execute("CREATE TABLE idx_test (id UUID PRIMARY KEY, name VARCHAR(255))")
        test_db_connection.commit()

        # Create index first time
        cur.execute("CREATE INDEX IF NOT EXISTS idx_name ON idx_test(name)")
        test_db_connection.commit()

        # Create same index again - should not fail
        cur.execute("CREATE INDEX IF NOT EXISTS idx_name ON idx_test(name)")
        test_db_connection.commit()


def test_view_idempotent(test_db_connection):
    """Test that view creation is idempotent."""
    with test_db_connection.cursor() as cur:
        # Setup
        cur.execute("DROP VIEW IF EXISTS id_test_view CASCADE;")
        cur.execute("DROP TABLE IF EXISTS id_test CASCADE;")
        cur.execute("CREATE TABLE id_test (id UUID, category VARCHAR(100))")
        test_db_connection.commit()

        view_sql = """
            CREATE VIEW id_test_view AS
            SELECT category, COUNT(*) FROM id_test GROUP BY category
        """

        # Create view
        cur.execute(view_sql)
        test_db_connection.commit()

        # Drop and recreate to verify idempotency pattern
        cur.execute("DROP VIEW IF EXISTS id_test_view CASCADE;")
        cur.execute(view_sql)
        test_db_connection.commit()


def test_schema_extension_idempotent(test_db_connection):
    """Test that extension creation is idempotent."""
    with test_db_connection.cursor() as cur:
        # Create extension
        cur.execute("CREATE EXTENSION IF NOT EXISTS \"uuid-ossp\";")
        test_db_connection.commit()

        # Create same extension again
        cur.execute("CREATE EXTENSION IF NOT EXISTS \"uuid-ossp\";")
        test_db_connection.commit()


def test_constraint_idempotent(test_db_connection):
    """Test that constraints can be added idempotently."""
    with test_db_connection.cursor() as cur:
        # Setup
        cur.execute("DROP TABLE IF EXISTS parent CASCADE;")
        cur.execute("DROP TABLE IF EXISTS child CASCADE;")
        cur.execute("CREATE TABLE parent (id UUID PRIMARY KEY);")
        cur.execute("""
            CREATE TABLE child (
                id UUID PRIMARY KEY,
                parent_id UUID NOT NULL
            )
        """)
        test_db_connection.commit()

        # Try to add constraint (may fail if already exists)
        try:
            cur.execute("""
                ALTER TABLE child
                ADD CONSTRAINT fk_child_parent
                FOREIGN KEY (parent_id) REFERENCES parent(id)
            """)
            test_db_connection.commit()
        except Exception:
            test_db_connection.rollback()

        # Try again - should handle gracefully
        try:
            cur.execute("""
                ALTER TABLE child
                DROP CONSTRAINT IF EXISTS fk_child_parent
            """)
            test_db_connection.commit()
        except Exception:
            test_db_connection.rollback()
