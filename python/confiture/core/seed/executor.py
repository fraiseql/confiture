"""Low-level seed file execution with savepoint management.

Executes seed files within PostgreSQL savepoints to isolate failures
and avoid parser limits from concatenation.

A seed file is a script the way ``psql`` reads one: statements, and ``COPY …
FROM stdin`` blocks whose rows are not SQL. The driver's ``execute`` parses
everything it is given, so the text between blocks is executed and each block's
rows go through the driver's ``COPY`` protocol — the file loads the same way it
would through ``psql``, inside this file's savepoint.
"""

from __future__ import annotations

from pathlib import Path

import psycopg

from confiture.core.sql_lexer import copy_blocks, strip_comments, transaction_statements
from confiture.exceptions import SeedError


def read_seed(seed_file: Path) -> str:
    """*seed_file*'s text, or a SeedError naming the file.

    Bytes, decoded: a text-mode read turns a carriage return inside a string
    literal into a newline, and a seed file is data.
    """
    try:
        return seed_file.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError) as e:
        raise SeedError(
            f"Failed to read seed file {seed_file}: {e}",
            seed_file=str(seed_file),
            sql_error=e,
            resolution_hint="A seed file is a readable file of UTF-8 text.",
        ) from e


class SeedExecutor:
    """Executes seed files within savepoints.

    Provides:
    - Per-file savepoint management
    - Transaction control
    - Error context capture
    - Validation of seed content
    """

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
        self.execute_sql(read_seed(seed_file), savepoint_name, source=seed_file)

    def execute_sql(self, sql_content: str, savepoint_name: str, *, source: Path) -> None:
        """Execute already-read seed SQL (possibly converted) inside a savepoint.

        Args:
            sql_content: The SQL to run.
            savepoint_name: Savepoint isolating this file.
            source: The file the SQL came from, for error context.
        """
        seed_file = source
        self._validate_seed_content(sql_content)

        try:
            # Create savepoint
            self._create_savepoint(savepoint_name)

            with self.connection.cursor() as cursor:
                run_script(cursor, sql_content)

            # Release savepoint on success
            self._release_savepoint(savepoint_name)

        except SeedError:
            # SeedError from validation - re-raise as-is
            self._rollback_to_savepoint(savepoint_name)
            raise
        except psycopg.Error as e:
            # Catch execution errors
            self._rollback_to_savepoint(savepoint_name)
            raise SeedError(
                f"Failed to execute seed file {seed_file.name}: {e}",
                seed_file=str(seed_file),
                sql_error=e,
            ) from e

    def _validate_seed_content(self, sql_content: str) -> None:
        """Validate seed file content.

        Rejects seed files that contain transaction control statements, as
        these conflict with the outer transaction. A statement, not a word:
        ``'Begin here'`` in a value is data.

        Args:
            sql_content: SQL content to validate

        Raises:
            SeedError: If seed file contains invalid commands
        """
        if transaction_statements(sql_content):
            raise SeedError(
                "Seed files must not contain transaction control statements (BEGIN, COMMIT, "
                "ROLLBACK, SAVEPOINT): each file already runs in a savepoint of its own, "
                "inside the run's transaction.",
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
        """Undo this file's statements and nothing before them.

        The transaction stays open: it is the caller's, and committing it here
        kept every file before a failure and none after it — while a run with no
        failure committed nothing at all.

        Args:
            name: Name of savepoint to rollback to
        """
        try:
            with self.connection.cursor() as cursor:
                cursor.execute(f"ROLLBACK TO SAVEPOINT {name}")
        except psycopg.Error:
            # Savepoint rollback failed, do full rollback
            self.connection.rollback()


def run_script(cursor: psycopg.Cursor, sql: str) -> None:
    """Run *sql* as ``psql`` would: its statements, and each COPY block's rows streamed.

    The one way a seed script reaches the database through the driver — ``seed
    apply`` and the prep-seed validator's level 5 both run seeds through it.
    """
    position = 0
    for block in copy_blocks(sql):
        _execute_code(cursor, sql[position : block.start])
        with cursor.copy(block.statement) as copy:
            copy.write(block.data)
        position = block.end
    _execute_code(cursor, sql[position:])


def _execute_code(cursor: psycopg.Cursor, sql: str) -> None:
    """Execute *sql* unless it holds nothing but comments and space."""
    if strip_comments(sql).strip():
        cursor.execute(sql)
