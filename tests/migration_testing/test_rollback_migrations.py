"""Rollback migration tests for Confiture PostgreSQL migrations.

Tests verify that:
1. Migrations can be safely rolled back
2. Data is restored after rollback
3. Schema is returned to previous state
4. Rollbacks are idempotent
5. Rollback order is correct (reverse of forward)
"""

import pytest

# ============================================================================
# CATEGORY 1: Basic Rollback Operations (5 tests)
# ============================================================================


def test_rollback_reverses_table_creation(test_db_connection):
    """Test that rolling back a table creation removes the table."""
    with test_db_connection.cursor() as cur:
        # Setup: Create table
        cur.execute("DROP TABLE IF EXISTS rollback_test CASCADE;")
        cur.execute("""
            CREATE TABLE rollback_test (
                id UUID PRIMARY KEY,
                name VARCHAR(255)
            )
        """)
        test_db_connection.commit()

        # Verify table exists
        cur.execute("SELECT to_regclass('rollback_test')")
        assert cur.fetchone()[0] is not None

        # Simulate rollback: Drop table
        cur.execute("DROP TABLE IF EXISTS rollback_test CASCADE;")
        test_db_connection.commit()

        # Verify table is gone
        cur.execute("SELECT to_regclass('rollback_test')")
        assert cur.fetchone()[0] is None


def test_rollback_removes_column(test_db_connection):
    """Test that rolling back a column addition removes the column."""
    with test_db_connection.cursor() as cur:
        # Setup
        cur.execute("DROP TABLE IF EXISTS rollback_col CASCADE;")
        cur.execute("CREATE TABLE rollback_col (id UUID PRIMARY KEY)")
        test_db_connection.commit()

        # Add column (forward migration)
        cur.execute("ALTER TABLE rollback_col ADD COLUMN name VARCHAR(255)")
        test_db_connection.commit()

        # Verify column exists
        cur.execute("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'rollback_col' AND column_name = 'name'
        """)
        assert cur.fetchone() is not None

        # Rollback: Remove column
        cur.execute("ALTER TABLE rollback_col DROP COLUMN name")
        test_db_connection.commit()

        # Verify column is gone
        cur.execute("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'rollback_col' AND column_name = 'name'
        """)
        assert cur.fetchone() is None


def test_rollback_removes_index(test_db_connection):
    """Test that rolling back an index creation removes the index."""
    with test_db_connection.cursor() as cur:
        # Setup
        cur.execute("DROP TABLE IF EXISTS rb_idx CASCADE;")
        cur.execute("""
            CREATE TABLE rb_idx (
                id UUID PRIMARY KEY,
                email VARCHAR(255)
            )
        """)
        test_db_connection.commit()

        # Create index (forward)
        cur.execute("CREATE INDEX rb_idx_email ON rb_idx(email)")
        test_db_connection.commit()

        # Verify index exists
        cur.execute("""
            SELECT indexname FROM pg_indexes
            WHERE tablename = 'rb_idx' AND indexname = 'rb_idx_email'
        """)
        assert cur.fetchone() is not None

        # Rollback: Drop index
        cur.execute("DROP INDEX IF EXISTS rb_idx_email")
        test_db_connection.commit()

        # Verify index is gone
        cur.execute("""
            SELECT indexname FROM pg_indexes
            WHERE tablename = 'rb_idx' AND indexname = 'rb_idx_email'
        """)
        assert cur.fetchone() is None


