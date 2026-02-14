"""Tests for INSERT to COPY converter with complex SQL patterns.

Phase 11, Cycle 2: Add detection for SQL patterns that cannot be converted.
"""

from __future__ import annotations

import pytest

from confiture.core.seed.insert_to_copy_converter import InsertToCopyConverter


class TestComplexSQLDetection:
    """Test detection of SQL patterns that cannot be converted."""

    def test_detects_now_function(self) -> None:
        """Test that NOW() function is detected as non-convertible."""
        converter = InsertToCopyConverter()
        sql = "INSERT INTO users (created_at) VALUES (NOW());"

        assert not converter._can_convert_to_copy(sql)

    def test_detects_uuid_generate_function(self) -> None:
        """Test that uuid_generate_v4() is detected as non-convertible."""
        converter = InsertToCopyConverter()
        sql = "INSERT INTO users (id) VALUES (uuid_generate_v4());"

        assert not converter._can_convert_to_copy(sql)

    def test_detects_current_timestamp(self) -> None:
        """Test that CURRENT_TIMESTAMP is detected as non-convertible."""
        converter = InsertToCopyConverter()
        sql = "INSERT INTO events (ts) VALUES (CURRENT_TIMESTAMP);"

        assert not converter._can_convert_to_copy(sql)

    def test_detects_on_conflict_clause(self) -> None:
        """Test that ON CONFLICT clause is detected as non-convertible."""
        converter = InsertToCopyConverter()
        sql = """INSERT INTO users (id, name) VALUES (1, 'Alice')
                 ON CONFLICT (id) DO UPDATE SET name = 'Alice';"""

        assert not converter._can_convert_to_copy(sql)

    def test_detects_on_duplicate_key_clause(self) -> None:
        """Test that ON DUPLICATE KEY is detected as non-convertible."""
        converter = InsertToCopyConverter()
        sql = """INSERT INTO users (id, name) VALUES (1, 'Alice')
                 ON DUPLICATE KEY UPDATE name = 'Alice';"""

        assert not converter._can_convert_to_copy(sql)

    def test_detects_select_in_values(self) -> None:
        """Test that SELECT in VALUES clause is detected as non-convertible."""
        converter = InsertToCopyConverter()
        sql = "INSERT INTO users (name) VALUES ((SELECT name FROM defaults LIMIT 1));"

        assert not converter._can_convert_to_copy(sql)

    def test_detects_with_cte(self) -> None:
        """Test that CTE (WITH clause) is detected as non-convertible."""
        converter = InsertToCopyConverter()
        sql = """WITH temp AS (SELECT 1 as id)
                 INSERT INTO users (id) SELECT id FROM temp;"""

        assert not converter._can_convert_to_copy(sql)

    def test_detects_function_call_in_values(self) -> None:
        """Test that function calls in VALUES are detected."""
        converter = InsertToCopyConverter()
        sql = "INSERT INTO users (name) VALUES (UPPER('alice'));"

        assert not converter._can_convert_to_copy(sql)

    def test_detects_cast_in_values(self) -> None:
        """Test that CAST expressions in VALUES might not be handled."""
        converter = InsertToCopyConverter()
        sql = "INSERT INTO users (value) VALUES (CAST('123' AS INTEGER));"

        # CAST is a function-like construct
        assert not converter._can_convert_to_copy(sql)

    def test_detects_case_when_in_values(self) -> None:
        """Test that CASE WHEN in VALUES is detected."""
        converter = InsertToCopyConverter()
        sql = "INSERT INTO users (status) VALUES (CASE WHEN 1=1 THEN 'active' ELSE 'inactive' END);"

        assert not converter._can_convert_to_copy(sql)

    def test_detects_arithmetic_in_values(self) -> None:
        """Test that arithmetic expressions in VALUES are detected."""
        converter = InsertToCopyConverter()
        sql = "INSERT INTO stats (count) VALUES (1 + 2);"

        assert not converter._can_convert_to_copy(sql)

    def test_detects_string_concatenation_in_values(self) -> None:
        """Test that string concatenation in VALUES is detected."""
        converter = InsertToCopyConverter()
        sql = "INSERT INTO users (name) VALUES ('John' || ' ' || 'Doe');"

        assert not converter._can_convert_to_copy(sql)

    def test_detects_nested_parentheses(self) -> None:
        """Test that nested parentheses in VALUES are detected."""
        converter = InsertToCopyConverter()
        sql = "INSERT INTO users (data) VALUES ((SELECT (SELECT 1)));"

        assert not converter._can_convert_to_copy(sql)

    def test_allows_simple_values(self) -> None:
        """Test that simple values are allowed."""
        converter = InsertToCopyConverter()
        sql = "INSERT INTO users (id, name, active) VALUES (1, 'Alice', true);"

        assert converter._can_convert_to_copy(sql)

    def test_allows_null_values(self) -> None:
        """Test that NULL values are allowed."""
        converter = InsertToCopyConverter()
        sql = "INSERT INTO users (id, email) VALUES (1, NULL);"

        assert converter._can_convert_to_copy(sql)

    def test_allows_multiple_rows(self) -> None:
        """Test that multiple simple rows are allowed."""
        converter = InsertToCopyConverter()
        sql = """INSERT INTO users (id, name) VALUES
                 (1, 'Alice'),
                 (2, 'Bob'),
                 (3, 'Charlie');"""

        assert converter._can_convert_to_copy(sql)
