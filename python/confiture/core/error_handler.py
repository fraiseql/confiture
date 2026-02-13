"""CLI error handler for structured error output.

This module provides functions for formatting errors for CLI output and
determining the appropriate exit code based on error type and code.
"""

from typing import Any

from rich.console import Console

from confiture.core.error_context import format_error_with_context
from confiture.exceptions import ConfiturError

console = Console()


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

    # Database connection errors
    if isinstance(error, ConfigurationError) and any(
        keyword in error_msg
        for keyword in ["connection", "connect", "database", "postgresql"]
    ):
        if "permission" in error_msg or "denied" in error_msg:
            return "DB_PERMISSION_DENIED"
        return "DB_CONNECTION_FAILED"

    # File not found errors
    if isinstance(error, (SchemaError, FileNotFoundError)):
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
    if isinstance(error, SeedError) and (
        "validation" in error_msg or "validate" in error_msg
    ):
        return "SEED_VALIDATION_FAILED"

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

    # For other exceptions, return generic error code
    return 1


def print_error_to_console(error: Exception) -> None:
    """Print an error to the console with Rich formatting.

    Tries to detect specific error contexts and provide enhanced error
    messages with solutions. Falls back to standard formatting if no
    context is detected.

    Args:
        error: The exception to print
    """
    # Try to detect and use enhanced error context
    error_context = _detect_error_context(error)
    if error_context:
        formatted = format_error_with_context(error_context, str(error))
        console.print(formatted)
        return

    # Fall back to standard error formatting
    if isinstance(error, ConfiturError):
        formatted = format_error_for_cli(error)
        console.print(formatted)
    else:
        # Generic exception without special formatting
        console.print(f"[red]Error: {error}[/red]")


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
