"""Tests for CopyParser - parsing PostgreSQL COPY format back into seed data."""

from confiture.core.seed.copy_parser import CopyParser


class TestBasicCopyParsing:
    """Test basic COPY format parsing."""

    def test_parses_simple_copy_data(self) -> None:
        """Test parsing simple COPY format data."""
        parser = CopyParser()
        copy_data = "1\tAlice\n2\tBob\n\\."
        columns = ["id", "name"]

        rows = parser.parse_table(copy_data, columns)

        assert len(rows) == 2
        assert rows[0]["id"] == "1"
        assert rows[0]["name"] == "Alice"
        assert rows[1]["id"] == "2"
        assert rows[1]["name"] == "Bob"

    def test_parses_null_values(self) -> None:
        """Test that \\N is converted back to None."""
        parser = CopyParser()
        copy_data = "1\tAlice\n2\t\\N\n\\."
        columns = ["id", "email"]

        rows = parser.parse_table(copy_data, columns)

        assert rows[0]["email"] == "Alice"
        assert rows[1]["email"] is None

    def test_unescapes_backslash(self) -> None:
        """Test that escaped backslashes are unescaped."""
        parser = CopyParser()
        copy_data = "1\tC:\\\\Users\\\\Alice\n\\."
        columns = ["id", "path"]

        rows = parser.parse_table(copy_data, columns)

        # Should convert \\ back to \
        assert "Users" in rows[0]["path"]
        assert "\\" in rows[0]["path"]

    def test_unescapes_newlines(self) -> None:
        """Test that escaped newlines are unescaped."""
        parser = CopyParser()
        copy_data = "1\tLine1\\nLine2\n\\."
        columns = ["id", "text"]

        rows = parser.parse_table(copy_data, columns)

        # Should convert \n back to newline
        assert "Line1" in rows[0]["text"]
        assert "Line2" in rows[0]["text"]

    def test_unescapes_tabs(self) -> None:
        """Test that escaped tabs are unescaped."""
        parser = CopyParser()
        copy_data = "1\tCol1\\tCol2\n\\."
        columns = ["id", "text"]

        rows = parser.parse_table(copy_data, columns)

        # Should convert \t back to tab (but within value, not column separator)
        assert "\t" in rows[0]["text"] or "Col1" in rows[0]["text"]

    def test_parses_multiple_rows(self) -> None:
        """Test parsing multiple rows."""
        parser = CopyParser()
        copy_data = "1\tactive\n2\tinactive\n3\tpending\n\\."
        columns = ["id", "status"]

        rows = parser.parse_table(copy_data, columns)

        assert len(rows) == 3
        assert rows[0]["status"] == "active"
        assert rows[1]["status"] == "inactive"
        assert rows[2]["status"] == "pending"

    def test_parses_empty_table(self) -> None:
        """Test parsing an empty table (no data rows)."""
        parser = CopyParser()
        copy_data = "\\."
        columns = ["id", "name"]

        rows = parser.parse_table(copy_data, columns)

        assert len(rows) == 0

    def test_parses_numeric_values(self) -> None:
        """Test parsing numeric values."""
        parser = CopyParser()
        copy_data = "1\t100\t99.99\n\\."
        columns = ["id", "quantity", "price"]

        rows = parser.parse_table(copy_data, columns)

        assert rows[0]["quantity"] == "100"
        assert rows[0]["price"] == "99.99"

    def test_parses_uuid_values(self) -> None:
        """Test parsing UUID values."""
        parser = CopyParser()
        uuid_str = "550e8400-e29b-41d4-a716-446655440000"
        copy_data = f"{uuid_str}\tAlice\n\\."
        columns = ["id", "name"]

        rows = parser.parse_table(copy_data, columns)

        assert rows[0]["id"] == uuid_str

    def test_parses_boolean_values(self) -> None:
        """Test parsing boolean values."""
        parser = CopyParser()
        copy_data = "1\ttrue\n2\tfalse\n\\."
        columns = ["id", "active"]

        rows = parser.parse_table(copy_data, columns)

        assert rows[0]["active"] == "true"
        assert rows[1]["active"] == "false"


class TestColumnMapping:
    """Test column mapping in parsing."""

    def test_maps_columns_in_order(self) -> None:
        """Test that columns are mapped in correct order."""
        parser = CopyParser()
        copy_data = "Alice\t1\talice@example.com\n\\."
        columns = ["name", "id", "email"]

        rows = parser.parse_table(copy_data, columns)

        assert rows[0]["name"] == "Alice"
        assert rows[0]["id"] == "1"
        assert rows[0]["email"] == "alice@example.com"

    def test_handles_different_column_order(self) -> None:
        """Test handling different column orderings."""
        parser = CopyParser()
        copy_data = "alice@example.com\t1\tAlice\n\\."
        columns = ["email", "id", "name"]

        rows = parser.parse_table(copy_data, columns)

        assert rows[0]["email"] == "alice@example.com"
        assert rows[0]["id"] == "1"
        assert rows[0]["name"] == "Alice"


