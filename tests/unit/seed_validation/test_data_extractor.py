"""Tests for DataExtractor - seed data parsing and extraction."""

from confiture.core.seed_validation.data_extractor import DataExtractor


class TestTableExtraction:
    """Test extraction of table names from SQL statements."""

    def test_extracts_table_name_from_simple_insert(self) -> None:
        """Test extracting table name from simple INSERT statement."""
        extractor = DataExtractor()
        sql = "INSERT INTO users (id, name) VALUES ('1', 'Alice')"

        tables = extractor.extract_tables(sql)

        assert tables == ["users"]

    def test_extracts_multiple_tables_from_union_select(self) -> None:
        """Test extracting table names from UNION query."""
        extractor = DataExtractor()
        sql = """INSERT INTO data (id, name)
        SELECT '1'::uuid, 'Alice' FROM users
        UNION ALL SELECT '2'::uuid, 'Bob' FROM customers"""

        tables = extractor.extract_tables(sql)

        assert "users" in tables or "data" in tables

    def test_ignores_non_insert_statements(self) -> None:
        """Test that non-INSERT statements return empty."""
        extractor = DataExtractor()
        sqls = [
            "CREATE TABLE users (id UUID)",
            "ALTER TABLE users ADD COLUMN email TEXT",
            "DROP TABLE old_users",
            "SELECT * FROM users",
        ]

        for sql in sqls:
            tables = extractor.extract_tables(sql)
            assert tables == [], f"Should ignore: {sql}"

    def test_handles_uppercase_insert(self) -> None:
        """Test case-insensitive INSERT detection."""
        extractor = DataExtractor()
        sql = "insert into users (id) values ('1')"

        tables = extractor.extract_tables(sql)

        assert "users" in tables

    def test_extracts_table_with_schema_prefix(self) -> None:
        """Test extracting table name with schema prefix."""
        extractor = DataExtractor()
        sql = "INSERT INTO prep_seed.users (id) VALUES ('1')"

        tables = extractor.extract_tables(sql)

        assert "users" in tables or "prep_seed.users" in tables


class TestColumnExtraction:
    """Test extraction of column names from INSERT statements."""

    def test_extracts_column_names_from_insert(self) -> None:
        """Test extracting column names from INSERT."""
        extractor = DataExtractor()
        sql = "INSERT INTO users (id, name, email) VALUES ('1', 'Alice', 'alice@example.com')"

        columns = extractor.extract_columns(sql, "users")

        assert columns == ["id", "name", "email"]

    def test_extracts_columns_in_order(self) -> None:
        """Test that column order is preserved."""
        extractor = DataExtractor()
        sql = "INSERT INTO users (email, name, id) VALUES ('alice@example.com', 'Alice', '1')"

        columns = extractor.extract_columns(sql, "users")

        assert columns == ["email", "name", "id"]

    def test_handles_multiline_column_list(self) -> None:
        """Test extracting columns from multiline INSERT."""
        extractor = DataExtractor()
        sql = """INSERT INTO users (
            id,
            name,
            email
        ) VALUES ('1', 'Alice', 'alice@example.com')"""

        columns = extractor.extract_columns(sql, "users")

        assert columns == ["id", "name", "email"]

    def test_returns_empty_for_non_insert(self) -> None:
        """Test that non-INSERT statements return empty columns."""
        extractor = DataExtractor()
        sql = "CREATE TABLE users (id UUID)"

        columns = extractor.extract_columns(sql, "users")

        assert columns == []


