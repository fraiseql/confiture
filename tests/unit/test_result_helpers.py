"""Tests for helper methods and properties on result models."""

from confiture.models.results import (
    MigrateUpResult,
    MigrationApplied,
    MigrationInfo,
    MigrationStatus,
    StatusResult,
)


class TestMigrateUpResultHasErrors:
    def test_migrate_up_result_has_errors_true(self) -> None:
        result = MigrateUpResult(
            success=False,
            migrations_applied=[],
            total_execution_time_ms=0,
            errors=["fail"],
        )
        assert result.has_errors is True

    def test_migrate_up_result_has_errors_false(self) -> None:
        result = MigrateUpResult(
            success=True,
            migrations_applied=[],
            total_execution_time_ms=0,
            errors=[],
        )
        assert result.has_errors is False


class TestMigrateUpResultErrorSummary:
    def test_migrate_up_result_error_summary_with_errors(self) -> None:
        result = MigrateUpResult(
            success=False,
            migrations_applied=[],
            total_execution_time_ms=0,
            errors=["first", "second"],
        )
        assert result.error_summary == "first"

    def test_migrate_up_result_error_summary_empty(self) -> None:
        result = MigrateUpResult(
            success=True,
            migrations_applied=[],
            total_execution_time_ms=0,
            errors=[],
        )
        assert result.error_summary is None


class TestMigrateUpResultByVersion:
    def test_migrate_up_result_by_version_found(self) -> None:
        m1 = MigrationApplied(version="001", name="create_users", execution_time_ms=10)
        m2 = MigrationApplied(version="002", name="add_email", execution_time_ms=20)
        result = MigrateUpResult(
            success=True,
            migrations_applied=[m1, m2],
            total_execution_time_ms=30,
        )
        found = result.by_version("002")
        assert found is not None
        assert found.name == "add_email"
        assert found.execution_time_ms == 20

    def test_migrate_up_result_by_version_not_found(self) -> None:
        m1 = MigrationApplied(version="001", name="create_users", execution_time_ms=10)
        result = MigrateUpResult(
            success=True,
            migrations_applied=[m1],
            total_execution_time_ms=10,
        )
        assert result.by_version("999") is None


class TestStatusResultGetMigration:
    def test_status_result_get_migration_found(self) -> None:
        migrations = [
            MigrationInfo(version="001", name="create_users", status="applied"),
            MigrationInfo(version="002", name="add_email", status="pending"),
        ]
        status = StatusResult(
            migrations=migrations,
            tracking_table_exists=True,
            tracking_table="tb_confiture",
            summary={"applied": 1, "pending": 1, "total": 2},
        )
        found = status.get_migration("002")
        assert found is not None
        assert found.name == "add_email"
        assert found.status == "pending"

    def test_status_result_get_migration_not_found(self) -> None:
        status = StatusResult(
            migrations=[
                MigrationInfo(version="001", name="create_users", status="applied"),
            ],
            tracking_table_exists=True,
            tracking_table="tb_confiture",
            summary={"applied": 1, "pending": 0, "total": 1},
        )
        assert status.get_migration("999") is None


class TestStatusResultGetStatus:
    def test_status_result_get_status(self) -> None:
        migrations = [
            MigrationInfo(version="001", name="create_users", status="applied"),
            MigrationInfo(version="002", name="add_email", status="pending"),
        ]
        status = StatusResult(
            migrations=migrations,
            tracking_table_exists=True,
            tracking_table="tb_confiture",
            summary={"applied": 1, "pending": 1, "total": 2},
        )
        assert status.get_status("001") == "applied"
        assert status.get_status("002") == "pending"
        assert status.get_status("999") is None


class TestMigrationStatusConstants:
    def test_migration_status_constants(self) -> None:
        assert MigrationStatus.APPLIED == "applied"
        assert MigrationStatus.PENDING == "pending"
        assert MigrationStatus.UNKNOWN == "unknown"

    def test_migration_status_exported(self) -> None:
        from confiture import MigrationStatus as Exported

        assert Exported.APPLIED == "applied"
        assert Exported.PENDING == "pending"
        assert Exported.UNKNOWN == "unknown"
