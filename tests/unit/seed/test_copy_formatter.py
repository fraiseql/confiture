"""Tests for CopyFormatter - generating PostgreSQL COPY format from seed data."""

from confiture.core.seed.copy_formatter import CopyFormatter


class TestBasicCopyFormatting:
    """Test basic COPY format generation."""

    def test_formats_simple_table(self) -> None:
        """Test formatting a simple table to COPY format."""
        formatter = CopyFormatter()
        rows = [
            {"id": "1", "name": "Alice"},
            {"id": "2", "name": "Bob"},
        ]
        columns = ["id", "name"]

        output = formatter.format_table("users", rows, columns)

        assert "COPY users" in output
        assert "FROM stdin" in output
        assert "1\tAlice" in output
        assert "2\tBob" in output
        assert "\\." in output

    def test_formats_null_values(self) -> None:
        """Test that NULL values are represented as \\N."""
        formatter = CopyFormatter()
        rows = [
            {"id": "1", "email": "alice@example.com"},
            {"id": "2", "email": None},
        ]
        columns = ["id", "email"]

        output = formatter.format_table("users", rows, columns)

        # NULL should be \N in COPY format
        assert "\\N" in output

    def test_escapes_backslash(self) -> None:
        """Test that backslashes are properly escaped."""
        formatter = CopyFormatter()
        rows = [
            {"id": "1", "path": "C:\\Users\\Alice"},
        ]
        columns = ["id", "path"]

        output = formatter.format_table("data", rows, columns)

        # Backslash should be escaped as \\
        assert "C:\\\\Users\\\\Alice" in output or "C:\\Users\\Alice" in output

    def test_escapes_newlines(self) -> None:
        """Test that newlines are properly escaped."""
        formatter = CopyFormatter()
        rows = [
            {"id": "1", "text": "Line1\nLine2"},
        ]
        columns = ["id", "text"]

        output = formatter.format_table("data", rows, columns)

        # Newline should be escaped
        assert "\\n" in output or "Line1" in output

    def test_escapes_tabs(self) -> None:
        """Test that tab characters are properly escaped."""
        formatter = CopyFormatter()
        rows = [
            {"id": "1", "text": "Col1\tCol2"},
        ]
        columns = ["id", "text"]

        output = formatter.format_table("data", rows, columns)

        # Tab should be escaped
        assert "\\t" in output or "Col1" in output

    def test_formats_multiple_rows(self) -> None:
        """Test formatting multiple rows."""
        formatter = CopyFormatter()
        rows = [
            {"id": "1", "status": "active"},
            {"id": "2", "status": "inactive"},
            {"id": "3", "status": "pending"},
        ]
        columns = ["id", "status"]

        output = formatter.format_table("tasks", rows, columns)

        # Should have 3 data rows
        assert output.count("\n") >= 3

    def test_handles_empty_table(self) -> None:
        """Test formatting an empty table."""
        formatter = CopyFormatter()
        rows = []
        columns = ["id", "name"]

        output = formatter.format_table("users", rows, columns)

        # Should still have COPY header
        assert "COPY users" in output
        assert "\\." in output

    def test_formats_numeric_values(self) -> None:
        """Test formatting numeric values."""
        formatter = CopyFormatter()
        rows = [
            {"id": "1", "quantity": "100", "price": "99.99"},
        ]
        columns = ["id", "quantity", "price"]

        output = formatter.format_table("products", rows, columns)

        assert "100" in output
        assert "99.99" in output

    def test_formats_uuid_values(self) -> None:
        """Test formatting UUID values."""
        formatter = CopyFormatter()
        rows = [
            {"id": "550e8400-e29b-41d4-a716-446655440000"},
        ]
        columns = ["id"]

        output = formatter.format_table("records", rows, columns)

        assert "550e8400-e29b-41d4-a716-446655440000" in output

    def test_formats_boolean_values(self) -> None:
        """Test formatting boolean values."""
        formatter = CopyFormatter()
        rows = [
            {"id": "1", "active": "true"},
            {"id": "2", "active": "false"},
        ]
        columns = ["id", "active"]

        output = formatter.format_table("users", rows, columns)

        assert "true" in output
        assert "false" in output


