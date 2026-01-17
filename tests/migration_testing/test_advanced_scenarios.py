"""Advanced scenario tests for Confiture PostgreSQL migrations.

Tests verify complex real-world migration patterns:
1. Multi-table migrations
2. Complex constraint scenarios
3. Data transformations
4. Rollback safety
5. Advanced dependencies
"""


def test_multi_table_migration_with_dependencies(test_db_connection):
    """Test creating multiple dependent tables."""
    with test_db_connection.cursor() as cur:
        # Drop existing
        cur.execute("DROP TABLE IF EXISTS adv_comments CASCADE;")
        cur.execute("DROP TABLE IF EXISTS adv_posts CASCADE;")
        cur.execute("DROP TABLE IF EXISTS adv_users CASCADE;")

        # Create users
        cur.execute("""
            CREATE TABLE adv_users (
                id UUID PRIMARY KEY,
                username VARCHAR(255) UNIQUE NOT NULL,
                email VARCHAR(255) UNIQUE NOT NULL,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)

        # Create posts (depends on users)
        cur.execute("""
            CREATE TABLE adv_posts (
                id UUID PRIMARY KEY,
                user_id UUID NOT NULL REFERENCES adv_users(id) ON DELETE CASCADE,
                title VARCHAR(500) NOT NULL,
                content TEXT,
                published_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)

        # Create comments (depends on posts and users)
        cur.execute("""
            CREATE TABLE adv_comments (
                id UUID PRIMARY KEY,
                post_id UUID NOT NULL REFERENCES adv_posts(id) ON DELETE CASCADE,
                author_id UUID NOT NULL REFERENCES adv_users(id) ON DELETE CASCADE,
                content TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)

        test_db_connection.commit()

        # Verify all tables exist
        for table in ["adv_users", "adv_posts", "adv_comments"]:
            cur.execute("SELECT to_regclass(%s)", (table,))
            assert cur.fetchone()[0] is not None


def test_complex_constraint_scenario(test_db_connection):
    """Test scenario with multiple constraint types."""
    with test_db_connection.cursor() as cur:
        # Drop existing
        cur.execute("DROP TABLE IF EXISTS adv_orders CASCADE;")
        cur.execute("DROP TABLE IF EXISTS adv_customers CASCADE;")
        cur.execute("DROP TABLE IF EXISTS adv_products CASCADE;")

        # Create tables with various constraints
        cur.execute("""
            CREATE TABLE adv_products (
                id UUID PRIMARY KEY,
                name VARCHAR(255) NOT NULL UNIQUE,
                price NUMERIC NOT NULL CHECK (price > 0),
                stock_quantity INT NOT NULL CHECK (stock_quantity >= 0)
            )
        """)

        cur.execute("""
            CREATE TABLE adv_customers (
                id UUID PRIMARY KEY,
                name VARCHAR(255) NOT NULL,
                email VARCHAR(255) UNIQUE,
                age INT CHECK (age >= 18),
                registration_date TIMESTAMP DEFAULT NOW()
            )
        """)

        cur.execute("""
            CREATE TABLE adv_orders (
                id UUID PRIMARY KEY,
                customer_id UUID NOT NULL REFERENCES adv_customers(id),
                product_id UUID NOT NULL REFERENCES adv_products(id),
                quantity INT NOT NULL CHECK (quantity > 0),
                order_date TIMESTAMP DEFAULT NOW(),
                CONSTRAINT unique_customer_product UNIQUE (customer_id, product_id)
            )
        """)

        test_db_connection.commit()

        # Verify constraints
        cur.execute("""
            SELECT COUNT(*) FROM information_schema.table_constraints
            WHERE table_name = 'adv_orders'
        """)
        constraint_count = cur.fetchone()[0]
        assert constraint_count >= 3  # PK + FK + unique


def test_data_transformation_migration(test_db_connection):
    """Test multi-step data transformation."""
    with test_db_connection.cursor() as cur:
        # Step 1: Create original schema
        cur.execute("DROP TABLE IF EXISTS adv_transform CASCADE;")
        cur.execute("""
            CREATE TABLE adv_transform (
                id UUID PRIMARY KEY,
                full_name VARCHAR(500),
                date_of_birth VARCHAR(10)
            )
        """)

        # Insert test data
        cur.execute("""
            INSERT INTO adv_transform (id, full_name, date_of_birth) VALUES
            (gen_random_uuid(), 'John Michael Doe', '1990-05-15'),
            (gen_random_uuid(), 'Jane Elizabeth Smith', '1992-08-22')
        """)
        test_db_connection.commit()

        # Step 2: Add new columns
        cur.execute("ALTER TABLE adv_transform ADD COLUMN first_name VARCHAR(255)")
        cur.execute("ALTER TABLE adv_transform ADD COLUMN middle_name VARCHAR(255)")
        cur.execute("ALTER TABLE adv_transform ADD COLUMN last_name VARCHAR(255)")
        cur.execute("ALTER TABLE adv_transform ADD COLUMN dob DATE")
        test_db_connection.commit()

        # Step 3: Transform data
        # Note: PostgreSQL SPLIT_PART doesn't support negative indices, so we use array approach
        cur.execute("""
            UPDATE adv_transform
            SET
                first_name = (STRING_TO_ARRAY(full_name, ' '))[1],
                last_name = (STRING_TO_ARRAY(full_name, ' '))[ARRAY_LENGTH(STRING_TO_ARRAY(full_name, ' '), 1)],
                dob = TO_DATE(date_of_birth, 'YYYY-MM-DD')
        """)
        test_db_connection.commit()

        # Verify transformation
        cur.execute("SELECT first_name, last_name FROM adv_transform WHERE first_name = 'John'")
        result = cur.fetchone()
        assert result is not None
        assert result[0] == "John"
        assert result[1] == "Doe"


def test_denormalization_migration(test_db_connection):
    """Test schema denormalization for performance."""
    with test_db_connection.cursor() as cur:
        # Original normalized schema
        cur.execute("DROP TABLE IF EXISTS adv_profiles CASCADE;")
        cur.execute("DROP TABLE IF EXISTS adv_denorm_users CASCADE;")

        cur.execute("""
            CREATE TABLE adv_denorm_users (
                id UUID PRIMARY KEY,
                name VARCHAR(255)
            )
        """)

        cur.execute("""
            CREATE TABLE adv_profiles (
                id UUID PRIMARY KEY,
                user_id UUID UNIQUE REFERENCES adv_denorm_users(id),
                bio TEXT,
                avatar_url VARCHAR(500),
                website VARCHAR(255)
            )
        """)

        # Insert data
        user_id = None
        cur.execute("""
            INSERT INTO adv_denorm_users (id, name) VALUES (gen_random_uuid(), 'Alice')
            RETURNING id
        """)
        user_id = cur.fetchone()[0]

        cur.execute(
            """
            INSERT INTO adv_profiles (id, user_id, bio, avatar_url, website) VALUES
            (gen_random_uuid(), %s, 'Software Engineer', 'http://avatar.jpg', 'example.com')
        """,
            (user_id,),
        )
        test_db_connection.commit()

        # Denormalization: Add profile fields to users
        cur.execute("ALTER TABLE adv_denorm_users ADD COLUMN bio TEXT")
        cur.execute("ALTER TABLE adv_denorm_users ADD COLUMN avatar_url VARCHAR(500)")
        cur.execute("ALTER TABLE adv_denorm_users ADD COLUMN website VARCHAR(255)")
        test_db_connection.commit()

        # Copy data
        cur.execute("""
            UPDATE adv_denorm_users u
            SET bio = p.bio, avatar_url = p.avatar_url, website = p.website
            FROM adv_profiles p
            WHERE u.id = p.user_id
        """)
        test_db_connection.commit()

        # Verify denormalization
        cur.execute("SELECT bio FROM adv_denorm_users WHERE name = 'Alice'")
        result = cur.fetchone()
        assert result is not None
        assert result[0] == "Software Engineer"


def test_versioned_schema_migration(test_db_connection):
    """Test schema versioning and evolution."""
    with test_db_connection.cursor() as cur:
        # Create versioned table
        cur.execute("DROP TABLE IF EXISTS adv_versioned CASCADE;")
        cur.execute("""
            CREATE TABLE adv_versioned (
                id UUID PRIMARY KEY,
                data JSONB,
                schema_version INT DEFAULT 1,
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW()
            )
        """)
        test_db_connection.commit()

        # Insert v1 data
        cur.execute("""
            INSERT INTO adv_versioned (id, data, schema_version) VALUES
            (gen_random_uuid(), '{"name": "Alice", "age": 30}'::jsonb, 1)
        """)
        test_db_connection.commit()

        # Add versioning columns
        cur.execute("ALTER TABLE adv_versioned ADD COLUMN if not exists email VARCHAR(255)")
        test_db_connection.commit()

        # Update to v2
        cur.execute("""
            UPDATE adv_versioned
            SET schema_version = 2, data = data || '{"email": "alice@example.com"}'::jsonb
            WHERE schema_version = 1
        """)
        test_db_connection.commit()


def test_partitioning_migration(test_db_connection):
    """Test time-based or value-based partitioning."""
    with test_db_connection.cursor() as cur:
        # Create main partitioned table
        # Note: Primary key must include partition key in PostgreSQL
        cur.execute("DROP TABLE IF EXISTS adv_events CASCADE;")
        cur.execute("""
            CREATE TABLE adv_events (
                id UUID,
                event_type VARCHAR(100),
                event_date DATE NOT NULL,
                data JSONB,
                created_at TIMESTAMP DEFAULT NOW(),
                PRIMARY KEY (id, event_date)
            ) PARTITION BY RANGE (event_date)
        """)

        # Create partitions for different date ranges
        cur.execute("""
            CREATE TABLE adv_events_2025_01 PARTITION OF adv_events
            FOR VALUES FROM ('2025-01-01') TO ('2025-02-01')
        """)

        cur.execute("""
            CREATE TABLE adv_events_2025_02 PARTITION OF adv_events
            FOR VALUES FROM ('2025-02-01') TO ('2025-03-01')
        """)

        test_db_connection.commit()


def test_indexing_strategy_migration(test_db_connection):
    """Test comprehensive indexing strategy."""
    with test_db_connection.cursor() as cur:
        # Create table
        cur.execute("DROP TABLE IF EXISTS adv_indexed CASCADE;")
        cur.execute("""
            CREATE TABLE adv_indexed (
                id UUID PRIMARY KEY,
                user_id UUID,
                status VARCHAR(50),
                created_at TIMESTAMP,
                amount NUMERIC,
                category VARCHAR(100)
            )
        """)

        # Add various indices
        cur.execute("CREATE INDEX idx_user_id ON adv_indexed(user_id)")
        cur.execute("CREATE INDEX idx_status ON adv_indexed(status)")
        cur.execute("CREATE INDEX idx_created_at ON adv_indexed(created_at DESC)")
        cur.execute("CREATE INDEX idx_composite ON adv_indexed(user_id, status, created_at DESC)")
        cur.execute(
            "CREATE INDEX idx_partial ON adv_indexed(user_id, amount) WHERE status = 'active'"
        )

        test_db_connection.commit()

        # Verify indices
        cur.execute("""
            SELECT COUNT(*) FROM pg_indexes
            WHERE tablename = 'adv_indexed'
        """)
        index_count = cur.fetchone()[0]
        assert index_count >= 5


def test_trigger_and_function_migration(test_db_connection):
    """Test migration with triggers and functions."""
    with test_db_connection.cursor() as cur:
        # Create audit table
        cur.execute("DROP TABLE IF EXISTS adv_audit CASCADE;")
        cur.execute("DROP TABLE IF EXISTS adv_data CASCADE;")

        cur.execute("""
            CREATE TABLE adv_data (
                id UUID PRIMARY KEY,
                name VARCHAR(255),
                updated_at TIMESTAMP DEFAULT NOW()
            )
        """)

        cur.execute("""
            CREATE TABLE adv_audit (
                id UUID PRIMARY KEY,
                data_id UUID REFERENCES adv_data(id),
                action VARCHAR(50),
                old_values JSONB,
                new_values JSONB,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)

        # Create audit function
        cur.execute("""
            CREATE OR REPLACE FUNCTION adv_audit_trigger()
            RETURNS TRIGGER AS $$
            BEGIN
                INSERT INTO adv_audit (id, data_id, action, new_values)
                VALUES (gen_random_uuid(), NEW.id, 'UPDATE', row_to_json(NEW));
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;
        """)

        # Create trigger
        cur.execute("""
            CREATE TRIGGER adv_audit_update
            AFTER UPDATE ON adv_data
            FOR EACH ROW EXECUTE FUNCTION adv_audit_trigger();
        """)

        test_db_connection.commit()

        # Test trigger
        data_id = None
        cur.execute(
            "INSERT INTO adv_data (id, name) VALUES (gen_random_uuid(), 'Initial') RETURNING id"
        )
        data_id = cur.fetchone()[0]
        test_db_connection.commit()

        # Update to trigger audit
        cur.execute("UPDATE adv_data SET name = 'Updated' WHERE id = %s", (data_id,))
        test_db_connection.commit()

        # Verify audit
        cur.execute("SELECT COUNT(*) FROM adv_audit WHERE data_id = %s", (data_id,))
        audit_count = cur.fetchone()[0]
        assert audit_count >= 1


def test_materialized_view_migration(test_db_connection):
    """Test materialized view creation for performance."""
    with test_db_connection.cursor() as cur:
        # Setup source data
        cur.execute("DROP MATERIALIZED VIEW IF EXISTS adv_mat_view CASCADE;")
        cur.execute("DROP TABLE IF EXISTS adv_raw_data CASCADE;")

        cur.execute("""
            CREATE TABLE adv_raw_data (
                id UUID PRIMARY KEY,
                category VARCHAR(100),
                amount NUMERIC,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)

        # Insert sample data
        cur.execute("""
            INSERT INTO adv_raw_data (id, category, amount) VALUES
            (gen_random_uuid(), 'A', 100),
            (gen_random_uuid(), 'A', 150),
            (gen_random_uuid(), 'B', 200),
            (gen_random_uuid(), 'B', 250)
        """)
        test_db_connection.commit()

        # Create materialized view
        cur.execute("""
            CREATE MATERIALIZED VIEW adv_mat_view AS
            SELECT
                category,
                COUNT(*) as count,
                SUM(amount) as total,
                AVG(amount) as average
            FROM adv_raw_data
            GROUP BY category
        """)

        test_db_connection.commit()

        # Query materialized view
        cur.execute("SELECT COUNT(*) FROM adv_mat_view")
        result = cur.fetchone()[0]
        assert result == 2


def test_schema_extension_migration(test_db_connection):
    """Test adding schema extensions and custom types."""
    with test_db_connection.cursor() as cur:
        # Enable extensions
        cur.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')
        cur.execute('CREATE EXTENSION IF NOT EXISTS "pg_trgm"')
        test_db_connection.commit()

        # Create custom type
        cur.execute("DROP TYPE IF EXISTS adv_status CASCADE")
        cur.execute("""
            CREATE TYPE adv_status AS ENUM ('active', 'inactive', 'pending', 'deleted')
        """)
        test_db_connection.commit()

        # Create table using custom type
        cur.execute("DROP TABLE IF EXISTS adv_with_custom_type CASCADE;")
        cur.execute("""
            CREATE TABLE adv_with_custom_type (
                id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
                status adv_status DEFAULT 'pending'
            )
        """)

        test_db_connection.commit()


# Note: Complete advanced scenarios suite (14 tests) requires:
# - Extended data transformation scenarios
# - Complete trigger/function implementations
# - Real-world migration patterns
# - Rollback verification for complex scenarios
# This is a foundation for the full advanced scenarios suite.