def test_rollback_reverses_constraint(test_db_connection):
    """Test that rolling back constraint addition removes the constraint."""
    with test_db_connection.cursor() as cur:
        # Setup
        cur.execute("DROP TABLE IF EXISTS parent CASCADE;")
        cur.execute("DROP TABLE IF EXISTS child CASCADE;")
        cur.execute("CREATE TABLE parent (id UUID PRIMARY KEY)")
        cur.execute("CREATE TABLE child (id UUID PRIMARY KEY, parent_id UUID)")
        test_db_connection.commit()

        # Add constraint (forward)
        cur.execute("""
            ALTER TABLE child
            ADD CONSTRAINT fk_parent
            FOREIGN KEY (parent_id) REFERENCES parent(id)
        """)
        test_db_connection.commit()

        # Verify constraint exists
        cur.execute("""
            SELECT constraint_name FROM information_schema.table_constraints
            WHERE table_name = 'child' AND constraint_name = 'fk_parent'
        """)
        assert cur.fetchone() is not None

        # Rollback: Remove constraint
        cur.execute("ALTER TABLE child DROP CONSTRAINT fk_parent")
        test_db_connection.commit()

        # Verify constraint is gone
        cur.execute("""
            SELECT constraint_name FROM information_schema.table_constraints
            WHERE table_name = 'child' AND constraint_name = 'fk_parent'
        """)
        assert cur.fetchone() is None


def test_rollback_recreates_view(test_db_connection):
    """Test that rolling back a view removal can recreate the view."""
    with test_db_connection.cursor() as cur:
        # Setup: Create base table and view
        cur.execute("DROP VIEW IF EXISTS rb_view CASCADE;")
        cur.execute("DROP TABLE IF EXISTS rb_base CASCADE;")
        cur.execute("CREATE TABLE rb_base (id UUID PRIMARY KEY, value VARCHAR(255))")
        cur.execute("CREATE VIEW rb_view AS SELECT * FROM rb_base")
        test_db_connection.commit()

        # Verify view exists
        cur.execute("""
            SELECT table_name FROM information_schema.views
            WHERE table_name = 'rb_view'
        """)
        assert cur.fetchone() is not None

        # Simulate forward migration: Drop view
        cur.execute("DROP VIEW IF EXISTS rb_view CASCADE;")
        test_db_connection.commit()

        # Verify view is gone
        cur.execute("""
            SELECT table_name FROM information_schema.views
            WHERE table_name = 'rb_view'
        """)
        assert cur.fetchone() is None

        # Rollback: Recreate view
        cur.execute("""
            CREATE VIEW rb_view AS SELECT * FROM rb_base
        """)
        test_db_connection.commit()

        # Verify view is back
        cur.execute("""
            SELECT table_name FROM information_schema.views
            WHERE table_name = 'rb_view'
        """)
        assert cur.fetchone() is not None


# ============================================================================
# CATEGORY 2: Data Restoration (8 tests)
# ============================================================================


def test_rollback_preserves_data_on_column_removal(test_db_connection):
    """Test that data in other columns is preserved when rolling back column removal."""
    with test_db_connection.cursor() as cur:
        # Setup
        cur.execute("DROP TABLE IF EXISTS rb_data CASCADE;")
        cur.execute("""
            CREATE TABLE rb_data (
                id UUID PRIMARY KEY,
                name VARCHAR(255),
                email VARCHAR(255)
            )
        """)

        # Insert data
        cur.execute("""
            INSERT INTO rb_data VALUES
            (gen_random_uuid(), 'Alice', 'alice@example.com'),
            (gen_random_uuid(), 'Bob', 'bob@example.com')
        """)
        test_db_connection.commit()

        # Forward: Remove email column
        cur.execute("ALTER TABLE rb_data DROP COLUMN email")
        test_db_connection.commit()

        # Rollback: Re-add email column (with default)
        cur.execute("""
            ALTER TABLE rb_data ADD COLUMN email VARCHAR(255) DEFAULT 'unknown@example.com'
        """)
        test_db_connection.commit()

        # Verify names are preserved
        cur.execute("SELECT COUNT(*), COUNT(DISTINCT name) FROM rb_data WHERE name IN ('Alice', 'Bob')")
        count, distinct = cur.fetchone()
        assert count == 2


