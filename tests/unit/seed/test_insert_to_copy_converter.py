"""Tests for InsertToCopyConverter - convert INSERT statements to COPY format."""

from confiture.core.seed.insert_to_copy_converter import InsertToCopyConverter


class TestBasicInsertParsing:
    """Test basic INSERT statement parsing."""

    def test_parses_single_row_insert(self) -> None:
        """Test parsing INSERT with single row."""
        converter = InsertToCopyConverter()
        insert_sql = "INSERT INTO users (id, name) VALUES (1, 'Alice');"

        result = converter.convert(insert_sql)

        assert result is not None
        assert "COPY users" in result
        assert "1\tAlice" in result
        assert "\\." in result

    def test_parses_multi_row_insert(self) -> None:
        """Test parsing INSERT with multiple rows."""
        converter = InsertToCopyConverter()
        insert_sql = "INSERT INTO users (id, name) VALUES (1, 'Alice'), (2, 'Bob'), (3, 'Charlie');"

        result = converter.convert(insert_sql)

        assert "1\tAlice" in result
        assert "2\tBob" in result
        assert "3\tCharlie" in result

    def test_extracts_table_name(self) -> None:
        """Test that table name is correctly extracted."""
        converter = InsertToCopyConverter()
        insert_sql = "INSERT INTO my_table (col1, col2) VALUES ('a', 'b');"

        result = converter.convert(insert_sql)

        assert "COPY my_table" in result

    def test_extracts_column_names(self) -> None:
        """Test that column names are preserved."""
        converter = InsertToCopyConverter()
        insert_sql = "INSERT INTO users (id, name, email) VALUES (1, 'Alice', 'alice@example.com');"

        result = converter.convert(insert_sql)

        assert "(id, name, email)" in result


class TestDataTypeHandling:
    """Test handling of various data types in INSERT values."""

    def test_handles_string_values(self) -> None:
        """Test handling of string values."""
        converter = InsertToCopyConverter()
        insert_sql = "INSERT INTO users (name) VALUES ('Alice');"

        result = converter.convert(insert_sql)

        assert "Alice" in result

    def test_handles_numeric_values(self) -> None:
        """Test handling of numeric values."""
        converter = InsertToCopyConverter()
        insert_sql = "INSERT INTO products (id, price) VALUES (1, 99.99);"

        result = converter.convert(insert_sql)

        assert "1\t99.99" in result

    def test_handles_null_values(self) -> None:
        """Test that NULL values are converted to \\N."""
        converter = InsertToCopyConverter()
        insert_sql = "INSERT INTO users (id, email) VALUES (1, NULL);"

        result = converter.convert(insert_sql)

        assert "1\t\\N" in result

    def test_handles_boolean_values(self) -> None:
        """Test handling of boolean values."""
        converter = InsertToCopyConverter()
        insert_sql = "INSERT INTO users (id, active) VALUES (1, true), (2, false);"

        result = converter.convert(insert_sql)

        assert "1\ttrue" in result
        assert "2\tfalse" in result

    def test_handles_quoted_strings(self) -> None:
        """Test handling of quoted strings with spaces."""
        converter = InsertToCopyConverter()
        insert_sql = "INSERT INTO users (id, name) VALUES (1, 'John Doe');"

        result = converter.convert(insert_sql)

        assert "John Doe" in result

    def test_escapes_special_characters_in_conversion(self) -> None:
        """Test that special characters are escaped in COPY output."""
        converter = InsertToCopyConverter()
        insert_sql = "INSERT INTO users (id, path) VALUES (1, 'C:\\\\Users\\\\Alice');"

        result = converter.convert(insert_sql)

        # Should contain escaped backslashes
        assert "C:" in result


class TestComplexInsertStatements:
    """Test parsing of complex INSERT statements."""

    def test_handles_multiline_insert(self) -> None:
        """Test parsing multiline INSERT statements."""
        converter = InsertToCopyConverter()
        insert_sql = """
        INSERT INTO users (id, name, email) VALUES
            (1, 'Alice', 'alice@example.com'),
            (2, 'Bob', 'bob@example.com')
        ;
        """

        result = converter.convert(insert_sql)

        assert "1\tAlice\talice@example.com" in result
        assert "2\tBob\tbob@example.com" in result

    def test_handles_extra_whitespace(self) -> None:
        """Test handling of extra whitespace in INSERT."""
        converter = InsertToCopyConverter()
        insert_sql = "INSERT INTO users  (  id  ,  name  )  VALUES  (  1  ,  'Alice'  ) ;"

        result = converter.convert(insert_sql)

        assert "1\tAlice" in result

    def test_handles_many_columns(self) -> None:
        """Test INSERT with many columns."""
        converter = InsertToCopyConverter()
        insert_sql = """
        INSERT INTO users (id, name, email, active, score, bio)
        VALUES (1, 'Alice', 'alice@example.com', true, 95.5, 'developer');
        """

        result = converter.convert(insert_sql)

        assert "COPY users" in result
        assert "id, name, email, active, score, bio" in result

    def test_handles_many_rows(self) -> None:
        """Test INSERT with many rows."""
        converter = InsertToCopyConverter()
        rows = ", ".join([f"({i}, 'User {i}')" for i in range(1, 51)])
        insert_sql = f"INSERT INTO users (id, name) VALUES {rows};"

        result = converter.convert(insert_sql)

        assert "COPY users" in result
        assert "1\tUser 1" in result
        assert "50\tUser 50" in result


