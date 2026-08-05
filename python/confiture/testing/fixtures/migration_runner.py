"""Migration execution utility for testing.

Wraps confiture migrations to provide structured test results and execution
tracking for PrintOptim's migration test suite.
"""

import contextlib
import time
from dataclasses import dataclass
from pathlib import Path

import psycopg
from psycopg import sql as pgsql


@dataclass
class MigrationResult:
    """Result of a migration execution."""

    success: bool
    migration_file: str
    duration_seconds: float
    stdout: str
    stderr: str
    error: Exception | None = None


class MigrationRunner:
    """Execute migrations in test environment using confiture.

    This wraps confiture's Migrator to provide test utilities for:
    - Executing migrations with timing
    - Capturing structured results
    - Supporting dry-run mode
    - Tracking rollbacks
    """

    def __init__(
        self,
        connection: psycopg.Connection,
        migrations_dir: Path | None = None,
        tracking_table: str = "tb_confiture",
    ):
        """Initialize migration runner.

        Args:
            connection: PostgreSQL connection for migration execution
            migrations_dir: Path to migrations directory (default: db/migrations)
            tracking_table: Migration ledger name, bare or schema-qualified.
                Defaults to ``tb_confiture``; pass the project's configured
                ``tracking_table`` when it differs (#190).
        """
        self.connection = connection
        self.tracking_table = tracking_table
        self.migrations_dir = migrations_dir or (
            Path(__file__).parent.parent.parent.parent.parent / "db" / "migrations"
        )

    def run(self, migration_name: str, dry_run: bool = False) -> MigrationResult:
        """Execute a migration.

        Args:
            migration_name: Name without extension (e.g., "002_add_floor_plan")
            dry_run: If True, only show what would be executed

        Returns:
            MigrationResult with execution details
        """
        migration_file = self.migrations_dir / f"{migration_name}.sql"

        if not migration_file.exists():
            raise FileNotFoundError(f"Migration not found: {migration_file}")

        start_time = time.time()

        try:
            if dry_run:
                # Parse SQL but don't execute
                with open(migration_file) as f:
                    sql = f.read()
                return MigrationResult(
                    success=True,
                    migration_file=str(migration_file),
                    duration_seconds=0,
                    stdout=f"DRY-RUN: Would execute migration {migration_name}\n"
                    f"SQL preview (first 500 chars):\n{sql[:500]}...",
                    stderr="",
                )

            # Execute migration within a transaction
            with self.connection.cursor() as cur:
                with open(migration_file) as f:
                    sql = f.read()

                # Execute the migration SQL
                cur.execute(sql)
                self.connection.commit()

            duration = time.time() - start_time

            return MigrationResult(
                success=True,
                migration_file=str(migration_file),
                duration_seconds=duration,
                stdout=f"✓ Migration {migration_name} executed successfully in {duration:.3f}s",
                stderr="",
            )

        except Exception as e:
            duration = time.time() - start_time
            self.connection.rollback()

            return MigrationResult(
                success=False,
                migration_file=str(migration_file),
                duration_seconds=duration,
                stdout="",
                stderr=str(e),
                error=e,
            )

    def rollback(self, migration_name: str) -> MigrationResult:
        """Execute rollback for a migration.

        Args:
            migration_name: Name without _rollback suffix (e.g., "002_add_floor_plan")

        Returns:
            MigrationResult with execution details
        """
        rollback_file = self.migrations_dir / f"{migration_name}_rollback.sql"

        if not rollback_file.exists():
            raise FileNotFoundError(f"Rollback not found: {rollback_file}")

        # Execute rollback (same logic as run)
        return self.run(f"{migration_name}_rollback")

    def get_applied_migrations(self) -> list[str]:
        """Get list of applied migrations from the configured tracking table.

        Returns:
            List of migration slugs that have been applied. Empty when the
            ledger does not exist yet — a database built from schema files has
            no ledger, which is a legitimate state.

        Raises:
            psycopg.Error: For any failure that is *not* an absent ledger —
                a dropped connection, a permission error, a malformed query.
                These used to be swallowed into ``[]``, which made this test
                fixture report "nothing applied" for a broken database and
                turned assertions against it silently vacuous (#190).
        """
        schema, _, base = self.tracking_table.partition(".")
        ident = pgsql.Identifier(schema, base) if base else pgsql.Identifier(schema)

        try:
            with self.connection.cursor() as cur:
                cur.execute(pgsql.SQL("SELECT slug FROM {} ORDER BY applied_at ASC").format(ident))
                return [row[0] for row in cur.fetchall()]
        except psycopg.errors.UndefinedTable:
            # The one genuinely-empty case: no ledger yet.
            with contextlib.suppress(psycopg.Error):
                self.connection.rollback()
            return []

    def get_pending_migrations(self) -> list[str]:
        """Get list of pending migrations not yet applied.

        Returns:
            List of migration file names (without .sql) that haven't been applied
        """
        applied = self.get_applied_migrations()
        applied_set = set(applied)

        # Find all migration files (not rollbacks)
        migration_files = sorted(
            [
                f.stem
                for f in self.migrations_dir.glob("*.sql")
                if not f.name.endswith("_rollback.sql") and f.name[0].isdigit()
            ]
        )

        # Return only those not yet applied
        return [m for m in migration_files if m not in applied_set]
