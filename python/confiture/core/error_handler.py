"""CLI error handler for structured error output.

This module provides functions for formatting errors for CLI output and
determining the appropriate exit code based on error type and code.
"""

from typing import Any

from rich.console import Console

from confiture.core.error_context import format_error_with_context
from confiture.exceptions import ConfiturError

console = Console()

# Phrases that signal a genuinely *missing* path. A ``*_DIR_NOT_FOUND`` context is
# only chosen when one of these is present — otherwise a schema/seed *apply*
# failure that merely carries the word "schema"/"seed" (e.g. a syntax error while
# applying DDL) would be mislabeled as a missing directory (#159). "could not
# find" / "not find" keep the FileNotFoundError dir messages classified; "no
# such" also covers a raw OS ``[Errno 2] No such file or directory``.
_MISSING_DIR_SIGNALS = (
    "not found",
    "could not find",
    "not find",
    "does not exist",
    "doesn't exist",
    "no such",
    "no sql files",
)


def _detect_error_context(error: Exception) -> str | None:
    """Detect error context code from exception type and message.

    Maps specific error types and patterns to error context codes for
    enhanced error messages with solutions.

    Args:
        error: The exception to analyze

    Returns:
        Error context code if matched, None otherwise
    """
    from confiture.exceptions import (
        ConfigurationError,
        MigrationConflictError,
        SchemaError,
        SeedError,
    )

    error_msg = str(error).lower()

    # #152: DSN-precedence routing errors are NOT connectivity problems — their
    # own resolution_hint is the right guidance ("drop one source" / "set a
    # DSN"). Skip the connection template, which the literal "database" keyword
    # (e.g. inside CONFITURE_DATABASE_URL) would otherwise wrongly trigger. Note
    # CONFIG_006 is genuinely "connection failed" and is intentionally excluded.
    if isinstance(error, ConfigurationError) and getattr(error, "error_code", None) in {
        "CONFIG_007",
        "CONFIG_010",
    }:
        return None

    # Database connection errors
    if isinstance(error, ConfigurationError) and any(
        keyword in error_msg for keyword in ["connection", "connect", "database", "postgresql"]
    ):
        if "permission" in error_msg or "denied" in error_msg:
            return "DB_PERMISSION_DENIED"
        return "DB_CONNECTION_FAILED"

    # Missing-directory errors. Gated on an explicit "missing" signal so an
    # apply/syntax failure carrying the bare word "schema"/"seed" is not
    # mislabeled as a missing directory (#159); those fall through to the
    # SQL_SYNTAX_ERROR check below.
    if isinstance(error, (SchemaError, FileNotFoundError)) and any(
        signal in error_msg for signal in _MISSING_DIR_SIGNALS
    ):
        if "seeds" in error_msg or "seed" in error_msg:
            return "SEEDS_DIR_NOT_FOUND"
        if "migration" in error_msg:
            return "MIGRATIONS_DIR_NOT_FOUND"
        if "schema" in error_msg:
            return "SCHEMA_DIR_NOT_FOUND"

    # Migration conflicts
    if isinstance(error, MigrationConflictError):
        return "MIGRATION_CONFLICT"

    # Seed validation errors
    if isinstance(error, SeedError) and ("validation" in error_msg or "validate" in error_msg):
        return "SEED_VALIDATION_FAILED"

    # SQL syntax errors
    if any(
        keyword in error_msg
        for keyword in [
            "syntax error",
            "syntax",
            "invalid syntax",
            "unexpected token",
            "parse error",
            "at ';'",
        ]
    ):
        return "SQL_SYNTAX_ERROR"

    # Table already exists
    if "already exists" in error_msg and ("table" in error_msg or "relation" in error_msg):
        return "TABLE_ALREADY_EXISTS"

    # Foreign key constraint
    if any(keyword in error_msg for keyword in ["foreign key", "constraint", "violate"]):
        return "FOREIGN_KEY_CONSTRAINT"

    # Disk space issues
    if any(
        keyword in error_msg for keyword in ["no space", "disk full", "out of space", "disk space"]
    ):
        return "INSUFFICIENT_DISK_SPACE"

    # Lock timeout
    if any(keyword in error_msg for keyword in ["lock timeout", "timeout", "deadlock"]):
        return "LOCK_TIMEOUT"

    return None