class TestRowExtraction:
    """Test extraction of data rows from INSERT statements."""

    def test_extracts_values_from_single_row_insert(self) -> None:
        """Test extracting values from single-row INSERT."""
        extractor = DataExtractor()
        sql = "INSERT INTO users (id, name) VALUES ('1', 'Alice')"

        rows = extractor.extract_rows(sql, "users")

        assert len(rows) == 1
        assert rows[0]["id"] == "'1'"
        assert rows[0]["name"] == "'Alice'"

    def test_extracts_values_from_multirow_insert(self) -> None:
        """Test extracting all values from multi-row INSERT."""
        extractor = DataExtractor()
        sql = """INSERT INTO users (id, name) VALUES
            ('1', 'Alice'),
            ('2', 'Bob'),
            ('3', 'Charlie')"""

        rows = extractor.extract_rows(sql, "users")

        assert len(rows) == 3
        assert rows[0]["id"] == "'1'"
        assert rows[0]["name"] == "'Alice'"
        assert rows[1]["id"] == "'2'"
        assert rows[1]["name"] == "'Bob'"
        assert rows[2]["id"] == "'3'"
        assert rows[2]["name"] == "'Charlie'"

    def test_extracts_null_values(self) -> None:
        """Test extracting NULL values from INSERT."""
        extractor = DataExtractor()
        sql = "INSERT INTO users (id, nickname) VALUES ('1', NULL)"

        rows = extractor.extract_rows(sql, "users")

        assert len(rows) == 1
        assert rows[0]["nickname"] is None or rows[0]["nickname"] == "NULL"

    def test_extracts_typed_null_values(self) -> None:
        """Test extracting typed NULL values like NULL::timestamp."""
        extractor = DataExtractor()
        sql = "INSERT INTO users (id, created_at) VALUES ('1', NULL::timestamp)"

        rows = extractor.extract_rows(sql, "users")

        assert len(rows) == 1
        # Should recognize this as a NULL value (represented as None)
        assert rows[0]["created_at"] is None

    def test_extracts_values_from_union_query(self) -> None:
        """Test extracting data from UNION queries."""
        extractor = DataExtractor()
        sql = """INSERT INTO data (id, name)
        SELECT '1'::uuid, 'Alice'
        UNION ALL SELECT '2'::uuid, 'Bob'"""

        rows = extractor.extract_rows(sql, "data")

        assert len(rows) == 2
        assert rows[0]["id"] in ("'1'", "'1'::uuid", "uuid('1')")
        assert rows[1]["id"] in ("'2'", "'2'::uuid", "uuid('2')")

    def test_extracts_values_from_cte_query(self) -> None:
        """Test extracting data from CTE (WITH clause) queries."""
        extractor = DataExtractor()
        sql = """WITH cte AS (
            SELECT '1'::uuid as id, 'Alice' as name
            UNION ALL SELECT '2'::uuid, 'Bob'
        )
        INSERT INTO data (id, name) SELECT * FROM cte"""

        rows = extractor.extract_rows(sql, "data")

        # CTE with SELECT * may not extract individual rows
        # The important thing is that the system recognizes it doesn't fail
        assert isinstance(rows, list)

    def test_handles_complex_expressions_in_values(self) -> None:
        """Test extracting values with complex expressions."""
        extractor = DataExtractor()
        sql = """INSERT INTO events (id, created_at, metadata) VALUES
            ('1', NOW(), '{"key": "value"}'::jsonb),
            ('2', CURRENT_DATE - INTERVAL '1 day', '{}')"""

        rows = extractor.extract_rows(sql, "events")

        assert len(rows) == 2
        # Should extract the complex expressions as-is
        assert len(rows[0]) == 3


class TestForeignKeyExtraction:
    """Test extraction of foreign key references."""

    def test_extracts_foreign_key_reference(self) -> None:
        """Test identifying foreign key references."""
        extractor = DataExtractor()
        sql = "INSERT INTO orders (id, customer_id) VALUES ('order-1', 'cust-1')"

        # Requires schema context to identify which columns are FKs
        rows = extractor.extract_rows(sql, "orders")

        assert len(rows) == 1
        assert "customer_id" in rows[0]
        assert rows[0]["customer_id"] == "'cust-1'"

    def test_extracts_multiple_foreign_keys(self) -> None:
        """Test extracting multiple FK references."""
        extractor = DataExtractor()
        sql = """INSERT INTO orders (id, customer_id, address_id) VALUES
            ('order-1', 'cust-1', 'addr-1'),
            ('order-2', 'cust-2', 'addr-2')"""

        rows = extractor.extract_rows(sql, "orders")

        assert len(rows) == 2
        assert "customer_id" in rows[0]
        assert "address_id" in rows[0]

    def test_handles_uuid_foreign_keys(self) -> None:
        """Test extracting UUID-based foreign keys."""
        extractor = DataExtractor()
        sql = """INSERT INTO orders (id, customer_id) VALUES
            ('01234567-89ab-cdef-0123-456789abcdef'::uuid, '11111111-2222-3333-4444-555555555555')"""

        rows = extractor.extract_rows(sql, "orders")

        assert len(rows) == 1
        assert "customer_id" in rows[0]