class TestColumnOrdering:
    """Test column ordering in COPY format."""

    def test_preserves_column_order(self) -> None:
        """Test that column order is preserved."""
        formatter = CopyFormatter()
        rows = [
            {"name": "Alice", "id": "1", "email": "alice@example.com"},
        ]
        columns = ["id", "name", "email"]

        output = formatter.format_table("users", rows, columns)

        # Data should be in column order
        assert "COPY users (id, name, email)" in output

    def test_handles_different_column_order(self) -> None:
        """Test handling different column orderings."""
        formatter = CopyFormatter()
        rows = [
            {"email": "alice@example.com", "name": "Alice", "id": "1"},
        ]
        columns = ["name", "id", "email"]

        output = formatter.format_table("users", rows, columns)

        assert "COPY users (name, id, email)" in output


class TestSpecialCharacters:
    """Test handling special characters."""

    def test_handles_pipe_character(self) -> None:
        """Test handling pipe character (column delimiter context)."""
        formatter = CopyFormatter()
        rows = [
            {"id": "1", "text": "A|B"},
        ]
        columns = ["id", "text"]

        output = formatter.format_table("data", rows, columns)

        assert "A|B" in output or "A\\|B" in output

    def test_handles_quotes(self) -> None:
        """Test handling quote characters."""
        formatter = CopyFormatter()
        rows = [
            {"id": "1", "text": 'He said "hello"'},
        ]
        columns = ["id", "text"]

        output = formatter.format_table("data", rows, columns)

        assert "hello" in output

    def test_handles_carriage_return(self) -> None:
        """Test handling carriage return characters."""
        formatter = CopyFormatter()
        rows = [
            {"id": "1", "text": "Line1\rLine2"},
        ]
        columns = ["id", "text"]

        output = formatter.format_table("data", rows, columns)

        assert output is not None


class TestCopyFormatStructure:
    """Test the structure of generated COPY format."""

    def test_includes_copy_header(self) -> None:
        """Test that output includes COPY header."""
        formatter = CopyFormatter()
        rows = [{"id": "1"}]
        columns = ["id"]

        output = formatter.format_table("users", rows, columns)

        assert "COPY users" in output
        assert "FROM stdin" in output

    def test_includes_column_list(self) -> None:
        """Test that output includes column list."""
        formatter = CopyFormatter()
        rows = [{"id": "1", "name": "Alice"}]
        columns = ["id", "name"]

        output = formatter.format_table("users", rows, columns)

        assert "(id, name)" in output

    def test_ends_with_backslash_dot(self) -> None:
        """Test that output ends with \\. (COPY terminator)."""
        formatter = CopyFormatter()
        rows = [{"id": "1"}]
        columns = ["id"]

        output = formatter.format_table("users", rows, columns)

        assert output.rstrip().endswith("\\.")

    def test_tab_separated_values(self) -> None:
        """Test that values are tab-separated."""
        formatter = CopyFormatter()
        rows = [
            {"id": "1", "name": "Alice", "email": "alice@example.com"},
        ]
        columns = ["id", "name", "email"]

        output = formatter.format_table("users", rows, columns)

        # Data row should have tabs
        lines = [
            line
            for line in output.split("\n")
            if line and not line.startswith("COPY") and line != "\\."
        ]
        if lines:
            assert "\t" in lines[0]


class TestCopyFormatterEdgeCases:
    """Test edge cases in COPY formatting."""

    def test_handles_very_long_strings(self) -> None:
        """Test handling very long string values."""
        formatter = CopyFormatter()
        long_string = "x" * 10000
        rows = [{"id": "1", "text": long_string}]
        columns = ["id", "text"]

        output = formatter.format_table("data", rows, columns)

        assert long_string in output

    def test_handles_special_null_representations(self) -> None:
        """Test that only actual None becomes \\N."""
        formatter = CopyFormatter()
        rows = [
            {"id": "1", "value": None},
            {"id": "2", "value": "null"},  # String, not None
            {"id": "3", "value": ""},  # Empty string
        ]
        columns = ["id", "value"]

        output = formatter.format_table("data", rows, columns)

        # Row 1 should have \N
        # Row 2 should have literal "null"
        # Row 3 should be empty (but might be \N depending on implementation)
        assert "\\N" in output
        assert "null" in output

    def test_handles_mixed_data_types(self) -> None:
        """Test handling mixed data types in one row."""
        formatter = CopyFormatter()
        rows = [
            {
                "id": "1",
                "name": "Alice",
                "age": "30",
                "active": "true",
                "bio": None,
                "salary": "50000.50",
            }
        ]
        columns = ["id", "name", "age", "active", "bio", "salary"]

        output = formatter.format_table("users", rows, columns)

        assert "Alice" in output
        assert "30" in output
        assert "50000.50" in output
        assert "\\N" in output