def format_error_for_cli(error: ConfiturError) -> str:
    """Format a ConfiturError for CLI output with Rich formatting.

    Includes error code (if present), message, context, and resolution hint.

    Args:
        error: The error to format

    Returns:
        Formatted error string (may include ANSI color codes)

    Example:
        >>> error = ConfigurationError(
        ...     "Missing field",
        ...     error_code="CONFIG_001",
        ...     resolution_hint="Add the field to config"
        ... )
        >>> output = format_error_for_cli(error)
        >>> print(output)
        ❌ Error CONFIG_001
        Missing field
        💡 Add the field to config
    """
    lines: list[str] = []

    # Add error code if present
    if error.error_code:
        lines.append(f"[red]❌ Error {error.error_code}[/red]")
    else:
        lines.append("[red]❌ Error[/red]")

    # Add message
    lines.append(str(error))

    # Add context if present
    if error.context:
        context_items = [f"  {k}: {v}" for k, v in error.context.items()]
        context_str = "\n".join(context_items)
        lines.append(f"[dim]Context:[/dim]\n{context_str}")

    # Add resolution hint if present
    if error.resolution_hint:
        lines.append(f"[yellow]💡 {error.resolution_hint}[/yellow]")

    return "\n".join(lines)


def handle_cli_error(error: Exception) -> int:
    """Handle an exception and return the appropriate exit code.

    For ConfiturError instances with an error_code, looks up the exit code
    from the error code registry. For other exceptions, returns 1 (generic error).

    Args:
        error: The exception to handle

    Returns:
        Exit code (0-10) appropriate for the error type

    Example:
        >>> error = ConfigurationError("config", error_code="CONFIG_001")
        >>> exit_code = handle_cli_error(error)
        >>> exit_code
        2
    """
    # Handle ConfiturError specifically
    if isinstance(error, ConfiturError):
        # Try to get exit code from error's exit_code property
        # which looks it up in the registry
        if error.error_code:
            try:
                return error.exit_code
            except ValueError:
                # Code not in registry, use default
                return 1
        return 1

    # Lock contention maps to LOCK_1300 (exit 6 per #146) even though
    # LockAcquisitionError is not a ConfiturError (issue #147).
    from confiture.core.locking import LockAcquisitionError

    if isinstance(error, LockAcquisitionError):
        from confiture.core.error_codes import ERROR_CODE_REGISTRY

        return ERROR_CODE_REGISTRY.get("LOCK_1300").exit_code

    # For other exceptions, return generic error code
    return 1


def print_error_to_console(error: Exception, error_console: Console | None = None) -> None:
    """Print an error to the console with Rich formatting.

    Tries to detect specific error contexts and provide enhanced error
    messages with solutions. Falls back to standard formatting if no
    context is detected.

    Args:
        error: The exception to print
        error_console: Optional Rich Console to use for error output.
            If None, uses the default console. Use to write errors to stderr.
    """
    # Use provided console or fall back to default
    out_console = error_console or console

    # Try to detect and use enhanced error context
    error_context = _detect_error_context(error)
    if error_context:
        formatted = format_error_with_context(error_context, str(error))
        out_console.print(formatted)
        return

    # Fall back to standard error formatting
    if isinstance(error, ConfiturError):
        formatted = format_error_for_cli(error)
        out_console.print(formatted)
    else:
        # Generic exception without special formatting
        out_console.print(f"[red]Error: {error}[/red]")


def get_error_context(error: Exception) -> dict[str, Any]:
    """Extract structured context from an error.

    For ConfiturError instances, returns the context dict. For other
    exceptions, returns a minimal dict with the exception message.

    Args:
        error: The exception to extract context from

    Returns:
        Dict with error context

    Example:
        >>> error = ConfiturError("test", context={"file": "config.yaml"})
        >>> get_error_context(error)
        {'file': 'config.yaml'}
    """
    if isinstance(error, ConfiturError):
        return error.context
    return {"message": str(error)}
