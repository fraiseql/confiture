"""Pytest plugin for confiture migration testing.

This module provides pytest fixtures for migration testing with automatic
transaction rollback.

Usage:
    # In conftest.py
    pytest_plugins = ["confiture.testing.pytest"]

    # Or enable automatically when confiture is installed (via entry point)

Available fixtures:
    - confiture_db_url: Database URL (override to customize)
    - tb_confiture_dir: Migrations directory (override to customize)
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

import contextlib
import os
from collections.abc import Generator
from pathlib import Path
from typing import TYPE_CHECKING

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
def tb_confiture_dir() -> Path:
    """Provide migrations directory for testing.

    Override this fixture to use a custom migrations directory:

        @pytest.fixture
        def tb_confiture_dir():
            return Path("custom/migrations")

    Returns:
        Path to migrations directory
    """
    return Path("db/migrations")


@pytest.fixture
def confiture_sandbox(
    confiture_db_url: str,
    tb_confiture_dir: Path,
) -> Generator[MigrationSandbox, None, None]:
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
            migrations_dir=tb_confiture_dir,
        ) as sandbox:
            yield sandbox
    except Exception as e:
        pytest.skip(f"Database not available: {e}")


@pytest.fixture
def confiture_validator(confiture_sandbox: MigrationSandbox) -> DataValidator:
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
def confiture_snapshotter(confiture_sandbox: MigrationSandbox) -> SchemaSnapshotter:
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


# ---------------------------------------------------------------------------
# Per-worker test-database fixtures (pytest-xdist)
#
# These are OPT-IN: they only run when a test requests them, so existing plugin
# users are unaffected. The primary integration surface for apps that freeze a
# settings/pool singleton at import time is the import-time helper
# ``confiture.testing.worker_db.resolve_worker_db_url`` (call it from conftest.py
# BEFORE importing the app) — these fixtures are convenience for apps that read
# their database URL lazily and cannot retro-fix an already-frozen singleton.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def confiture_test_server_url() -> str:
    """PG server URL for test-db provisioning (override to customise).

    ``CONFITURE_TEST_DB_URL`` takes precedence.
    """
    return os.getenv("CONFITURE_TEST_DB_URL", "postgresql://localhost/confiture_test")


@pytest.fixture(scope="session")
def confiture_template_name() -> str:
    """Template database name (override to customise)."""
    return "confiture_template"


@pytest.fixture(scope="session")
def confiture_env() -> str:
    """Environment whose schema builds the template (override to customise)."""
    return "local"


@pytest.fixture(scope="session")
def confiture_project_dir() -> Path:
    """Project directory the template schema is built from (override to customise)."""
    return Path(".")


@pytest.fixture(scope="session")
def confiture_worker_id() -> str | None:
    """The active pytest-xdist worker id (``"gw0"``…), or None for single-process."""
    from confiture.testing.worker_db import current_worker_id

    return current_worker_id()


@pytest.fixture(scope="session")
def confiture_template_db(
    confiture_test_server_url: str,
    confiture_template_name: str,
    confiture_env: str,
    confiture_project_dir: Path,
) -> str:
    """Ensure the shared template database exists and matches the current db/ hash.

    Built exactly once even under ``-n N`` (single-flight via a PostgreSQL
    advisory lock in :meth:`TestDbProvisioner.ensure_template`). Skips cleanly
    when no database is reachable.

    Returns:
        The template database name.
    """
    import psycopg

    from confiture.core.builder import SchemaBuilder
    from confiture.core.test_db import TestDbProvisioner

    try:
        builder = SchemaBuilder(env=confiture_env, project_dir=confiture_project_dir)
        schema_hash = builder.compute_hash()
        schema_sql = builder.build(schema_only=True)
        _schema_files, seed_files = builder.categorize_sql_files()
        provisioner = TestDbProvisioner(confiture_test_server_url)
        provisioner.ensure_template(
            confiture_template_name,
            schema_hash=schema_hash,
            schema_sql=schema_sql,
            seed_files=seed_files or None,
        )
    except psycopg.OperationalError as e:
        pytest.skip(f"confiture test database unavailable: {e}")
    return confiture_template_name


@pytest.fixture(scope="session")
def confiture_worker_db(
    confiture_template_db: str,
    confiture_test_server_url: str,
    confiture_worker_id: str | None,
) -> Generator[str, None, None]:
    """Yield a per-worker database cloned from the shared template.

    One clone per xdist worker (session scope is per worker process), dropped on
    teardown. The yielded value is the clone's connection URL.

    Note:
        Apps that freeze their settings/pool at import time must instead call
        ``confiture.testing.worker_db.resolve_worker_db_url`` from conftest.py at
        import time — this fixture runs too late to fix a frozen singleton.
    """
    import psycopg

    from confiture.core.test_db import TestDbProvisioner
    from confiture.testing.worker_db import resolve_worker_db_name

    provisioner = TestDbProvisioner(confiture_test_server_url)
    target = resolve_worker_db_name(
        f"{confiture_template_db}_db", worker_id=confiture_worker_id
    )

    try:
        provisioner.drop(target)  # reap a leftover clone from a crashed run
        clone = provisioner.clone(confiture_template_db, target)
    except psycopg.OperationalError as e:
        pytest.skip(f"confiture test database unavailable: {e}")

    try:
        yield clone.target_url
    finally:
        with contextlib.suppress(psycopg.OperationalError):
            provisioner.drop(target)  # best-effort teardown


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
        def migration(self, confiture_sandbox: MigrationSandbox):  # noqa: ARG001
            """Migration fixture injected by @migration_test decorator."""
            return confiture_sandbox.load(migration_name)

        # Add the fixture to the class
        cls.migration = migration
        return cls

    return decorator
