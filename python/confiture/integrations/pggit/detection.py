"""
pgGit detection and version checking.

These functions help determine if pgGit is available and compatible
before attempting to use pgGit features.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from confiture.integrations.pggit.exceptions import (
    PgGitNotAvailableError,
    PgGitVersionError,
)

if TYPE_CHECKING:
    from psycopg import Connection

# Minimum supported pgGit version
# This should match the version that has all required functions
MIN_PGGIT_VERSION = (0, 1, 0)


def is_pggit_available(connection: Connection) -> bool:
    """
    Check if pgGit extension is installed and available.

    This function checks for the presence of the pgGit extension
    in the current database. It does NOT verify that pgGit is
    properly initialized or functional.

    Args:
        connection: Active PostgreSQL connection (psycopg3)

    Returns:
        True if pgGit extension exists, False otherwise

    Example:
        >>> with psycopg.connect(DATABASE_URL) as conn:
        ...     if is_pggit_available(conn):
        ...         print("pgGit is available!")
        ...     else:
        ...         print("pgGit not installed")
    """
    try:
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT EXISTS (
                    SELECT 1 FROM pg_extension WHERE extname = 'pggit'
                )
            """)
            result = cursor.fetchone()
            return bool(result and result[0])
    except Exception:
        return False


def get_pggit_version(connection: Connection) -> tuple[int, int, int] | None:
    """
    Get the installed pgGit version.

    Args:
        connection: Active PostgreSQL connection (psycopg3)

    Returns:
        Tuple of (major, minor, patch) or None if pgGit not available
        or version cannot be determined.

    Example:
        >>> version = get_pggit_version(conn)
        >>> if version and version >= (0, 1, 2):
        ...     print("Version 0.1.2 or newer")
    """
    if not is_pggit_available(connection):
        return None

    try:
        with connection.cursor() as cursor:
            # Try pggit.version() function first
            cursor.execute("SELECT pggit.version()")
            result = cursor.fetchone()

            if result and result[0]:
                version_str = str(result[0])
                # Parse version string like "0.1.2" or "0.1.2-beta"
                match = re.match(r"(\d+)\.(\d+)\.(\d+)", version_str)
                if match:
                    return (
                        int(match.group(1)),
                        int(match.group(2)),
                        int(match.group(3)),
                    )
    except Exception:
        pass

    # Fallback: try to get version from extension metadata
    try:
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT extversion FROM pg_extension WHERE extname = 'pggit'
            """)
            result = cursor.fetchone()

            if result and result[0]:
                version_str = str(result[0])
                match = re.match(r"(\d+)\.(\d+)\.(\d+)", version_str)
                if match:
                    return (
                        int(match.group(1)),
                        int(match.group(2)),
                        int(match.group(3)),
                    )
    except Exception:
        pass

    return None


def require_pggit(
    connection: Connection,
    min_version: tuple[int, int, int] | None = None,
) -> tuple[int, int, int]:
    """
    Require pgGit to be available with minimum version.

    Use this at the start of functions that require pgGit to ensure
    the extension is available before proceeding.

    Args:
        connection: Active PostgreSQL connection (psycopg3)
        min_version: Minimum required version tuple (default: MIN_PGGIT_VERSION)

    Returns:
        The installed pgGit version tuple

    Raises:
        PgGitNotAvailableError: If pgGit is not installed
        PgGitVersionError: If pgGit version is too old

    Example:
        >>> def my_branch_operation(conn):
        ...     require_pggit(conn, min_version=(0, 1, 2))
        ...     # Now safe to use pgGit functions
        ...     conn.execute("SELECT pggit.create_branch('feature/x')")
    """
    if min_version is None:
        min_version = MIN_PGGIT_VERSION

    if not is_pggit_available(connection):
        raise PgGitNotAvailableError(
            "pgGit extension is not installed in this database. "
            "Install with: CREATE EXTENSION pggit CASCADE;\n\n"
            "Note: pgGit is for development databases only. "
            "Do not install pgGit on production databases."
        )

    version = get_pggit_version(connection)

    if version is None:
        raise PgGitVersionError(
            "Could not determine pgGit version. "
            "The extension may be corrupted or incompatible."
        )

    if version < min_version:
        current = ".".join(map(str, version))
        required = ".".join(map(str, min_version))
        raise PgGitVersionError(
            f"pgGit version {current} is too old. "
            f"Minimum required version is {required}. "
            "Please update pgGit to continue."
        )

    return version


def is_pggit_initialized(connection: Connection) -> bool:
    """
    Check if pgGit is initialized (has required tables/functions).

    pgGit may be installed but not yet initialized. This function
    checks for the presence of core pgGit tables.

    Args:
        connection: Active PostgreSQL connection

    Returns:
        True if pgGit is initialized, False otherwise
    """
    if not is_pggit_available(connection):
        return False

    try:
        with connection.cursor() as cursor:
            # Check for core pgGit tables
            cursor.execute("""
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.tables
                    WHERE table_schema = 'pggit'
                    AND table_name IN ('objects', 'object_history', 'branches')
                )
            """)
            result = cursor.fetchone()
            return bool(result and result[0])
    except Exception:
        return False


def get_pggit_info(connection: Connection) -> dict | None:
    """
    Get comprehensive pgGit installation information.

    Useful for diagnostics and debugging.

    Args:
        connection: Active PostgreSQL connection

    Returns:
        Dict with pgGit info or None if not available

    Example return:
        {
            "available": True,
            "version": (0, 1, 2),
            "version_string": "0.1.2",
            "initialized": True,
            "tables": ["objects", "object_history", "branches", ...],
            "functions_count": 42,
        }
    """
    if not is_pggit_available(connection):
        return None

    info: dict = {
        "available": True,
        "version": get_pggit_version(connection),
        "version_string": None,
        "initialized": is_pggit_initialized(connection),
        "tables": [],
        "functions_count": 0,
    }

    if info["version"]:
        info["version_string"] = ".".join(map(str, info["version"]))

    try:
        with connection.cursor() as cursor:
            # Get table list
            cursor.execute("""
                SELECT table_name FROM information_schema.tables
                WHERE table_schema = 'pggit'
                ORDER BY table_name
            """)
            info["tables"] = [row[0] for row in cursor.fetchall()]

            # Get function count
            cursor.execute("""
                SELECT COUNT(*) FROM information_schema.routines
                WHERE routine_schema = 'pggit'
            """)
            result = cursor.fetchone()
            info["functions_count"] = result[0] if result else 0
    except Exception:
        pass

    return info
