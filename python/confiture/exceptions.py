"""Confiture exception hierarchy

All exceptions raised by Confiture inherit from ConfiturError.
This allows users to catch all Confiture-specific errors with a single except clause.
"""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from confiture.core.preconditions import Precondition


class ErrorSeverity(str, Enum):
    """Severity levels for errors.

    Attributes:
        INFO: Informational, no action needed
        WARNING: Should investigate but not blocking
        ERROR: Blocking issue, must fix
        CRITICAL: Severe issue, potential data loss

    Example:
        >>> from confiture.models.error import ErrorSeverity
        >>> ErrorSeverity.ERROR
        <ErrorSeverity.ERROR: 'error'>
        >>> ErrorSeverity.ERROR == "error"
        True
    """

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class ConfiturError(Exception):
    """Base exception for all Confiture errors.

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
        error_code: Machine-readable error code (e.g., "CONFIG_001").
                   All subclasses provide defaults; callers may override.

        severity: Error severity (INFO, WARNING, ERROR, CRITICAL).

        context: Structured context dict. Universal keys (all optional):
                 - "file_path": str — path to the file that caused the error
                 - "migration_version": str — version string (e.g., "20260228180602")
                 - "database_name": str — target database name
                 - "recovery_suggestions": list[str] — manual recovery steps

                 Subclasses may add domain-specific keys; see their docstrings.

        resolution_hint: Human-readable suggestion for resolving the error.
                        Example: "Check database permissions for schema 'public'"
                        Rendered by ``__str__`` so it survives every consumer,
                        including library callers that only ever see the string
                        form of the exception (issue #211).

        message: The base message, without the resolution hint. Renderers and
                 keyword classifiers read this; ``str(self)`` is for humans.
    """

    #: Separator introducing the hint in ``__str__``. Deliberately plain ASCII —
    #: exception strings land in log files and tracebacks whose encoding we do
    #: not control. The CLI renders its own ``💡`` from ``resolution_hint``.
    _HINT_PREFIX = "Hint: "

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

    @property
    def message(self) -> str:
        """The base message, without the ``resolution_hint`` suffix.

        ``str(self)`` appends the hint (#211), which is right for a human
        reading a traceback and wrong for anything that re-renders the hint
        separately or keyword-matches the message. Those read this instead.
        """
        return str(self.args[0]) if self.args else ""

    def _render_message(self) -> str:
        """The human-readable body, before the hint.

        Subclasses that enrich the rendered text (rather than the stored
        message) override this instead of ``__str__``, so the hint stays last.
        """
        return super().__str__()

    def __str__(self) -> str:
        """Render message + resolution hint.

        The hint is the whole point of computing it: without this, it reaches a
        human only through the CLI's Rich renderer or the JSON envelope, and
        every library consumer — pytest fixtures, orchestration code, plain
        logging — drops it (#211).

        Example:
            >>> print(ConfiturError("Boom.", resolution_hint="Try --force."))
            Boom.
            Hint: Try --force.
        """
        base = self._render_message()
        if self.resolution_hint:
            return f"{base}\n{self._HINT_PREFIX}{self.resolution_hint}"
        return base

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
            "message": self.message,
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
            # Reason: import cycle: confiture.core (its __init__ imports core.dry_run) -> exceptions -> error_codes -> models.error -> models/__init__ -> models.migration
            from confiture.error_codes import ERROR_CODE_REGISTRY

            definition = ERROR_CODE_REGISTRY.get(self.error_code)
            return definition.exit_code
        return 1


def base_message(error: BaseException) -> str:
    """The hint-free message of *error*.

    ``str()`` on a :class:`ConfiturError` appends its ``resolution_hint`` (#211).
    Renderers that already print the hint on their own line, and classifiers that
    keyword-match the message, want the body alone. Anything else is returned by
    ``str()`` unchanged.
    """
    if isinstance(error, ConfiturError):
        return error.message
    return str(error)