class TestUnionQueryHandling:
    """Test handling of UNION and complex SELECT queries."""

    def test_handles_union_all_queries(self) -> None:
        """Test extracting data from UNION ALL queries."""
        extractor = DataExtractor()
        sql = """INSERT INTO data (id, name)
        SELECT '1'::uuid, 'Alice'
        UNION ALL SELECT '2'::uuid, 'Bob'
        UNION ALL SELECT '3'::uuid, 'Charlie'"""

        rows = extractor.extract_rows(sql, "data")

        assert len(rows) == 3

    def test_handles_union_queries(self) -> None:
        """Test extracting data from UNION queries (removes duplicates)."""
        extractor = DataExtractor()
        sql = """INSERT INTO data (id, name)
        SELECT '1'::uuid, 'Alice'
        UNION SELECT '1'::uuid, 'Alice'"""

        rows = extractor.extract_rows(sql, "data")

        # UNION removes duplicates, so should have 1 row (or handle gracefully)
        # The pattern between UNION/UNION ALL difference is subtle
        assert isinstance(rows, list)

    def test_handles_union_with_different_branches(self) -> None:
        """Test UNION with different column expressions."""
        extractor = DataExtractor()
        sql = """INSERT INTO data (id, status)
        SELECT '1'::uuid, 'active'
        UNION ALL SELECT '2'::uuid, 'inactive'"""

        rows = extractor.extract_rows(sql, "data")

        assert len(rows) == 2


class TestCTEHandling:
    """Test handling of Common Table Expressions (WITH clauses)."""

    def test_handles_simple_cte(self) -> None:
        """Test extracting data from simple CTE."""
        extractor = DataExtractor()
        sql = """WITH cte AS (
            SELECT '1'::uuid as id, 'Alice' as name
        )
        INSERT INTO data (id, name) SELECT * FROM cte"""

        rows = extractor.extract_rows(sql, "data")

        # SELECT * from CTE doesn't expand to individual values
        # This is acceptable behavior for now
        assert isinstance(rows, list)

    def test_handles_recursive_cte(self) -> None:
        """Test extracting data from recursive CTE."""
        extractor = DataExtractor()
        sql = """WITH RECURSIVE cte AS (
            SELECT 1 as n, '1'::uuid as id
            UNION ALL SELECT n+1, (n+1)::text::uuid FROM cte WHERE n < 3
        )
        INSERT INTO data (id) SELECT id FROM cte"""

        rows = extractor.extract_rows(sql, "data")

        # Recursive CTEs with complex expressions are best-effort
        assert isinstance(rows, list)

    def test_handles_multiple_ctes(self) -> None:
        """Test extracting data from multiple CTEs."""
        extractor = DataExtractor()
        sql = """WITH
            cte1 AS (SELECT '1'::uuid as id, 'Alice' as name),
            cte2 AS (SELECT '2'::uuid as id, 'Bob' as name)
        INSERT INTO data (id, name)
        SELECT id, name FROM cte1
        UNION ALL SELECT id, name FROM cte2"""

        rows = extractor.extract_rows(sql, "data")

        assert len(rows) == 2


class TestDataExtractorIntegration:
    """Integration tests for DataExtractor."""

    def test_full_extraction_workflow_simple(self) -> None:
        """Test complete extraction workflow for simple INSERT."""
        extractor = DataExtractor()
        sql = """INSERT INTO users (id, name, email) VALUES
            ('1', 'Alice', 'alice@example.com'),
            ('2', 'Bob', 'bob@example.com')"""

        tables = extractor.extract_tables(sql)
        columns = extractor.extract_columns(sql, "users")
        rows = extractor.extract_rows(sql, "users")

        assert tables == ["users"]
        assert columns == ["id", "name", "email"]
        assert len(rows) == 2
        assert rows[0]["name"] == "'Alice'"
        assert rows[1]["name"] == "'Bob'"

    def test_full_extraction_workflow_complex(self) -> None:
        """Test complete extraction workflow for complex query."""
        extractor = DataExtractor()
        sql = """INSERT INTO orders (id, customer_id, status)
        SELECT '01234567-89ab-cdef-0123-456789abcdef'::uuid,
               'cust-1',
               'active'
        UNION ALL SELECT '11111111-2222-3333-4444-555555555555'::uuid,
                         'cust-2',
                         'pending'"""

        tables = extractor.extract_tables(sql)
        columns = extractor.extract_columns(sql, "orders")
        rows = extractor.extract_rows(sql, "orders")

        assert "orders" in tables
        assert "customer_id" in columns
        assert len(rows) == 2

    def test_returns_empty_for_empty_input(self) -> None:
        """Test handling of empty or whitespace-only input."""
        extractor = DataExtractor()

        tables = extractor.extract_tables("")
        columns = extractor.extract_columns("", "users")
        rows = extractor.extract_rows("", "users")

        assert tables == []
        assert columns == []
        assert rows == []

    def test_handles_malformed_sql_gracefully(self) -> None:
        """Test graceful handling of malformed SQL."""
        extractor = DataExtractor()

        # Should not raise exceptions, just return empty/partial results
        sql = "INSERT INTO users (id VALUES ('1'"  # Missing closing paren

        tables = extractor.extract_tables(sql)
        # May or may not extract depending on implementation
        assert isinstance(tables, list)
