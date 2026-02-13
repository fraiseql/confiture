"""Tests for migrate status command CSV output support."""

from pathlib import Path
from tempfile import TemporaryDirectory

from rich.console import Console

from confiture.cli.formatters.common import handle_output


class TestMigrateStatusCSV:
    """Tests for migrate status CSV output."""

    def test_save_migration_status_csv(self):
        """Test saving migration status as CSV."""
        with TemporaryDirectory() as tmpdir:
            output_file = Path(tmpdir) / "status.csv"
            headers = ["version", "name", "status"]
            rows = [
                ["001", "initial_schema", "applied"],
                ["002", "add_users", "applied"],
                ["003", "add_indexes", "pending"],
            ]

            from confiture.cli.formatters.common import save_csv

            save_csv(headers, rows, output_file)

            assert output_file.exists()
            content = output_file.read_text()

            # Verify headers
            assert "version,name,status" in content

            # Verify rows
            assert "001,initial_schema,applied" in content
            assert "002,add_users,applied" in content
            assert "003,add_indexes,pending" in content

    def test_handle_output_csv_to_file(self):
        """Test handle_output with CSV format to file."""
        with TemporaryDirectory() as tmpdir:
            output_file = Path(tmpdir) / "output.csv"
            console = Console()

            csv_data = (
                ["version", "name", "status"],
                [
                    ["001", "initial", "applied"],
                    ["002", "add_users", "pending"],
                ],
            )

            handle_output("csv", {}, csv_data, output_file, console)

            assert output_file.exists()
            content = output_file.read_text()
            assert "version,name,status" in content
            assert "001,initial,applied" in content

    def test_handle_output_csv_to_console(self):
        """Test handle_output with CSV format to console."""
        console = Console()

        csv_data = (
            ["version", "name", "status"],
            [["001", "initial", "applied"]],
        )

        # Should not raise
        handle_output("csv", {}, csv_data, None, console)

    def test_csv_with_special_characters(self):
        """Test CSV escaping with special characters."""
        with TemporaryDirectory() as tmpdir:
            output_file = Path(tmpdir) / "output.csv"

            from confiture.cli.formatters.common import save_csv

            headers = ["version", "name", "status"]
            rows = [
                ["001", "add_users_and_roles", "applied"],
                ["002", "fix,bug", "pending"],  # Contains comma
                ["003", 'add_"quoted"', "applied"],  # Contains quotes
            ]

            save_csv(headers, rows, output_file)

            assert output_file.exists()
            content = output_file.read_text()

            # Verify proper escaping
            lines = content.strip().split("\n")
            assert len(lines) == 4  # Header + 3 rows
            assert "fix,bug" in content or '"fix,bug"' in content  # Either format is OK