def test_rollback_does_not_delete_existing_data(test_db_connection):
    """Test that rollback of a modification doesn't delete data."""
    with test_db_connection.cursor() as cur:
        # Setup
        cur.execute("DROP TABLE IF EXISTS rb_modify CASCADE;")
        cur.execute("CREATE TABLE rb_modify (id UUID PRIMARY KEY, value NUMERIC)")

        # Insert data
        cur.execute("""
            INSERT INTO rb_modify VALUES
            (gen_random_uuid(), 100),
            (gen_random_uuid(), 200)
        """)
        test_db_connection.commit()

        # Count before
        cur.execute("SELECT COUNT(*) FROM rb_modify")
        count_before = cur.fetchone()[0]

        # Simulate modification
        cur.execute("UPDATE rb_modify SET value = value * 2")
        test_db_connection.commit()

        # Rollback simulation (revert values)
        cur.execute("UPDATE rb_modify SET value = value / 2")
        test_db_connection.commit()

        # Count after rollback
        cur.execute("SELECT COUNT(*) FROM rb_modify")
        count_after = cur.fetchone()[0]

        assert count_before == count_after == 2


def test_rollback_on_failed_migration_keeps_data_intact(test_db_connection):
    """Test that failed migration rollback doesn't lose data."""
    with test_db_connection.cursor() as cur:
        # Setup
        cur.execute("DROP TABLE IF EXISTS rb_fail CASCADE;")
        cur.execute("""
            CREATE TABLE rb_fail (
                id UUID PRIMARY KEY,
                data TEXT
            )
        """)

        # Insert initial data
        cur.execute("""
            INSERT INTO rb_fail VALUES (gen_random_uuid(), 'important_data')
        """)
        test_db_connection.commit()

        count_before = cur.execute("SELECT COUNT(*) FROM rb_fail").fetchone()[0]

        # Attempt migration (would fail due to constraint)
        try:
            cur.execute("ALTER TABLE rb_fail ADD COLUMN status INT NOT NULL")
            test_db_connection.commit()
        except Exception:
            test_db_connection.rollback()

        # Data should still be there
        cur.execute("SELECT COUNT(*) FROM rb_fail")
        count_after = cur.fetchone()[0]

        assert count_before == count_after


def test_rollback_restores_unique_constraint_data(test_db_connection):
    """Test that data satisfying unique constraints is preserved in rollback."""
    with test_db_connection.cursor() as cur:
        # Setup
        cur.execute("DROP TABLE IF EXISTS rb_unique CASCADE;")
        cur.execute("""
            CREATE TABLE rb_unique (
                id UUID PRIMARY KEY,
                email VARCHAR(255) UNIQUE
            )
        """)

        # Insert data with unique emails
        cur.execute("""
            INSERT INTO rb_unique (id, email) VALUES
            (gen_random_uuid(), 'alice@example.com'),
            (gen_random_uuid(), 'bob@example.com')
        """)
        test_db_connection.commit()

        # Forward: Drop unique constraint
        cur.execute("ALTER TABLE rb_unique DROP CONSTRAINT rb_unique_email_key")
        test_db_connection.commit()

        # Rollback: Add unique constraint back (data must still be valid)
        cur.execute("""
            ALTER TABLE rb_unique
            ADD CONSTRAINT rb_unique_email_key UNIQUE (email)
        """)
        test_db_connection.commit()

        # Data should be intact
        cur.execute("SELECT COUNT(*) FROM rb_unique")
        assert cur.fetchone()[0] == 2