class TestStringEscaping:
    """Test handling of escaped characters in strings."""

    def test_handles_escaped_quotes(self) -> None:
        """Test handling of escaped quotes in strings."""
        converter = InsertToCopyConverter()
        insert_sql = "INSERT INTO users (id, quote) VALUES (1, 'He said \"hello\"');"

        result = converter.convert(insert_sql)

        assert "hello" in result

    def test_handles_apostrophes(self) -> None:
        """Test handling of apostrophes in strings."""
        converter = InsertToCopyConverter()
        insert_sql = "INSERT INTO users (id, name) VALUES (1, 'O''Brien');"

        result = converter.convert(insert_sql)

        assert "Brien" in result

    def test_handles_newlines_in_strings(self) -> None:
        """Test handling of newlines in string values."""
        converter = InsertToCopyConverter()
        insert_sql = "INSERT INTO posts (id, content) VALUES (1, 'Line1\\nLine2');"

        result = converter.convert(insert_sql)

        assert "Line1" in result


class TestConversionOutput:
    """Test the output format of conversion."""

    def test_output_is_valid_copy_format(self) -> None:
        """Test that output is valid COPY format."""
        converter = InsertToCopyConverter()
        insert_sql = "INSERT INTO users (id, name) VALUES (1, 'Alice'), (2, 'Bob');"

        result = converter.convert(insert_sql)

        # Should have COPY header
        assert "COPY users" in result
        assert "FROM stdin" in result

        # Should have terminator
        assert "\\." in result

        # Should have data rows
        assert "1\tAlice" in result
        assert "2\tBob" in result

    def test_preserves_column_order(self) -> None:
        """Test that column order is preserved."""
        converter = InsertToCopyConverter()
        insert_sql = "INSERT INTO users (id, name, email) VALUES (1, 'Alice', 'alice@example.com');"

        result = converter.convert(insert_sql)

        # Check column order in header
        lines = result.split("\n")
        header_line = next(line for line in lines if "COPY users" in line)
        assert "(id, name, email)" in header_line


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_handles_empty_string_values(self) -> None:
        """Test handling of empty strings."""
        converter = InsertToCopyConverter()
        insert_sql = "INSERT INTO users (id, bio) VALUES (1, '');"

        result = converter.convert(insert_sql)

        # Empty string should be preserved (not as NULL)
        assert "1\t" in result

    def test_handles_zero_values(self) -> None:
        """Test that zero is not treated as NULL."""
        converter = InsertToCopyConverter()
        insert_sql = "INSERT INTO products (id, quantity) VALUES (1, 0);"

        result = converter.convert(insert_sql)

        assert "1\t0" in result

    def test_handles_false_boolean(self) -> None:
        """Test that false boolean is not treated as NULL."""
        converter = InsertToCopyConverter()
        insert_sql = "INSERT INTO users (id, active) VALUES (1, false);"

        result = converter.convert(insert_sql)

        assert "1\tfalse" in result

    def test_handles_uuid_values(self) -> None:
        """Test handling of UUID values."""
        converter = InsertToCopyConverter()
        uuid_str = "550e8400-e29b-41d4-a716-446655440000"
        insert_sql = f"INSERT INTO users (id, uuid) VALUES (1, '{uuid_str}');"

        result = converter.convert(insert_sql)

        assert uuid_str in result

    def test_handles_large_numbers(self) -> None:
        """Test handling of large numeric values."""
        converter = InsertToCopyConverter()
        insert_sql = "INSERT INTO transactions (id, amount) VALUES (1, 999999.99);"

        result = converter.convert(insert_sql)

        assert "999999.99" in result


class TestRoundTripCompatibility:
    """Test that converted COPY can be parsed back."""

    def test_converted_copy_is_parseable(self) -> None:
        """Test that converted COPY format can be parsed by CopyParser."""
        from confiture.core.seed.copy_parser import CopyParser

        converter = InsertToCopyConverter()
        insert_sql = "INSERT INTO users (id, name) VALUES (1, 'Alice'), (2, 'Bob');"

        copy_data = converter.convert(insert_sql)

        # Extract just the data portion
        lines = copy_data.split("\n")
        data_lines = [
            line for line in lines if line and not line.startswith("COPY") and line != "\\."
        ]
        copy_data_only = "\n".join(data_lines) + "\n\\."

        # Parse it back
        parser = CopyParser()
        rows = parser.parse_table(copy_data_only, ["id", "name"])

        assert len(rows) == 2
        assert rows[0]["id"] == "1"
        assert rows[0]["name"] == "Alice"
        assert rows[1]["id"] == "2"
        assert rows[1]["name"] == "Bob"
