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
    confiture_migrations_dir,
    confiture_sandbox,
    confiture_snapshotter,
    confiture_validator,
    migration_test,
)

__all__ = [
    # Decorator
    "migration_test",
    # Fixtures (for documentation, actual fixtures registered via plugin)
    "confiture_db_url",
    "confiture_migrations_dir",
    "confiture_sandbox",
    "confiture_validator",
    "confiture_snapshotter",
]
