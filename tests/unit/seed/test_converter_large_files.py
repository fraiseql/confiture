"""Tests for INSERT to COPY converter with large files.

Tests converter performance and correctness on files with 5000+ records.
"""

from __future__ import annotations

import pytest

from confiture.core.seed.insert_to_copy_converter import InsertToCopyConverter


class TestLargeFileConversion:
    """Test converter with large files (5000+ records)."""

    def test_converts_5000_row_file(self) -> None:
        """Test conversion of INSERT with 5000 rows."""
        rows = [(i, f"user_{i}", f"user{i}@example.com") for i in range(5000)]
        values_clause = ", ".join(
            f"({row[0]}, '{row[1]}', '{row[2]}')" for row in rows
        )
        sql = f"INSERT INTO users (id, name, email) VALUES {values_clause};"

        converter = InsertToCopyConverter()
        result = converter.try_convert(sql, file_path="large_users.sql")

        assert result.success is True, f"Failed: {result.reason}"
        assert result.rows_converted == 5000
        assert "COPY users" in result.copy_format

    def test_converts_10000_row_file(self) -> None:
        """Test conversion of INSERT with 10000 rows."""
        rows = [(i, f"item_{i}") for i in range(10000)]
        values_clause = ", ".join(f"({row[0]}, '{row[1]}')" for row in rows)
        sql = f"INSERT INTO items (id, name) VALUES {values_clause};"

        converter = InsertToCopyConverter()
        result = converter.try_convert(sql, file_path="large_items.sql")

        assert result.success is True, f"Failed: {result.reason}"
        assert result.rows_converted == 10000

    def test_converts_large_file_with_null_values(self) -> None:
        """Test conversion of large file with NULL values."""
        rows = []
        for i in range(5000):
            if i % 3 == 0:
                rows.append(f"({i}, NULL, NULL)")
            elif i % 3 == 1:
                rows.append(f"({i}, 'value_{i}', NULL)")
            else:
                rows.append(f"({i}, 'value_{i}', '{i}@test.com')")

        values_clause = ", ".join(rows)
        sql = f"INSERT INTO users (id, name, email) VALUES {values_clause};"

        converter = InsertToCopyConverter()
        result = converter.try_convert(sql, file_path="large_nulls.sql")

        assert result.success is True, f"Failed: {result.reason}"
        assert result.rows_converted == 5000

    def test_converts_large_file_with_special_characters(self) -> None:
        """Test conversion of large file with special characters."""
        rows = []
        for i in range(5000):
            name = f"user_{i}_{chr(65 + (i % 26))}"  # Add varying characters
            email = f"user+{i}@example.com"
            rows.append(f"({i}, '{name}', '{email}')")

        values_clause = ", ".join(rows)
        sql = f"INSERT INTO users (id, name, email) VALUES {values_clause};"

        converter = InsertToCopyConverter()
        result = converter.try_convert(sql, file_path="large_special.sql")

        assert result.success is True, f"Failed: {result.reason}"
        assert result.rows_converted == 5000

    def test_large_file_output_has_all_rows(self) -> None:
        """Test that all rows are present in converted COPY output."""
        rows = [(i, f"data_{i}") for i in range(5000)]
        values_clause = ", ".join(f"({row[0]}, '{row[1]}')" for row in rows)
        sql = f"INSERT INTO data (id, value) VALUES {values_clause};"

        converter = InsertToCopyConverter()
        result = converter.try_convert(sql, file_path="large_data.sql")

        assert result.success is True
        # Count lines in output (excluding header and footer)
        lines = result.copy_format.strip().split("\n")
        # Lines = [header, data rows..., footer]
        data_lines = len(lines) - 2  # Exclude COPY header and \. footer
        assert data_lines == 5000

    def test_large_file_conversion_performance(self) -> None:
        """Test that large file conversion completes in reasonable time."""
        import time

        rows = [(i, f"item_{i}", f"{i * 10.5}") for i in range(5000)]
        values_clause = ", ".join(f"({row[0]}, '{row[1]}', {row[2]})" for row in rows)
        sql = f"INSERT INTO products (id, name, price) VALUES {values_clause};"

        converter = InsertToCopyConverter()
        start = time.time()
        result = converter.try_convert(sql, file_path="large_products.sql")
        elapsed = time.time() - start

        assert result.success is True
        assert result.rows_converted == 5000
        # Should complete in under 5 seconds even on slow systems
        assert elapsed < 5.0, f"Conversion took {elapsed:.2f}s (expected <5s)"

    def test_batch_conversion_with_large_files(self) -> None:
        """Test batch conversion with multiple large files."""
        converter = InsertToCopyConverter()

        files = {}
        for file_num in range(3):
            rows = [(i, f"data_{file_num}_{i}") for i in range(2000)]
            values_clause = ", ".join(f"({row[0]}, '{row[1]}')" for row in rows)
            sql = f"INSERT INTO table_{file_num} (id, value) VALUES {values_clause};"
            files[f"file_{file_num}.sql"] = sql

        report = converter.convert_batch(files)

        assert report.total_files == 3
        assert report.successful == 3
        assert report.failed == 0
        total_rows = sum(r.rows_converted for r in report.results if r.success)
        assert total_rows == 6000  # 3 files * 2000 rows each

    def test_very_long_strings_in_large_file(self) -> None:
        """Test conversion of large file with very long string values."""
        long_string = "a" * 1000  # 1KB string
        rows = [(i, long_string, f"item_{i}") for i in range(1000)]
        values_clause = ", ".join(
            f"({row[0]}, '{row[1]}', '{row[2]}')" for row in rows
        )
        sql = f"INSERT INTO data (id, content, name) VALUES {values_clause};"

        converter = InsertToCopyConverter()
        result = converter.try_convert(sql, file_path="large_strings.sql")

        assert result.success is True
        assert result.rows_converted == 1000

    def test_large_file_with_multiline_values(self) -> None:
        """Test conversion where values contain escaped newlines."""
        rows = []
        for i in range(1000):
            # Include escaped newlines in values
            content = f"Line 1\\nLine 2 {i}\\nLine 3"
            rows.append(f"({i}, '{content}')")

        values_clause = ", ".join(rows)
        sql = f"INSERT INTO notes (id, content) VALUES {values_clause};"

        converter = InsertToCopyConverter()
        result = converter.try_convert(sql, file_path="large_multiline.sql")

        assert result.success is True
        assert result.rows_converted == 1000
