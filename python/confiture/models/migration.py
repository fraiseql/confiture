"""Migration base class for database migrations."""

import inspect
from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING, Any

import psycopg

if TYPE_CHECKING:
    from confiture.core.hooks import Hook
    from confiture.core.preconditions import Precondition


def _source_file_of(cls: type) -> Path | None:
    """The file a migration class was loaded from, or ``None`` when it has none.

    ``load_migration_class`` imports migrations from their path, so the module
    carries ``__file__``. A class built in memory (a test, an ``exec``) has
    none, and ``inspect`` says so by raising rather than returning.
    """
    try:
        source = inspect.getfile(cls)
    except (TypeError, OSError):
        return None
    candidate = Path(source)
    return candidate if candidate.is_file() else None


class Migration(ABC):
    """Base class for all database migrations.

    Each migration must:
    - Define a version (e.g., "20260228120530")
    - Define a name (e.g., "create_users")
    - Implement up() method for applying the migration
    - Implement down() method for rolling back the migration

    Alternatively, for simple SQL-only migrations, subclass SQLMigration
    and define `up_sql` and `down_sql` class attributes instead of methods.

    Migrations can optionally define preconditions for fail-fast validation:
    - up_preconditions: Checks before applying the migration (up)
    - down_preconditions: Checks before rolling back the migration (down)

    Preconditions are validated BEFORE the migration runs. If any fail,
    the migration is aborted with a clear error message.

    Migrations can optionally define hooks that execute before/after DDL:
    - before_validation_hooks: Pre-flight checks before migration
    - before_ddl_hooks: Data prep before structural changes
    - after_ddl_hooks: Data backfill after structural changes
    - after_validation_hooks: Verification after data operations
    - cleanup_hooks: Final cleanup operations
    - error_hooks: Error handlers during rollback

    Transaction Control:
        By default, migrations run inside a transaction with savepoints.
        Set `transactional = False` for operations that cannot run in
        a transaction, such as:
        - CREATE INDEX CONCURRENTLY
        - DROP INDEX CONCURRENTLY
        - VACUUM
        - REINDEX CONCURRENTLY

        WARNING: Non-transactional migrations cannot be automatically
        rolled back if they fail. Manual cleanup may be required.

    Example:
        >>> class CreateUsers(Migration):
        ...     version = "20260228120530"
        ...     name = "create_users"
        ...
        ...     def up(self):
        ...         self.execute('''
        ...             CREATE TABLE users (
        ...                 id SERIAL PRIMARY KEY,
        ...                 username TEXT NOT NULL
        ...             )
        ...         ''')
        ...
        ...     def down(self):
        ...         self.execute('DROP TABLE users')

    Example with hooks:
        >>> class AddAnalyticsTable(Migration):
        ...     version = "20260228120531"
        ...     name = "add_analytics_table"
        ...     after_ddl_hooks = [BackfillAnalyticsHook()]
        ...
        ...     def up(self):
        ...         self.execute('CREATE TABLE analytics (...)')
        ...
        ...     def down(self):
        ...         self.execute('DROP TABLE analytics')

    Example using execute_file to load SQL from a file:
        >>> class UpdateFunction(Migration):
        ...     version = "20260301100000"
        ...     name = "update_function"
        ...
        ...     def up(self):
        ...         self.execute_file("db/schema/functions/my_function.sql")
        ...
        ...     def down(self):
        ...         self.execute_file("db/schema/functions/my_function_old.sql")

    Example non-transactional (CREATE INDEX CONCURRENTLY):
        >>> class AddSearchIndex(Migration):
        ...     version = "20260301090000"
        ...     name = "add_search_index"
        ...     transactional = False  # Required for CONCURRENTLY
        ...
        ...     def up(self):
        ...         self.execute('CREATE INDEX CONCURRENTLY idx_search ON products(name)')
        ...
        ...     def down(self):
        ...         self.execute('DROP INDEX CONCURRENTLY IF EXISTS idx_search')

    Example SQL-only migration (using SQLMigration):
        >>> class MoveCatalogTables(SQLMigration):
        ...     version = "20260228130000"
        ...     name = "move_catalog_tables"
        ...
        ...     up_sql = "ALTER TABLE tenant.products SET SCHEMA catalog;"
        ...     down_sql = "ALTER TABLE catalog.products SET SCHEMA tenant;"

    Example with preconditions (fail-fast validation):
        >>> from confiture.core.preconditions import TableExists, TableNotExists
        >>>
        >>> class MoveCatalogTables(Migration):
        ...     version = "004"
        ...     name = "move_catalog_tables"
        ...
        ...     # Validated BEFORE migration runs
        ...     up_preconditions = [
        ...         TableExists("tb_datasupplier", schema="tenant"),
        ...         TableNotExists("tb_datasupplier", schema="catalog"),
        ...     ]
        ...
        ...     down_preconditions = [
        ...         TableExists("tb_datasupplier", schema="catalog"),
        ...         TableNotExists("tb_datasupplier", schema="tenant"),
        ...     ]
        ...
        ...     def up(self):
        ...         self.execute("ALTER TABLE tenant.tb_datasupplier SET SCHEMA catalog")
        ...
        ...     def down(self):
        ...         self.execute("ALTER TABLE catalog.tb_datasupplier SET SCHEMA tenant")
    """

    # Subclasses must define these
    version: str
    name: str

    # Configuration attributes
    transactional: bool = True  # Default: run in transaction with savepoints
    strict_mode: bool = False  # Default: lenient error handling
    # Issue #137 — declarative "this migration must run as superuser".
    # `MigratorSession.up()` halts at the first migration with this set;
    # the operator resolves with `confiture migrate apply-as <role>`.
    requires_superuser: bool = False

    # Precondition attributes (optional, default to empty lists)
    # Validated before migration execution - fail fast if not satisfied
    up_preconditions: list["Precondition"] = []
    down_preconditions: list["Precondition"] = []

    # Hook attributes (optional, default to empty lists)
    before_validation_hooks: list["Hook"] = []
    before_ddl_hooks: list["Hook"] = []
    after_ddl_hooks: list["Hook"] = []
    after_validation_hooks: list["Hook"] = []
    cleanup_hooks: list["Hook"] = []
    error_hooks: list["Hook"] = []

    def __init__(self, connection: psycopg.Connection):
        """Initialize migration with database connection.

        Args:
            connection: psycopg3 database connection

        Raises:
            TypeError: If version or name not defined in subclass
        """
        self.connection = connection

        # Ensure subclass defined version and name
        if not hasattr(self.__class__, "version") or self.__class__.version is None:
            raise TypeError(f"{self.__class__.__name__} must define a 'version' class attribute")
        if not hasattr(self.__class__, "name") or self.__class__.name is None:
            raise TypeError(f"{self.__class__.__name__} must define a 'name' class attribute")

    @abstractmethod
    def up(self) -> None:
        """Apply the migration.

        This method must be implemented by subclasses to perform
        the forward migration (e.g., CREATE TABLE, ALTER TABLE).

        Raises:
            NotImplementedError: If not implemented by subclass
        """
        raise NotImplementedError(f"{self.__class__.__name__}.up() must be implemented")

    @abstractmethod
    def down(self) -> None:
        """Rollback the migration.

        This method must be implemented by subclasses to perform
        the reverse migration (e.g., DROP TABLE, revert ALTER).

        Raises:
            NotImplementedError: If not implemented by subclass
        """
        raise NotImplementedError(f"{self.__class__.__name__}.down() must be implemented")

    def get_up_sql_statements(self) -> list[str]:
        """Get the SQL statements that would be executed by up().

        Returns:
            List of SQL statements, or empty list if not applicable.

        Note:
            Base implementation returns empty list. Subclasses should override
            for dry-run support.
        """
        return []

    def execute_file(self, path: str | Path) -> None:
        """Execute SQL read from a file.

        Resolves ``path`` the way every other part of confiture does
        (:func:`confiture.core.sql_path.resolve_sql_file`): an absolute path
        as-is; a relative one against the **project root**, then this
        migration's own directory, then the working directory. So
        ``execute_file("db/schema/fn.sql")`` names the same file whether
        ``confiture migrate up`` runs from the repository root or from a
        deployment wrapper's directory — and the same file the idempotency
        analyzer verified before the deploy.

        The project root is the nearest ancestor of this migration's source
        file carrying ``pyproject.toml``, ``.git`` or ``db/``. A migration
        class with no source file (built in memory) resolves from the working
        directory only, which is what every migration did before 0.46.0.

        Args:
            path: Path to a ``.sql`` file (absolute, or relative as above).

        Raises:
            FileNotFoundError: If no candidate is a file; the message lists
                every path tried.
            ValueError: If the file is empty or contains only whitespace.
            SQLError: If the SQL execution fails.

        Example:
            >>> class UpdateFunction(Migration):
            ...     version = "20260426120000"
            ...     name = "update_function"
            ...
            ...     def up(self):
            ...         self.execute_file("db/schema/functions/my_function.sql")
            ...
            ...     def down(self):
            ...         pass
        """
        from confiture.core.sql_path import find_project_root, resolve_sql_file

        source = _source_file_of(type(self))
        resolution = resolve_sql_file(
            path,
            migration_file=source,
            project_root=find_project_root(source) if source is not None else None,
            confine=False,
        )
        if resolution.path is None:
            tried = ", ".join(str(candidate) for candidate in resolution.tried)
            raise FileNotFoundError(f"SQL file not found: {path} (tried: {tried})")
        sql = resolution.path.read_text(encoding="utf-8")
        if not sql.strip():
            raise ValueError(f"SQL file is empty: {resolution.path}")
        self.execute(sql)

    def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> None:
        """Execute a SQL statement.

        In strict mode:
        - Validates statement success explicitly
        - May check for PostgreSQL warnings (future enhancement)

        In normal mode:
        - Only fails on actual errors (default)
        - Ignores notices and warnings

        Args:
            sql: SQL statement to execute
            params: Optional query parameters (for parameterized queries)

        Raises:
            SQLError: If SQL execution fails, with detailed context

        Example:
            >>> self.execute("CREATE TABLE users (id INT)")
            >>> self.execute("INSERT INTO users (name) VALUES (%s)", ("Alice",))
        """
        from confiture.exceptions import SQLError

        try:
            with self.connection.cursor() as cursor:
                if params:
                    cursor.execute(sql, params)
                else:
                    cursor.execute(sql)

                # In strict mode, we could check for warnings here
                # For now, this is a placeholder for future enhancement
                if self.strict_mode:
                    # PostgreSQL notices are sent via connection.notices
                    # or through a notice handler
                    pass

        except Exception as e:
            # Wrap the error with SQL context
            raise SQLError(sql, params, e) from e


