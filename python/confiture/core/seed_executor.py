"""Low-level seed file execution with savepoint management.

Phase 9: Sequential Seed File Execution

Executes seed files within PostgreSQL savepoints to isolate failures
and avoid parser limits from concatenation.
"""

from __future__ import annotations

import re
from pathlib import Path

from confiture.exceptions import SeedError


class SeedExecutor:
    """Executes seed files within savepoints.

    Provides:
    - Per-file savepoint management
    - Transaction control
    - Error context capture
    - Validation of seed content
    """

    # Pattern to detect transaction control commands
    TRANSACTION_COMMANDS = re.compile(
        r"\b(BEGIN|START\s+TRANSACTION|COMMIT|ROLLBACK|SAVEPOINT)\b", re.IGNORECASE
    )

    def __init__(self, connection) -> None:
        """Initialize SeedExecutor.

        Args:
            connection: PostgreSQL connection object
        """
        self.connection = connection

    def execute_file(self, seed_file: Path, savepoint_name: str) -> None:
        """Execute a seed file within a savepoint.

        Reads the seed file and executes it within a savepoint for isolation.
        On error, rolls back the savepoint to prevent partial data.

        Args:
            seed_file: Path to seed file to execute
            savepoint_name: Name of savepoint for isolation

        Raises:
            SeedError: If seed file is invalid or execution fails
        """
        # Read seed file
        try:
            sql_content = seed_file.read_text(encoding="utf-8")
        except Exception as e:
            raise SeedError(
                f"Failed to read seed file: {seed_file}",
                seed_file=str(seed_file),
                sql_error=e,
            ) from e

        # Validate seed content (reject transaction commands)
        self._validate_seed_content(sql_content)

        try:
            # Create savepoint
            self._create_savepoint(savepoint_name)

            # Execute seed file
            with self.connection.cursor() as cursor:
                cursor.execute(sql_content)

            # Release savepoint on success
            self._release_savepoint(savepoint_name)

        except SeedError:
            # SeedError from validation - re-raise as-is
            self._rollback_to_savepoint(savepoint_name)
            raise
        except Exception as e:
            # Catch execution errors
            self._rollback_to_savepoint(savepoint_name)
            raise SeedError(
                f"Failed to execute seed file {seed_file.name}: {e}",
                seed_file=str(seed_file),
                sql_error=e,
            ) from e

    def _validate_seed_content(self, sql_content: str) -> None:
        """Validate seed file content.

        Rejects seed files that contain transaction control commands,
        as these conflict with the outer transaction.

        Args:
            sql_content: SQL content to validate

        Raises:
            SeedError: If seed file contains invalid commands
        """
        # Check for transaction commands
        if self.TRANSACTION_COMMANDS.search(sql_content):
            raise SeedError(
                "Seed files must not contain transaction control commands (BEGIN, COMMIT, ROLLBACK, SAVEPOINT). "
                "Use --sequential mode which wraps each file in its own savepoint.",
                resolution_hint="Remove BEGIN/COMMIT/ROLLBACK statements from seed files",
            )

    def _create_savepoint(self, name: str) -> None:
        """Create a savepoint for transaction isolation.

        Args:
            name: Name of savepoint to create
        """
        with self.connection.cursor() as cursor:
            cursor.execute(f"SAVEPOINT {name}")

    def _release_savepoint(self, name: str) -> None:
        """Release a savepoint (commit nested transaction).

        Args:
            name: Name of savepoint to release
        """
        with self.connection.cursor() as cursor:
            cursor.execute(f"RELEASE SAVEPOINT {name}")

    def _rollback_to_savepoint(self, name: str) -> None:
        """Rollback to a savepoint (undo nested transaction).

        Args:
            name: Name of savepoint to rollback to
        """
        try:
            with self.connection.cursor() as cursor:
                cursor.execute(f"ROLLBACK TO SAVEPOINT {name}")
            self.connection.commit()
        except Exception:
            # Savepoint rollback failed, do full rollback
            self.connection.rollback()
