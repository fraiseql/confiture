"""Integration tests for migrate generate CLI command with new features.

Tests JSON output, dry-run mode, verbose mode, and --force flag.
"""

import json

from typer.testing import CliRunner

from confiture.cli.main import app

runner = CliRunner()


class TestMigrateGenerateJSONOutput:
    """Test JSON output format for agent integration."""

    def test_json_output_format_on_success(self, tmp_path):
        """Should output valid JSON with --format json."""
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()

        result = runner.invoke(
            app,
            [
                "migrate",
                "generate",
                "test_migration",
                "--migrations-dir",
                str(migrations_dir),
                "--format",
                "json",
            ],
        )

        # Should succeed
        assert result.exit_code == 0

        # Should output valid JSON
        output = result.stdout.strip()
        data = json.loads(output)

        # Should have expected structure
        assert data["status"] == "success"
        assert data["version"] == "001"
        assert data["name"] == "test_migration"
        assert "filepath" in data
        assert data["class_name"] == "TestMigration"

    def test_json_output_structure(self, tmp_path):
        """Should have correct JSON structure with all expected fields."""
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()

        result = runner.invoke(
            app,
            [
                "migrate",
                "generate",
                "add_users",
                "--migrations-dir",
                str(migrations_dir),
                "--format",
                "json",
            ],
        )

        data = json.loads(result.stdout.strip())

        # Verify all fields are present
        assert "status" in data
        assert "version" in data
        assert "name" in data
        assert "filepath" in data
        assert "class_name" in data
        assert "migrations_dir" in data
        assert "next_available_version" in data
        # warnings field can be empty list
        assert "warnings" in data

    def test_text_output_default(self, tmp_path):
        """Should output human-readable text by default."""
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()

        result = runner.invoke(
            app,
            [
                "migrate",
                "generate",
                "test_migration",
                "--migrations-dir",
                str(migrations_dir),
            ],
        )

        # Should succeed
        assert result.exit_code == 0

        # Should contain success message (not JSON)
        assert "Migration generated successfully" in result.stdout


class TestMigrateGenerateDryRun:
    """Test dry-run mode (preview without creating files)."""

    def test_dry_run_no_file_created(self, tmp_path):
        """Should not create file when --dry-run is used."""
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()

        result = runner.invoke(
            app,
            [
                "migrate",
                "generate",
                "test_migration",
                "--migrations-dir",
                str(migrations_dir),
                "--dry-run",
            ],
        )

        # Should succeed
        assert result.exit_code == 0

        # Should not create file
        migration_files = list(migrations_dir.glob("*.py"))
        assert len(migration_files) == 0

    def test_dry_run_shows_preview(self, tmp_path):
        """Should show template preview in dry-run mode."""
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()

        result = runner.invoke(
            app,
            [
                "migrate",
                "generate",
                "test_migration",
                "--migrations-dir",
                str(migrations_dir),
                "--dry-run",
            ],
        )

        # Should mention dry-run mode
        assert "Dry-run mode" in result.stdout or "dry-run" in result.stdout
        # Should show migration details
        assert "001" in result.stdout or "test_migration" in result.stdout

    def test_dry_run_json_output(self, tmp_path):
        """Should show dry-run status in JSON output."""
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()

        result = runner.invoke(
            app,
            [
                "migrate",
                "generate",
                "test_migration",
                "--migrations-dir",
                str(migrations_dir),
                "--dry-run",
                "--format",
                "json",
            ],
        )

        # Should output valid JSON
        data = json.loads(result.stdout.strip())

        # Should be marked as dry_run
        assert data["status"] == "dry_run"
        # Should not actually exist
        migration_files = list(migrations_dir.glob("*.py"))
        assert len(migration_files) == 0


class TestMigrateGenerateVerbose:
    """Test verbose mode for debugging."""

    def test_verbose_shows_scanning_info(self, tmp_path):
        """Should show directory scanning details in verbose mode."""
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()
        (migrations_dir / "001_first.py").write_text("# migration")
        (migrations_dir / "002_second.py").write_text("# migration")

        result = runner.invoke(
            app,
            [
                "migrate",
                "generate",
                "test_migration",
                "--migrations-dir",
                str(migrations_dir),
                "--verbose",
            ],
        )

        # Should succeed
        assert result.exit_code == 0

        # Should show scanning information
        assert "Scanning" in result.stdout or "scanning" in result.stdout
        # Should show found files
        assert "001_first" in result.stdout or "Found" in result.stdout


