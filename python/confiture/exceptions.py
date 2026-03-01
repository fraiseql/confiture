"""Confiture exception hierarchy

All exceptions raised by Confiture inherit from ConfiturError.
This allows users to catch all Confiture-specific errors with a single except clause.
"""

from typing import Any

from confiture.models.error import ErrorSeverity


class ConfiturError(Exception):
    """Base exception for all Confiture errors

    All Confiture-specific exceptions inherit from this base class.
    This allows catching all Confiture errors with:

        try:
            confiture.build()
        except ConfiturError as e:
            # Handle any Confiture error
            pass

    Supports optional error codes for structured error handling:

        try:
            confiture.build()
        except ConfiturError as e:
            if e.error_code == "CONFIG_001":
                # Handle missing configuration
                pass

    Attributes:
        error_code: Machine-readable error code (e.g., "CONFIG_001")
        severity: Error severity level (INFO, WARNING, ERROR, CRITICAL)
        context: Additional context dict for error details
        resolution_hint: Optional suggestion for resolving the error
    """

    def __init__(
        self,
        message: str,
        *,
        error_code: str | None = None,
        severity: ErrorSeverity | None = None,
        context: dict[str, Any] | None = None,
        resolution_hint: str | None = None,
    ) -> None:
        """Initialize ConfiturError with optional error code support.

        Args:
            message: Human-readable error message
            error_code: Optional machine-readable error code
            severity: Optional error severity (defaults to ERROR)
            context: Optional dict with error context
            resolution_hint: Optional hint on how to resolve the error
        """
        super().__init__(message)
        self.error_code = error_code
        self.severity = severity or ErrorSeverity.ERROR
        self.context = context or {}
        self.resolution_hint = resolution_hint

    def to_dict(self) -> dict[str, Any]:
        """Get machine-readable representation of the error.

        Returns:
            Dict with error_code, severity, message, context, resolution_hint

        Example:
            >>> error = ConfiturError("test", error_code="CONFIG_001")
            >>> error.to_dict()
            {'error_code': 'CONFIG_001', 'severity': 'error', 'message': 'test', ...}
        """
        return {
            "error_code": self.error_code,
            "severity": self.severity.value,
            "message": str(self),
            "context": self.context,
            "resolution_hint": self.resolution_hint,
        }

    @property
    def exit_code(self) -> int:
        """Get the process exit code for this error.

        Returns exit code from error code registry if error_code is set,
        otherwise returns 1 (generic error).

        Returns:
            Exit code (0-10)
        """
        if self.error_code:
            from confiture.core.error_codes import ERROR_CODE_REGISTRY

            definition = ERROR_CODE_REGISTRY.get(self.error_code)
            return definition.exit_code
        return 1


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
        *,
        error_code: str | None = None,
        severity: ErrorSeverity | None = None,
        context: dict[str, Any] | None = None,
        resolution_hint: str | None = None,
    ) -> None:
        super().__init__(
            message,
            error_code=error_code,
            severity=severity,
            context=context,
            resolution_hint=resolution_hint,
        )
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
        *,
        error_code: str | None = None,
        severity: ErrorSeverity | None = None,
        context: dict[str, Any] | None = None,
        resolution_hint: str | None = None,
    ) -> None:
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
        super().__init__(
            message,
            error_code=error_code,
            severity=severity,
            context=context,
            resolution_hint=resolution_hint,
        )


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


class MigrationConflictError(MigrationError):
    """Migration version or name conflicts detected

    Raised when:
    - Multiple migration files have the same version number
    - Multiple migration files have the same name with different versions
    - Migration generation would create conflicts

    Attributes:
        conflicting_files: List of Path objects for conflicting files
    """

    def __init__(
        self,
        message: str,
        conflicting_files: list | None = None,
        *,
        error_code: str | None = None,
        severity: ErrorSeverity | None = None,
        context: dict[str, Any] | None = None,
        resolution_hint: str | None = None,
    ) -> None:
        super().__init__(
            message,
            error_code=error_code or "MIGR_106",
            severity=severity,
            context=context,
            resolution_hint=resolution_hint,
        )
        self.conflicting_files = conflicting_files or []