class ConfigurationError(ConfiturError):
    """Invalid configuration (YAML, environment, database connection).

    Raised when:
    - Environment YAML file is malformed or missing
    - Required configuration fields are missing
    - Database connection string is invalid
    - Include/exclude directory patterns are invalid

    Example:
        >>> raise ConfigurationError("Missing database_url in local.yaml")
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
        super().__init__(
            message,
            error_code=error_code or "CONFIG_001",
            severity=severity,
            context=context,
            resolution_hint=resolution_hint,
        )


class MigrationError(ConfiturError):
    """Migration execution failure.

    Raised when:
    - Migration file cannot be loaded
    - Migration up() or down() fails
    - Migration has already been applied
    - Migration rollback fails

    Attributes:
        version: Migration version that failed (e.g., "001")
        migration_name: Human-readable migration name

    Additional context keys:
        - "migration_name": str — human-readable migration name
        - "sql_statement": str — the SQL that failed (truncated)
        - "affected_tables": list[str] — tables modified by the migration
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
            error_code=error_code or "MIGR_001",
            severity=severity,
            context=context,
            resolution_hint=resolution_hint,
        )
        self.version = version
        self.migration_name = migration_name


class SchemaError(ConfiturError):
    """Invalid schema DDL or schema build failure.

    Raised when:
    - SQL syntax error in DDL files
    - Missing required schema directories
    - Circular dependencies between schema files
    - Schema hash computation fails

    Example:
        >>> raise SchemaError("Syntax error in 10_tables/users.sql at line 15")
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
        super().__init__(
            message,
            error_code=error_code or "SCHEMA_001",
            severity=severity,
            context=context,
            resolution_hint=resolution_hint,
        )


class SyncError(ConfiturError):
    """Production data sync failure.

    Raised when:
    - Cannot connect to source database
    - Table does not exist in source or target
    - Anonymization rule fails
    - Data copy operation fails

    Example:
        >>> raise SyncError("Table 'users' not found in source database")
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
        super().__init__(
            message,
            error_code=error_code or "SYNC_001",
            severity=severity,
            context=context,
            resolution_hint=resolution_hint,
        )


class DifferError(ConfiturError):
    """Schema diff detection error.

    Raised when:
    - Cannot parse SQL DDL
    - Schema comparison fails
    - Ambiguous schema changes detected

    Example:
        >>> raise DifferError("Cannot parse CREATE TABLE statement")
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
        super().__init__(
            message,
            error_code=error_code or "DIFF_001",
            severity=severity,
            context=context,
            resolution_hint=resolution_hint,
        )


class ValidationError(ConfiturError):
    """Data or schema validation error.

    Raised when:
    - Row count mismatch after migration
    - Foreign key constraints violated
    - Custom validation rules fail

    Example:
        >>> raise ValidationError("Row count mismatch: expected 10000, got 9999")
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
        super().__init__(
            message,
            error_code=error_code or "VALID_001",
            severity=severity,
            context=context,
            resolution_hint=resolution_hint,
        )


class VerifyFileError(ValidationError):
    """Verify file contains forbidden SQL (DDL/DML).

    Raised when:
    - A .verify.sql file contains ALTER, INSERT, UPDATE, DELETE, or other non-SELECT statements
    - Verify files must only contain SELECT (or WITH ... SELECT) queries

    Example:
        >>> raise VerifyFileError("Verify file contains forbidden ALTER statement")
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
        super().__init__(
            message,
            error_code=error_code or "VERIFY_001",
            severity=severity,
            context=context,
            resolution_hint=resolution_hint,
        )


class RollbackError(ConfiturError):
    """Migration rollback failure.

    Raised when:
    - Cannot rollback migration (irreversible change)
    - Rollback SQL fails
    - Database state is inconsistent after rollback

    This is a critical error that may require manual intervention.

    Example:
        >>> raise RollbackError("Cannot rollback: data already deleted")
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
        super().__init__(
            message,
            error_code=error_code or "ROLLBACK_001",
            severity=severity,
            context=context,
            resolution_hint=resolution_hint,
        )


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
        sql: str | Any,
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

        # Normalise sql to a plain string — callers may pass
        # psycopg.sql.Composable objects (Composed, SQL, Identifier …).
        as_string = getattr(sql, "as_string", None)
        sql_str: str = as_string(None) if callable(as_string) else str(sql)

        # Add SQL snippet (first 100 chars)
        sql_preview = sql_str.strip()[:100]
        if len(sql_str.strip()) > 100:
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
            error_code=error_code or "SQL_001",
            severity=severity,
            context=context,
            resolution_hint=resolution_hint,
        )