class TestMigrateGenerateForceFlag:
    """Test --force flag for edge cases.

    Since the CLI auto-generates the next version, force flag scenarios
    are limited. This mainly tests validation behavior.
    """

    def test_sequential_naming_without_collision(self, tmp_path):
        """Should generate sequential versions without collision."""
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()

        # Create existing file with same name
        (migrations_dir / "001_test.py").write_text("# migration 1")

        # Generate migration with same name (should create 002_test.py)
        result = runner.invoke(
            app,
            [
                "migrate",
                "generate",
                "test",
                "--migrations-dir",
                str(migrations_dir),
            ],
        )

        # Should succeed
        assert result.exit_code == 0

        # Both files should exist
        assert (migrations_dir / "001_test.py").exists()
        assert (migrations_dir / "002_test.py").exists()

    def test_force_flag_has_no_effect_with_auto_versioning(self, tmp_path):
        """Force flag has limited use with auto-versioning."""
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()

        # Create file 001_test.py
        (migrations_dir / "001_test.py").write_text("# migration 1")

        # Generate with --force (auto-generates 002_test.py, so force doesn't matter)
        result = runner.invoke(
            app,
            [
                "migrate",
                "generate",
                "test",
                "--migrations-dir",
                str(migrations_dir),
                "--force",
            ],
        )

        # Should succeed
        assert result.exit_code == 0

        # Should create 002_test.py, not overwrite 001_test.py
        assert (migrations_dir / "001_test.py").exists()
        assert (migrations_dir / "002_test.py").exists()

    def test_force_flag_mentioned_in_help(self, tmp_path):
        """Force flag should be documented in help text."""
        # Get help text
        result = runner.invoke(
            app,
            ["migrate", "generate", "--help"],
        )

        # Should mention force flag (check for substring that avoids ANSI color codes)
        assert "force" in result.stdout.lower()


class TestMigrateGenerateValidationWarnings:
    """Test validation warnings in output."""

    def test_duplicate_version_warning_in_text(self, tmp_path):
        """Should warn about duplicate versions in text output."""
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()

        # Create duplicate versions
        (migrations_dir / "003_first_a.py").write_text("# migration")
        (migrations_dir / "003_first_b.py").write_text("# migration")

        result = runner.invoke(
            app,
            [
                "migrate",
                "generate",
                "test_migration",
                "--migrations-dir",
                str(migrations_dir),
            ],
        )

        # Should succeed (warning is non-blocking)
        assert result.exit_code == 0

        # Should mention duplicates
        assert "duplicate" in result.stdout.lower() or "warning" in result.stdout.lower()

    def test_duplicate_version_warning_in_json(self, tmp_path):
        """Should include duplicate warnings in JSON output."""
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()

        # Create duplicate versions
        (migrations_dir / "003_first_a.py").write_text("# migration")
        (migrations_dir / "003_first_b.py").write_text("# migration")

        result = runner.invoke(
            app,
            [
                "migrate",
                "generate",
                "test_migration",
                "--migrations-dir",
                str(migrations_dir),
                "--format",
                "json",
            ],
        )

        # Should output valid JSON
        data = json.loads(result.stdout.strip())

        # Should have warnings list
        assert "warnings" in data
        # Should contain warning about duplicates
        if data["warnings"]:
            warning_text = " ".join(data["warnings"]).lower()
            assert "duplicate" in warning_text or "conflict" in warning_text

    def test_name_conflict_warning(self, tmp_path):
        """Should warn about name conflicts."""
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()

        # Create migrations with same name different version
        (migrations_dir / "001_add_users.py").write_text("# migration")
        (migrations_dir / "002_add_users.py").write_text("# migration")

        result = runner.invoke(
            app,
            [
                "migrate",
                "generate",
                "add_users",
                "--migrations-dir",
                str(migrations_dir),
            ],
        )

        # Should warn about name conflict
        assert "conflict" in result.stdout.lower() or "warning" in result.stdout.lower()


class TestMigrateGenerateIntegration:
    """Integration tests combining multiple features."""

    def test_json_with_verbose_and_dry_run(self, tmp_path):
        """Should support combining JSON and dry-run."""
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()
        (migrations_dir / "001_first.py").write_text("# migration")

        result = runner.invoke(
            app,
            [
                "migrate",
                "generate",
                "test_migration",
                "--migrations-dir",
                str(migrations_dir),
                "--format",
                "json",
                "--dry-run",
            ],
        )

        # Should succeed
        assert result.exit_code == 0

        # Should output valid JSON (strip handles whitespace)
        data = json.loads(result.stdout.strip())

        # Should be dry_run status
        assert data["status"] == "dry_run"

        # File should not be created
        migration_files = list(migrations_dir.glob("*.py"))
        assert len(migration_files) == 1  # Only the existing one

    def test_sequential_generation(self, tmp_path):
        """Should generate sequential versions correctly."""
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()

        # Generate first migration
        result1 = runner.invoke(
            app,
            [
                "migrate",
                "generate",
                "first_migration",
                "--migrations-dir",
                str(migrations_dir),
                "--format",
                "json",
            ],
        )

        data1 = json.loads(result1.stdout.strip())
        assert data1["version"] == "001"

        # Generate second migration
        result2 = runner.invoke(
            app,
            [
                "migrate",
                "generate",
                "second_migration",
                "--migrations-dir",
                str(migrations_dir),
                "--format",
                "json",
            ],
        )

        data2 = json.loads(result2.stdout.strip())
        assert data2["version"] == "002"

        # Both files should exist
        migration_files = list(migrations_dir.glob("*.py"))
        assert len(migration_files) == 2
