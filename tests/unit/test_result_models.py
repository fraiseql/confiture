"""Tests for command result models.

Validates BuildResult, MigrateUpResult, and related dataclasses
used for structured output (JSON/CSV).
"""

import pytest

from confiture.models.results import (
    BuildResult,
    BuildWarning,
    MigrateUpResult,
    MigrationApplied,
)


class TestBuildWarning:
    """A build diagnostic that reaches the envelope, not only the console (#268)."""

    def test_the_registry_states_both_the_severity_and_the_sentence(self):
        """One place says what a code means, so the payload cannot disagree with the codebook."""
        warning = BuildWarning.of("SEED_002", count=2)

        assert warning.to_dict() == {
            "code": "SEED_002",
            "severity": "warning",
            "message": "2 seed file(s) failed",
            "file": None,
        }

    def test_a_warning_can_name_the_file_it_is_about(self):
        """The duplicate scan skips one file at a time; the entry says which."""
        warning = BuildWarning.of("SCHEMA_206", file="db/schema/10_tables/odd.sql")

        assert warning.to_dict()["file"] == "db/schema/10_tables/odd.sql"
        assert warning.to_dict()["severity"] == "warning"
        assert warning.message.startswith("db/schema/10_tables/odd.sql: pglast could not parse")

    def test_an_unregistered_code_is_refused(self):
        """A warning whose code no consumer can look up is a bug, not a payload."""
        with pytest.raises(ValueError, match="NOPE_999"):
            BuildWarning.of("NOPE_999")

    def test_a_template_placeholder_nobody_filled_is_refused(self):
        """A half-written sentence never reaches a consumer."""
        with pytest.raises(KeyError):
            BuildWarning.of("SEED_002")


class TestBuildResult:
    """Tests for BuildResult dataclass."""

    def test_build_result_success(self):
        """Test successful build result creation and serialization."""
        result = BuildResult(
            success=True,
            files_processed=10,
            schema_size_bytes=5000,
            output_path="/path/to/schema.sql",
            hash="abc123def456",
            execution_time_ms=150,
            seed_files_applied=3,
        )

        assert result.success is True
        assert result.files_processed == 10
        assert result.schema_size_bytes == 5000
        assert result.output_path == "/path/to/schema.sql"
        assert result.hash == "abc123def456"
        assert result.execution_time_ms == 150
        assert result.seed_files_applied == 3

    def test_build_result_failure(self):
        """Test failed build result with error message."""
        result = BuildResult(
            success=False,
            files_processed=0,
            schema_size_bytes=0,
            output_path="",
            error="Connection failed",
        )

        assert result.success is False
        assert result.error == "Connection failed"

    def test_build_result_to_dict_success(self):
        """Test BuildResult.to_dict() for successful build."""
        result = BuildResult(
            success=True,
            files_processed=10,
            schema_size_bytes=5000,
            output_path="/path/to/schema.sql",
            hash="abc123",
            execution_time_ms=150,
            seed_files_applied=3,
            warnings=[BuildWarning.of("SEED_002", count=1)],
        )

        data = result.to_dict()

        assert data["success"] is True
        assert data["files_processed"] == 10
        assert data["schema_size_bytes"] == 5000
        assert data["output_path"] == "/path/to/schema.sql"
        assert data["hash"] == "abc123"
        assert data["execution_time_ms"] == 150
        assert data["seed_files_applied"] == 3
        assert data["warnings"] == [
            {
                "code": "SEED_002",
                "severity": "warning",
                "message": "1 seed file(s) failed",
                "file": None,
            }
        ]
        assert "error" in data

    def test_build_result_to_dict_failure(self):
        """Test BuildResult.to_dict() for failed build."""
        result = BuildResult(
            success=False,
            files_processed=0,
            schema_size_bytes=0,
            output_path="",
            error="Connection failed",
        )

        data = result.to_dict()

        assert data["success"] is False
        assert data["error"] == "Connection failed"
        assert data["files_processed"] == 0

    def test_build_result_defaults(self):
        """Test BuildResult uses sensible defaults."""
        result = BuildResult(
            success=True,
            files_processed=5,
            schema_size_bytes=1000,
            output_path="/tmp/schema.sql",
        )

        assert result.hash is None
        assert result.execution_time_ms == 0
        assert result.seed_files_applied == 0
        assert result.warnings == []
        assert result.error is None


