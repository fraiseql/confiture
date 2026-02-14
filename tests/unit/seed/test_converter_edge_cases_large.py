"""Tests for converter edge cases that might fail on large files.

Tests for patterns that could cause regex backtracking or other issues.
"""

from __future__ import annotations

import time

from confiture.core.seed.insert_to_copy_converter import InsertToCopyConverter


class TestLargeFileEdgeCases:
    """Test converter with edge cases on large files."""

    def test_many_close_parens_in_strings(self) -> None:
        """Test large file where strings contain many closing parentheses."""
        rows = []
        for i in range(5000):
            # String with many closing parens
            value = f"value_{i}))))))))"
            rows.append(f"({i}, '{value}')")

        values_clause = ", ".join(rows)
        sql = f"INSERT INTO data (id, value) VALUES {values_clause};"

        converter = InsertToCopyConverter()
        result = converter.try_convert(sql, file_path="many_parens.sql")

        assert result.success is True, f"Failed: {result.reason}"
        assert result.rows_converted == 5000

    def test_many_escaped_quotes_in_strings(self) -> None:
        """Test large file where strings contain many escaped quotes."""
        rows = []
        for i in range(5000):
            # String with many escaped single quotes
            value = f"value_{i}'' '' '' '' ''"
            rows.append(f"({i}, '{value}')")

        values_clause = ", ".join(rows)
        sql = f"INSERT INTO data (id, value) VALUES {values_clause};"

        converter = InsertToCopyConverter()
        result = converter.try_convert(sql, file_path="many_quotes.sql")

        assert result.success is True, f"Failed: {result.reason}"
        assert result.rows_converted == 5000

    def test_unicode_strings_large_file(self) -> None:
        """Test large file with unicode characters."""
        rows = []
        for i in range(5000):
            # Unicode characters
            value = f"Ñ_文字_مرحبا_{i}"
            rows.append(f"({i}, '{value}')")

        values_clause = ", ".join(rows)
        sql = f"INSERT INTO data (id, value) VALUES {values_clause};"

        converter = InsertToCopyConverter()
        result = converter.try_convert(sql, file_path="unicode.sql")

        assert result.success is True, f"Failed: {result.reason}"
        assert result.rows_converted == 5000

    def test_very_wide_rows_large_file(self) -> None:
        """Test large file with many columns (wide rows)."""
        # Create 100 columns with values
        col_count = 100
        rows = []
        for i in range(500):  # Fewer rows but more columns
            values = ", ".join(f"'{i}_{j}'" for j in range(col_count))
            rows.append(f"({i}, {values})")

        col_names = ", ".join([f"col_{j}" for j in range(col_count)])
        values_clause = ", ".join(rows)
        sql = f"INSERT INTO wide_table (id, {col_names}) VALUES {values_clause};"

        converter = InsertToCopyConverter()
        result = converter.try_convert(sql, file_path="wide_rows.sql")

        assert result.success is True, f"Failed: {result.reason}"
        assert result.rows_converted == 500

    def test_decimal_precision_large_file(self) -> None:
        """Test large file with high-precision decimals."""
        rows = []
        for i in range(5000):
            # High precision decimal
            value = f"{i * 1.123456789123456789}"
            rows.append(f"({i}, {value})")

        values_clause = ", ".join(rows)
        sql = f"INSERT INTO prices (id, price) VALUES {values_clause};"

        converter = InsertToCopyConverter()
        result = converter.try_convert(sql, file_path="decimals.sql")

        assert result.success is True, f"Failed: {result.reason}"
        assert result.rows_converted == 5000

    def test_regex_catastrophic_backtracking_protection(self) -> None:
        """Test that converter doesn't suffer from catastrophic backtracking."""
        # Create a pathological case: string that looks like it might match
        # but doesn't, causing backtracking
        rows = []
        for i in range(1000):
            # Long string with many parentheses
            value = "x" * 100 + "(" * 20 + ")" * 20
            rows.append(f"({i}, '{value}')")

        values_clause = ", ".join(rows)
        sql = f"INSERT INTO data (id, value) VALUES {values_clause};"

        converter = InsertToCopyConverter()
        start = time.time()
        result = converter.try_convert(sql, file_path="backtrack.sql")
        elapsed = time.time() - start

        assert result.success is True, f"Failed: {result.reason}"
        assert result.rows_converted == 1000
        # Should complete quickly even with backtracking potential
        assert elapsed < 2.0, f"Took {elapsed:.2f}s (potential backtracking issue)"

    def test_mixed_data_types_large_file(self) -> None:
        """Test large file with all data types mixed."""
        rows = []
        for i in range(5000):
            rows.append(
                f"({i}, 'text_{i}', {i * 1.5}, {i % 2 == 0}, NULL, {i * 100})"
            )

        values_clause = ", ".join(rows)
        sql = (
            "INSERT INTO mixed (id, text, price, active, notes, quantity) "
            f"VALUES {values_clause};"
        )

        converter = InsertToCopyConverter()
        result = converter.try_convert(sql, file_path="mixed.sql")

        assert result.success is True, f"Failed: {result.reason}"
        assert result.rows_converted == 5000

    def test_consecutive_nulls_large_file(self) -> None:
        """Test large file with many consecutive NULL columns."""
        rows = []
        for i in range(5000):
            # Many NULLs in sequence
            rows.append(f"({i}, NULL, NULL, NULL, 'value_{i}', NULL, NULL)")

        values_clause = ", ".join(rows)
        sql = (
            "INSERT INTO sparse (id, a, b, c, d, e, f) "
            f"VALUES {values_clause};"
        )

        converter = InsertToCopyConverter()
        result = converter.try_convert(sql, file_path="nulls.sql")

        assert result.success is True, f"Failed: {result.reason}"
        assert result.rows_converted == 5000

    def test_single_massive_insert(self) -> None:
        """Test single INSERT with all 5000+ rows in one statement."""
        import time

        rows = [(i, f"item_{i}") for i in range(5000)]
        values_clause = ", ".join(f"({row[0]}, '{row[1]}')" for row in rows)
        sql = f"INSERT INTO items (id, name) VALUES {values_clause};"

        sql_size = len(sql)
        assert sql_size > 100_000  # Large SQL statement (100KB+)

        converter = InsertToCopyConverter()
        start = time.time()
        result = converter.try_convert(sql, file_path="massive.sql")
        elapsed = time.time() - start

        assert result.success is True, f"Failed: {result.reason}"
        assert result.rows_converted == 5000
        print(f"Converted 5000 rows ({sql_size} bytes) in {elapsed:.3f}s")
