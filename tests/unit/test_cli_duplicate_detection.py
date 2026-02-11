"""Unit tests for CLI duplicate version detection in validate and status commands."""

import json

from typer.testing import CliRunner

from confiture.cli.main import app

runner = CliRunner()


class TestMigrateValidateDuplicates:
    """Test that 'migrate validate' reports duplicate versions."""

    def test_validate_reports_duplicates_text(self, tmp_path):
        """validate should report duplicate versions in text format and exit 1."""
        migrations_dir = tmp_path / "db" / "migrations"
        migrations_dir.mkdir(parents=True)
        (migrations_dir / "001_create_users.py").write_text("# migration a")
        (migrations_dir / "001_backfill_data.up.sql").write_text("INSERT INTO;")

        result = runner.invoke(
            app,
            ["migrate", "validate", "--migrations-dir", str(migrations_dir)],
        )

        assert result.exit_code == 1
        assert "001" in result.output
        assert "duplicate" in result.output.lower() or "Duplicate" in result.output

    def test_validate_reports_duplicates_json(self, tmp_path):
        """validate should report duplicate versions in JSON format and exit 1."""
        migrations_dir = tmp_path / "db" / "migrations"
        migrations_dir.mkdir(parents=True)
        (migrations_dir / "001_create_users.py").write_text("# migration a")
        (migrations_dir / "001_backfill_data.up.sql").write_text("INSERT INTO;")

        result = runner.invoke(
            app,
            [
                "migrate",
                "validate",
                "--migrations-dir",
                str(migrations_dir),
                "--format",
                "json",
            ],
        )

        assert result.exit_code == 1
        data = json.loads(result.output)
        assert "duplicate_versions" in data
        assert "001" in data["duplicate_versions"]

    def test_validate_clean_when_no_duplicates(self, tmp_path):
        """validate should pass clean when there are no duplicates or orphans."""
        migrations_dir = tmp_path / "db" / "migrations"
        migrations_dir.mkdir(parents=True)
        (migrations_dir / "001_create_users.py").write_text("# migration a")
        (migrations_dir / "002_add_email.up.sql").write_text("ALTER TABLE;")

        result = runner.invoke(
            app,
            ["migrate", "validate", "--migrations-dir", str(migrations_dir)],
        )

        assert result.exit_code == 0


class TestMigrateStatusDuplicates:
    """Test that 'migrate status' warns about duplicate versions."""

    def test_status_warns_about_duplicates_text(self, tmp_path):
        """status should warn about duplicates but still exit 0."""
        migrations_dir = tmp_path / "db" / "migrations"
        migrations_dir.mkdir(parents=True)
        (migrations_dir / "001_create_users.py").write_text("# migration a")
        (migrations_dir / "001_backfill_data.up.sql").write_text("INSERT INTO;")

        result = runner.invoke(
            app,
            ["migrate", "status", "--migrations-dir", str(migrations_dir)],
        )

        assert result.exit_code == 0
        assert "duplicate" in result.output.lower() or "Duplicate" in result.output

    def test_status_warns_about_duplicates_json(self, tmp_path):
        """status should include duplicate_versions in JSON output and exit 0."""
        migrations_dir = tmp_path / "db" / "migrations"
        migrations_dir.mkdir(parents=True)
        (migrations_dir / "001_create_users.py").write_text("# migration a")
        (migrations_dir / "001_backfill_data.up.sql").write_text("INSERT INTO;")

        result = runner.invoke(
            app,
            [
                "migrate",
                "status",
                "--migrations-dir",
                str(migrations_dir),
                "--format",
                "json",
            ],
        )

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "duplicate_versions" in data
        assert "001" in data["duplicate_versions"]

    def test_status_clean_when_no_duplicates(self, tmp_path):
        """status should not mention duplicates when there are none."""
        migrations_dir = tmp_path / "db" / "migrations"
        migrations_dir.mkdir(parents=True)
        (migrations_dir / "001_create_users.py").write_text("# migration a")
        (migrations_dir / "002_add_email.up.sql").write_text("ALTER TABLE;")

        result = runner.invoke(
            app,
            ["migrate", "status", "--migrations-dir", str(migrations_dir)],
        )

        assert result.exit_code == 0
        assert "duplicate" not in result.output.lower()