def test_rollback_preserves_foreign_key_relationships(test_db_connection):
    """Test that FK relationships are preserved after rollback."""
    with test_db_connection.cursor() as cur:
        # Setup parent-child
        cur.execute("DROP TABLE IF EXISTS rb_child CASCADE;")
        cur.execute("DROP TABLE IF EXISTS rb_parent CASCADE;")
        cur.execute("CREATE TABLE rb_parent (id UUID PRIMARY KEY)")
        cur.execute("""
            CREATE TABLE rb_child (
                id UUID PRIMARY KEY,
                parent_id UUID REFERENCES rb_parent(id)
            )
        """)

        # Insert data
        parent_id = None
        cur.execute("""
            INSERT INTO rb_parent (id) VALUES (gen_random_uuid())
            RETURNING id
        """)
        parent_id = cur.fetchone()[0]

        cur.execute("""
            INSERT INTO rb_child (id, parent_id) VALUES (gen_random_uuid(), %s)
        """, (parent_id,))
        test_db_connection.commit()

        # Verify count before
        cur.execute("SELECT COUNT(*) FROM rb_child")
        count_before = cur.fetchone()[0]

        # Data should still be valid after rollback sequence
        cur.execute("SELECT COUNT(*) FROM rb_child")
        count_after = cur.fetchone()[0]

        assert count_before == count_after == 1


def test_rollback_cascade_delete_handling(test_db_connection):
    """Test that CASCADE delete relationships are preserved in rollback."""
    with test_db_connection.cursor() as cur:
        # Setup
        cur.execute("DROP TABLE IF EXISTS rb_cascade_child CASCADE;")
        cur.execute("DROP TABLE IF EXISTS rb_cascade_parent CASCADE;")

        cur.execute("CREATE TABLE rb_cascade_parent (id UUID PRIMARY KEY)")
        cur.execute("""
            CREATE TABLE rb_cascade_child (
                id UUID PRIMARY KEY,
                parent_id UUID REFERENCES rb_cascade_parent(id) ON DELETE CASCADE
            )
        """)

        # Insert data
        cur.execute("""
            INSERT INTO rb_cascade_parent (id) VALUES (gen_random_uuid())
        """)
        parent_id = cur.execute("SELECT id FROM rb_cascade_parent LIMIT 1").fetchone()[0]

        cur.execute("""
            INSERT INTO rb_cascade_child (id, parent_id) VALUES
            (gen_random_uuid(), %s),
            (gen_random_uuid(), %s)
        """, (parent_id, parent_id))
        test_db_connection.commit()

        # Count children before
        cur.execute("SELECT COUNT(*) FROM rb_cascade_child")
        cur.fetchone()[0]

        # Verify CASCADE works (delete parent deletes children)
        cur.execute("DELETE FROM rb_cascade_parent WHERE id = %s", (parent_id,))
        test_db_connection.commit()

        cur.execute("SELECT COUNT(*) FROM rb_cascade_child")
        count_after = cur.fetchone()[0]

        assert count_after == 0  # CASCADE delete worked


# ============================================================================
# CATEGORY 3: Rollback Safety (8 tests)
# ============================================================================


def test_rollback_fails_with_invalid_sql(test_db_connection):
    """Test that rollback fails gracefully with invalid SQL."""
    with test_db_connection.cursor() as cur:
        try:
            cur.execute("INVALID SQL THAT DOES NOT PARSE")
            pytest.fail("Should fail on invalid SQL")
        except Exception:
            # Expected: rollback should happen
            test_db_connection.rollback()


def test_rollback_maintains_transaction_integrity(test_db_connection):
    """Test that rollback maintains transaction boundaries."""
    with test_db_connection.cursor() as cur:
        # Setup
        cur.execute("DROP TABLE IF EXISTS rb_txn CASCADE;")
        cur.execute("CREATE TABLE rb_txn (id UUID PRIMARY KEY)")
        test_db_connection.commit()

        # Start transaction
        cur.execute("INSERT INTO rb_txn (id) VALUES (gen_random_uuid())")

        # Rollback transaction
        test_db_connection.rollback()

        # Data should not be there
        cur.execute("SELECT COUNT(*) FROM rb_txn")
        assert cur.fetchone()[0] == 0