class MigrationOverwriteError(MigrationError):
    """Migration file would be overwritten

    Raised when:
    - Attempting to create migration file that already exists
    - No --force flag provided

    Attributes:
        filepath: Path to existing file that would be overwritten
    """

    def __init__(
        self,
        filepath: Any,
        *,
        error_code: str | None = None,
        severity: ErrorSeverity | None = None,
        context: dict[str, Any] | None = None,
        resolution_hint: str | None = None,
    ) -> None:
        super().__init__(
            f"Migration file already exists: {filepath.name}",
            error_code=error_code or "MIGRATION_004",
            severity=severity,
            context=context,
            resolution_hint=resolution_hint or "Use --force flag to overwrite existing file",
        )
        self.filepath = filepath


class ExternalGeneratorError(ConfiturError):
    """External migration generator command failed

    Raised when:
    - The generator command exits with a non-zero return code
    - The generator writes an empty SQL file

    Attributes:
        returncode: Exit code from the subprocess (if available)
        stderr: Standard error output from the generator (if available)
    """

    def __init__(
        self,
        message: str,
        returncode: int | None = None,
        stderr: str | None = None,
        *,
        error_code: str | None = None,
        severity: ErrorSeverity | None = None,
        context: dict[str, Any] | None = None,
        resolution_hint: str | None = None,
    ) -> None:
        super().__init__(
            message,
            error_code=error_code,
            severity=severity,
            context=context,
            resolution_hint=resolution_hint,
        )
        self.returncode = returncode
        self.stderr = stderr


class RebuildError(ConfiturError):
    """Schema rebuild failure

    Raised when:
    - Schema build fails during rebuild
    - DDL application fails
    - Tracking table bootstrap fails
    - Schema cleanup fails

    Example:
        >>> raise RebuildError("Rebuild failed: cannot apply DDL")
    """

    pass


class RestoreError(ConfiturError):
    """pg_restore failure, interruption, or unsupported dump format

    Raised when:
    - Backup file is plain-text SQL format (requires custom or directory format)
    - pg_restore is not installed or not on PATH
    - pg_restore exits with non-zero status
    - Restore is interrupted by the user (Ctrl+C)
    - Post-restore table count is below the required minimum

    Example:
        >>> raise RestoreError("Backup is plain-text format; use pg_dump -Fc instead")
    """

    pass


class SeedError(ConfiturError):
    """Seed file execution error

    Raised when:
    - Seed file cannot be loaded
    - Seed SQL execution fails
    - Seed file contains invalid commands (BEGIN/COMMIT/ROLLBACK)
    - Savepoint operations fail

    Attributes:
        seed_file: Path to seed file that failed (if applicable)
        sql_error: Original SQL error (if applicable)
    """

    def __init__(
        self,
        message: str,
        seed_file: str | None = None,
        sql_error: Exception | None = None,
        *,
        error_code: str | None = None,
        severity: ErrorSeverity | None = None,
        context: dict[str, Any] | None = None,
        resolution_hint: str | None = None,
    ) -> None:
        super().__init__(
            message,
            error_code=error_code,
            severity=severity,
            context=context,
            resolution_hint=resolution_hint,
        )
        self.seed_file = seed_file
        self.sql_error = sql_error


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
    "MigrationConflictError",
    "MigrationOverwriteError",
    "SchemaError",
    "SyncError",
    "DifferError",
    "ValidationError",
    "RollbackError",
    "SQLError",
    "GitError",
    "NotAGitRepositoryError",
    "ExternalGeneratorError",
    "RebuildError",
    "RestoreError",
    "SeedError",
    "PreconditionError",
    "PreconditionValidationError",
    "PreStateSimulationError",
]
