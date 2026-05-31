"""Error code registry and definitions for structured error handling.

This module provides a central registry of error codes that enables deterministic
error handling in agent workflows while maintaining backward compatibility.

Error codes follow the format: CATEGORY_NNN where:
- CATEGORY is a 3-6 letter category name (CONFIG, MIGR, SCHEMA, etc.)
- NNN is a 3-digit number within the category (001-999)

Categories and their exit codes (the #146 stabilized convention; see
docs/reference/exit-codes.md and CANONICAL_EXIT_CODES below for the contract):
- CONFIG (001-099): Configuration errors → exit code 5
    (carve-out: CONFIG_006 "connection failed" → 3)
- MIGR (100-199): Migration execution errors → exit code 3
    (carve-outs: MIGR_101/105 success-with-signal → 0)
- SCHEMA (200-299): Schema DDL and build errors → exit code 4
- SYNC (300-399): Production data sync errors → exit code 5
- DIFFER (400-499): Schema diff detection errors → exit code 5
    (carve-out: DIFFER_402 ambiguous-change advisory → 1)
- VALID (500-599): Validation errors → exit code 5
- ROLLBACK (600-699): Rollback errors → exit code 8
- SQL (700-799): SQL execution errors → exit code 1
- GIT (800-899): Git operation errors → exit code 7
- PGGIT (900-999): pgGit integration errors → exit code 7
- PRECON (1000-1099): Precondition errors → exit code 5
    (carve-out: PRECON_1001 "tracking table absent" → 2)
- HOOK (1100-1199): Hook execution errors → exit code 1
- POOL (1200-1299): Connection pool errors → exit code 6
- LOCK (1300-1399): Database locking errors → exit code 6
- ANON (1400-1499): Anonymization errors → exit code 5
- LINT (1500-1599): Schema linting errors → exit code 5
    (carve-out: LINT_1501 non-blocking advisory → 0)
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
        Populated ErrorCodeRegistry with all 72 error codes
    """
    registry = ErrorCodeRegistry()

    # ========== CONFIG (001-099): Configuration errors → exit code 2 ==========
    config_codes = [
        ErrorCodeDefinition(
            code="CONFIG_001",
            message_template="Missing required field '{field}' in {file}",
            severity=ErrorSeverity.ERROR,
            exit_code=5,
            resolution_hint="Add the field to your config file or set the corresponding environment variable",
        ),
        ErrorCodeDefinition(
            code="CONFIG_002",
            message_template="Invalid YAML syntax in {file}",
            severity=ErrorSeverity.ERROR,
            exit_code=5,
            resolution_hint="Check the YAML syntax in your configuration file",
        ),
        ErrorCodeDefinition(
            code="CONFIG_003",
            message_template="Invalid database URL format",
            severity=ErrorSeverity.ERROR,
            exit_code=5,
            resolution_hint="Use format: postgresql://user:password@host:port/database",
        ),
        ErrorCodeDefinition(
            code="CONFIG_004",
            message_template="Environment config not found: {env}",
            severity=ErrorSeverity.ERROR,
            exit_code=5,
            resolution_hint="Create configuration file for this environment or use an existing one",
        ),
        ErrorCodeDefinition(
            code="CONFIG_005",
            message_template="Invalid include/exclude pattern",
            severity=ErrorSeverity.ERROR,
            exit_code=5,
            resolution_hint="Check glob patterns in your configuration",
        ),
        ErrorCodeDefinition(
            code="CONFIG_006",
            message_template="Database connection failed",
            severity=ErrorSeverity.ERROR,
            exit_code=3,
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
        ErrorCodeDefinition(
            code="MIGR_107",
            message_template=(
                "Migration {version} ({name}) issued an explicit COMMIT or "
                "ROLLBACK in its body, breaking confiture's transaction envelope"
            ),
            severity=ErrorSeverity.ERROR,
            exit_code=3,
            resolution_hint=(
                "Remove any explicit COMMIT or ROLLBACK from the migration body. "
                "Confiture manages the outer transaction; embedded transaction "
                "control leaves the database in an unrecoverable state if a "
                "subsequent statement fails. If you need autocommit semantics, "
                "set transactional = False on the migration."
            ),
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
            exit_code=2,
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

    # ========== MIGR extra: granular migration execution codes ==========
    migr_extra_codes = [
        ErrorCodeDefinition(
            code="MIGR_010",
            message_template="Lock timeout waiting for migration lock",
            severity=ErrorSeverity.ERROR,
            exit_code=3,
            resolution_hint="Retry with a higher --lock-timeout value or schedule during low-traffic window",
        ),
        ErrorCodeDefinition(
            code="MIGR_011",
            message_template="Checksum mismatch for migration '{version}'",
            severity=ErrorSeverity.ERROR,
            exit_code=3,
            resolution_hint="Migration file was modified after application. Restore the original file or use --force to override.",
        ),
        ErrorCodeDefinition(
            code="CONFIG_010",
            message_template="Database URL not set in environment '{env}'",
            severity=ErrorSeverity.ERROR,
            exit_code=5,
            resolution_hint="Set database_url in db/environments/{env}.yaml or DATABASE_URL environment variable",
        ),
    ]

    for code in migr_extra_codes:
        registry.register(code)

    # ========== Default error codes for exception types ==========
    # These are the base codes used as defaults in exception __init__ methods.
    # More specific codes (e.g., MIGR_100, SCHEMA_200) are used at raise sites.
    default_codes = [
        ErrorCodeDefinition(
            code="MIGR_001",
            message_template="Migration error",
            severity=ErrorSeverity.ERROR,
            exit_code=3,
            resolution_hint="Check migration files and database state",
        ),
        ErrorCodeDefinition(
            code="MIGR_004",
            message_template="Migration file already exists",
            severity=ErrorSeverity.ERROR,
            exit_code=3,
            resolution_hint="Use --force flag to overwrite existing file",
        ),
        ErrorCodeDefinition(
            code="SCHEMA_001",
            message_template="Schema error",
            severity=ErrorSeverity.ERROR,
            exit_code=4,
            resolution_hint="Check SQL DDL files for errors",
        ),
        ErrorCodeDefinition(
            code="SYNC_001",
            message_template="Sync error",
            severity=ErrorSeverity.ERROR,
            exit_code=5,
            resolution_hint="Check source and target database connections",
        ),
        ErrorCodeDefinition(
            code="DIFF_001",
            message_template="Schema diff error",
            severity=ErrorSeverity.ERROR,
            exit_code=5,
            resolution_hint="Check SQL DDL for parsing issues",
        ),
        ErrorCodeDefinition(
            code="VALID_001",
            message_template="Validation error",
            severity=ErrorSeverity.ERROR,
            exit_code=5,
            resolution_hint="Check validation rules and data integrity",
        ),
        ErrorCodeDefinition(
            code="VERIFY_001",
            message_template="Verify file contains forbidden SQL",
            severity=ErrorSeverity.ERROR,
            exit_code=5,
            resolution_hint="Verify files must only contain SELECT queries",
        ),
        ErrorCodeDefinition(
            code="ROLLBACK_001",
            message_template="Rollback error",
            severity=ErrorSeverity.CRITICAL,
            exit_code=8,
            resolution_hint="Check rollback SQL and database state",
        ),
        ErrorCodeDefinition(
            code="SQL_001",
            message_template="SQL execution error",
            severity=ErrorSeverity.ERROR,
            exit_code=1,
            resolution_hint="Check the SQL statement for errors",
        ),
        ErrorCodeDefinition(
            code="GIT_001",
            message_template="Git operation error",
            severity=ErrorSeverity.ERROR,
            exit_code=7,
            resolution_hint="Check git repository status",
        ),
        ErrorCodeDefinition(
            code="GIT_002",
            message_template="Not a git repository",
            severity=ErrorSeverity.ERROR,
            exit_code=7,
            resolution_hint="Initialize a git repository or use a valid repository path",
        ),
        ErrorCodeDefinition(
            code="GRANT_001",
            message_template="Grant accompaniment error",
            severity=ErrorSeverity.ERROR,
            exit_code=7,
            resolution_hint="Stage a migration file alongside grant changes",
        ),
        ErrorCodeDefinition(
            code="GEN_001",
            message_template="External generator error",
            severity=ErrorSeverity.ERROR,
            exit_code=3,
            resolution_hint="Check the external generator command and its output",
        ),
        ErrorCodeDefinition(
            code="REBUILD_001",
            message_template="Schema rebuild error",
            severity=ErrorSeverity.ERROR,
            exit_code=4,
            resolution_hint="Check schema DDL and database state",
        ),
        ErrorCodeDefinition(
            code="RESTORE_001",
            message_template="Restore error",
            severity=ErrorSeverity.ERROR,
            exit_code=5,
            resolution_hint="Check backup format and pg_restore availability",
        ),
        ErrorCodeDefinition(
            code="SEED_001",
            message_template="Seed execution error",
            severity=ErrorSeverity.ERROR,
            exit_code=5,
            resolution_hint="Check seed file syntax and database state",
        ),
    ]

    for code in default_codes:
        registry.register(code)

    return registry


# Global registry instance
ERROR_CODE_REGISTRY = _create_global_registry()


# ============================================================================
# Canonical exit-code contract (issue #146)
# ============================================================================
#
# CANONICAL_EXIT_CODES is the single, HAND-AUTHORED source of truth for the
# integer process exit code every symbolic error code maps to. It is written
# directly from docs/reference/exit-codes.md — it is NOT derived from the
# registry. The convention test (tests/unit/test_exit_code_convention.py)
# asserts ERROR_CODE_REGISTRY == this dict; deriving one from the other would
# make that test a tautology. The redundancy IS the enforcement mechanism.
#
# Family defaults (the renumbered convention #146 freezes as a contract):
#   2 = tracking table absent (PRECON_1001 only)   3 = DB connection failed
#   4 = schema/DDL/build       5 = config invalid + validation/sync/lint/...
#   6 = lock / pool contention 7 = git / pggit / grant
#   8 = irreversible rollback  1 = generic SQL/hook   0 = success-with-signal
#
# Per-code carve-outs that deliberately differ from their family default are
# annotated inline; do not "align" them to the family number during audits.
CANONICAL_EXIT_CODES: dict[str, int] = {
    # CONFIG family → 5 (config invalid), with CONFIG_006 carved out to 3.
    "CONFIG_001": 5,
    "CONFIG_002": 5,
    "CONFIG_003": 5,
    "CONFIG_004": 5,
    "CONFIG_005": 5,
    "CONFIG_006": 3,  # carve-out: DB connection failed (family is otherwise 5)
    "CONFIG_010": 5,
    # MIGR family → 3, with two success-with-signal carve-outs at 0.
    "MIGR_001": 3,
    "MIGR_004": 3,
    "MIGR_010": 3,
    "MIGR_011": 3,
    "MIGR_100": 3,
    "MIGR_101": 0,  # carve-out: already applied — success-with-signal
    "MIGR_102": 3,
    "MIGR_103": 3,
    "MIGR_104": 3,
    "MIGR_105": 0,  # carve-out: no pending migrations — success-with-signal
    "MIGR_106": 3,
    "MIGR_107": 3,
    # SCHEMA family → 4.
    "SCHEMA_001": 4,
    "SCHEMA_200": 4,
    "SCHEMA_201": 4,
    "SCHEMA_202": 4,
    "SCHEMA_203": 4,
    "SCHEMA_204": 4,
    # SYNC family → 5.
    "SYNC_001": 5,
    "SYNC_300": 5,
    "SYNC_301": 5,
    "SYNC_302": 5,
    "SYNC_303": 5,
    # DIFFER family → 5, with DIFFER_402 carved out to 1 (generic advisory).
    "DIFFER_400": 5,
    "DIFFER_401": 5,
    "DIFFER_402": 1,  # carve-out: ambiguous-change advisory (family is otherwise 5)
    "DIFF_001": 5,
    # VALID family → 5.
    "VALID_001": 5,
    "VALID_500": 5,
    "VALID_501": 5,
    "VALID_502": 5,
    "VERIFY_001": 5,
    # ROLLBACK family → 8 (irreversible / inconsistent state).
    "ROLLBACK_001": 8,
    "ROLLBACK_600": 8,
    "ROLLBACK_601": 8,
    "ROLLBACK_602": 8,
    # SQL family → 1 (generic execution failure).
    "SQL_001": 1,
    "SQL_700": 1,
    "SQL_701": 1,
    "SQL_702": 1,
    "SQL_703": 1,
    # GIT / PGGIT / GRANT → 7.
    "GIT_001": 7,
    "GIT_002": 7,
    "GIT_800": 7,
    "GIT_801": 7,
    "GIT_802": 7,
    "GRANT_001": 7,
    "PGGIT_900": 7,
    "PGGIT_901": 7,
    # GEN → 3 (migration generation belongs with the MIGR family number).
    "GEN_001": 3,
    # PRECON family → 5, with PRECON_1001 carved out to 2 (no tracking table).
    "PRECON_1000": 5,
    "PRECON_1001": 2,  # carve-out: tracking table absent (family is otherwise 5)
    # HOOK family → 1 (generic; a hook failure is not a confiture-domain error).
    "HOOK_1100": 1,
    "HOOK_1101": 1,
    # POOL / LOCK → 6 (contention).
    "POOL_1200": 6,
    "POOL_1201": 6,
    "LOCK_1300": 6,
    "LOCK_1301": 6,
    # ANON family → 5.
    "ANON_1400": 5,
    "ANON_1401": 5,
    # LINT family → 5, with LINT_1501 carved out to 0 (non-blocking advisory).
    "LINT_1500": 5,
    "LINT_1501": 0,  # carve-out: lint warning — informational, non-blocking
    # REBUILD → 4 (schema family number).
    "REBUILD_001": 4,
    # RESTORE / SEED → 5.
    "RESTORE_001": 5,
    "SEED_001": 5,
}


# Human-readable meaning of each integer exit code in the canonical convention.
# This is the operator-facing summary; the per-code mapping lives in
# CANONICAL_EXIT_CODES above. Codes 0–8 are in use; 9 is reserved.
EXIT_CODE_MEANINGS: dict[int, str] = {
    0: "Success (including success-with-signal: already applied, nothing pending, advisories)",
    1: "Generic failure (SQL/hook execution, ambiguous-change advisory, status: pending)",
    2: "Tracking table absent — confiture not initialized on this database yet",
    3: "Database connection failed — host/auth/network unreachable",
    4: "Schema / DDL / build error",
    5: "Configuration invalid, or validation / sync / lint / precondition failure",
    6: "Lock or connection-pool contention — another writer holds the lock",
    7: "Git / pgGit / grant-accompaniment error",
    8: "Irreversible rollback, or inconsistent state after rollback",
}


def render_exit_codes_doc() -> str:
    """Render the canonical exit-code reference as Markdown.

    The output is generated from the HAND-AUTHORED ``CANONICAL_EXIT_CODES`` and
    ``EXIT_CODE_MEANINGS`` — never from the registry — so the human-facing doc
    can never drift from the frozen contract. ``docs/reference/exit-codes.md``
    embeds this between generated-section markers; a coverage test asserts every
    in-use code has a row.

    Returns:
        Markdown containing the summary table and the per-code breakdown.
    """
    used_codes = sorted(set(CANONICAL_EXIT_CODES.values()))

    lines: list[str] = []
    lines.append("| Exit | Meaning |")
    lines.append("|------|---------|")
    for code in used_codes:
        lines.append(f"| {code} | {EXIT_CODE_MEANINGS.get(code, '(reserved)')} |")

    lines.append("")
    lines.append("### Symbolic codes per exit code")
    lines.append("")
    for code in used_codes:
        symbols = sorted(c for c, ec in CANONICAL_EXIT_CODES.items() if ec == code)
        lines.append(f"- **{code}** — {EXIT_CODE_MEANINGS.get(code, '(reserved)')}")
        lines.append(f"  - {', '.join(symbols)}")

    return "\n".join(lines)