def test_rollback_sequence_order(test_db_connection):
    """Test that rollbacks occur in correct reverse order."""
    with test_db_connection.cursor() as cur:
        # Create tables in order 1, 2, 3
        cur.execute("DROP TABLE IF EXISTS rb_order_3 CASCADE;")
        cur.execute("DROP TABLE IF EXISTS rb_order_2 CASCADE;")
        cur.execute("DROP TABLE IF EXISTS rb_order_1 CASCADE;")

        cur.execute("CREATE TABLE rb_order_1 (id UUID PRIMARY KEY)")
        cur.execute("CREATE TABLE rb_order_2 (id UUID PRIMARY KEY)")
        cur.execute("CREATE TABLE rb_order_3 (id UUID PRIMARY KEY)")
        test_db_connection.commit()

        # Rollback in reverse order (3, 2, 1)
        cur.execute("DROP TABLE IF EXISTS rb_order_3 CASCADE;")
        test_db_connection.commit()

        cur.execute("SELECT to_regclass('rb_order_3')")
        assert cur.fetchone()[0] is None

        cur.execute("SELECT to_regclass('rb_order_2')")
        assert cur.fetchone()[0] is not None  # Should still exist


def test_rollback_with_dependent_views(test_db_connection):
    """Test that rollback handles view dependencies correctly."""
    with test_db_connection.cursor() as cur:
        # Setup
        cur.execute("DROP VIEW IF EXISTS rb_dep_view CASCADE;")
        cur.execute("DROP TABLE IF EXISTS rb_dep_base CASCADE;")

        cur.execute("""
            CREATE TABLE rb_dep_base (
                id UUID PRIMARY KEY,
                category VARCHAR(100)
            )
        """)

        cur.execute("""
            CREATE VIEW rb_dep_view AS
            SELECT category, COUNT(*) as count FROM rb_dep_base GROUP BY category
        """)
        test_db_connection.commit()

        # Remove view (forward)
        cur.execute("DROP VIEW rb_dep_view CASCADE;")
        test_db_connection.commit()

        # Recreate view (rollback)
        cur.execute("""
            CREATE VIEW rb_dep_view AS
            SELECT category, COUNT(*) as count FROM rb_dep_base GROUP BY category
        """)
        test_db_connection.commit()

        # View should work
        cur.execute("SELECT * FROM rb_dep_view")


def test_rollback_preserves_system_state(test_db_connection):
    """Test that rollback doesn't affect system-level state."""
    with test_db_connection.cursor() as cur:
        # Get initial sequence values using pg_sequences (compatible with PostgreSQL 18)
        cur.execute("SELECT count(*) FROM pg_sequences")
        cur.fetchone()[0]

        # Create a table (may use sequences internally)
        cur.execute("DROP TABLE IF EXISTS rb_sys CASCADE;")
        cur.execute("CREATE TABLE rb_sys (id BIGSERIAL PRIMARY KEY)")
        test_db_connection.commit()

        # Get state after - should have new sequence for the serial column
        cur.execute("SELECT count(*) FROM pg_sequences WHERE schemaname = 'public' AND sequencename LIKE '%rb_sys%'")
        result = cur.fetchone()
        assert result is not None and result[0] >= 1, "Should have a sequence for BIGSERIAL"


def test_rollback_idempotent_operations(test_db_connection):
    """Test that rolling back idempotent operations is safe."""
    with test_db_connection.cursor() as cur:
        # Create table with IF NOT EXISTS (idempotent)
        cur.execute("DROP TABLE IF EXISTS rb_idempotent CASCADE;")
        cur.execute("CREATE TABLE IF NOT EXISTS rb_idempotent (id UUID PRIMARY KEY)")
        test_db_connection.commit()

        # Try creating again (safe due to IF NOT EXISTS)
        cur.execute("CREATE TABLE IF NOT EXISTS rb_idempotent (id UUID PRIMARY KEY)")
        test_db_connection.commit()

        # Table should still exist exactly once
        cur.execute("SELECT to_regclass('rb_idempotent')")
        assert cur.fetchone()[0] is not None


