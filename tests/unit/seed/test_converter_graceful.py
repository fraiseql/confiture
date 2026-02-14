"""Tests for INSERT to COPY converter graceful degradation.

Phase 11, Cycle 3: Add try_convert() method with graceful fallback.
"""

from __future__ import annotations

import pytest

from confiture.core.seed.insert_to_copy_converter import InsertToCopyConverter
from confiture.models.results import ConversionResult


class TestGracefulDegradation:
    """Test graceful degradation with ConversionResult."""

    def test_try_convert_simple_success(self) -> None:
        """Test try_convert with simple convertible INSERT."""
        converter = InsertToCopyConverter()
        sql = "INSERT INTO users (id, name) VALUES (1, 'Alice');"

        result = converter.try_convert(sql, file_path="test.sql")

        assert result.success is True
        assert result.file_path == "test.sql"
        assert result.copy_format is not None
        assert result.rows_converted == 1
        assert result.reason is None

    def test_try_convert_now_function_failure(self) -> None:
        """Test try_convert gracefully handles NOW() function."""
        converter = InsertToCopyConverter()
        sql = "INSERT INTO events (created_at) VALUES (NOW());"

        result = converter.try_convert(sql, file_path="events.sql")

        assert result.success is False
        assert result.file_path == "events.sql"
        assert result.copy_format is None
        assert result.rows_converted is None
        assert result.reason is not None
        assert "cannot" in result.reason.lower() or "function" in result.reason.lower()

    def test_try_convert_uuid_function_failure(self) -> None:
        """Test try_convert gracefully handles uuid_generate_v4()."""
        converter = InsertToCopyConverter()
        sql = "INSERT INTO ids (id) VALUES (uuid_generate_v4());"

        result = converter.try_convert(sql, file_path="ids.sql")

        assert result.success is False
        assert result.reason is not None

    def test_try_convert_on_conflict_failure(self) -> None:
        """Test try_convert gracefully handles ON CONFLICT clause."""
        converter = InsertToCopyConverter()
        sql = """INSERT INTO users (id, name) VALUES (1, 'Alice')
                 ON CONFLICT (id) DO UPDATE SET name = 'Bob';"""

        result = converter.try_convert(sql, file_path="upsert.sql")

        assert result.success is False
        assert result.reason is not None

    def test_try_convert_select_failure(self) -> None:
        """Test try_convert gracefully handles SELECT in VALUES."""
        converter = InsertToCopyConverter()
        sql = "INSERT INTO users (name) SELECT name FROM defaults;"

        result = converter.try_convert(sql, file_path="select.sql")

        assert result.success is False
        assert result.reason is not None

    def test_try_convert_null_values(self) -> None:
        """Test try_convert handles NULL values correctly."""
        converter = InsertToCopyConverter()
        sql = "INSERT INTO users (id, email) VALUES (1, NULL), (2, 'test@example.com');"

        result = converter.try_convert(sql, file_path="nulls.sql")

        assert result.success is True
        assert result.rows_converted == 2

    def test_try_convert_multi_row_success(self) -> None:
        """Test try_convert with multiple rows."""
        converter = InsertToCopyConverter()
        sql = """INSERT INTO users (id, name, active) VALUES
                 (1, 'Alice', true),
                 (2, 'Bob', false),
                 (3, 'Charlie', true);"""

        result = converter.try_convert(sql, file_path="batch.sql")

        assert result.success is True
        assert result.rows_converted == 3

    def test_try_convert_with_cte_failure(self) -> None:
        """Test try_convert gracefully handles CTE."""
        converter = InsertToCopyConverter()
        sql = """WITH temp AS (SELECT 1 as id)
                 INSERT INTO users (id) SELECT id FROM temp;"""

        result = converter.try_convert(sql, file_path="cte.sql")

        assert result.success is False

    def test_try_convert_case_when_failure(self) -> None:
        """Test try_convert gracefully handles CASE WHEN."""
        converter = InsertToCopyConverter()
        sql = "INSERT INTO status (value) VALUES (CASE WHEN 1=1 THEN 'yes' ELSE 'no' END);"

        result = converter.try_convert(sql, file_path="case.sql")

        assert result.success is False

    def test_try_convert_reason_is_descriptive(self) -> None:
        """Test that failure reason is descriptive."""
        converter = InsertToCopyConverter()
        sql = "INSERT INTO users (created) VALUES (NOW());"

        result = converter.try_convert(sql)

        assert result.success is False
        # Reason should indicate what was wrong
        reason = result.reason.lower()
        assert "cannot" in reason or "cannot be converted" in reason or "function" in reason

    def test_try_convert_preserves_file_path(self) -> None:
        """Test that file_path is always preserved in result."""
        converter = InsertToCopyConverter()
        sql_success = "INSERT INTO users (id) VALUES (1);"
        sql_failure = "INSERT INTO users (created) VALUES (NOW());"

        result_success = converter.try_convert(sql_success, file_path="/path/to/users.sql")
        result_failure = converter.try_convert(sql_failure, file_path="/path/to/events.sql")

        assert result_success.file_path == "/path/to/users.sql"
        assert result_failure.file_path == "/path/to/events.sql"

    def test_try_convert_default_file_path(self) -> None:
        """Test that try_convert works without file_path."""
        converter = InsertToCopyConverter()
        sql = "INSERT INTO users (id) VALUES (1);"

        result = converter.try_convert(sql)

        assert result.file_path == ""
        assert result.success is True

    def test_try_convert_string_concat_failure(self) -> None:
        """Test try_convert detects string concatenation."""
        converter = InsertToCopyConverter()
        sql = "INSERT INTO users (name) VALUES ('John' || ' ' || 'Doe');"

        result = converter.try_convert(sql, file_path="concat.sql")

        assert result.success is False

    def test_try_convert_arithmetic_failure(self) -> None:
        """Test try_convert detects arithmetic operations."""
        converter = InsertToCopyConverter()
        sql = "INSERT INTO stats (count) VALUES (1 + 2);"

        result = converter.try_convert(sql, file_path="math.sql")

        assert result.success is False