class TestMigrationApplied:
    """Tests for MigrationApplied dataclass."""

    def test_migration_applied_creation(self):
        """Test MigrationApplied creation with all fields."""
        migration = MigrationApplied(
            version="001",
            name="initial_schema",
            duration_ms=100,
            rows_affected=50,
        )

        assert migration.version == "001"
        assert migration.name == "initial_schema"
        assert migration.duration_ms == 100
        assert migration.rows_affected == 50

    def test_migration_applied_to_dict(self):
        """Test MigrationApplied.to_dict()."""
        migration = MigrationApplied(
            version="002",
            name="add_users_table",
            duration_ms=200,
            rows_affected=0,
        )

        data = migration.to_dict()

        assert data["version"] == "002"
        assert data["name"] == "add_users_table"
        assert data["duration_ms"] == 200
        assert data["rows_affected"] == 0

    def test_migration_applied_defaults(self):
        """Test MigrationApplied uses sensible defaults."""
        migration = MigrationApplied(
            version="003",
            name="add_indexes",
            duration_ms=300,
        )

        assert migration.rows_affected == 0


class TestMigrateUpResult:
    """Tests for MigrateUpResult dataclass."""

    def test_migrate_up_result_success(self):
        """Test successful migrate up result."""
        migrations = [
            MigrationApplied("001", "initial", 100, 50),
            MigrationApplied("002", "add_users", 200, 0),
        ]

        result = MigrateUpResult(
            success=True,
            migrations_applied=migrations,
            total_duration_ms=300,
        )

        assert result.success is True
        assert len(result.migrations_applied) == 2
        assert result.total_duration_ms == 300
        assert result.checksums_verified is True
        assert result.dry_run is False

    def test_migrate_up_result_failure(self):
        """Test failed migrate up result."""
        result = MigrateUpResult(
            success=False,
            migrations_applied=[],
            total_duration_ms=0,
            errors=["Migration conflict"],
        )

        assert result.success is False
        assert result.has_errors is True
        assert result.error_summary == "Migration conflict"
        assert len(result.migrations_applied) == 0

    def test_migrate_up_result_to_dict(self):
        """Test MigrateUpResult.to_dict()."""
        migrations = [
            MigrationApplied("001", "initial", 100),
            MigrationApplied("002", "add_users", 200),
        ]

        result = MigrateUpResult(
            success=True,
            migrations_applied=migrations,
            total_duration_ms=300,
            checksums_verified=True,
            dry_run=False,
            warnings=["Check indexes"],
        )

        data = result.to_dict()

        assert data["success"] is True
        assert len(data["applied"]) == 2
        assert data["applied"][0]["version"] == "001"
        assert data["applied"][1]["version"] == "002"
        assert data["total_duration_ms"] == 300
        assert data["checksums_verified"] is True
        assert data["dry_run"] is False
        assert data["warnings"] == ["Check indexes"]

    def test_migrate_up_result_empty(self):
        """Test migrate up result with no migrations applied."""
        result = MigrateUpResult(
            success=True,
            migrations_applied=[],
            total_duration_ms=0,
        )

        data = result.to_dict()

        assert data["success"] is True
        assert len(data["applied"]) == 0

    def test_migrate_up_result_dry_run(self):
        """Test migrate up result in dry-run mode."""
        migrations = [
            MigrationApplied("001", "initial", 50),
        ]

        result = MigrateUpResult(
            success=True,
            migrations_applied=migrations,
            total_duration_ms=50,
            dry_run=True,
        )

        data = result.to_dict()

        assert data["dry_run"] is True
        assert data["success"] is True