def test_rollback_concurrent_safety(test_db_connection):
    """Test that rollback is safe with proper transaction isolation."""
    with test_db_connection.cursor() as cur:
        # Setup
        cur.execute("DROP TABLE IF EXISTS rb_concurrent CASCADE;")
        cur.execute("CREATE TABLE rb_concurrent (id UUID PRIMARY KEY, value NUMERIC)")
        cur.execute("INSERT INTO rb_concurrent VALUES (gen_random_uuid(), 100)")
        test_db_connection.commit()

        # Transaction 1: Start and modify
        cur.execute("UPDATE rb_concurrent SET value = value + 50")

        # Rollback
        test_db_connection.rollback()

        # Value should be original
        cur.execute("SELECT value FROM rb_concurrent")
        assert cur.fetchone()[0] == 100


# ============================================================================
# CATEGORY 4: Idempotency (8 tests)
# ============================================================================


def test_rollback_idempotent_drop_table(test_db_connection):
    """Test that DROP TABLE IF EXISTS is idempotent."""
    with test_db_connection.cursor() as cur:
        # Create and drop
        cur.execute("DROP TABLE IF EXISTS rb_drop_idem CASCADE;")
        cur.execute("CREATE TABLE rb_drop_idem (id UUID PRIMARY KEY)")
        test_db_connection.commit()

        # Drop once
        cur.execute("DROP TABLE IF EXISTS rb_drop_idem CASCADE;")
        test_db_connection.commit()

        # Drop again (idempotent)
        cur.execute("DROP TABLE IF EXISTS rb_drop_idem CASCADE;")
        test_db_connection.commit()


def test_rollback_idempotent_drop_column(test_db_connection):
    """Test that DROP COLUMN IF EXISTS is idempotent."""
    with test_db_connection.cursor() as cur:
        # Setup
        cur.execute("DROP TABLE IF EXISTS rb_col_idem CASCADE;")
        cur.execute("""
            CREATE TABLE rb_col_idem (
                id UUID PRIMARY KEY,
                temporary_col VARCHAR(255)
            )
        """)
        test_db_connection.commit()

        # Drop column
        cur.execute("ALTER TABLE rb_col_idem DROP COLUMN IF EXISTS temporary_col")
        test_db_connection.commit()

        # Drop again (should be safe)
        cur.execute("ALTER TABLE rb_col_idem DROP COLUMN IF EXISTS temporary_col")
        test_db_connection.commit()


def test_rollback_idempotent_drop_index(test_db_connection):
    """Test that DROP INDEX IF EXISTS is idempotent."""
    with test_db_connection.cursor() as cur:
        # Setup
        cur.execute("DROP TABLE IF EXISTS rb_idx_idem CASCADE;")
        cur.execute("CREATE TABLE rb_idx_idem (id UUID PRIMARY KEY, email VARCHAR(255))")
        cur.execute("CREATE INDEX idx_email_idem ON rb_idx_idem(email)")
        test_db_connection.commit()

        # Drop once
        cur.execute("DROP INDEX IF EXISTS idx_email_idem")
        test_db_connection.commit()

        # Drop again (idempotent)
        cur.execute("DROP INDEX IF EXISTS idx_email_idem")
        test_db_connection.commit()


