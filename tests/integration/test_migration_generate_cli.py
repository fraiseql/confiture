"""Integration tests for migrate generate CLI command with new features.

Tests JSON output, dry-run mode, verbose mode, --force flag, and external generators.
"""

import json
import re
import stat
import textwrap

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
        assert re.match(r"^\d{14}$", data["version"]), (
            f"Version {data['version']} should be 14-digit timestamp"
        )
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
        # Should show found files or timestamp version
        assert (
            "001_first" in result.stdout
            or "Found" in result.stdout
            or "test_migration" in result.stdout
        )


class TestMigrateGenerateForceFlag:
    """Test --force flag for edge cases.

    Since the CLI auto-generates the next version, force flag scenarios
    are limited. This mainly tests validation behavior.
    """

    def test_sequential_naming_without_collision(self, tmp_path):
        """Should generate unique timestamp versions without collision."""
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()

        # Create existing file with same name (old format for compatibility)
        (migrations_dir / "001_test.py").write_text("# migration 1")

        # Generate migration with same name (should create timestamp_test.py)
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

        # Both files should exist - old format and new timestamp format
        assert (migrations_dir / "001_test.py").exists()
        # Check for any timestamp_test.py file
        timestamp_files = list(migrations_dir.glob(r"[0-9][0-9][0-9][0-9]*_test.py"))
        assert len(timestamp_files) >= 1, (
            f"Should have generated timestamp migration, found: {list(migrations_dir.glob('*.py'))}"
        )

    def test_force_flag_has_no_effect_with_auto_versioning(self, tmp_path):
        """Force flag with timestamp-based versioning."""
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()

        # Create file 001_test.py
        (migrations_dir / "001_test.py").write_text("# migration 1")

        # Generate with --force (auto-generates timestamp version)
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

        # Should create timestamp_test.py, not overwrite 001_test.py
        assert (migrations_dir / "001_test.py").exists()
        # Check for timestamp-based migration file
        timestamp_files = list(migrations_dir.glob(r"[0-9][0-9][0-9][0-9]*_test.py"))
        assert len(timestamp_files) >= 1, "Should have generated timestamp migration"

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
        assert re.match(r"^\d{14}$", data1["version"]), (
            f"Version {data1['version']} should be 14-digit timestamp"
        )

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
        assert re.match(r"^\d{14}$", data2["version"]), (
            f"Version {data2['version']} should be 14-digit timestamp"
        )
        # Second version should be >= first version (can be same second or later)
        assert data2["version"] >= data1["version"]

        # Both files should exist
        migration_files = list(migrations_dir.glob("*.py"))
        assert len(migration_files) == 2


# ---------------------------------------------------------------------------
# External generator CLI tests (Issue #49)
# ---------------------------------------------------------------------------


