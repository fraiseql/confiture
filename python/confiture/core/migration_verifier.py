"""Migration verification using .verify.sql sidecar files.

After applying migrations, there's no built-in way to verify each migration
achieved its intended outcome. The .verify.sql sidecar pattern lets users
write assertion queries that are executed inside a SAVEPOINT (read-only,
no side effects) and checked for truthiness.

File format contract:
- Must contain a single SELECT (or WITH ... SELECT) statement
- No DDL, no DML
- Return at least one row; first column must be truthy (true/t/1/non-null/non-zero)
- Zero rows = FAILED; false/f/0/NULL in first column = FAILED
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import sqlparse

from confiture.core.migrator import _version_from_migration_filename
from confiture.exceptions import VerifyFileError


@dataclass
class VerifyResult:
    """Result of verifying a single migration.

    Attributes:
        version: Migration version string (e.g., "001" or "20260228120530")
        name: Human-readable migration name
        verify_file: Path to the .verify.sql file, or None if not found
        status: "verified", "failed", "skipped", or "no_file"
        actual_value: The first column of the first row returned, or None
        error: Error message if status is "failed", or None
    """

    version: str
    name: str
    verify_file: Path | None
    status: Literal["verified", "failed", "skipped", "no_file"]
    actual_value: Any | None = None
    error: str | None = None


class MigrationVerifier:
    """Verify applied migrations using .verify.sql sidecar files.

    Executes each verify query inside a SAVEPOINT/ROLLBACK (read-only, no
    side effects) and checks the first column of the first row for truthiness.

    Uses the same connection as Migrator — do not create a separate connection.

    Attributes:
        connection: Database connection (psycopg3 sync connection)
        migrations_dir: Directory containing migration files

    Example:
        >>> verifier = MigrationVerifier(connection=conn, migrations_dir=Path("db/migrations"))
        >>> results = verifier.verify_all(applied_versions=["001", "002"])
        >>> for r in results:
        ...     print(f"{r.version}: {r.status}")
    """

    def __init__(self, connection: Any, migrations_dir: Path):
        """Initialize migration verifier.

        Args:
            connection: Database connection
            migrations_dir: Directory containing migration files and .verify.sql files
        """
        self.connection = connection
        self.migrations_dir = migrations_dir

    def discover_verify_files(self) -> dict[str, Path]:
        """Map version string -> .verify.sql Path.

        Scans the migrations directory for *.verify.sql files and extracts
        the version prefix from each filename.

        Returns:
            Dictionary mapping version string to verify file path
        """
        result: dict[str, Path] = {}
        for f in self.migrations_dir.glob("*.verify.sql"):
            stem = f.name[: -len(".verify.sql")]
            version = _version_from_migration_filename(stem)
            result[version] = f
        return result

    def validate_verify_sql(self, content: str) -> None:
        """Reject DDL/DML using sqlparse statement type detection.

        Args:
            content: SQL content from the verify file

        Raises:
            VerifyFileError: If content contains forbidden SQL (DDL/DML)
        """
        parsed = sqlparse.parse(content)
        for stmt in parsed:
            stype = stmt.get_type()
            if stype and stype not in ("SELECT", "UNKNOWN"):
                raise VerifyFileError(
                    f"Verify file contains forbidden {stype} statement. "
                    "Only SELECT (or WITH ... SELECT) is allowed."
                )

    def run_verify(self, version: str, name: str, verify_file: Path) -> VerifyResult:
        """Execute verify query inside SAVEPOINT. Returns VerifyResult.

        The query runs inside SAVEPOINT/ROLLBACK TO SAVEPOINT to ensure
        no side effects even if the file somehow contains DML.

        Args:
            version: Migration version string
            name: Human-readable migration name
            verify_file: Path to the .verify.sql file

        Returns:
            VerifyResult with status, actual_value, and error fields

        Raises:
            VerifyFileError: If the verify file contains forbidden SQL
        """
        content = verify_file.read_text().strip()
        self.validate_verify_sql(content)

        cursor = self.connection.cursor()
        try:
            cursor.execute("SAVEPOINT verify_check")
            cursor.execute(content)
            row = cursor.fetchone()
            cursor.execute("ROLLBACK TO SAVEPOINT verify_check")

            if row is None:
                return VerifyResult(
                    version=version,
                    name=name,
                    verify_file=verify_file,
                    status="failed",
                    error="Query returned zero rows",
                )

            value = row[0]
            if _is_truthy(value):
                return VerifyResult(
                    version=version,
                    name=name,
                    verify_file=verify_file,
                    status="verified",
                    actual_value=value,
                )
            return VerifyResult(
                version=version,
                name=name,
                verify_file=verify_file,
                status="failed",
                actual_value=value,
            )

        except VerifyFileError:
            raise
        except Exception as e:
            cursor.execute("ROLLBACK TO SAVEPOINT verify_check")
            return VerifyResult(
                version=version,
                name=name,
                verify_file=verify_file,
                status="failed",
                error=str(e),
            )

    def verify_all(
        self,
        applied_versions: list[str],
        target_version: str | None = None,
    ) -> list[VerifyResult]:
        """Run verify for all applied migrations (or just target_version).

        Args:
            applied_versions: List of applied migration version strings
            target_version: If set, only verify this version

        Returns:
            List of VerifyResult, one per applied version (or just target)
        """
        verify_files = self.discover_verify_files()
        results = []

        for version in applied_versions:
            if target_version and version != target_version:
                continue

            if version in verify_files:
                name = self._name_from_file(verify_files[version])
                result = self.run_verify(version, name, verify_files[version])
            else:
                name = version
                result = VerifyResult(
                    version=version,
                    name=name,
                    verify_file=None,
                    status="no_file",
                )
            results.append(result)

        return results

    def _name_from_file(self, path: Path) -> str:
        """Extract human name from verify filename.

        Args:
            path: Path to .verify.sql file

        Returns:
            Human-readable name (everything after the version prefix)
        """
        stem = path.name[: -len(".verify.sql")]
        parts = stem.split("_", 1)
        return parts[1] if len(parts) > 1 else stem


def _is_truthy(value: Any) -> bool:
    """Check if a verify query result value is truthy.

    Args:
        value: The first column of the first row from the verify query

    Returns:
        True if the value is considered truthy (verification passed)
    """
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.lower() in ("true", "t", "yes", "1")
    return bool(value)
