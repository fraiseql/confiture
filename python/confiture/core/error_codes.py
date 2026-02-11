"""Error code registry and definitions for structured error handling.

This module provides a central registry of error codes that enables deterministic
error handling in agent workflows while maintaining backward compatibility.

Error codes follow the format: CATEGORY_NNN where:
- CATEGORY is a 3-6 letter category name (CONFIG, MIGR, SCHEMA, etc.)
- NNN is a 3-digit number within the category (001-999)

Categories and their exit codes:
- CONFIG (001-099): Configuration errors → exit code 2
- MIGR (100-199): Migration execution errors → exit code 3
- SCHEMA (200-299): Schema DDL and build errors → exit code 4
- SYNC (300-399): Production data sync errors → exit code 5
- DIFFER (400-499): Schema diff detection errors → exit code 5
- VALID (500-599): Validation errors → exit code 5
- ROLLBACK (600-699): Rollback errors → exit code 8
- SQL (700-799): SQL execution errors → exit code 1
- GIT (800-899): Git operation errors → exit code 7
- PGGIT (900-999): pgGit integration errors → exit code 7
- PRECON (1000-1099): Precondition errors → exit code 5
- HOOK (1100-1199): Hook execution errors → exit code 1
- POOL (1200-1299): Connection pool errors → exit code 6
- LOCK (1300-1399): Database locking errors → exit code 6
- ANON (1400-1499): Anonymization errors → exit code 5
- LINT (1500-1599): Schema linting errors → exit code 5
"""

from dataclasses import dataclass

from confiture.models.error import ErrorSeverity


@dataclass(frozen=True)
class ErrorCodeDefinition:
    """Definition of a single error code.

    Attributes:
        code: Error code (e.g., "CONFIG_001")
        message_template: Message template with optional format placeholders
        severity: Severity level (INFO, WARNING, ERROR, CRITICAL)
        exit_code: Process exit code for this error (0-10)
        resolution_hint: Optional suggestion on how to resolve the error
    """

    code: str
    message_template: str
    severity: ErrorSeverity
    exit_code: int
    resolution_hint: str | None = None


class ErrorCodeRegistry:
    """Central registry for error code definitions.

    Provides O(1) lookup of error codes and maintains mapping between
    exception types and their default error codes.

    Example:
        >>> registry = ErrorCodeRegistry()
        >>> definition = ErrorCodeDefinition(
        ...     code="CONFIG_001",
        ...     message_template="Missing field '{field}'",
        ...     severity=ErrorSeverity.ERROR,
        ...     exit_code=2,
        ... )
        >>> registry.register(definition)
        >>> registered = registry.get("CONFIG_001")
        >>> registered.code
        'CONFIG_001'
    """

    def __init__(self) -> None:
        """Initialize empty registry."""
        self._codes: dict[str, ErrorCodeDefinition] = {}
        self._exception_defaults: dict[type, str] = {}

    def register(self, definition: ErrorCodeDefinition) -> None:
        """Register an error code definition.

        Args:
            definition: Error code definition to register

        Raises:
            ValueError: If code is already registered
        """
        if definition.code in self._codes:
            msg = f"Error code {definition.code} already registered"
            raise ValueError(msg)

        self._codes[definition.code] = definition

    def get(self, code: str) -> ErrorCodeDefinition:
        """Get an error code definition by code.

        Lookup is O(1) using internal dict.

        Args:
            code: Error code (e.g., "CONFIG_001")

        Returns:
            Error code definition

        Raises:
            ValueError: If code is not registered
        """
        if code not in self._codes:
            msg = f"Error code not found: {code}"
            raise ValueError(msg)

        return self._codes[code]

    def set_exception_default(self, exc_type: type, code: str) -> None:
        """Set the default error code for an exception type.

        Args:
            exc_type: Exception class
            code: Default error code for this exception type
        """
        self._exception_defaults[exc_type] = code

    def get_for_exception(self, exc_type: type) -> str | None:
        """Get the default error code for an exception type.

        Args:
            exc_type: Exception class

        Returns:
            Default error code for this exception type, or None if not set
        """
        return self._exception_defaults.get(exc_type)

    def all_codes(self) -> list[ErrorCodeDefinition]:
        """Get all registered error code definitions.

        Returns:
            List of all error code definitions
        """
        return list(self._codes.values())

    def size(self) -> int:
        """Get the number of registered error codes.

        Returns:
            Total number of error codes in registry
        """
        return len(self._codes)


