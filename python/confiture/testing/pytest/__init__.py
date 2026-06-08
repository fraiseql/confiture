"""Pytest integration for confiture migration testing.

This module provides both the pytest plugin and the migration_test decorator.

Usage:
    # Enable the plugin in conftest.py
    pytest_plugins = ["confiture.testing.pytest"]

    # Use the decorator for migration-specific tests
    from confiture.testing.pytest import migration_test

    @migration_test("003_move_catalog_tables")
    class TestMigration003:
        def test_up_preserves_data(self, confiture_sandbox, migration):
            migration.up()
            assert confiture_sandbox.validator.constraints_valid()
"""

# Re-export from the plugin module
from confiture.testing.pytest_plugin import (
    confiture_db_url,
    confiture_env,
    confiture_project_dir,
    confiture_sandbox,
    confiture_snapshotter,
    confiture_template_db,
    confiture_template_name,
    confiture_test_server_url,
    confiture_validator,
    confiture_worker_db,
    confiture_worker_id,
    migration_test,
)
from confiture.testing.worker_db import (
    current_worker_id,
    resolve_worker_db_name,
    resolve_worker_db_url,
)

__all__ = [
    # Decorator
    "migration_test",
    # Migration-sandbox fixtures (for documentation; registered via plugin)
    "confiture_db_url",
    "confiture_sandbox",
    "confiture_validator",
    "confiture_snapshotter",
    # Per-worker test-database fixtures (pytest-xdist)
    "confiture_test_server_url",
    "confiture_template_name",
    "confiture_env",
    "confiture_project_dir",
    "confiture_worker_id",
    "confiture_template_db",
    "confiture_worker_db",
    # Import-time helpers (primary integration surface)
    "resolve_worker_db_name",
    "resolve_worker_db_url",
    "current_worker_id",
]
