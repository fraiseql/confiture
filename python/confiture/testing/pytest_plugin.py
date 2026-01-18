"""Pytest plugin for confiture migration testing.

This module provides pytest fixtures for migration testing with automatic
transaction rollback.

Usage:
    # In conftest.py
    pytest_plugins = ["confiture.testing.pytest"]

    # Or enable automatically when confiture is installed (via entry point)

Available fixtures:
    - confiture_db_url: Database URL (override to customize)
    - confiture_migrations_dir: Migrations directory (override to customize)
    - confiture_sandbox: MigrationSandbox with automatic rollback
    - confiture_validator: DataValidator from sandbox
    - confiture_snapshotter: SchemaSnapshotter from sandbox

Example test file:
    >>> def test_migration(confiture_sandbox):
    ...     migration = confiture_sandbox.load("003_move_tables")
    ...     migration.up()
    ...     assert confiture_sandbox.validator.constraints_valid()
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, Generator

import pytest

if TYPE_CHECKING:
    from confiture.testing.fixtures.data_validator import DataValidator
    from confiture.testing.fixtures.schema_snapshotter import SchemaSnapshotter
    from confiture.testing.sandbox import MigrationSandbox


@pytest.fixture
def confiture_db_url() -> str:
    """Provide database URL for migration testing.

    Override this fixture to use a different database:

        @pytest.fixture
        def confiture_db_url():
            return "postgresql://localhost/my_test_db"

    Environment variable CONFITURE_TEST_DB_URL takes precedence.

    Returns:
        Database connection URL
    """
    return os.getenv(
        "CONFITURE_TEST_DB_URL",
        "postgresql://localhost/confiture_test",
    )


@pytest.fixture
def confiture_migrations_dir() -> Path:
    """Provide migrations directory for testing.

    Override this fixture to use a custom migrations directory:

        @pytest.fixture
        def confiture_migrations_dir():
            return Path("custom/migrations")

    Returns:
        Path to migrations directory
    """
    return Path("db/migrations")


@pytest.fixture
def confiture_sandbox(
    confiture_db_url: str,
    confiture_migrations_dir: Path,
) -> Generator["MigrationSandbox", None, None]:
    """Provide a migration sandbox with automatic rollback.

    Creates a MigrationSandbox that automatically rolls back all changes
    at the end of the test.

    Usage:
        def test_migration(confiture_sandbox):
            migration = confiture_sandbox.load("003_move_tables")
            baseline = confiture_sandbox.capture_baseline()
            migration.up()
            confiture_sandbox.assert_no_data_loss(baseline)

    Yields:
        MigrationSandbox instance

    Note:
        This fixture requires a running PostgreSQL database.
        Tests will be skipped if the database is not available.
    """
    from confiture.testing.sandbox import MigrationSandbox

    try:
        with MigrationSandbox(
            db_url=confiture_db_url,
            migrations_dir=confiture_migrations_dir,
        ) as sandbox:
            yield sandbox
    except Exception as e:
        pytest.skip(f"Database not available: {e}")


@pytest.fixture
def confiture_validator(confiture_sandbox: "MigrationSandbox") -> "DataValidator":
    """Provide data validator from sandbox.

    Convenience fixture that extracts the validator from the sandbox.

    Usage:
        def test_constraints(confiture_sandbox, confiture_validator):
            confiture_sandbox.load("003").up()
            assert confiture_validator.constraints_valid()

    Returns:
        DataValidator instance
    """
    return confiture_sandbox.validator


@pytest.fixture
def confiture_snapshotter(confiture_sandbox: "MigrationSandbox") -> "SchemaSnapshotter":
    """Provide schema snapshotter from sandbox.

    Convenience fixture that extracts the snapshotter from the sandbox.

    Usage:
        def test_schema_changes(confiture_sandbox, confiture_snapshotter):
            before = confiture_snapshotter.capture()
            confiture_sandbox.load("003").up()
            after = confiture_snapshotter.capture()
            changes = confiture_snapshotter.compare(before, after)
            assert "products" in changes["tables_added"]

    Returns:
        SchemaSnapshotter instance
    """
    return confiture_sandbox.snapshotter


def migration_test(migration_name: str):
    """Decorator to inject migration fixture for specific migration.

    Use this decorator on test classes to automatically inject a `migration`
    fixture that loads the specified migration.

    Usage:
        from confiture.testing.pytest import migration_test

        @migration_test("003_move_catalog_tables")
        class TestMigration003:
            def test_up_preserves_data(self, confiture_sandbox, migration):
                baseline = confiture_sandbox.capture_baseline()
                migration.up()
                confiture_sandbox.assert_no_data_loss(baseline)

            def test_down_reverses_changes(self, confiture_sandbox, migration):
                migration.up()
                migration.down()
                # Assert schema is back to original state

    Args:
        migration_name: Name of the migration to load (e.g., "003_move_catalog_tables")

    Returns:
        Class decorator that adds migration fixture
    """

    def decorator(cls):
        # Create a migration fixture for this specific test class
        @pytest.fixture
        def migration(self, confiture_sandbox: "MigrationSandbox"):
            """Migration fixture injected by @migration_test decorator."""
            return confiture_sandbox.load(migration_name)

        # Add the fixture to the class
        cls.migration = migration
        return cls

    return decorator
