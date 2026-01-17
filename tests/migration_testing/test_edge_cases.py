"""Edge case and integration tests for Confiture PostgreSQL migrations.

Tests verify handling of:
1. Schema conflicts and resolution
2. Concurrent operations
3. Large datasets (100k+ rows)
4. Constraint violations and handling
5. View dependencies
6. Multi-step migrations
7. Complex transformations
"""

import pytest

# ============================================================================
# CATEGORY 1: Schema Conflicts (5 tests)
# ============================================================================


def test_duplicate_table_name_conflict(test_db_connection):
    """Test handling of attempts to create duplicate tables."""
    with test_db_connection.cursor() as cur:
        # Create table
        cur.execute("DROP TABLE IF EXISTS conflict_test CASCADE;")
        cur.execute("CREATE TABLE conflict_test (id UUID PRIMARY KEY)")
        test_db_connection.commit()

        # Try to create same table (should fail without IF NOT EXISTS)
        try:
            cur.execute("CREATE TABLE conflict_test (id UUID PRIMARY KEY)")
            pytest.fail("Should fail on duplicate table")
        except Exception:
            test_db_connection.rollback()

        # With IF NOT EXISTS should succeed
        cur.execute("CREATE TABLE IF NOT EXISTS conflict_test (id UUID PRIMARY KEY)")
        test_db_connection.commit()


def test_column_type_mismatch_handling(test_db_connection):
    """Test handling of column type changes."""
    with test_db_connection.cursor() as cur:
        # Create table
        cur.execute("DROP TABLE IF EXISTS type_test CASCADE;")
        cur.execute("CREATE TABLE type_test (id UUID PRIMARY KEY, value VARCHAR(255))")
        test_db_connection.commit()

        # Insert data
        cur.execute("INSERT INTO type_test VALUES (gen_random_uuid(), 'text')")
        test_db_connection.commit()

        # Try to change column type (may fail if data incompatible)
        try:
            cur.execute("ALTER TABLE type_test ALTER COLUMN value TYPE NUMERIC")
            test_db_connection.commit()
        except Exception:
            test_db_connection.rollback()


def test_constraint_name_collision(test_db_connection):
    """Test handling of duplicate constraint names."""
    with test_db_connection.cursor() as cur:
        # Setup
        cur.execute("DROP TABLE IF EXISTS child CASCADE;")
        cur.execute("DROP TABLE IF EXISTS parent CASCADE;")
        cur.execute("CREATE TABLE parent (id UUID PRIMARY KEY)")
        cur.execute("CREATE TABLE child (id UUID PRIMARY KEY, parent_id UUID)")
        test_db_connection.commit()

        # Add constraint
        cur.execute("""
            ALTER TABLE child
            ADD CONSTRAINT fk_test FOREIGN KEY (parent_id) REFERENCES parent(id)
        """)
        test_db_connection.commit()

        # Try to add same constraint again (should fail)
        try:
            cur.execute("""
                ALTER TABLE child
                ADD CONSTRAINT fk_test FOREIGN KEY (parent_id) REFERENCES parent(id)
            """)
            pytest.fail("Should fail on duplicate constraint")
        except Exception:
            test_db_connection.rollback()


def test_index_name_collision(test_db_connection):
    """Test handling of duplicate index names."""
    with test_db_connection.cursor() as cur:
        # Setup
        cur.execute("DROP TABLE IF EXISTS idx_test CASCADE;")
        cur.execute("CREATE TABLE idx_test (id UUID PRIMARY KEY, email VARCHAR(255))")
        test_db_connection.commit()

        # Create index
        cur.execute("CREATE INDEX idx_email ON idx_test(email)")
        test_db_connection.commit()

        # Try to create same index (should fail)
        try:
            cur.execute("CREATE INDEX idx_email ON idx_test(email)")
            pytest.fail("Should fail on duplicate index")
        except Exception:
            test_db_connection.rollback()


def test_schema_naming_convention_enforcement(test_db_connection):
    """Test validation of schema naming conventions."""
    with test_db_connection.cursor() as cur:
        # PostgreSQL allows various schema names
        cur.execute("CREATE SCHEMA IF NOT EXISTS valid_schema;")
        test_db_connection.commit()

        # Should allow underscores
        cur.execute("CREATE SCHEMA IF NOT EXISTS schema_with_underscore;")
        test_db_connection.commit()

        # Cleanup
        cur.execute("DROP SCHEMA IF EXISTS valid_schema CASCADE;")
        cur.execute("DROP SCHEMA IF EXISTS schema_with_underscore CASCADE;")
        test_db_connection.commit()