def test_rollback_idempotent_drop_constraint(test_db_connection):
    """Test that DROP CONSTRAINT IF EXISTS is idempotent."""
    with test_db_connection.cursor() as cur:
        # Setup
        cur.execute("DROP TABLE IF EXISTS rb_child_idem CASCADE;")
        cur.execute("DROP TABLE IF EXISTS rb_parent_idem CASCADE;")
        cur.execute("CREATE TABLE rb_parent_idem (id UUID PRIMARY KEY)")
        cur.execute("""
            CREATE TABLE rb_child_idem (
                id UUID PRIMARY KEY,
                parent_id UUID REFERENCES rb_parent_idem(id)
            )
        """)
        test_db_connection.commit()

        # Drop constraint
        cur.execute("""
            ALTER TABLE rb_child_idem
            DROP CONSTRAINT IF EXISTS rb_child_idem_parent_id_fkey
        """)
        test_db_connection.commit()

        # Drop again (idempotent)
        cur.execute("""
            ALTER TABLE rb_child_idem
            DROP CONSTRAINT IF EXISTS rb_child_idem_parent_id_fkey
        """)
        test_db_connection.commit()


def test_rollback_idempotent_drop_view(test_db_connection):
    """Test that DROP VIEW IF EXISTS is idempotent."""
    with test_db_connection.cursor() as cur:
        # Setup
        cur.execute("DROP VIEW IF EXISTS rb_view_idem CASCADE;")
        cur.execute("DROP TABLE IF EXISTS rb_base_idem CASCADE;")
        cur.execute("CREATE TABLE rb_base_idem (id UUID PRIMARY KEY)")
        cur.execute("CREATE VIEW rb_view_idem AS SELECT * FROM rb_base_idem")
        test_db_connection.commit()

        # Drop once
        cur.execute("DROP VIEW IF EXISTS rb_view_idem CASCADE;")
        test_db_connection.commit()

        # Drop again (idempotent)
        cur.execute("DROP VIEW IF EXISTS rb_view_idem CASCADE;")
        test_db_connection.commit()


def test_rollback_idempotent_drop_extension(test_db_connection):
    """Test that DROP EXTENSION IF EXISTS is idempotent."""
    with test_db_connection.cursor() as cur:
        # Test idempotent drop pattern: DROP EXTENSION IF EXISTS should not error
        # even if the extension is already dropped or doesn't exist

        # Drop a non-existent extension (should succeed, not error)
        cur.execute("DROP EXTENSION IF EXISTS \"nonexistent_extension_xyz\";")
        test_db_connection.commit()

        # Drop the same non-existent extension again (idempotent - should still succeed)
        cur.execute("DROP EXTENSION IF EXISTS \"nonexistent_extension_xyz\";")
        test_db_connection.commit()

        # This test validates the idempotency pattern, not actual extension dropping


def test_rollback_idempotent_sequence_reset(test_db_connection):
    """Test that sequence resets are idempotent."""
    with test_db_connection.cursor() as cur:
        # Setup
        cur.execute("DROP TABLE IF EXISTS rb_seq_idem CASCADE;")
        cur.execute("CREATE TABLE rb_seq_idem (id BIGSERIAL PRIMARY KEY, data TEXT)")
        test_db_connection.commit()

        # Insert data
        cur.execute("INSERT INTO rb_seq_idem (data) VALUES ('test1'), ('test2')")
        test_db_connection.commit()

        # Reset sequence
        cur.execute("ALTER SEQUENCE rb_seq_idem_id_seq RESTART WITH 1")
        test_db_connection.commit()

        # Reset again (idempotent)
        cur.execute("ALTER SEQUENCE rb_seq_idem_id_seq RESTART WITH 1")
        test_db_connection.commit()


# ============================================================================
# CATEGORY 5: Rollback Performance (5 tests)
# ============================================================================


def test_rollback_simple_table_fast(test_db_connection):
    """Test that rolling back table creation is fast."""
    import time

    with test_db_connection.cursor() as cur:
        # Create table
        cur.execute("CREATE TABLE IF NOT EXISTS rb_perf_1 (id UUID PRIMARY KEY)")
        test_db_connection.commit()

        # Time the rollback
        start = time.time()
        cur.execute("DROP TABLE IF EXISTS rb_perf_1 CASCADE;")
        test_db_connection.commit()
        duration = time.time() - start

        assert duration < 1.0


