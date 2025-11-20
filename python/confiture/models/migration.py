"""Migration base class for database migrations."""

from abc import ABC, abstractmethod
from typing import Any

import psycopg


class Migration(ABC):
    """Base class for all database migrations.

    Each migration must:
    - Define a version (e.g., "001", "002")
    - Define a name (e.g., "create_users")
    - Implement up() method for applying the migration
    - Implement down() method for rolling back the migration

    Example:
        >>> class CreateUsers(Migration):
        ...     version = "001"
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
    """

    # Subclasses must define these
    version: str
    name: str

    # Configuration attributes
    strict_mode: bool = False  # Default: lenient error handling

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
                    # TODO: Implement warning detection
                    # PostgreSQL notices are sent via connection.notices
                    # or through a notice handler
                    pass

        except Exception as e:
            # Wrap the error with SQL context
            raise SQLError(sql, params, e) from e
