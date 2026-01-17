"""Load testing for Confiture PostgreSQL migrations.

Tests verify migration performance and safety with:
1. Large datasets (100k+ rows)
2. Bulk operations
3. Complex transformations
4. Concurrent scenarios
"""

import time


def test_create_large_table(test_db_connection):
    """Test creating table structure for large data."""
    with test_db_connection.cursor() as cur:
        cur.execute("DROP TABLE IF EXISTS load_test CASCADE;")
        cur.execute("""
            CREATE TABLE load_test (
                id UUID PRIMARY KEY,
                sequence_no BIGINT,
                category VARCHAR(100),
                value NUMERIC,
                data TEXT,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)
        test_db_connection.commit()


def test_bulk_insert_10k_rows(test_db_connection):
    """Test inserting 10k rows."""
    with test_db_connection.cursor() as cur:
        # Setup
        cur.execute("DROP TABLE IF EXISTS load_10k CASCADE;")
        cur.execute("""
            CREATE TABLE load_10k (
                id UUID PRIMARY KEY,
                sequence_no BIGINT,
                value NUMERIC
            )
        """)
        test_db_connection.commit()

        # Insert 10k rows
        start = time.time()
        cur.execute("""
            INSERT INTO load_10k (id, sequence_no, value)
            SELECT gen_random_uuid(), i, i * 1.5
            FROM generate_series(1, 10000) i
        """)
        test_db_connection.commit()
        duration = time.time() - start

        # Should complete in reasonable time
        assert duration < 30.0

        # Verify count
        cur.execute("SELECT COUNT(*) FROM load_10k")
        assert cur.fetchone()[0] == 10000


def test_bulk_insert_50k_rows(test_db_connection):
    """Test inserting 50k rows."""
    with test_db_connection.cursor() as cur:
        # Setup
        cur.execute("DROP TABLE IF EXISTS load_50k CASCADE;")
        cur.execute("""
            CREATE TABLE load_50k (
                id UUID PRIMARY KEY,
                sequence_no BIGINT,
                value NUMERIC
            )
        """)
        test_db_connection.commit()

        # Insert 50k rows
        start = time.time()
        cur.execute("""
            INSERT INTO load_50k (id, sequence_no, value)
            SELECT gen_random_uuid(), i, i * 1.5
            FROM generate_series(1, 50000) i
        """)
        test_db_connection.commit()
        time.time() - start

        # Verify
        cur.execute("SELECT COUNT(*) FROM load_50k")
        assert cur.fetchone()[0] == 50000


def test_index_creation_on_large_table(test_db_connection):
    """Test index creation on 50k row table."""
    with test_db_connection.cursor() as cur:
        # Setup with data
        cur.execute("DROP TABLE IF EXISTS load_idx CASCADE;")
        cur.execute("""
            CREATE TABLE load_idx (
                id UUID PRIMARY KEY,
                category VARCHAR(100),
                value NUMERIC
            )
        """)

        cur.execute("""
            INSERT INTO load_idx (id, category, value)
            SELECT gen_random_uuid(), 'cat_' || (i % 50)::text, i * 1.5
            FROM generate_series(1, 50000) i
        """)
        test_db_connection.commit()

        # Create index
        start = time.time()
        cur.execute("CREATE INDEX idx_load_category ON load_idx(category)")
        test_db_connection.commit()
        duration = time.time() - start

        assert duration < 30.0


def test_constraint_on_large_table(test_db_connection):
    """Test adding FK constraint to large table."""
    with test_db_connection.cursor() as cur:
        # Setup
        cur.execute("DROP TABLE IF EXISTS load_child CASCADE;")
        cur.execute("DROP TABLE IF EXISTS load_parent CASCADE;")

        cur.execute("CREATE TABLE load_parent (id UUID PRIMARY KEY)")
        cur.execute("""
            CREATE TABLE load_child (
                id UUID PRIMARY KEY,
                parent_id UUID,
                value NUMERIC
            )
        """)

        # Insert parent data
        cur.execute("""
            INSERT INTO load_parent (id)
            SELECT gen_random_uuid() FROM generate_series(1, 1000)
        """)

        # Insert child data (20k rows with FK refs)
        cur.execute("""
            INSERT INTO load_child (id, parent_id, value)
            SELECT
                gen_random_uuid(),
                (SELECT id FROM load_parent OFFSET random() * 999 LIMIT 1),
                i * 1.5
            FROM generate_series(1, 20000) i
        """)
        test_db_connection.commit()

        # Add constraint
        start = time.time()
        cur.execute("""
            ALTER TABLE load_child
            ADD CONSTRAINT fk_load_parent
            FOREIGN KEY (parent_id) REFERENCES load_parent(id)
        """)
        test_db_connection.commit()
        duration = time.time() - start

        assert duration < 30.0


def test_bulk_update_on_large_table(test_db_connection):
    """Test bulk update on 50k row table."""
    with test_db_connection.cursor() as cur:
        # Setup
        cur.execute("DROP TABLE IF EXISTS load_update CASCADE;")
        cur.execute("""
            CREATE TABLE load_update (
                id UUID PRIMARY KEY,
                sequence_no BIGINT,
                value NUMERIC,
                doubled NUMERIC
            )
        """)

        cur.execute("""
            INSERT INTO load_update (id, sequence_no, value, doubled)
            SELECT gen_random_uuid(), i, i * 1.5, 0
            FROM generate_series(1, 50000) i
        """)
        test_db_connection.commit()

        # Bulk update
        start = time.time()
        cur.execute("""
            UPDATE load_update SET doubled = value * 2
        """)
        test_db_connection.commit()
        time.time() - start

        # Verify update
        cur.execute("SELECT COUNT(*) FROM load_update WHERE doubled > 0")
        assert cur.fetchone()[0] == 50000


def test_bulk_delete_on_large_table(test_db_connection):
    """Test bulk delete on large table."""
    with test_db_connection.cursor() as cur:
        # Setup
        cur.execute("DROP TABLE IF EXISTS load_delete CASCADE;")
        cur.execute("""
            CREATE TABLE load_delete (
                id UUID PRIMARY KEY,
                sequence_no BIGINT,
                category VARCHAR(100)
            )
        """)

        cur.execute("""
            INSERT INTO load_delete (id, sequence_no, category)
            SELECT gen_random_uuid(), i, 'cat_' || (i % 10)::text
            FROM generate_series(1, 50000) i
        """)
        test_db_connection.commit()

        # Bulk delete (50% of rows)
        start = time.time()
        cur.execute("""
            DELETE FROM load_delete WHERE sequence_no > 25000
        """)
        test_db_connection.commit()
        time.time() - start

        # Verify delete
        cur.execute("SELECT COUNT(*) FROM load_delete")
        remaining = cur.fetchone()[0]
        assert remaining == 25000


def test_aggregation_on_large_table(test_db_connection):
    """Test aggregation query on large table."""
    with test_db_connection.cursor() as cur:
        # Setup
        cur.execute("DROP TABLE IF EXISTS load_agg CASCADE;")
        cur.execute("""
            CREATE TABLE load_agg (
                id UUID PRIMARY KEY,
                category VARCHAR(100),
                amount NUMERIC
            )
        """)

        cur.execute("""
            INSERT INTO load_agg (id, category, amount)
            SELECT
                gen_random_uuid(),
                'cat_' || (i % 100)::text,
                i * 2.5
            FROM generate_series(1, 100000) i
        """)
        test_db_connection.commit()

        # Aggregate query
        start = time.time()
        cur.execute("""
            SELECT category, COUNT(*), SUM(amount), AVG(amount)
            FROM load_agg
            GROUP BY category
            ORDER BY SUM(amount) DESC
            LIMIT 10
        """)
        results = cur.fetchall()
        duration = time.time() - start

        # Should complete quickly
        assert duration < 10.0
        assert len(results) > 0


def test_view_on_large_table(test_db_connection):
    """Test view creation and querying on large table."""
    with test_db_connection.cursor() as cur:
        # Setup
        cur.execute("DROP VIEW IF EXISTS load_view CASCADE;")
        cur.execute("DROP TABLE IF EXISTS load_view_base CASCADE;")

        cur.execute("""
            CREATE TABLE load_view_base (
                id UUID PRIMARY KEY,
                category VARCHAR(100),
                amount NUMERIC
            )
        """)

        # Insert 100k rows
        cur.execute("""
            INSERT INTO load_view_base (id, category, amount)
            SELECT
                gen_random_uuid(),
                'cat_' || (i % 100)::text,
                i * 2.5
            FROM generate_series(1, 100000) i
        """)
        test_db_connection.commit()

        # Create aggregating view
        cur.execute("""
            CREATE VIEW load_view AS
            SELECT
                category,
                COUNT(*) as count,
                SUM(amount) as total,
                AVG(amount) as average
            FROM load_view_base
            GROUP BY category
        """)
        test_db_connection.commit()

        # Query view
        start = time.time()
        cur.execute("""
            SELECT category, total FROM load_view
            WHERE total > 1000000
            ORDER BY total DESC
        """)
        cur.fetchall()
        duration = time.time() - start

        assert duration < 10.0


def test_join_on_large_tables(test_db_connection):
    """Test JOIN operation on large tables."""
    with test_db_connection.cursor() as cur:
        # Setup
        cur.execute("DROP TABLE IF EXISTS load_orders CASCADE;")
        cur.execute("DROP TABLE IF EXISTS load_customers CASCADE;")

        cur.execute("""
            CREATE TABLE load_customers (
                id UUID PRIMARY KEY,
                name VARCHAR(255)
            )
        """)

        cur.execute("""
            CREATE TABLE load_orders (
                id UUID PRIMARY KEY,
                customer_id UUID REFERENCES load_customers(id),
                amount NUMERIC
            )
        """)

        # Insert customers (1k)
        cur.execute("""
            INSERT INTO load_customers (id, name)
            SELECT gen_random_uuid(), 'customer_' || i
            FROM generate_series(1, 1000) i
        """)

        # Insert orders (50k)
        cur.execute("""
            INSERT INTO load_orders (id, customer_id, amount)
            SELECT
                gen_random_uuid(),
                (SELECT id FROM load_customers OFFSET random() * 999 LIMIT 1),
                random() * 1000
            FROM generate_series(1, 50000) i
        """)
        test_db_connection.commit()

        # JOIN query
        start = time.time()
        cur.execute("""
            SELECT c.name, COUNT(o.id) as order_count, SUM(o.amount) as total
            FROM load_customers c
            LEFT JOIN load_orders o ON c.id = o.customer_id
            GROUP BY c.id, c.name
            LIMIT 100
        """)
        cur.fetchall()
        duration = time.time() - start

        assert duration < 10.0


def test_transaction_with_many_operations(test_db_connection):
    """Test transaction with many individual operations."""
    with test_db_connection.cursor() as cur:
        # Setup
        cur.execute("DROP TABLE IF EXISTS load_txn CASCADE;")
        cur.execute("""
            CREATE TABLE load_txn (
                id UUID PRIMARY KEY,
                value NUMERIC
            )
        """)
        test_db_connection.commit()

        # Many operations in transaction
        start = time.time()
        for i in range(100):
            cur.execute("""
                INSERT INTO load_txn (id, value) VALUES (gen_random_uuid(), %s)
            """, (i * 1.5,))
        test_db_connection.commit()
        time.time() - start

        # Verify all inserted
        cur.execute("SELECT COUNT(*) FROM load_txn")
        assert cur.fetchone()[0] == 100


# Note: Complete load testing suite (11 tests) requires:
# - Extended performance metrics
# - Memory usage tracking
# - Index performance analysis
# - Constraint validation at scale
# This is a foundation for the full load testing suite.