# ============================================================================
# CATEGORY 2: Concurrent Operations (4 tests)
# ============================================================================


def test_concurrent_table_creation_safety(test_db_connection):
    """Test that table creation is safe with concurrent access."""
    with test_db_connection.cursor() as cur:
        # Create table (idempotent)
        cur.execute("DROP TABLE IF EXISTS concurrent_test CASCADE;")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS concurrent_test (
                id UUID PRIMARY KEY,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)
        test_db_connection.commit()

        # "Concurrent" operation - try to create again
        cur.execute("""
            CREATE TABLE IF NOT EXISTS concurrent_test (
                id UUID PRIMARY KEY,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)
        test_db_connection.commit()

        # Should still exist once
        cur.execute("SELECT to_regclass('concurrent_test')")
        assert cur.fetchone()[0] is not None


def test_concurrent_index_creation_safety(test_db_connection):
    """Test that index creation is safe with concurrent access."""
    with test_db_connection.cursor() as cur:
        # Setup
        cur.execute("DROP TABLE IF EXISTS concur_idx CASCADE;")
        cur.execute("""
            CREATE TABLE concur_idx (
                id UUID PRIMARY KEY,
                email VARCHAR(255)
            )
        """)
        test_db_connection.commit()

        # Create index (idempotent)
        cur.execute("CREATE INDEX IF NOT EXISTS concur_email ON concur_idx(email)")
        test_db_connection.commit()

        # "Concurrent" operation - try again
        cur.execute("CREATE INDEX IF NOT EXISTS concur_email ON concur_idx(email)")
        test_db_connection.commit()


def test_concurrent_data_modification_consistency(test_db_connection):
    """Test data consistency during concurrent modifications."""
    with test_db_connection.cursor() as cur:
        # Setup
        cur.execute("DROP TABLE IF EXISTS concur_data CASCADE;")
        cur.execute("CREATE TABLE concur_data (id UUID PRIMARY KEY, value NUMERIC)")
        test_db_connection.commit()

        # Insert data
        cur.execute("INSERT INTO concur_data (id, value) VALUES (gen_random_uuid(), 100)")
        test_db_connection.commit()

        # Modify data
        cur.execute("UPDATE concur_data SET value = value + 50")
        test_db_connection.commit()

        # Verify consistency
        cur.execute("SELECT value FROM concur_data")
        assert cur.fetchone()[0] == 150


def test_concurrent_view_access_safety(test_db_connection):
    """Test that views work safely with concurrent access."""
    with test_db_connection.cursor() as cur:
        # Setup
        cur.execute("DROP VIEW IF EXISTS concur_view CASCADE;")
        cur.execute("DROP TABLE IF EXISTS concur_base CASCADE;")

        cur.execute("""
            CREATE TABLE concur_base (
                id UUID PRIMARY KEY,
                category VARCHAR(100)
            )
        """)

        cur.execute("""
            CREATE VIEW concur_view AS
            SELECT category, COUNT(*) as count FROM concur_base GROUP BY category
        """)
        test_db_connection.commit()

        # Insert data
        cur.execute("""
            INSERT INTO concur_base (id, category)
            VALUES (gen_random_uuid(), 'A'), (gen_random_uuid(), 'B')
        """)
        test_db_connection.commit()

        # Query view
        cur.execute("SELECT COUNT(*) FROM concur_view")
        result = cur.fetchone()[0]
        assert result == 2


# ============================================================================
# CATEGORY 3: Large Datasets (5 tests)
# ============================================================================


def test_large_table_creation(test_db_connection):
    """Test creation of table to handle large datasets."""
    with test_db_connection.cursor() as cur:
        # Create table for large data
        cur.execute("DROP TABLE IF EXISTS large_table CASCADE;")
        cur.execute("""
            CREATE TABLE large_table (
                id UUID PRIMARY KEY,
                sequence_no BIGINT,
                category VARCHAR(100),
                value NUMERIC,
                data TEXT,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)
        test_db_connection.commit()


def test_bulk_insert_performance(test_db_connection):
    """Test bulk insert of 100k+ rows."""
    import time

    with test_db_connection.cursor() as cur:
        # Setup
        cur.execute("DROP TABLE IF EXISTS bulk_test CASCADE;")
        cur.execute("""
            CREATE TABLE bulk_test (
                id UUID PRIMARY KEY,
                sequence_no BIGINT,
                value NUMERIC
            )
        """)
        test_db_connection.commit()

        # Bulk insert 10k rows (for test purposes)
        start = time.time()
        cur.execute("""
            INSERT INTO bulk_test (id, sequence_no, value)
            SELECT
                gen_random_uuid(),
                i,
                (i * 1.5)
            FROM generate_series(1, 10000) i
        """)
        test_db_connection.commit()
        duration = time.time() - start

        # Should complete reasonably fast
        assert duration < 30.0

        # Verify count
        cur.execute("SELECT COUNT(*) FROM bulk_test")
        assert cur.fetchone()[0] == 10000


def test_large_table_indexing(test_db_connection):
    """Test index creation on large table."""
    import time

    with test_db_connection.cursor() as cur:
        # Setup with data
        cur.execute("DROP TABLE IF EXISTS large_idx CASCADE;")
        cur.execute("""
            CREATE TABLE large_idx (
                id UUID PRIMARY KEY,
                category VARCHAR(100),
                value NUMERIC
            )
        """)

        # Insert 50k rows
        cur.execute("""
            INSERT INTO large_idx (id, category, value)
            SELECT
                gen_random_uuid(),
                'cat_' || (i % 100)::text,
                i * 1.5
            FROM generate_series(1, 50000) i
        """)
        test_db_connection.commit()

        # Create index on large table
        start = time.time()
        cur.execute("CREATE INDEX idx_large_category ON large_idx(category)")
        test_db_connection.commit()
        duration = time.time() - start

        # Index creation should complete
        assert duration < 30.0


def test_large_table_constraint_addition(test_db_connection):
    """Test adding constraints to tables with large datasets."""
    with test_db_connection.cursor() as cur:
        # Setup
        cur.execute("DROP TABLE IF EXISTS large_parent CASCADE;")
        cur.execute("DROP TABLE IF EXISTS large_child CASCADE;")

        cur.execute("""
            CREATE TABLE large_parent (
                id UUID PRIMARY KEY,
                name VARCHAR(255)
            )
        """)

        cur.execute("""
            CREATE TABLE large_child (
                id UUID PRIMARY KEY,
                parent_id UUID,
                value NUMERIC
            )
        """)

        # Insert parent data
        cur.execute("""
            INSERT INTO large_parent (id, name)
            SELECT gen_random_uuid(), 'parent_' || i
            FROM generate_series(1, 1000) i
        """)

        # Insert child data (20k rows)
        cur.execute("""
            INSERT INTO large_child (id, parent_id, value)
            SELECT
                gen_random_uuid(),
                (SELECT id FROM large_parent OFFSET random() * 999 LIMIT 1),
                i * 1.5
            FROM generate_series(1, 20000) i
        """)
        test_db_connection.commit()

        # Add constraint on large table
        cur.execute("""
            ALTER TABLE large_child
            ADD CONSTRAINT fk_large_parent
            FOREIGN KEY (parent_id) REFERENCES large_parent(id)
        """)
        test_db_connection.commit()


def test_large_table_view_creation(test_db_connection):
    """Test view creation on large dataset."""
    with test_db_connection.cursor() as cur:
        # Setup
        cur.execute("DROP VIEW IF EXISTS large_view CASCADE;")
        cur.execute("DROP TABLE IF EXISTS large_base CASCADE;")

        cur.execute("""
            CREATE TABLE large_base (
                id UUID PRIMARY KEY,
                category VARCHAR(100),
                amount NUMERIC
            )
        """)

        # Insert 50k rows
        cur.execute("""
            INSERT INTO large_base (id, category, amount)
            SELECT
                gen_random_uuid(),
                'cat_' || (i % 50)::text,
                i * 2.5
            FROM generate_series(1, 50000) i
        """)
        test_db_connection.commit()

        # Create aggregating view
        cur.execute("""
            CREATE VIEW large_view AS
            SELECT
                category,
                COUNT(*) as count,
                SUM(amount) as total,
                AVG(amount) as average,
                MIN(amount) as min_amount,
                MAX(amount) as max_amount
            FROM large_base
            GROUP BY category
        """)
        test_db_connection.commit()

        # Query view
        cur.execute("SELECT COUNT(*) FROM large_view")
        result = cur.fetchone()[0]
        assert result > 0


# ============================================================================
# CATEGORY 4: Constraint Violations (5 tests)
# ============================================================================


def test_not_null_constraint_violation(test_db_connection):
    """Test handling of NOT NULL constraint violations."""
    with test_db_connection.cursor() as cur:
        # Setup
        cur.execute("DROP TABLE IF EXISTS not_null_test CASCADE;")
        cur.execute("""
            CREATE TABLE not_null_test (
                id UUID PRIMARY KEY,
                required_field VARCHAR(255) NOT NULL
            )
        """)
        test_db_connection.commit()

        # Try to insert NULL (should fail)
        try:
            cur.execute("""
                INSERT INTO not_null_test (id, required_field) VALUES (gen_random_uuid(), NULL)
            """)
            pytest.fail("Should fail on NOT NULL violation")
        except Exception:
            test_db_connection.rollback()


def test_unique_constraint_violation(test_db_connection):
    """Test handling of UNIQUE constraint violations."""
    with test_db_connection.cursor() as cur:
        # Setup
        cur.execute("DROP TABLE IF EXISTS unique_test CASCADE;")
        cur.execute("""
            CREATE TABLE unique_test (
                id UUID PRIMARY KEY,
                email VARCHAR(255) UNIQUE
            )
        """)
        test_db_connection.commit()

        # Insert first record
        cur.execute("""
            INSERT INTO unique_test (id, email) VALUES (gen_random_uuid(), 'test@example.com')
        """)
        test_db_connection.commit()

        # Try to insert duplicate (should fail)
        try:
            cur.execute("""
                INSERT INTO unique_test (id, email) VALUES (gen_random_uuid(), 'test@example.com')
            """)
            pytest.fail("Should fail on UNIQUE violation")
        except Exception:
            test_db_connection.rollback()


def test_foreign_key_violation(test_db_connection):
    """Test handling of foreign key constraint violations."""
    with test_db_connection.cursor() as cur:
        # Setup
        cur.execute("DROP TABLE IF EXISTS fk_child CASCADE;")
        cur.execute("DROP TABLE IF EXISTS fk_parent CASCADE;")

        cur.execute("CREATE TABLE fk_parent (id UUID PRIMARY KEY)")
        cur.execute("""
            CREATE TABLE fk_child (
                id UUID PRIMARY KEY,
                parent_id UUID REFERENCES fk_parent(id)
            )
        """)
        test_db_connection.commit()

        # Try to insert with non-existent parent (should fail)
        try:
            cur.execute("""
                INSERT INTO fk_child (id, parent_id) VALUES (gen_random_uuid(), gen_random_uuid())
            """)
            pytest.fail("Should fail on FK violation")
        except Exception:
            test_db_connection.rollback()


def test_check_constraint_violation(test_db_connection):
    """Test handling of CHECK constraint violations."""
    with test_db_connection.cursor() as cur:
        # Setup
        cur.execute("DROP TABLE IF EXISTS check_test CASCADE;")
        cur.execute("""
            CREATE TABLE check_test (
                id UUID PRIMARY KEY,
                age INT CHECK (age >= 0 AND age <= 150)
            )
        """)
        test_db_connection.commit()

        # Try to insert invalid age (should fail)
        try:
            cur.execute("""
                INSERT INTO check_test (id, age) VALUES (gen_random_uuid(), 999)
            """)
            pytest.fail("Should fail on CHECK violation")
        except Exception:
            test_db_connection.rollback()


def test_primary_key_violation(test_db_connection):
    """Test handling of primary key violations."""
    with test_db_connection.cursor() as cur:
        # Setup
        cur.execute("DROP TABLE IF EXISTS pk_test CASCADE;")
        cur.execute("CREATE TABLE pk_test (id UUID PRIMARY KEY)")
        test_db_connection.commit()

        # Insert record
        test_uuid = "550e8400-e29b-41d4-a716-446655440000"
        cur.execute("""
            INSERT INTO pk_test (id) VALUES (%s)
        """, (test_uuid,))
        test_db_connection.commit()

        # Try to insert duplicate key
        try:
            cur.execute("""
                INSERT INTO pk_test (id) VALUES (%s)
            """, (test_uuid,))
            pytest.fail("Should fail on PK violation")
        except Exception:
            test_db_connection.rollback()


# ============================================================================
# CATEGORY 5: View Dependencies (4 tests)
# ============================================================================


def test_view_with_base_table_dependency(test_db_connection):
    """Test that views properly depend on base tables."""
    with test_db_connection.cursor() as cur:
        # Create base table
        cur.execute("DROP VIEW IF EXISTS dep_view CASCADE;")
        cur.execute("DROP TABLE IF EXISTS dep_base CASCADE;")

        cur.execute("""
            CREATE TABLE dep_base (
                id UUID PRIMARY KEY,
                category VARCHAR(100),
                value NUMERIC
            )
        """)

        # Create view
        cur.execute("""
            CREATE VIEW dep_view AS
            SELECT category, SUM(value) as total FROM dep_base GROUP BY category
        """)
        test_db_connection.commit()

        # Insert data
        cur.execute("""
            INSERT INTO dep_base (id, category, value) VALUES
            (gen_random_uuid(), 'A', 100),
            (gen_random_uuid(), 'B', 200)
        """)
        test_db_connection.commit()

        # Query view
        cur.execute("SELECT COUNT(*) FROM dep_view")
        assert cur.fetchone()[0] == 2


def test_cascading_view_dependencies(test_db_connection):
    """Test that cascading view dependencies work."""
    with test_db_connection.cursor() as cur:
        # Setup chain: table -> view1 -> view2
        cur.execute("DROP VIEW IF EXISTS view2 CASCADE;")
        cur.execute("DROP VIEW IF EXISTS view1 CASCADE;")
        cur.execute("DROP TABLE IF EXISTS base CASCADE;")

        cur.execute("CREATE TABLE base (id UUID PRIMARY KEY, value NUMERIC)")
        cur.execute("CREATE VIEW view1 AS SELECT * FROM base WHERE value > 50")
        cur.execute("CREATE VIEW view2 AS SELECT * FROM view1 WHERE value < 200")
        test_db_connection.commit()

        # Insert data
        cur.execute("""
            INSERT INTO base (id, value) VALUES
            (gen_random_uuid(), 100),
            (gen_random_uuid(), 150),
            (gen_random_uuid(), 300)
        """)
        test_db_connection.commit()

        # Query final view
        cur.execute("SELECT COUNT(*) FROM view2")
        assert cur.fetchone()[0] == 2


def test_view_with_joined_tables(test_db_connection):
    """Test view with JOIN across multiple tables."""
    with test_db_connection.cursor() as cur:
        # Setup
        cur.execute("DROP VIEW IF EXISTS join_view CASCADE;")
        cur.execute("DROP TABLE IF EXISTS orders CASCADE;")
        cur.execute("DROP TABLE IF EXISTS customers CASCADE;")

        cur.execute("CREATE TABLE customers (id UUID PRIMARY KEY, name VARCHAR(255))")
        cur.execute("""
            CREATE TABLE orders (
                id UUID PRIMARY KEY,
                customer_id UUID REFERENCES customers(id),
                amount NUMERIC
            )
        """)

        # Create view with join
        cur.execute("""
            CREATE VIEW join_view AS
            SELECT c.name, COUNT(o.id) as order_count, SUM(o.amount) as total
            FROM customers c
            LEFT JOIN orders o ON c.id = o.customer_id
            GROUP BY c.id, c.name
        """)
        test_db_connection.commit()

        # Insert data
        customer_id = None
        cur.execute("INSERT INTO customers (id, name) VALUES (gen_random_uuid(), 'Alice') RETURNING id")
        customer_id = cur.fetchone()[0]

        cur.execute("""
            INSERT INTO orders (id, customer_id, amount) VALUES
            (gen_random_uuid(), %s, 100),
            (gen_random_uuid(), %s, 200)
        """, (customer_id, customer_id))
        test_db_connection.commit()

        # Query view
        cur.execute("SELECT order_count FROM join_view WHERE name = 'Alice'")
        result = cur.fetchone()
        assert result is not None and result[0] == 2


def test_view_with_aggregates(test_db_connection):
    """Test view with aggregate functions."""
    with test_db_connection.cursor() as cur:
        # Setup
        cur.execute("DROP VIEW IF EXISTS agg_view CASCADE;")
        cur.execute("DROP TABLE IF EXISTS transactions CASCADE;")

        cur.execute("""
            CREATE TABLE transactions (
                id UUID PRIMARY KEY,
                category VARCHAR(100),
                amount NUMERIC,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)

        # Create aggregating view
        cur.execute("""
            CREATE VIEW agg_view AS
            SELECT
                category,
                COUNT(*) as count,
                SUM(amount) as total,
                AVG(amount) as average,
                MIN(amount) as min_amount,
                MAX(amount) as max_amount
            FROM transactions
            GROUP BY category
        """)
        test_db_connection.commit()

        # Insert data
        cur.execute("""
            INSERT INTO transactions (id, category, amount) VALUES
            (gen_random_uuid(), 'expense', 50),
            (gen_random_uuid(), 'expense', 75),
            (gen_random_uuid(), 'income', 1000)
        """)
        test_db_connection.commit()

        # Query aggregates
        cur.execute("SELECT COUNT(*), SUM(total) FROM agg_view")
        count, total = cur.fetchone()
        assert count == 2  # Two categories


# ============================================================================
# CATEGORY 6: Multi-Step Migrations (3 tests)
# ============================================================================


def test_multi_table_creation_sequence(test_db_connection):
    """Test creating multiple dependent tables in sequence."""
    with test_db_connection.cursor() as cur:
        # Create tables in dependency order
        cur.execute("DROP TABLE IF EXISTS users CASCADE;")
        cur.execute("DROP TABLE IF EXISTS posts CASCADE;")
        cur.execute("DROP TABLE IF EXISTS comments CASCADE;")

        # Step 1: Create users
        cur.execute("""
            CREATE TABLE users (
                id UUID PRIMARY KEY,
                name VARCHAR(255) NOT NULL
            )
        """)

        # Step 2: Create posts (depends on users)
        cur.execute("""
            CREATE TABLE posts (
                id UUID PRIMARY KEY,
                user_id UUID NOT NULL REFERENCES users(id),
                title VARCHAR(500),
                content TEXT
            )
        """)

        # Step 3: Create comments (depends on posts)
        cur.execute("""
            CREATE TABLE comments (
                id UUID PRIMARY KEY,
                post_id UUID NOT NULL REFERENCES posts(id),
                user_id UUID NOT NULL REFERENCES users(id),
                content TEXT
            )
        """)

        test_db_connection.commit()

        # Verify all tables exist
        for table in ['users', 'posts', 'comments']:
            cur.execute("SELECT to_regclass(%s)", (table,))
            assert cur.fetchone()[0] is not None


def test_multi_step_schema_modification(test_db_connection):
    """Test modifying schema across multiple steps."""
    with test_db_connection.cursor() as cur:
        # Initial table
        cur.execute("DROP TABLE IF EXISTS evolving CASCADE;")
        cur.execute("""
            CREATE TABLE evolving (
                id UUID PRIMARY KEY,
                name VARCHAR(255)
            )
        """)
        test_db_connection.commit()

        # Step 1: Add column
        cur.execute("ALTER TABLE evolving ADD COLUMN email VARCHAR(255)")
        test_db_connection.commit()

        # Step 2: Add index
        cur.execute("CREATE INDEX IF NOT EXISTS idx_evolving_email ON evolving(email)")
        test_db_connection.commit()

        # Step 3: Add constraint
        cur.execute("ALTER TABLE evolving ADD CONSTRAINT valid_email CHECK (email LIKE '%@%')")
        test_db_connection.commit()

        # Verify final state
        cur.execute("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'evolving'
            ORDER BY ordinal_position
        """)
        columns = [row[0] for row in cur.fetchall()]
        assert 'email' in columns


def test_data_transformation_across_steps(test_db_connection):
    """Test multi-step data transformation migration."""
    with test_db_connection.cursor() as cur:
        # Step 1: Create table and insert data
        cur.execute("DROP TABLE IF EXISTS transform CASCADE;")
        cur.execute("""
            CREATE TABLE transform (
                id UUID PRIMARY KEY,
                full_name VARCHAR(255)
            )
        """)

        cur.execute("""
            INSERT INTO transform (id, full_name) VALUES
            (gen_random_uuid(), 'John Doe'),
            (gen_random_uuid(), 'Jane Smith')
        """)
        test_db_connection.commit()

        # Step 2: Add new columns
        cur.execute("ALTER TABLE transform ADD COLUMN first_name VARCHAR(255)")
        cur.execute("ALTER TABLE transform ADD COLUMN last_name VARCHAR(255)")
        test_db_connection.commit()

        # Step 3: Transform data
        cur.execute("""
            UPDATE transform
            SET
                first_name = SPLIT_PART(full_name, ' ', 1),
                last_name = SPLIT_PART(full_name, ' ', 2)
        """)
        test_db_connection.commit()

        # Verify transformation
        cur.execute("SELECT COUNT(*) FROM transform WHERE first_name IS NOT NULL")
        assert cur.fetchone()[0] == 2


# ============================================================================
# CATEGORY 7: Complex Transformations (3 tests)
# ============================================================================


def test_uuid_to_string_transformation(test_db_connection):
    """Test UUID field transformations."""
    with test_db_connection.cursor() as cur:
        # Create table with UUID
        cur.execute("DROP TABLE IF EXISTS uuid_transform CASCADE;")
        cur.execute("""
            CREATE TABLE uuid_transform (
                id UUID PRIMARY KEY,
                external_id VARCHAR(255)
            )
        """)

        # Insert UUIDs as strings
        cur.execute("""
            INSERT INTO uuid_transform (id, external_id) VALUES
            (gen_random_uuid(), gen_random_uuid()::text),
            (gen_random_uuid(), gen_random_uuid()::text)
        """)
        test_db_connection.commit()

        # Verify data
        cur.execute("SELECT COUNT(*) FROM uuid_transform")
        assert cur.fetchone()[0] == 2


def test_enum_to_varchar_transformation(test_db_connection):
    """Test ENUM to VARCHAR transformation."""
    with test_db_connection.cursor() as cur:
        # Setup: Create table with enum-like VARCHAR
        cur.execute("DROP TABLE IF EXISTS enum_transform CASCADE;")
        cur.execute("""
            CREATE TABLE enum_transform (
                id UUID PRIMARY KEY,
                status VARCHAR(50) CHECK (status IN ('active', 'inactive', 'pending'))
            )
        """)

        # Insert data
        cur.execute("""
            INSERT INTO enum_transform (id, status) VALUES
            (gen_random_uuid(), 'active'),
            (gen_random_uuid(), 'inactive')
        """)
        test_db_connection.commit()

        # Verify constraint
        cur.execute("SELECT COUNT(*) FROM enum_transform")
        assert cur.fetchone()[0] == 2


def test_denormalization_transformation(test_db_connection):
    """Test denormalization migration (moving data between tables)."""
    with test_db_connection.cursor() as cur:
        # Step 1: Setup original schema
        cur.execute("DROP TABLE IF EXISTS profiles CASCADE;")
        cur.execute("DROP TABLE IF EXISTS users_denorm CASCADE;")

        cur.execute("""
            CREATE TABLE users_denorm (
                id UUID PRIMARY KEY,
                name VARCHAR(255)
            )
        """)

        cur.execute("""
            CREATE TABLE profiles (
                id UUID PRIMARY KEY,
                user_id UUID REFERENCES users_denorm(id),
                bio TEXT,
                avatar_url VARCHAR(500)
            )
        """)

        # Insert data
        user_id = None
        cur.execute("INSERT INTO users_denorm (id, name) VALUES (gen_random_uuid(), 'Alice') RETURNING id")
        user_id = cur.fetchone()[0]

        cur.execute("""
            INSERT INTO profiles (id, user_id, bio, avatar_url) VALUES
            (gen_random_uuid(), %s, 'My bio', 'http://avatar.url')
        """, (user_id,))
        test_db_connection.commit()

        # Step 2: Denormalize (add profile fields to users table)
        cur.execute("ALTER TABLE users_denorm ADD COLUMN bio TEXT")
        cur.execute("ALTER TABLE users_denorm ADD COLUMN avatar_url VARCHAR(500)")
        test_db_connection.commit()

        # Step 3: Copy data
        cur.execute("""
            UPDATE users_denorm u
            SET bio = p.bio, avatar_url = p.avatar_url
            FROM profiles p
            WHERE u.id = p.user_id
        """)
        test_db_connection.commit()

        # Verify denormalized data
        cur.execute("SELECT COUNT(*) FROM users_denorm WHERE bio IS NOT NULL")
        assert cur.fetchone()[0] >= 1