class GitError(ConfiturError):
    """Git operation error.

    Raised when:
    - Git command fails (invalid ref, file not found, etc.)
    - Git not installed or available
    - Git repository operations fail

    Example:
        >>> raise GitError("Invalid git reference 'nonexistent_ref'")
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
        super().__init__(
            message,
            error_code=error_code or "GIT_001",
            severity=severity,
            context=context,
            resolution_hint=resolution_hint,
        )


class NotAGitRepositoryError(GitError):
    """Directory is not a git repository.

    Raised when:
    - Attempting git operations in non-git directory
    - .git directory not found

    Example:
        >>> raise NotAGitRepositoryError("Not a git repository: /tmp/not-git")
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
        super().__init__(
            message,
            error_code=error_code or "GIT_002",
            severity=severity,
            context=context,
            resolution_hint=resolution_hint,
        )


class GrantAccompanimentError(GitError):
    """Grant file changes without corresponding migration.

    Raised when:
    - Files in db/7_grant/ changed but no .up.sql migration was staged
    - Migrate environments (staging, production) will not apply the grants

    Example:
        >>> raise GrantAccompanimentError("Grant changes staged without migration file")
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
        super().__init__(
            message,
            error_code=error_code or "GRANT_001",
            severity=severity,
            context=context,
            resolution_hint=resolution_hint,
        )


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
            error_code=error_code or "MIGR_004",
            severity=severity,
            context=context,
            resolution_hint=resolution_hint or "Use --force flag to overwrite existing file",
        )
        self.filepath = filepath


class DatabaseNotInitializedError(ConfiturError):
    """The tracking table is absent — confiture is not initialized on this DB.

    The fresh-database signal: a command that needs the tracking table (e.g.
    ``migrate current``) found it missing. Defaults to ``PRECON_1001``, which
    exits 2 per the #146 convention (a distinct, low-numbered "not initialized
    yet" signal, separate from connection failures and config errors).

    Note: distinct from ``confiture.core.preconditions.PreconditionError``,
    which is the migration-runtime precondition failure (a different concern).

    Example:
        >>> raise DatabaseNotInitializedError("Tracking table absent")
    """

    def __init__(
        self,
        message: str = "Database not initialized",
        *,
        error_code: str | None = None,
        severity: ErrorSeverity | None = None,
        context: dict[str, Any] | None = None,
        resolution_hint: str | None = None,
    ) -> None:
        super().__init__(
            message,
            error_code=error_code or "PRECON_1001",
            severity=severity,
            context=context,
            resolution_hint=(
                resolution_hint
                or "Run 'confiture migrate up' to initialize the tracking table, "
                "or 'confiture migrate baseline --through <version>' if the schema "
                "is already applied."
            ),
        )


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
            error_code=error_code or "GEN_001",
            severity=severity,
            context=context,
            resolution_hint=resolution_hint,
        )
        self.returncode = returncode
        self.stderr = stderr


class RebuildError(ConfiturError):
    """Schema rebuild failure.

    Raised when:
    - Schema build fails during rebuild
    - DDL application fails
    - Tracking table bootstrap fails
    - Schema cleanup fails

    Example:
        >>> raise RebuildError("Rebuild failed: cannot apply DDL")
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
        super().__init__(
            message,
            error_code=error_code or "REBUILD_001",
            severity=severity,
            context=context,
            resolution_hint=resolution_hint,
        )


class RestoreError(ConfiturError):
    """pg_restore failure, interruption, or unsupported dump format.

    Raised when:
    - Backup file is plain-text SQL format (requires custom or directory format)
    - pg_restore is not installed or not on PATH
    - pg_restore exits with non-zero status
    - Restore is interrupted by the user (Ctrl+C)
    - Post-restore table count is below the required minimum

    Example:
        >>> raise RestoreError("Backup is plain-text format; use pg_dump -Fc instead")
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
        super().__init__(
            message,
            error_code=error_code or "RESTORE_001",
            severity=severity,
            context=context,
            resolution_hint=resolution_hint,
        )


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
            error_code=error_code or "SEED_001",
            severity=severity,
            context=context,
            resolution_hint=resolution_hint,
        )
        self.seed_file = seed_file
        self.sql_error = sql_error


class UnsafeOperationError(ConfiturError):
    """Raised when a destructive DDL operation is attempted without force flag.

    Raised when:
    - DROP TABLE, DROP COLUMN, or other destructive operations are requested
    - The force_destructive flag is not set

    Example:
        >>> raise UnsafeOperationError("DROP TABLE is destructive. Use --force.")
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
        super().__init__(
            message,
            error_code=error_code or "DDL_001",
            severity=severity,
            context=context,
            resolution_hint=resolution_hint,
        )


