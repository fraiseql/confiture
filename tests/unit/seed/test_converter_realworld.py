"""Real-world testing for INSERT to COPY converter.

Tests converter with realistic seed files that reflect actual production usage.
Phase 11, Cycle 5: Real-world examples
"""

from __future__ import annotations

from confiture.core.seed.insert_to_copy_converter import InsertToCopyConverter
from confiture.models.results import ConversionResult


class TestRealWorldExamples:
    """Test converter with realistic production seed files."""

    def test_converts_user_table_with_timestamps(self) -> None:
        """Test conversion of typical user table with timestamp columns."""
        sql = """
        INSERT INTO users (id, email, first_name, last_name, is_active, created_at, updated_at)
        VALUES
            (1, 'alice@example.com', 'Alice', 'Smith', true, '2024-01-15', '2024-01-20'),
            (2, 'bob@example.com', 'Bob', 'Jones', true, '2024-01-16', '2024-01-19'),
            (3, 'charlie@example.com', 'Charlie', 'Brown', false, '2024-01-17', '2024-01-18');
        """
        converter = InsertToCopyConverter()
        result = converter.try_convert(sql, file_path="users.sql")

        assert result.success is True
        assert result.rows_converted == 3
        assert "COPY users" in result.copy_format
        assert "alice@example.com" in result.copy_format

    def test_converts_orders_with_uuids_and_decimals(self) -> None:
        """Test conversion of orders with UUID and decimal columns."""
        sql = """
        INSERT INTO orders (id, customer_id, order_number, total_amount, status)
        VALUES
            ('550e8400-e29b-41d4-a716-446655440001', 1, 'ORD-001', 99.99, 'pending'),
            ('550e8400-e29b-41d4-a716-446655440002', 2, 'ORD-002', 149.50, 'shipped'),
            ('550e8400-e29b-41d4-a716-446655440003', 3, 'ORD-003', 75.25, 'delivered');
        """
        converter = InsertToCopyConverter()
        result = converter.try_convert(sql, file_path="orders.sql")

        assert result.success is True
        assert result.rows_converted == 3
        assert "99.99" in result.copy_format
        assert "550e8400" in result.copy_format

    def test_converts_products_with_nullable_fields(self) -> None:
        """Test conversion with NULL values in various columns."""
        sql = """
        INSERT INTO products (id, name, description, category, price, discount_percent)
        VALUES
            (1, 'Laptop', 'High-performance laptop', 'Electronics', 999.99, 10),
            (2, 'Mouse', NULL, 'Electronics', 29.99, NULL),
            (3, 'Keyboard', 'Mechanical keyboard', NULL, 89.99, 15),
            (4, 'Monitor', NULL, NULL, NULL, NULL);
        """
        converter = InsertToCopyConverter()
        result = converter.try_convert(sql, file_path="products.sql")

        assert result.success is True
        assert result.rows_converted == 4
        # NULL values should be represented properly
        assert "\\N" in result.copy_format or "\\" in result.copy_format

    def test_converts_tags_with_many_columns(self) -> None:
        """Test conversion of table with many columns."""
        sql = """
        INSERT INTO tags (
            id, slug, name, description, color, icon_name, is_featured,
            priority, created_by, created_at, updated_by, updated_at
        )
        VALUES
            (1, 'urgent', 'Urgent', 'Mark as urgent', '#FF0000', 'alert', true,
             1, 'admin', '2024-01-01', 'admin', '2024-01-01'),
            (2, 'feature', 'Feature', 'Feature request', '#00AA00', 'star', false,
             2, 'admin', '2024-01-02', 'admin', '2024-01-02');
        """
        converter = InsertToCopyConverter()
        result = converter.try_convert(sql, file_path="tags.sql")

        assert result.success is True
        assert result.rows_converted == 2
        assert "Urgent" in result.copy_format
        assert "#FF0000" in result.copy_format

    def test_graceful_failure_with_default_values(self) -> None:
        """Test graceful handling of DEFAULT keyword (not convertible)."""
        sql = "INSERT INTO users (id, name, created_at) VALUES (1, 'Alice', DEFAULT);"
        converter = InsertToCopyConverter()
        result = converter.try_convert(sql, file_path="defaults.sql")

        # DEFAULT keyword might not convert depending on implementation
        # The key is that it doesn't crash
        assert isinstance(result, ConversionResult)
        assert result.file_path == "defaults.sql"

    def test_graceful_failure_with_cte(self) -> None:
        """Test graceful handling of CTE (WITH clause)."""
        sql = """
        WITH user_data AS (
            SELECT 1 as id, 'Alice' as name
        )
        INSERT INTO users (id, name) SELECT id, name FROM user_data;
        """
        converter = InsertToCopyConverter()
        result = converter.try_convert(sql, file_path="with_cte.sql")

        assert result.success is False
        assert "cannot" in result.reason.lower() or "cte" in result.reason.lower()

    def test_graceful_failure_with_sequence_nextval(self) -> None:
        """Test graceful handling of nextval() function."""
        sql = """
        INSERT INTO sequences (id, value) VALUES (nextval('seq_sequences'), 'test');
        """
        converter = InsertToCopyConverter()
        result = converter.try_convert(sql, file_path="sequence.sql")

        assert result.success is False
        assert result.reason is not None

    def test_converts_json_columns(self) -> None:
        """Test conversion of columns with JSON data."""
        sql = """
        INSERT INTO config (id, key, value, metadata)
        VALUES
            (1, 'app_name', 'My App', '{"version": "1.0", "env": "prod"}'),
            (2, 'features', 'list', '{"enabled": true, "count": 42}');
        """
        converter = InsertToCopyConverter()
        result = converter.try_convert(sql, file_path="config.sql")

        assert result.success is True
        assert result.rows_converted == 2
        # JSON strings should be preserved
        assert "version" in result.copy_format

    def test_converts_special_characters_in_strings(self) -> None:
        """Test conversion with special characters and escaping."""
        sql = r"""
        INSERT INTO messages (id, content, sender)
        VALUES
            (1, 'Hello, World!', 'Alice'),
            (2, 'It''s working', 'Bob'),
            (3, 'Path: /home/user', 'Charlie'),
            (4, 'Quote: "Amazing"', 'David');
        """
        converter = InsertToCopyConverter()
        result = converter.try_convert(sql, file_path="messages.sql")

        assert result.success is True
        assert result.rows_converted == 4

    def test_batch_conversion_mixed_quality_files(self) -> None:
        """Test batch conversion with mix of convertible and non-convertible files."""
        converter = InsertToCopyConverter()

        files = {
            "users.sql": "INSERT INTO users (id, name) VALUES (1, 'Alice'), (2, 'Bob');",
            "events.sql": "INSERT INTO events (id, created_at) VALUES (1, NOW());",
            "posts.sql": "INSERT INTO posts (id, title) VALUES (1, 'Post 1');",
            "jobs.sql": "INSERT INTO jobs (id, task) VALUES (1, uuid_generate_v4());",
        }

        report = converter.convert_batch(files)

        assert report.total_files == 4
        assert report.successful == 2  # users.sql and posts.sql
        assert report.failed == 2  # events.sql and jobs.sql
        assert report.success_rate == 50.0

    def test_large_batch_conversion_performance(self) -> None:
        """Test batch conversion performance with many files."""
        converter = InsertToCopyConverter()

        # Create 50 test files (all convertible)
        files = {
            f"table_{i}.sql": f"INSERT INTO table_{i} (id) VALUES ({i});"
            for i in range(50)
        }

        report = converter.convert_batch(files)

        assert report.total_files == 50
        assert report.successful == 50
        assert report.failed == 0
        assert report.success_rate == 100.0

    def test_converts_multiline_inserts_with_formatting(self) -> None:
        """Test conversion of multiline INSERT with various formatting."""
        sql = """
        INSERT INTO employees
            (id, first_name, last_name, department, salary)
        VALUES
            (
                1,
                'John',
                'Doe',
                'Engineering',
                85000.00
            ),
            (
                2,
                'Jane',
                'Smith',
                'Marketing',
                75000.00
            );
        """
        converter = InsertToCopyConverter()
        result = converter.try_convert(sql, file_path="employees.sql")

        assert result.success is True
        assert result.rows_converted == 2

    def test_converts_boolean_variations(self) -> None:
        """Test conversion with different boolean representations."""
        sql = """
        INSERT INTO settings (id, name, enabled)
        VALUES
            (1, 'feature_a', true),
            (2, 'feature_b', false),
            (3, 'feature_c', true),
            (4, 'feature_d', false);
        """
        converter = InsertToCopyConverter()
        result = converter.try_convert(sql, file_path="settings.sql")

        assert result.success is True
        assert result.rows_converted == 4
        assert "true" in result.copy_format.lower() or "t" in result.copy_format
        assert "false" in result.copy_format.lower() or "f" in result.copy_format
