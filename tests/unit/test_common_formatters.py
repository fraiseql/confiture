"""Tests for common formatter utilities.

Tests JSON/CSV serialization, file I/O, and format handling.
"""

import json
from pathlib import Path
from tempfile import TemporaryDirectory

from rich.console import Console

from confiture.cli.formatters.common import (
    handle_output,
    print_csv,
    print_json,
    save_csv,
    save_json,
)


class TestSaveJson:
    """Tests for save_json function."""

    def test_save_json_creates_file(self):
        """Test save_json creates a file with formatted JSON."""
        with TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "output.json"
            data = {"key": "value", "count": 42}

            save_json(data, output_path)

            assert output_path.exists()
            loaded = json.loads(output_path.read_text())
            assert loaded["key"] == "value"
            assert loaded["count"] == 42

    def test_save_json_formats_with_indentation(self):
        """Test save_json uses proper indentation."""
        with TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "output.json"
            data = {"nested": {"value": 1}}

            save_json(data, output_path)

            content = output_path.read_text()
            assert '  "nested"' in content  # Indented

    def test_save_json_handles_none_values(self):
        """Test save_json handles None values."""
        with TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "output.json"
            data = {"key": None, "other": "value"}

            save_json(data, output_path)

            loaded = json.loads(output_path.read_text())
            assert loaded["key"] is None

    def test_save_json_overwrites_existing(self):
        """Test save_json overwrites existing file."""
        with TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "output.json"
            output_path.write_text('{"old": "data"}')

            save_json({"new": "data"}, output_path)

            loaded = json.loads(output_path.read_text())
            assert loaded["new"] == "data"
            assert "old" not in loaded


class TestSaveCsv:
    """Tests for save_csv function."""

    def test_save_csv_creates_file(self):
        """Test save_csv creates a file with CSV content."""
        with TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "output.csv"
            headers = ["name", "value"]
            rows = [["foo", 1], ["bar", 2]]

            save_csv(headers, rows, output_path)

            assert output_path.exists()
            content = output_path.read_text()
            assert "name,value" in content
            assert "foo,1" in content

    def test_save_csv_handles_quoted_values(self):
        """Test save_csv properly quotes values with commas."""
        with TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "output.csv"
            headers = ["name", "description"]
            rows = [["item", "has, comma"]]

            save_csv(headers, rows, output_path)

            content = output_path.read_text()
            assert '"has, comma"' in content  # Quoted

    def test_save_csv_escapes_quotes(self):
        """Test save_csv escapes quotes in values."""
        with TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "output.csv"
            headers = ["name"]
            rows = [['value "with" quotes']]

            save_csv(headers, rows, output_path)

            content = output_path.read_text()
            # CSV escaping doubles quotes
            assert '""' in content

    def test_save_csv_empty_rows(self):
        """Test save_csv with empty rows."""
        with TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "output.csv"
            headers = ["col1", "col2"]
            rows = []

            save_csv(headers, rows, output_path)

            content = output_path.read_text()
            lines = content.strip().split("\n")
            assert len(lines) == 1  # Just header
            assert "col1,col2" in lines[0]


class TestHandleOutput:
    """Tests for handle_output function."""

    def test_handle_output_json_to_file(self):
        """Test handle_output with JSON format to file."""
        with TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "output.json"
            console = Console()
            data = {"test": "data"}

            handle_output("json", data, None, output_path, console)

            assert output_path.exists()
            loaded = json.loads(output_path.read_text())
            assert loaded["test"] == "data"

    def test_handle_output_csv_to_file(self):
        """Test handle_output with CSV format to file."""
        with TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "output.csv"
            console = Console()
            data = {"count": 2}
            csv_data = (["name", "value"], [["foo", "1"], ["bar", "2"]])

            handle_output("csv", data, csv_data, output_path, console)

            assert output_path.exists()
            content = output_path.read_text()
            assert "name,value" in content

    def test_handle_output_csv_none_falls_back_to_json(self):
        """Test handle_output with CSV format when csv_data is None."""
        with TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "output.csv"
            console = Console()
            data = {"test": "data"}

            # Should not raise, just print warning
            handle_output("csv", data, None, output_path, console)

    def test_handle_output_json_to_console(self):
        """Test handle_output with JSON format to console (no file)."""
        console = Console()
        data = {"test": "data"}

        # Should not raise
        handle_output("json", data, None, None, console)


class TestPrintJson:
    """Tests for print_json function."""

    def test_print_json_valid_data(self):
        """Test print_json with valid JSON data."""
        console = Console()
        data = {"key": "value"}

        # Should not raise
        print_json(data, console)


class TestPrintCsv:
    """Tests for print_csv function."""

    def test_print_csv_valid_data(self):
        """Test print_csv with valid CSV data."""
        console = Console()
        headers = ["name", "value"]
        rows = [["foo", 1]]

        # Should not raise
        print_csv(headers, rows, console)
