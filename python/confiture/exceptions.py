"""Confiture exception hierarchy

All exceptions raised by Confiture inherit from ConfiturError.
This allows users to catch all Confiture-specific errors with a single except clause.
"""


class ConfiturError(Exception):
    """Base exception for all Confiture errors

    All Confiture-specific exceptions inherit from this base class.
    This allows catching all Confiture errors with:

        try:
            confiture.build()
        except ConfiturError as e:
            # Handle any Confiture error
            pass
    """

    pass


class ConfigurationError(ConfiturError):
    """Invalid configuration (YAML, environment, database connection)

    Raised when:
    - Environment YAML file is malformed or missing
    - Required configuration fields are missing
    - Database connection string is invalid
    - Include/exclude directory patterns are invalid

    Example:
        >>> raise ConfigurationError("Missing database_url in local.yaml")
    """

    pass


class MigrationError(ConfiturError):
    """Migration execution failure

    Raised when:
    - Migration file cannot be loaded
    - Migration up() or down() fails
    - Migration has already been applied
    - Migration rollback fails

    Attributes:
        version: Migration version that failed (e.g., "001")
        migration_name: Human-readable migration name
    """

    def __init__(
        self,
        message: str,
        version: str | None = None,
        migration_name: str | None = None,
    ):
        super().__init__(message)
        self.version = version
        self.migration_name = migration_name


class SchemaError(ConfiturError):
    """Invalid schema DDL or schema build failure

    Raised when:
    - SQL syntax error in DDL files
    - Missing required schema directories
    - Circular dependencies between schema files
    - Schema hash computation fails

    Example:
        >>> raise SchemaError("Syntax error in 10_tables/users.sql at line 15")
    """

    pass


class SyncError(ConfiturError):
    """Production data sync failure

    Raised when:
    - Cannot connect to source database
    - Table does not exist in source or target
    - Anonymization rule fails
    - Data copy operation fails

    Example:
        >>> raise SyncError("Table 'users' not found in source database")
    """

    pass


class DifferError(ConfiturError):
    """Schema diff detection error

    Raised when:
    - Cannot parse SQL DDL
    - Schema comparison fails
    - Ambiguous schema changes detected

    Example:
        >>> raise DifferError("Cannot parse CREATE TABLE statement")
    """

    pass


class ValidationError(ConfiturError):
    """Data or schema validation error

    Raised when:
    - Row count mismatch after migration
    - Foreign key constraints violated
    - Custom validation rules fail

    Example:
        >>> raise ValidationError("Row count mismatch: expected 10000, got 9999")
    """

    pass


class RollbackError(ConfiturError):
    """Migration rollback failure

    Raised when:
    - Cannot rollback migration (irreversible change)
    - Rollback SQL fails
    - Database state is inconsistent after rollback

    This is a critical error that may require manual intervention.

    Example:
        >>> raise RollbackError("Cannot rollback: data already deleted")
    """

    pass


class SQLError(ConfiturError):
    """SQL execution error with detailed context

    Raised when:
    - SQL statement fails during migration execution
    - Provides context about which SQL statement failed
    - Includes original SQL and error details

    Attributes:
        sql: The SQL statement that failed
        params: Query parameters (if any)
        original_error: The underlying database error

    Example:
        >>> raise SQLError(
        ...     "CREATE TABLE users (id INT PRIMARY KEY, name TEXT)",
        ...     None,
        ...     psycopg_error
        ... )
    """

    def __init__(
        self,
        sql: str,
        params: tuple[str, ...] | None,
        original_error: Exception,
    ):
        self.sql = sql
        self.params = params
        self.original_error = original_error

        # Create detailed error message
        message_parts = ["SQL execution failed"]

        # Add SQL snippet (first 100 chars)
        sql_preview = sql.strip()[:100]
        if len(sql.strip()) > 100:
            sql_preview += "..."
        message_parts.append(f"SQL: {sql_preview}")

        # Add parameters if present
        if params:
            message_parts.append(f"Parameters: {params}")

        # Add original error
        message_parts.append(f"Error: {original_error}")

        message = " | ".join(message_parts)
        super().__init__(message)


class GitError(ConfiturError):
    """Git operation error

    Raised when:
    - Git command fails (invalid ref, file not found, etc.)
    - Git not installed or available
    - Git repository operations fail

    Example:
        >>> raise GitError("Invalid git reference 'nonexistent_ref'")
    """

    pass


class NotAGitRepositoryError(GitError):
    """Directory is not a git repository

    Raised when:
    - Attempting git operations in non-git directory
    - .git directory not found

    Example:
        >>> raise NotAGitRepositoryError("Not a git repository: /tmp/not-git")
    """

    pass


# Re-export precondition exceptions for convenience
# These are defined in confiture.core.preconditions but users may want to
# import them from confiture.exceptions
from confiture.core.preconditions import (  # noqa: E402
    PreconditionError,
    PreconditionValidationError,
)

# Re-export sandbox exceptions
from confiture.testing.sandbox import PreStateSimulationError  # noqa: E402

__all__ = [
    "ConfiturError",
    "ConfigurationError",
    "MigrationError",
    "SchemaError",
    "SyncError",
    "DifferError",
    "ValidationError",
    "RollbackError",
    "SQLError",
    "GitError",
    "NotAGitRepositoryError",
    "PreconditionError",
    "PreconditionValidationError",
    "PreStateSimulationError",
]
