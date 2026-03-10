"""Test that timing keys are consistent across all result types."""

from confiture.models.results import (
    MigrateDownResult,
    MigrateRebuildResult,
    MigrateReinitResult,
    MigrateUpResult,
    MigrationApplied,
)


def test_migrate_up_result_timing_key() -> None:
    """Test MigrateUpResult uses total_duration_ms."""
    result = MigrateUpResult(
        success=True,
        migrations_applied=[],
        total_execution_time_ms=1000,
    )
    result_dict = result.to_dict()
    assert "total_duration_ms" in result_dict
    assert result_dict["total_duration_ms"] == 1000


def test_migrate_down_result_timing_key() -> None:
    """Test MigrateDownResult uses total_duration_ms."""
    result = MigrateDownResult(
        success=True,
        migrations_rolled_back=[],
        total_execution_time_ms=500,
    )
    result_dict = result.to_dict()
    assert "total_duration_ms" in result_dict
    assert result_dict["total_duration_ms"] == 500
    # Should use "rolled_back" as key instead of "migrations_rolled_back"
    assert "rolled_back" in result_dict


def test_migrate_reinit_result_timing_key() -> None:
    """Test MigrateReinitResult uses total_duration_ms."""
    result = MigrateReinitResult(
        success=True,
        deleted_count=1,
        migrations_marked=[],
        total_execution_time_ms=300,
    )
    result_dict = result.to_dict()
    assert "total_duration_ms" in result_dict
    assert result_dict["total_duration_ms"] == 300
    # Should use "marked" as key instead of "migrations_marked"
    assert "marked" in result_dict
    # Should NOT have "count" as it's redundant with len(marked)
    assert "count" not in result_dict


def test_migrate_rebuild_result_timing_key() -> None:
    """Test MigrateRebuildResult uses total_duration_ms and 'marked' collection key."""
    result = MigrateRebuildResult(
        success=True,
        schemas_dropped=[],
        ddl_statements_executed=0,
        migrations_marked=[MigrationApplied(version="001", name="test", execution_time_ms=10)],
        total_execution_time_ms=2000,
    )
    result_dict = result.to_dict()
    assert "total_duration_ms" in result_dict
    assert result_dict["total_duration_ms"] == 2000
    assert "marked" in result_dict
    assert "migrations_marked" not in result_dict


def test_all_result_types_use_consistent_collection_keys() -> None:
    """All result types should use short keys for migration collections in JSON."""
    up = MigrateUpResult(migrations_applied=[], total_execution_time_ms=0, success=True)
    assert "applied" in up.to_dict()
    assert "migrations_applied" not in up.to_dict()

    down = MigrateDownResult(migrations_rolled_back=[], total_execution_time_ms=0, success=True)
    assert "rolled_back" in down.to_dict()
    assert "migrations_rolled_back" not in down.to_dict()

    reinit = MigrateReinitResult(
        migrations_marked=[], total_execution_time_ms=0, success=True, deleted_count=0
    )
    assert "marked" in reinit.to_dict()
    assert "migrations_marked" not in reinit.to_dict()

    rebuild = MigrateRebuildResult(
        migrations_marked=[],
        total_execution_time_ms=0,
        success=True,
        schemas_dropped=[],
        ddl_statements_executed=0,
    )
    assert "marked" in rebuild.to_dict()
    assert "migrations_marked" not in rebuild.to_dict()


def test_migration_applied_timing_key() -> None:
    """Test MigrationApplied uses duration_ms."""
    migration = MigrationApplied(
        version="001",
        name="init",
        execution_time_ms=100,
    )
    migration_dict = migration.to_dict()
    assert "duration_ms" in migration_dict
    assert migration_dict["duration_ms"] == 100
    # Should NOT have execution_time_ms as that's internal field name
    assert "execution_time_ms" not in migration_dict


def test_all_result_types_use_consistent_timing() -> None:
    """Test all result types use consistent timing keys."""
    # Create instances with sample data
    migration = MigrationApplied(version="001", name="test", execution_time_ms=100)
    up_result = MigrateUpResult(
        success=True,
        migrations_applied=[migration],
        total_execution_time_ms=1000,
    )
    down_result = MigrateDownResult(
        success=True,
        migrations_rolled_back=[migration],
        total_execution_time_ms=500,
    )
    reinit_result = MigrateReinitResult(
        success=True,
        deleted_count=1,
        migrations_marked=[migration],
        total_execution_time_ms=300,
    )
    rebuild_result = MigrateRebuildResult(
        success=True,
        schemas_dropped=[],
        ddl_statements_executed=1,
        migrations_marked=[migration],
        total_execution_time_ms=2000,
    )

    # All aggregate timing keys should be "total_duration_ms"
    for result in [up_result, down_result, reinit_result, rebuild_result]:
        result_dict = result.to_dict()
        assert "total_duration_ms" in result_dict, (
            f"{result.__class__.__name__} missing total_duration_ms"
        )

    # All per-migration timing keys should be "duration_ms"
    for result in [up_result, down_result, reinit_result, rebuild_result]:
        result_dict = result.to_dict()
        # Find the list of migrations key (different for each type)
        migrations_keys = [
            k for k in result_dict if isinstance(result_dict[k], list) and len(result_dict[k]) > 0
        ]
        for migrations_list in [result_dict[k] for k in migrations_keys]:
            if migrations_list and isinstance(migrations_list[0], dict):
                for migration_dict in migrations_list:
                    assert "duration_ms" in migration_dict