class TestSpecialCharacterHandling:
    """Test handling special characters."""

    def test_unescapes_carriage_return(self) -> None:
        """Test unescaping carriage return."""
        parser = CopyParser()
        copy_data = "1\tLine1\\rLine2\n\\."
        columns = ["id", "text"]

        rows = parser.parse_table(copy_data, columns)

        assert "Line1" in rows[0]["text"]

    def test_unescapes_backspace(self) -> None:
        """Test unescaping backspace."""
        parser = CopyParser()
        copy_data = "1\ttext\\bmore\n\\."
        columns = ["id", "text"]

        rows = parser.parse_table(copy_data, columns)

        assert "text" in rows[0]["text"]

    def test_unescapes_form_feed(self) -> None:
        """Test unescaping form feed."""
        parser = CopyParser()
        copy_data = "1\ttext\\fmore\n\\."
        columns = ["id", "text"]

        rows = parser.parse_table(copy_data, columns)

        assert "text" in rows[0]["text"]

    def test_handles_empty_values(self) -> None:
        """Test handling empty string values."""
        parser = CopyParser()
        copy_data = "1\t\n2\tBob\n\\."
        columns = ["id", "name"]

        rows = parser.parse_table(copy_data, columns)

        assert rows[0]["name"] == ""
        assert rows[1]["name"] == "Bob"


class TestCopyParserEdgeCases:
    """Test edge cases in COPY parsing."""

    def test_handles_very_long_values(self) -> None:
        """Test handling very long string values."""
        parser = CopyParser()
        long_string = "x" * 10000
        copy_data = f"1\t{long_string}\n\\."
        columns = ["id", "text"]

        rows = parser.parse_table(copy_data, columns)

        assert rows[0]["text"] == long_string

    def test_handles_multiple_escaped_chars_in_value(self) -> None:
        """Test handling multiple escaped characters in one value."""
        parser = CopyParser()
        copy_data = "1\tLine1\\nLine2\\tCol2\\\\Path\n\\."
        columns = ["id", "text"]

        rows = parser.parse_table(copy_data, columns)

        assert "Line1" in rows[0]["text"]
        assert "Line2" in rows[0]["text"]

    def test_distinguishes_null_from_empty_string(self) -> None:
        """Test that NULL (\\N) is different from empty string."""
        parser = CopyParser()
        copy_data = "1\t\\N\n2\t\n3\tvalue\n\\."
        columns = ["id", "text"]

        rows = parser.parse_table(copy_data, columns)

        assert rows[0]["text"] is None
        assert rows[1]["text"] == ""
        assert rows[2]["text"] == "value"

    def test_handles_trailing_newline(self) -> None:
        """Test handling trailing newline before terminator."""
        parser = CopyParser()
        copy_data = "1\tAlice\n\\."
        columns = ["id", "name"]

        rows = parser.parse_table(copy_data, columns)

        assert len(rows) == 1
        assert rows[0]["name"] == "Alice"

    def test_handles_no_trailing_newline(self) -> None:
        """Test handling data without trailing newline before terminator."""
        parser = CopyParser()
        copy_data = "1\tAlice\n\\."
        columns = ["id", "name"]

        rows = parser.parse_table(copy_data, columns)

        assert len(rows) == 1


class TestParserRobustness:
    """Test parser robustness and error handling."""

    def test_handles_single_column(self) -> None:
        """Test parsing single column table."""
        parser = CopyParser()
        copy_data = "Alice\nBob\nCharlie\n\\."
        columns = ["name"]

        rows = parser.parse_table(copy_data, columns)

        assert len(rows) == 3
        assert rows[0]["name"] == "Alice"
        assert rows[1]["name"] == "Bob"
        assert rows[2]["name"] == "Charlie"

    def test_handles_many_columns(self) -> None:
        """Test parsing table with many columns."""
        parser = CopyParser()
        cols = ["col" + str(i) for i in range(20)]
        values = [str(i) for i in range(20)]
        copy_data = "\t".join(values) + "\n\\."

        rows = parser.parse_table(copy_data, cols)

        assert len(rows) == 1
        for i, col in enumerate(cols):
            assert rows[0][col] == str(i)

    def test_returns_list_of_dicts(self) -> None:
        """Test that parse_table returns list of dictionaries."""
        parser = CopyParser()
        copy_data = "1\tAlice\n\\."
        columns = ["id", "name"]

        rows = parser.parse_table(copy_data, columns)

        assert isinstance(rows, list)
        assert isinstance(rows[0], dict)

    def test_dict_keys_match_columns(self) -> None:
        """Test that dictionary keys match provided columns."""
        parser = CopyParser()
        copy_data = "1\tAlice\talice@example.com\n\\."
        columns = ["id", "name", "email"]

        rows = parser.parse_table(copy_data, columns)

        assert set(rows[0].keys()) == set(columns)


class TestRoundTripCompatibility:
    """Test round-trip compatibility with CopyFormatter."""

    def test_parses_formatter_output(self) -> None:
        """Test that parser can parse CopyFormatter output (without header)."""
        from confiture.core.seed.copy_formatter import CopyFormatter

        formatter = CopyFormatter()
        rows_original = [
            {"id": "1", "name": "Alice"},
            {"id": "2", "name": "Bob"},
        ]
        columns = ["id", "name"]

        # Format the data
        formatted = formatter.format_table("users", rows_original, columns)

        # Extract data portion (skip COPY header and terminator)
        lines = formatted.split("\n")
        data_lines = [
            line for line in lines if line and not line.startswith("COPY") and line != "\\."
        ]
        copy_data = "\n".join(data_lines) + "\n\\."

        # Parse it back
        parser = CopyParser()
        rows_parsed = parser.parse_table(copy_data, columns)

        # Should match original
        assert len(rows_parsed) == len(rows_original)
        for i, row in enumerate(rows_parsed):
            assert row["id"] == rows_original[i]["id"]
            assert row["name"] == rows_original[i]["name"]