def _create_global_registry() -> ErrorCodeRegistry:
    """Create and populate the global error code registry.

    Returns:
        Populated ErrorCodeRegistry with all 78 error codes
    """
    registry = ErrorCodeRegistry()

    # ========== CONFIG (001-099): Configuration errors → exit code 2 ==========
    config_codes = [
        ErrorCodeDefinition(
            code="CONFIG_001",
            message_template="Missing required field '{field}' in {file}",
            severity=ErrorSeverity.ERROR,
            exit_code=2,
            resolution_hint="Add the field to your config file or set the corresponding environment variable",
        ),
        ErrorCodeDefinition(
            code="CONFIG_002",
            message_template="Invalid YAML syntax in {file}",
            severity=ErrorSeverity.ERROR,
            exit_code=2,
            resolution_hint="Check the YAML syntax in your configuration file",
        ),
        ErrorCodeDefinition(
            code="CONFIG_003",
            message_template="Invalid database URL format",
            severity=ErrorSeverity.ERROR,
            exit_code=2,
            resolution_hint="Use format: postgresql://user:password@host:port/database",
        ),
        ErrorCodeDefinition(
            code="CONFIG_004",
            message_template="Environment config not found: {env}",
            severity=ErrorSeverity.ERROR,
            exit_code=2,
            resolution_hint="Create configuration file for this environment or use an existing one",
        ),
        ErrorCodeDefinition(
            code="CONFIG_005",
            message_template="Invalid include/exclude pattern",
            severity=ErrorSeverity.ERROR,
            exit_code=2,
            resolution_hint="Check glob patterns in your configuration",
        ),
        ErrorCodeDefinition(
            code="CONFIG_006",
            message_template="Database connection failed",
            severity=ErrorSeverity.ERROR,
            exit_code=2,
            resolution_hint="Check database URL, host, port, and credentials",
        ),
    ]

    for code in config_codes:
        registry.register(code)

    # ========== MIGR (100-199): Migration execution errors → exit code 3 ==========
    migr_codes = [
        ErrorCodeDefinition(
            code="MIGR_100",
            message_template="Migration {version} not found",
            severity=ErrorSeverity.ERROR,
            exit_code=3,
            resolution_hint="Check the migration version and ensure the file exists",
        ),
        ErrorCodeDefinition(
            code="MIGR_101",
            message_template="Migration {version} already applied",
            severity=ErrorSeverity.WARNING,
            exit_code=0,
            resolution_hint="This migration has already been applied to the database",
        ),
        ErrorCodeDefinition(
            code="MIGR_102",
            message_template="Migration file corrupted: {file}",
            severity=ErrorSeverity.ERROR,
            exit_code=3,
            resolution_hint="Regenerate or restore the migration file",
        ),
        ErrorCodeDefinition(
            code="MIGR_103",
            message_template="Migration dependency not met: {version}",
            severity=ErrorSeverity.ERROR,
            exit_code=3,
            resolution_hint="Apply prerequisite migrations before this one",
        ),
        ErrorCodeDefinition(
            code="MIGR_104",
            message_template="Migration locked by another process",
            severity=ErrorSeverity.ERROR,
            exit_code=3,
            resolution_hint="Wait for other migration to complete or check for stale locks",
        ),
        ErrorCodeDefinition(
            code="MIGR_105",
            message_template="No pending migrations to apply",
            severity=ErrorSeverity.INFO,
            exit_code=0,
            resolution_hint="Your database schema is up to date",
        ),
        ErrorCodeDefinition(
            code="MIGR_106",
            message_template="Duplicate migration version: {version}",
            severity=ErrorSeverity.ERROR,
            exit_code=3,
            resolution_hint="Multiple migration files share the same version number. "
            "Rename files to use unique version prefixes. "
            "Run 'confiture migrate validate' to see all duplicates.",
        ),
    ]

    for code in migr_codes:
        registry.register(code)

    # ========== SCHEMA (200-299): Schema DDL and build errors → exit code 4 ==========
    schema_codes = [
        ErrorCodeDefinition(
            code="SCHEMA_200",
            message_template="SQL syntax error in {file} at line {line}",
            severity=ErrorSeverity.ERROR,
            exit_code=4,
            resolution_hint="Fix the SQL syntax error at the specified location",
        ),
        ErrorCodeDefinition(
            code="SCHEMA_201",
            message_template="Schema directory not found: {directory}",
            severity=ErrorSeverity.ERROR,
            exit_code=4,
            resolution_hint="Create the schema directory or check the path",
        ),
        ErrorCodeDefinition(
            code="SCHEMA_202",
            message_template="Circular dependency detected",
            severity=ErrorSeverity.ERROR,
            exit_code=4,
            resolution_hint="Break the circular dependency between schema files",
        ),
        ErrorCodeDefinition(
            code="SCHEMA_203",
            message_template="Duplicate table definition: {table}",
            severity=ErrorSeverity.ERROR,
            exit_code=4,
            resolution_hint="Remove the duplicate table definition",
        ),
        ErrorCodeDefinition(
            code="SCHEMA_204",
            message_template="Schema hash mismatch",
            severity=ErrorSeverity.ERROR,
            exit_code=4,
            resolution_hint="Schema definition has changed; rebuild the schema",
        ),
    ]

    for code in schema_codes:
        registry.register(code)

    # ========== SYNC (300-399): Production data sync errors → exit code 5 ==========
    sync_codes = [
        ErrorCodeDefinition(
            code="SYNC_300",
            message_template="Cannot connect to source database",
            severity=ErrorSeverity.ERROR,
            exit_code=5,
            resolution_hint="Check source database connection settings",
        ),
        ErrorCodeDefinition(
            code="SYNC_301",
            message_template="Table '{table}' not found in source database",
            severity=ErrorSeverity.ERROR,
            exit_code=5,
            resolution_hint="Verify table exists in source database",
        ),
        ErrorCodeDefinition(
            code="SYNC_302",
            message_template="Anonymization rule failed for column '{column}'",
            severity=ErrorSeverity.ERROR,
            exit_code=5,
            resolution_hint="Check anonymization rule syntax",
        ),
        ErrorCodeDefinition(
            code="SYNC_303",
            message_template="Data copy operation failed",
            severity=ErrorSeverity.ERROR,
            exit_code=5,
            resolution_hint="Check both source and target database connections",
        ),
    ]

    for code in sync_codes:
        registry.register(code)

    # ========== DIFFER (400-499): Schema diff detection errors → exit code 5 ==========
    differ_codes = [
        ErrorCodeDefinition(
            code="DIFFER_400",
            message_template="Cannot parse SQL DDL",
            severity=ErrorSeverity.ERROR,
            exit_code=5,
            resolution_hint="Fix the SQL syntax in your schema files",
        ),
        ErrorCodeDefinition(
            code="DIFFER_401",
            message_template="Schema comparison failed",
            severity=ErrorSeverity.ERROR,
            exit_code=5,
            resolution_hint="Verify both schema definitions are valid",
        ),
        ErrorCodeDefinition(
            code="DIFFER_402",
            message_template="Ambiguous schema changes detected",
            severity=ErrorSeverity.WARNING,
            exit_code=1,
            resolution_hint="Review and clarify the schema changes",
        ),
    ]

    for code in differ_codes:
        registry.register(code)

    # ========== VALID (500-599): Validation errors → exit code 5 ==========
    valid_codes = [
        ErrorCodeDefinition(
            code="VALID_500",
            message_template="Row count mismatch: expected {expected}, got {actual}",
            severity=ErrorSeverity.ERROR,
            exit_code=5,
            resolution_hint="Verify data was copied correctly",
        ),
        ErrorCodeDefinition(
            code="VALID_501",
            message_template="Foreign key constraint violated",
            severity=ErrorSeverity.ERROR,
            exit_code=5,
            resolution_hint="Check foreign key relationships in your data",
        ),
        ErrorCodeDefinition(
            code="VALID_502",
            message_template="Custom validation rule failed",
            severity=ErrorSeverity.ERROR,
            exit_code=5,
            resolution_hint="Review custom validation rules",
        ),
    ]

    for code in valid_codes:
        registry.register(code)

    # ========== ROLLBACK (600-699): Rollback errors → exit code 8 ==========
    rollback_codes = [
        ErrorCodeDefinition(
            code="ROLLBACK_600",
            message_template="Cannot rollback: irreversible change",
            severity=ErrorSeverity.CRITICAL,
            exit_code=8,
            resolution_hint="Manual intervention required; cannot automatically rollback",
        ),
        ErrorCodeDefinition(
            code="ROLLBACK_601",
            message_template="Rollback SQL failed",
            severity=ErrorSeverity.CRITICAL,
            exit_code=8,
            resolution_hint="Check rollback script syntax and database state",
        ),
        ErrorCodeDefinition(
            code="ROLLBACK_602",
            message_template="Database state inconsistent after rollback",
            severity=ErrorSeverity.CRITICAL,
            exit_code=8,
            resolution_hint="Database may be partially rolled back; manual recovery needed",
        ),
    ]

    for code in rollback_codes:
        registry.register(code)

    # ========== SQL (700-799): SQL execution errors → exit code 1 ==========
    sql_codes = [
        ErrorCodeDefinition(
            code="SQL_700",
            message_template="SQL execution failed",
            severity=ErrorSeverity.ERROR,
            exit_code=1,
            resolution_hint="Check the SQL statement for errors",
        ),
        ErrorCodeDefinition(
            code="SQL_701",
            message_template="Prepared statement error",
            severity=ErrorSeverity.ERROR,
            exit_code=1,
            resolution_hint="Check statement parameters",
        ),
        ErrorCodeDefinition(
            code="SQL_702",
            message_template="Transaction deadlock detected",
            severity=ErrorSeverity.WARNING,
            exit_code=1,
            resolution_hint="Retry the transaction",
        ),
        ErrorCodeDefinition(
            code="SQL_703",
            message_template="Lock timeout exceeded",
            severity=ErrorSeverity.ERROR,
            exit_code=1,
            resolution_hint="Wait for locks to be released or reduce query load",
        ),
    ]

    for code in sql_codes:
        registry.register(code)

    # ========== GIT (800-899): Git operation errors → exit code 7 ==========
    git_codes = [
        ErrorCodeDefinition(
            code="GIT_800",
            message_template="Git command failed",
            severity=ErrorSeverity.ERROR,
            exit_code=7,
            resolution_hint="Check git repository status",
        ),
        ErrorCodeDefinition(
            code="GIT_801",
            message_template="Invalid git reference: {ref}",
            severity=ErrorSeverity.ERROR,
            exit_code=7,
            resolution_hint="Check the git reference name",
        ),
        ErrorCodeDefinition(
            code="GIT_802",
            message_template="Not a git repository",
            severity=ErrorSeverity.ERROR,
            exit_code=7,
            resolution_hint="Initialize a git repository or use a valid repository path",
        ),
    ]

    for code in git_codes:
        registry.register(code)

    # ========== PGGIT (900-999): pgGit integration errors → exit code 7 ==========
    pggit_codes = [
        ErrorCodeDefinition(
            code="PGGIT_900",
            message_template="pgGit command failed",
            severity=ErrorSeverity.ERROR,
            exit_code=7,
            resolution_hint="Check pgGit is installed and configured",
        ),
        ErrorCodeDefinition(
            code="PGGIT_901",
            message_template="Invalid pgGit configuration",
            severity=ErrorSeverity.ERROR,
            exit_code=7,
            resolution_hint="Check pgGit configuration in confiture config",
        ),
    ]

    for code in pggit_codes:
        registry.register(code)

    # ========== PRECON (1000-1099): Precondition errors → exit code 5 ==========
    precon_codes = [
        ErrorCodeDefinition(
            code="PRECON_1000",
            message_template="Precondition not met: {condition}",
            severity=ErrorSeverity.ERROR,
            exit_code=5,
            resolution_hint="Ensure the precondition is satisfied before retrying",
        ),
        ErrorCodeDefinition(
            code="PRECON_1001",
            message_template="Database not initialized",
            severity=ErrorSeverity.ERROR,
            exit_code=5,
            resolution_hint="Run 'confiture init' to initialize the database",
        ),
    ]

    for code in precon_codes:
        registry.register(code)

    # ========== HOOK (1100-1199): Hook execution errors → exit code 1 ==========
    hook_codes = [
        ErrorCodeDefinition(
            code="HOOK_1100",
            message_template="Pre-migration hook failed",
            severity=ErrorSeverity.ERROR,
            exit_code=1,
            resolution_hint="Check hook script and address the failure",
        ),
        ErrorCodeDefinition(
            code="HOOK_1101",
            message_template="Post-migration hook failed",
            severity=ErrorSeverity.ERROR,
            exit_code=1,
            resolution_hint="Migration succeeded but hook failed",
        ),
    ]

    for code in hook_codes:
        registry.register(code)

    # ========== POOL (1200-1299): Connection pool errors → exit code 6 ==========
    pool_codes = [
        ErrorCodeDefinition(
            code="POOL_1200",
            message_template="Connection pool exhausted",
            severity=ErrorSeverity.ERROR,
            exit_code=6,
            resolution_hint="Increase pool size or wait for connections to be released",
        ),
        ErrorCodeDefinition(
            code="POOL_1201",
            message_template="Connection pool initialization failed",
            severity=ErrorSeverity.ERROR,
            exit_code=6,
            resolution_hint="Check database connection settings",
        ),
    ]

    for code in pool_codes:
        registry.register(code)

    # ========== LOCK (1300-1399): Database locking errors → exit code 6 ==========
    lock_codes = [
        ErrorCodeDefinition(
            code="LOCK_1300",
            message_template="Cannot acquire database lock",
            severity=ErrorSeverity.ERROR,
            exit_code=6,
            resolution_hint="Wait for other operations to complete",
        ),
        ErrorCodeDefinition(
            code="LOCK_1301",
            message_template="Lock held by {holder}",
            severity=ErrorSeverity.WARNING,
            exit_code=6,
            resolution_hint="Check what operation is holding the lock",
        ),
    ]

    for code in lock_codes:
        registry.register(code)

    # ========== ANON (1400-1499): Anonymization errors → exit code 5 ==========
    anon_codes = [
        ErrorCodeDefinition(
            code="ANON_1400",
            message_template="Invalid anonymization rule",
            severity=ErrorSeverity.ERROR,
            exit_code=5,
            resolution_hint="Check anonymization rule syntax",
        ),
        ErrorCodeDefinition(
            code="ANON_1401",
            message_template="Anonymization function not found: {function}",
            severity=ErrorSeverity.ERROR,
            exit_code=5,
            resolution_hint="Define the anonymization function or use a built-in",
        ),
    ]

    for code in anon_codes:
        registry.register(code)

    # ========== LINT (1500-1599): Schema linting errors → exit code 5 ==========
    lint_codes = [
        ErrorCodeDefinition(
            code="LINT_1500",
            message_template="Schema lint error: {message}",
            severity=ErrorSeverity.ERROR,
            exit_code=5,
            resolution_hint="Fix the schema linting error",
        ),
        ErrorCodeDefinition(
            code="LINT_1501",
            message_template="Schema lint warning: {message}",
            severity=ErrorSeverity.WARNING,
            exit_code=0,
            resolution_hint="Address the linting warning",
        ),
    ]

    for code in lint_codes:
        registry.register(code)

    return registry


# Global registry instance
ERROR_CODE_REGISTRY = _create_global_registry()