class SQLMigration(Migration):
    """Migration that executes SQL from class attributes.

    A convenience class for simple SQL-only migrations that don't need
    Python logic. Instead of implementing up() and down() methods,
    define `up_sql` and `down_sql` class attributes.

    This reduces boilerplate for simple schema changes while maintaining
    full compatibility with the migration system (hooks, transactions, etc.).

    Attributes:
        up_sql: SQL to execute for the forward migration
        down_sql: SQL to execute for the rollback

    Example:
        >>> class MoveCatalogTables(SQLMigration):
        ...     version = "003"
        ...     name = "move_catalog_tables"
        ...
        ...     up_sql = '''
        ...         ALTER TABLE tenant.tb_datasupplier SET SCHEMA catalog;
        ...         ALTER TABLE tenant.tb_product SET SCHEMA catalog;
        ...     '''
        ...
        ...     down_sql = '''
        ...         ALTER TABLE catalog.tb_datasupplier SET SCHEMA tenant;
        ...         ALTER TABLE catalog.tb_product SET SCHEMA tenant;
        ...     '''

    Example with non-transactional mode:
        >>> class AddConcurrentIndex(SQLMigration):
        ...     version = "004"
        ...     name = "add_concurrent_index"
        ...     transactional = False
        ...
        ...     up_sql = "CREATE INDEX CONCURRENTLY idx_name ON users(name);"
        ...     down_sql = "DROP INDEX CONCURRENTLY IF EXISTS idx_name;"

    Note:
        - Multi-statement SQL is supported (separate with semicolons)
        - For complex migrations with conditional logic, use Migration base class
        - Hooks are fully supported with SQLMigration
    """

    # Subclasses must define these
    up_sql: str
    down_sql: str

    def __init__(self, connection: psycopg.Connection):
        """Initialize SQL migration.

        Args:
            connection: psycopg3 database connection

        Raises:
            TypeError: If version, name, up_sql, or down_sql not defined
        """
        super().__init__(connection)

        # Validate SQL attributes are defined
        if not hasattr(self.__class__, "up_sql") or self.__class__.up_sql is None:
            raise TypeError(f"{self.__class__.__name__} must define an 'up_sql' class attribute")
        if not hasattr(self.__class__, "down_sql") or self.__class__.down_sql is None:
            raise TypeError(f"{self.__class__.__name__} must define a 'down_sql' class attribute")

    def get_up_sql_statements(self) -> list[str]:
        """Get individual SQL statements from up_sql.

        Returns:
            List of SQL statements parsed from up_sql
        """
        import sqlparse

        statements = sqlparse.split(self.up_sql)
        return [stmt.strip() for stmt in statements if stmt.strip()]

    def up(self) -> None:
        """Apply the migration by executing up_sql."""
        self.execute(self.up_sql)

    def down(self) -> None:
        """Rollback the migration by executing down_sql."""
        self.execute(self.down_sql)
