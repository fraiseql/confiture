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

Pre-state simulation (Issue #10):
    >>> with MigrationSandbox(db_url) as sandbox:
    ...     migration = sandbox.load("004_move_catalog_tables")
    ...     sandbox.simulate_pre_state(migration)  # Runs DOWN to reconstruct pre-state
    ...     migration.up()  # Now test the UP migration
    ...     # Assertions...
"""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING

import psycopg

if TYPE_CHECKING:
    from confiture.models.migration import Migration
    from confiture.testing.fixtures.data_validator import DataBaseline, DataValidator
    from confiture.testing.fixtures.schema_snapshotter import SchemaSnapshotter


class PreStateSimulationError(Exception):
    """Raised when pre-state simulation fails.

    This typically happens when:
    - The DOWN migration fails
    - The migration has no reversible DOWN implementation
    - The database state doesn't support running DOWN
    """

    pass


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

        # Pre-state simulation tracking
        self._pre_state_simulated = False
        self._simulated_migration: Migration | None = None

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

    def simulate_pre_state(self, migration: Migration) -> None:
        """Simulate the pre-migration state by running the DOWN migration.

        This is useful when your local database is already in the post-migration
        state (e.g., you've already applied the migration), but you want to test
        the UP migration path.

        The method runs the DOWN migration to reconstruct the pre-migration state,
        allowing you to then test the UP migration.

        WARNING: This modifies the database state. All changes will be rolled back
        when the sandbox context exits.

        Args:
            migration: Migration instance to simulate pre-state for

        Raises:
            PreStateSimulationError: If DOWN migration fails

        Example:
            >>> with MigrationSandbox(db_url) as sandbox:
            ...     migration = sandbox.load("004_move_catalog_tables")
            ...
            ...     # Local DB has tables in 'catalog' schema (post-migration state)
            ...     # Simulate pre-state by running DOWN
            ...     sandbox.simulate_pre_state(migration)
            ...
            ...     # Now tables are in 'tenant' schema (pre-migration state)
            ...     # Test the UP migration
            ...     migration.up()
            ...
            ...     # Verify tables moved to 'catalog' schema
            ...     assert sandbox.table_exists("tb_datasupplier", schema="catalog")

        Note:
            This method tracks that pre-state was simulated. If the sandbox
            needs to restore state (e.g., for cleanup), it can use this info.
        """
        if not self._active:
            raise RuntimeError("Cannot simulate pre-state outside of sandbox context")

        try:
            migration.down()
            self._pre_state_simulated = True
            self._simulated_migration = migration
        except Exception as e:
            raise PreStateSimulationError(
                f"Failed to simulate pre-state for migration "
                f"{migration.version} ({migration.name}): {e}\n"
                f"The DOWN migration failed. This could mean:\n"
                f"  - The database is not in the expected post-migration state\n"
                f"  - The DOWN migration has a bug\n"
                f"  - The migration is not reversible"
            ) from e

    @contextmanager
    def in_pre_state(self, migration: Migration) -> Generator[Migration, None, None]:
        """Context manager for testing in pre-migration state.

        A convenience wrapper around simulate_pre_state() that yields the migration
        for testing. This is useful for clearly scoping the pre-state simulation.

        Args:
            migration: Migration instance to simulate pre-state for

        Yields:
            The same migration instance (for convenience)

        Raises:
            PreStateSimulationError: If DOWN migration fails

        Example:
            >>> with MigrationSandbox(db_url) as sandbox:
            ...     migration = sandbox.load("004_move_catalog_tables")
            ...
            ...     with sandbox.in_pre_state(migration):
            ...         # Database is now in pre-migration state
            ...         migration.up()
            ...
            ...         # Verify migration worked
            ...         assert sandbox.table_exists("tb_datasupplier", schema="catalog")
        """
        self.simulate_pre_state(migration)
        try:
            yield migration
        finally:
            # No explicit cleanup needed - sandbox rollback handles everything
            pass

    def table_exists(self, table: str, schema: str = "public") -> bool:
        """Check if a table exists in the database.

        Convenience method for assertions in tests.

        Args:
            table: Table name
            schema: Schema name (default: "public")

        Returns:
            True if table exists, False otherwise

        Example:
            >>> assert sandbox.table_exists("users")
            >>> assert sandbox.table_exists("products", schema="catalog")
        """
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.tables
                    WHERE table_schema = %s AND table_name = %s
                )
                """,
                (schema, table),
            )
            result = cursor.fetchone()
            return result[0] if result else False

    def column_exists(self, table: str, column: str, schema: str = "public") -> bool:
        """Check if a column exists in a table.

        Convenience method for assertions in tests.

        Args:
            table: Table name
            column: Column name
            schema: Schema name (default: "public")

        Returns:
            True if column exists, False otherwise

        Example:
            >>> assert sandbox.column_exists("users", "email")
        """
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = %s
                      AND table_name = %s
                      AND column_name = %s
                )
                """,
                (schema, table, column),
            )
            result = cursor.fetchone()
            return result[0] if result else False

    def get_row_count(self, table: str, schema: str = "public") -> int:
        """Get the number of rows in a table.

        Convenience method for assertions in tests.

        Args:
            table: Table name
            schema: Schema name (default: "public")

        Returns:
            Number of rows in the table

        Example:
            >>> assert sandbox.get_row_count("users") == 10
        """
        with self.connection.cursor() as cursor:
            cursor.execute(f'SELECT COUNT(*) FROM "{schema}"."{table}"')  # noqa: S608
            result = cursor.fetchone()
            return result[0] if result else 0