class BootstrapError(ConfiturError):
    """Raised by ``confiture bootstrap`` (issue #137).

    Distinct subclass so callers can catch all bootstrap failures
    independently of generic configuration errors.  Defaults to
    ``PRECON_1000`` (exit code 5) — a bootstrap failure is a precondition
    the operator must satisfy (e.g. a superuser DSN, or ``--all-schemas``)
    before the environment can be set up.
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
        super().__init__(
            message,
            error_code=error_code or "PRECON_1000",
            severity=severity,
            context=context,
            resolution_hint=resolution_hint,
        )


class BootstrapScopeError(BootstrapError):
    """``REASSIGN OWNED`` would affect schemas outside ``ownership.apply_to``.

    Confiture refuses to run ``REASSIGN OWNED BY postgres TO migrator``
    across schemas the operator hasn't explicitly opted into, because
    the statement is database-wide and could rename ownership in
    extensions or unrelated schemas.  Pass ``--all-schemas`` to
    override.
    """


class PreconditionError(ConfiturError):
    """A migration precondition did not hold (``PRECON_1000``).

    Attributes:
        precondition: The precondition that failed.
        migration_version: Version of the migration, when known.
        migration_name: Name of the migration, when known.
    """

    def __init__(
        self,
        precondition: Precondition | str,
        message: str | None = None,
        migration_version: str | None = None,
        migration_name: str | None = None,
        *,
        error_code: str | None = None,
        resolution_hint: str | None = None,
    ) -> None:
        self.precondition = precondition
        self.migration_version = migration_version
        self.migration_name = migration_name
        super().__init__(
            message if message is not None else str(precondition),
            error_code=error_code or "PRECON_1000",
            resolution_hint=resolution_hint,
            context={
                "precondition": str(precondition),
                "migration_version": migration_version,
                "migration_name": migration_name,
            },
        )


class PreconditionValidationError(ConfiturError):
    """Several migration preconditions did not hold (``PRECON_1000``).

    Attributes:
        failures: ``(precondition, error_message)`` pairs.
        migration_version: Version of the migration, when known.
        migration_name: Name of the migration, when known.
    """

    def __init__(
        self,
        failures: list[tuple[Precondition, str]],
        migration_version: str | None = None,
        migration_name: str | None = None,
        *,
        error_code: str | None = None,
    ) -> None:
        self.failures = failures
        self.migration_version = migration_version
        self.migration_name = migration_name
        lines = [f"Migration preconditions failed ({len(failures)} failures):"]
        for precondition, error in failures:
            lines.append(f"  - {precondition}: {error}")
        if migration_version:
            lines.append(
                f"Migration: {migration_version}"
                + (f" ({migration_name})" if migration_name else "")
            )
        super().__init__(
            "\n".join(lines),
            error_code=error_code or "PRECON_1000",
            context={
                "failures": [(str(p), e) for p, e in failures],
                "migration_version": migration_version,
            },
        )


class PreStateSimulationError(Exception):
    """Raised when the migration sandbox cannot simulate the pre-migration state.

    Typically the DOWN migration failed, has no reversible implementation, or
    the database state does not support running it.
    """


__all__ = [
    "BootstrapError",
    "BootstrapScopeError",
    "ConfigurationError",
    "ConfiturError",
    "DatabaseNotInitializedError",
    "DifferError",
    "ErrorSeverity",
    "ExternalGeneratorError",
    "GitError",
    "MigrationConflictError",
    "MigrationError",
    "MigrationOverwriteError",
    "NotAGitRepositoryError",
    "PreStateSimulationError",
    "PreconditionError",
    "PreconditionValidationError",
    "RebuildError",
    "RestoreError",
    "RollbackError",
    "SQLError",
    "SchemaError",
    "SeedError",
    "SyncError",
    "UnsafeOperationError",
    "ValidationError",
]