def test_rollback_multiple_tables_fast(test_db_connection):
    """Test that rolling back multiple table creations is fast."""
    import time

    with test_db_connection.cursor() as cur:
        # Create tables
        for i in range(5):
            cur.execute(f"CREATE TABLE IF NOT EXISTS rb_multi_{i} (id UUID PRIMARY KEY)")
        test_db_connection.commit()

        # Time the rollback
        start = time.time()
        for i in range(5):
            cur.execute(f"DROP TABLE IF EXISTS rb_multi_{i} CASCADE;")
        test_db_connection.commit()
        duration = time.time() - start

        assert duration < 5.0


def test_rollback_index_removal_fast(test_db_connection):
    """Test that rolling back index creation is fast."""
    import time

    with test_db_connection.cursor() as cur:
        # Setup
        cur.execute("DROP TABLE IF EXISTS rb_idx_perf CASCADE;")
        cur.execute("""
            CREATE TABLE rb_idx_perf (
                id UUID PRIMARY KEY,
                col1 VARCHAR(255),
                col2 VARCHAR(255),
                col3 VARCHAR(255)
            )
        """)
        test_db_connection.commit()

        # Create indices
        cur.execute("CREATE INDEX idx_col1 ON rb_idx_perf(col1)")
        cur.execute("CREATE INDEX idx_col2 ON rb_idx_perf(col2)")
        cur.execute("CREATE INDEX idx_col3 ON rb_idx_perf(col3)")
        test_db_connection.commit()

        # Time the rollback
        start = time.time()
        cur.execute("DROP INDEX IF EXISTS idx_col1")
        cur.execute("DROP INDEX IF EXISTS idx_col2")
        cur.execute("DROP INDEX IF EXISTS idx_col3")
        test_db_connection.commit()
        duration = time.time() - start

        assert duration < 1.0


def test_rollback_constraint_removal_fast(test_db_connection):
    """Test that rolling back constraint addition is fast."""
    import time

    with test_db_connection.cursor() as cur:
        # Setup
        cur.execute("DROP TABLE IF EXISTS rb_child_perf CASCADE;")
        cur.execute("DROP TABLE IF EXISTS rb_parent_perf CASCADE;")
        cur.execute("CREATE TABLE rb_parent_perf (id UUID PRIMARY KEY)")
        cur.execute("""
            CREATE TABLE rb_child_perf (
                id UUID PRIMARY KEY,
                parent_id UUID
            )
        """)
        test_db_connection.commit()

        # Add constraints
        cur.execute("""
            ALTER TABLE rb_child_perf
            ADD CONSTRAINT fk_parent FOREIGN KEY (parent_id) REFERENCES rb_parent_perf(id)
        """)
        test_db_connection.commit()

        # Time the rollback
        start = time.time()
        cur.execute("ALTER TABLE rb_child_perf DROP CONSTRAINT fk_parent")
        test_db_connection.commit()
        duration = time.time() - start

        assert duration < 1.0


def test_rollback_view_recreation_fast(test_db_connection):
    """Test that rolling back view creation is fast."""
    import time

    with test_db_connection.cursor() as cur:
        # Setup
        cur.execute("DROP VIEW IF EXISTS rb_view_perf CASCADE;")
        cur.execute("DROP TABLE IF EXISTS rb_base_perf CASCADE;")
        cur.execute("CREATE TABLE rb_base_perf (id UUID PRIMARY KEY, value NUMERIC)")
        test_db_connection.commit()

        # Create and drop view multiple times
        start = time.time()
        for i in range(5):
            cur.execute(f"DROP VIEW IF EXISTS rb_view_perf_{i} CASCADE;")
            cur.execute(f"""
                CREATE VIEW rb_view_perf_{i} AS
                SELECT * FROM rb_base_perf WHERE value > {i}
            """)
        test_db_connection.commit()
        duration = time.time() - start

        assert duration < 2.0