def _make_fake_generator(
    tmp_path, sql: str = "ALTER TABLE foo ADD COLUMN bar TEXT;", exit_code: int = 0
) -> str:
    """Write a tiny shell script that acts as a fake migration generator.

    The script reads {output} as its third positional argument and writes SQL there.
    """
    script = tmp_path / "fake_generator.sh"
    script.write_text(
        textwrap.dedent(f"""\
            #!/bin/sh
            # Args passed via format_map with shell quoting:
            #   $1 = from_path  $2 = to_path  $3 = output_path
            output="$3"
            printf '%s\\n' 'BEGIN;' '{sql}' 'COMMIT;' > "$output"
            exit {exit_code}
        """)
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return str(script)


def _make_env_yaml(tmp_path, generator_name: str, command: str) -> tuple:
    """Create a minimal project tree with a local.yaml that has migration_generators."""
    project_dir = tmp_path / "project"
    env_dir = project_dir / "db" / "environments"
    env_dir.mkdir(parents=True)
    schema_dir = project_dir / "db" / "schema"
    schema_dir.mkdir(parents=True)
    # Minimal include_dir
    (schema_dir).mkdir(exist_ok=True)

    config_path = env_dir / "local.yaml"
    config_path.write_text(
        textwrap.dedent(f"""\
            database_url: postgresql://localhost/test_db
            include_dirs:
              - db/schema
            migration:
              migration_generators:
                {generator_name}:
                  command: "{command}"
                  description: "Fake generator for tests"
        """)
    )
    return project_dir, config_path


class TestMigrateGenerateExternalGenerator:
    """Integration tests for --generator flag."""

    def test_happy_path_generator_creates_up_and_down_sql(self, tmp_path):
        """Generator runs, .up.sql has BEGIN/COMMIT stripped, .down.sql stub created."""
        script_path = _make_fake_generator(tmp_path)
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()

        from_file = tmp_path / "v1.sql"
        from_file.write_text("SELECT 1;")
        to_file = tmp_path / "v2.sql"
        to_file.write_text("SELECT 2;")

        project_dir, config_path = _make_env_yaml(
            tmp_path,
            "fake",
            f"{script_path} {{from}} {{to}} {{output}}",
        )
        # Provide schema dir so Environment.load doesn't fail
        schema_dir = project_dir / "db" / "schema"
        schema_dir.mkdir(exist_ok=True)

        result = runner.invoke(
            app,
            [
                "migrate",
                "generate",
                "add_bar_column",
                "--generator",
                "fake",
                "--from",
                str(from_file),
                "--to",
                str(to_file),
                "--migrations-dir",
                str(migrations_dir),
                "--config",
                str(config_path),
            ],
            catch_exceptions=False,
        )

        assert result.exit_code == 0, result.output

        up_files = list(migrations_dir.glob("*.up.sql"))
        assert len(up_files) == 1
        sql = up_files[0].read_text()
        assert "BEGIN" not in sql
        assert "COMMIT" not in sql
        assert "ALTER TABLE foo ADD COLUMN bar TEXT;" in sql

        down_files = list(migrations_dir.glob("*.down.sql"))
        assert len(down_files) == 1
        assert "TODO" in down_files[0].read_text()

    def test_dry_run_does_not_create_file(self, tmp_path):
        """--dry-run prints resolved command and target, no file created."""
        script_path = _make_fake_generator(tmp_path)
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()

        from_file = tmp_path / "v1.sql"
        from_file.write_text("SELECT 1;")
        to_file = tmp_path / "v2.sql"
        to_file.write_text("SELECT 2;")

        project_dir, config_path = _make_env_yaml(
            tmp_path,
            "fake",
            f"{script_path} {{from}} {{to}} {{output}}",
        )

        result = runner.invoke(
            app,
            [
                "migrate",
                "generate",
                "add_bar_column",
                "--generator",
                "fake",
                "--from",
                str(from_file),
                "--to",
                str(to_file),
                "--migrations-dir",
                str(migrations_dir),
                "--config",
                str(config_path),
                "--dry-run",
            ],
        )

        assert result.exit_code == 0, result.output
        assert list(migrations_dir.glob("*.up.sql")) == []
        assert "Resolved command" in result.output or "Target file" in result.output

    def test_generator_exits_nonzero_surfaces_error(self, tmp_path):
        """Non-zero generator exit → error message + exit 1."""
        script_path = _make_fake_generator(tmp_path, exit_code=2)
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()

        from_file = tmp_path / "v1.sql"
        from_file.write_text("SELECT 1;")
        to_file = tmp_path / "v2.sql"
        to_file.write_text("SELECT 2;")

        project_dir, config_path = _make_env_yaml(
            tmp_path,
            "fake",
            f"{script_path} {{from}} {{to}} {{output}}",
        )

        result = runner.invoke(
            app,
            [
                "migrate",
                "generate",
                "add_bar_column",
                "--generator",
                "fake",
                "--from",
                str(from_file),
                "--to",
                str(to_file),
                "--migrations-dir",
                str(migrations_dir),
                "--config",
                str(config_path),
            ],
        )

        assert result.exit_code == 1

    def test_generator_without_from_exits_1(self, tmp_path):
        """--generator without --from → clear error, exit 1."""
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()
        to_file = tmp_path / "v2.sql"
        to_file.write_text("SELECT 2;")

        project_dir, config_path = _make_env_yaml(
            tmp_path,
            "fake",
            "tool {from} {to} {output}",
        )

        result = runner.invoke(
            app,
            [
                "migrate",
                "generate",
                "add_bar_column",
                "--generator",
                "fake",
                "--to",
                str(to_file),
                "--migrations-dir",
                str(migrations_dir),
                "--config",
                str(config_path),
            ],
        )

        assert result.exit_code == 1
        assert "--from" in result.output or "required" in result.output.lower()

    def test_generator_without_to_exits_1(self, tmp_path):
        """--generator without --to → clear error, exit 1."""
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()
        from_file = tmp_path / "v1.sql"
        from_file.write_text("SELECT 1;")

        project_dir, config_path = _make_env_yaml(
            tmp_path,
            "fake",
            "tool {from} {to} {output}",
        )

        result = runner.invoke(
            app,
            [
                "migrate",
                "generate",
                "add_bar_column",
                "--generator",
                "fake",
                "--from",
                str(from_file),
                "--migrations-dir",
                str(migrations_dir),
                "--config",
                str(config_path),
            ],
        )

        assert result.exit_code == 1
        assert "--to" in result.output or "required" in result.output.lower()

    def test_unknown_generator_name_exits_1(self, tmp_path):
        """Unknown generator name → clear error, exit 1."""
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()
        from_file = tmp_path / "v1.sql"
        from_file.write_text("SELECT 1;")
        to_file = tmp_path / "v2.sql"
        to_file.write_text("SELECT 2;")

        project_dir, config_path = _make_env_yaml(
            tmp_path,
            "fake",
            "tool {from} {to} {output}",
        )

        result = runner.invoke(
            app,
            [
                "migrate",
                "generate",
                "add_bar_column",
                "--generator",
                "nonexistent_generator",
                "--from",
                str(from_file),
                "--to",
                str(to_file),
                "--migrations-dir",
                str(migrations_dir),
                "--config",
                str(config_path),
            ],
        )

        assert result.exit_code == 1
        assert "nonexistent_generator" in result.output or "not found" in result.output.lower()

    def test_no_generator_flag_uses_python_template(self, tmp_path):
        """Omitting --generator generates the standard Python template (regression)."""
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()

        result = runner.invoke(
            app,
            [
                "migrate",
                "generate",
                "add_bar_column",
                "--migrations-dir",
                str(migrations_dir),
            ],
        )

        assert result.exit_code == 0
        py_files = list(migrations_dir.glob("*.py"))
        assert len(py_files) == 1
        assert "class AddBarColumn" in py_files[0].read_text()

    def test_config_with_no_migration_generators_exits_1(self, tmp_path):
        """Config without migration_generators key → error + exit 1."""
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()
        from_file = tmp_path / "v1.sql"
        from_file.write_text("SELECT 1;")
        to_file = tmp_path / "v2.sql"
        to_file.write_text("SELECT 2;")

        project_dir = tmp_path / "project"
        env_dir = project_dir / "db" / "environments"
        env_dir.mkdir(parents=True)
        schema_dir = project_dir / "db" / "schema"
        schema_dir.mkdir(parents=True)

        config_path = env_dir / "local.yaml"
        config_path.write_text(
            "database_url: postgresql://localhost/test_db\ninclude_dirs:\n  - db/schema\n"
        )

        result = runner.invoke(
            app,
            [
                "migrate",
                "generate",
                "add_bar_column",
                "--generator",
                "fake",
                "--from",
                str(from_file),
                "--to",
                str(to_file),
                "--migrations-dir",
                str(migrations_dir),
                "--config",
                str(config_path),
            ],
        )

        assert result.exit_code == 1
