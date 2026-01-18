"""Migration testing sandbox.

Provides an isolated environment for testing migrations with automatic
rollback and pre-loaded testing utilities.

Example:
    >>> from confiture.testing import MigrationSandbox
    >>>
    >>> with MigrationSandbox(db_url) as sandbox:
    ...     migration = sandbox.load("003_move_tables")
    ...     migration.up()
    ...     assert sandbox.validator.constraints_valid()
    ...
    >>> # Auto-rollback at end of context
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import psycopg

if TYPE_CHECKING:
    from confiture.models.migration import Migration
    from confiture.testing.fixtures.data_validator import DataBaseline, DataValidator
    from confiture.testing.fixtures.schema_snapshotter import SchemaSnapshotter


class MigrationSandbox:
    """Test migrations in isolation with automatic rollback.

    A context manager that provides a sandboxed environment for migration testing:
    - Automatic transaction management (rollback on exit)
    - Pre-loaded testing utilities (validator, snapshotter)
    - Migration loading via load_migration()

    The sandbox can work in two modes:
    1. **URL mode**: Creates a new connection, uses transaction with rollback
    2. **Connection mode**: Uses existing connection, creates a savepoint for rollback

    Attributes:
        connection: The database connection being used
        validator: DataValidator for data integrity checks
        snapshotter: SchemaSnapshotter for schema comparison
        migrations_dir: Directory where migrations are located

    Example with URL:
        >>> with MigrationSandbox("postgresql://localhost/test_db") as sandbox:
        ...     migration = sandbox.load("003_move_tables")
        ...     baseline = sandbox.capture_baseline()
        ...     migration.up()
        ...     assert sandbox.validator.no_data_loss(baseline)

    Example with existing connection:
        >>> with MigrationSandbox(connection=existing_conn) as sandbox:
        ...     # Uses savepoint instead of full transaction
        ...     migration = sandbox.load("003")
        ...     migration.up()

    Example with custom migrations directory:
        >>> with MigrationSandbox(db_url, migrations_dir=Path("/custom/migrations")) as sandbox:
        ...     migration = sandbox.load("001_initial")
    """

    def __init__(
        self,
        db_url: str | None = None,
        *,
        connection: psycopg.Connection | None = None,
        migrations_dir: Path | None = None,
    ):
        """Initialize the migration sandbox.

        Args:
            db_url: Database connection URL. Creates a new connection.
            connection: Existing database connection. Uses savepoint for rollback.
            migrations_dir: Custom migrations directory. Defaults to "db/migrations".

        Raises:
            ValueError: If neither db_url nor connection is provided,
                       or if both are provided.

        Note:
            When using an existing connection, the sandbox creates a savepoint
            that will be rolled back on exit. This preserves the connection's
            transaction state.
        """
        if db_url is None and connection is None:
            raise ValueError("Either 'db_url' or 'connection' must be provided")
        if db_url is not None and connection is not None:
            raise ValueError("Provide either 'db_url' or 'connection', not both")

        self._db_url = db_url
        self._external_connection = connection
        self._owns_connection = db_url is not None
        self._savepoint_name = "confiture_sandbox"
        self._active = False

        self.migrations_dir = migrations_dir or Path("db/migrations")
        self.connection: psycopg.Connection = None  # type: ignore[assignment]
        self._validator: DataValidator | None = None
        self._snapshotter: SchemaSnapshotter | None = None

    def __enter__(self) -> MigrationSandbox:
        """Enter the sandbox context.

        Creates connection (if URL provided) and starts transaction/savepoint.

        Returns:
            Self for use in with statement
        """
        if self._owns_connection:
            # Create new connection with autocommit=False for transaction control
            assert self._db_url is not None
            self.connection = psycopg.connect(self._db_url, autocommit=False)
        else:
            # Use provided connection, create savepoint
            assert self._external_connection is not None
            self.connection = self._external_connection
            with self.connection.cursor() as cursor:
                cursor.execute(f"SAVEPOINT {self._savepoint_name}")

        self._active = True
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        """Exit the sandbox context.

        Rolls back all changes and closes connection (if we created it).

        Args:
            exc_type: Exception type if an error occurred
            exc_val: Exception value
            exc_tb: Exception traceback
        """
        if not self._active:
            return

        try:
            if self._owns_connection:
                # Rollback entire transaction
                self.connection.rollback()
                self.connection.close()
            else:
                # Rollback to savepoint
                with self.connection.cursor() as cursor:
                    cursor.execute(f"ROLLBACK TO SAVEPOINT {self._savepoint_name}")
                    cursor.execute(f"RELEASE SAVEPOINT {self._savepoint_name}")
        finally:
            self._active = False

    def load(self, name: str) -> Migration:
        """Load and instantiate a migration.

        Args:
            name: Migration name without .py extension (e.g., "003_move_tables")
                  or version prefix (e.g., "003")

        Returns:
            Instantiated Migration object ready to execute

        Raises:
            MigrationNotFoundError: If migration not found
            MigrationLoadError: If migration cannot be loaded

        Example:
            >>> migration = sandbox.load("003_move_catalog_tables")
            >>> migration.up()

            >>> # Also works with version prefix
            >>> migration = sandbox.load("003")
        """
        from confiture.testing.loader import load_migration

        # Determine if name is a version prefix or full name
        if "_" in name:
            # Full name provided
            migration_class = load_migration(name, migrations_dir=self.migrations_dir)
        else:
            # Version prefix provided
            migration_class = load_migration(version=name, migrations_dir=self.migrations_dir)

        return migration_class(connection=self.connection)

    @property
    def validator(self) -> DataValidator:
        """Get data validator for this sandbox.

        Returns:
            DataValidator configured with the sandbox's connection

        Example:
            >>> assert sandbox.validator.constraints_valid()
        """
        if self._validator is None:
            from confiture.testing.fixtures.data_validator import DataValidator

            self._validator = DataValidator(self.connection)
        return self._validator

    @property
    def snapshotter(self) -> SchemaSnapshotter:
        """Get schema snapshotter for this sandbox.

        Returns:
            SchemaSnapshotter configured with the sandbox's connection

        Example:
            >>> before = sandbox.snapshotter.capture()
            >>> migration.up()
            >>> after = sandbox.snapshotter.capture()
            >>> changes = sandbox.snapshotter.compare(before, after)
        """
        if self._snapshotter is None:
            from confiture.testing.fixtures.schema_snapshotter import SchemaSnapshotter

            self._snapshotter = SchemaSnapshotter(self.connection)
        return self._snapshotter

    def capture_baseline(self) -> DataBaseline:
        """Capture data baseline before migration.

        Convenience method that wraps validator.capture_baseline().

        Returns:
            DataBaseline snapshot for later comparison

        Example:
            >>> baseline = sandbox.capture_baseline()
            >>> migration.up()
            >>> sandbox.assert_no_data_loss(baseline)
        """
        return self.validator.capture_baseline()

    def assert_no_data_loss(self, baseline: DataBaseline) -> None:
        """Assert no data was lost since baseline.

        Convenience method that wraps validator.no_data_loss() with assertion.

        Args:
            baseline: Baseline captured before migration

        Raises:
            AssertionError: If data loss is detected

        Example:
            >>> baseline = sandbox.capture_baseline()
            >>> migration.up()
            >>> sandbox.assert_no_data_loss(baseline)  # Raises if data lost
        """
        if not self.validator.no_data_loss(baseline):
            raise AssertionError("Data loss detected after migration")

    def assert_constraints_valid(self) -> None:
        """Assert all database constraints are valid.

        Convenience method that wraps validator.constraints_valid() with assertion.

        Raises:
            AssertionError: If constraint violations are detected

        Example:
            >>> migration.up()
            >>> sandbox.assert_constraints_valid()  # Raises if violations found
        """
        if not self.validator.constraints_valid():
            raise AssertionError("Constraint violations detected after migration")

    def execute(self, sql: str) -> None:
        """Execute raw SQL in the sandbox.

        Useful for setting up test data or making assertions.

        Args:
            sql: SQL to execute

        Example:
            >>> sandbox.execute("INSERT INTO users (name) VALUES ('test')")
        """
        with self.connection.cursor() as cursor:
            cursor.execute(sql)

    def query(self, sql: str) -> list[tuple]:
        """Execute a query and return results.

        Args:
            sql: SQL query to execute

        Returns:
            List of result rows as tuples

        Example:
            >>> rows = sandbox.query("SELECT COUNT(*) FROM users")
            >>> assert rows[0][0] > 0
        """
        with self.connection.cursor() as cursor:
            cursor.execute(sql)
            return cursor.fetchall()
