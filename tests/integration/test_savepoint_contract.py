"""SAVEPOINT compatibility contract probe (issue #126).

Confiture wraps every applied migration in a top-level transaction with
a per-migration SAVEPOINT.  ``dry_run_execute`` adds an outer SAVEPOINT
inside that transaction; ``preflight --against`` adds an analogous outer
SAVEPOINT in a temporary preflight database.

These integration tests assert that a migration body MAY open its own
SAVEPOINT (either via psycopg's ``conn.transaction()`` or via an
explicit ``SAVEPOINT`` statement) and that the inner SAVEPOINT nests
cleanly under whatever envelope confiture has set up — no errors on the
connection, no leftover state after the outer rollback.

The contract documented in ``docs/reference/transaction-contract.md``
is built on these tests passing.  Treat any failure here as a *contract*
failure — file a separate bug and do not paper over with doc edits.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import psycopg
import pytest

from confiture.core._migrator.session import MigratorSession

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def contract_db() -> str:
    """Create and tear down a throwaway PostgreSQL database for one test."""
    db_name = f"confiture_savepoint_contract_{uuid.uuid4().hex[:8]}"
    try:
        admin = psycopg.connect("postgresql://localhost/postgres", autocommit=True)
        admin.execute(f'CREATE DATABASE "{db_name}"')
        admin.close()
    except psycopg.OperationalError as exc:
        pytest.skip(f"PostgreSQL not available: {exc}")

    db_url = f"postgresql://localhost/{db_name}"
    try:
        yield db_url
    finally:
        try:
            admin = psycopg.connect("postgresql://localhost/postgres", autocommit=True)
            admin.execute(f'DROP DATABASE IF EXISTS "{db_name}"')
            admin.close()
        except psycopg.OperationalError:
            pass


def _write_nested_savepoint_migration(tmp_path: Path) -> Path:
    """Create a Python migration whose ``up()`` opens its own SAVEPOINT.

    The migration:
      1. Creates ``contract_table``.
      2. Opens a nested SAVEPOINT via ``conn.transaction()`` and inserts
         a row inside it.  The inner block exits normally — that
         releases (commits) the inner SAVEPOINT.
      3. Opens an explicit ``SAVEPOINT contract_explicit`` and runs an
         ``INSERT … ON CONFLICT DO NOTHING`` inside it, then releases.

    None of these client-side SAVEPOINTs should conflict with whatever
    envelope confiture sets up.
    """
    mig = tmp_path / "20260528120000_nested_savepoint.py"
    mig.write_text(
        "from confiture.models.migration import Migration\n"
        "\n"
        "\n"
        "class NestedSavepoint(Migration):\n"
        "    version = '20260528120000'\n"
        "    name = 'nested_savepoint'\n"
        "\n"
        "    def up(self) -> None:\n"
        "        self.connection.execute(\n"
        "            'CREATE TABLE contract_table (id int PRIMARY KEY, label text)'\n"
        "        )\n"
        "        with self.connection.transaction():\n"
        "            self.connection.execute(\n"
        "                \"INSERT INTO contract_table (id, label) VALUES (1, 'inner')\"\n"
        "            )\n"
        "        self.connection.execute('SAVEPOINT contract_explicit')\n"
        "        self.connection.execute(\n"
        "            \"INSERT INTO contract_table (id, label) VALUES (2, 'explicit') \"\n"
        "            'ON CONFLICT DO NOTHING'\n"
        "        )\n"
        "        self.connection.execute('RELEASE SAVEPOINT contract_explicit')\n"
        "\n"
        "    def down(self) -> None:\n"
        "        self.connection.execute('DROP TABLE contract_table')\n"
    )
    return mig


def _public_table_count(db_url: str) -> int:
    conn = psycopg.connect(db_url)
    try:
        row = conn.execute(
            "SELECT COUNT(*) FROM pg_tables WHERE schemaname = 'public' "
            "AND tablename = 'contract_table'"
        ).fetchone()
        return row[0]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_nested_savepoint_in_migration_body_under_dry_run_execute(
    contract_db: str, tmp_path: Path
) -> None:
    """Inner SAVEPOINT commits; outer ``dry_run_execute`` rolls back cleanly."""
    _write_nested_savepoint_migration(tmp_path)

    session = MigratorSession(
        config=None,
        migrations_dir=tmp_path,
        database_url_override=contract_db,
    )
    with session:
        result = session.up(dry_run_execute=True)

    assert result.success is True, result.errors
    assert result.dry_run is True
    assert result.dry_run_execute is True
    assert len(result.migrations_applied) == 1
    assert result.migrations_applied[0].name == "nested_savepoint"

    # Outer rollback verified — ``contract_table`` does not persist.
    assert _public_table_count(contract_db) == 0


@pytest.mark.integration
def test_nested_savepoint_in_migration_body_under_preflight_against(
    contract_db: str, tmp_path: Path
) -> None:
    """Inner SAVEPOINT commits; outer ``preflight --against`` rolls back cleanly."""
    _write_nested_savepoint_migration(tmp_path)
    pending = sorted(tmp_path.glob("*.py"))

    session = MigratorSession(
        config=None,
        migrations_dir=tmp_path,
        database_url_override=contract_db,
    )
    with session:
        result = session.run_against(pending, against_url=contract_db)

    assert result.all_passed is True
    assert len(result.migrations) == 1
    assert result.migrations[0].success is True
    assert result.migrations[0].name == "nested_savepoint"
    assert result.db_consumed is False

    # Outer rollback verified — ``contract_table`` does not persist.
    assert _public_table_count(contract_db) == 0
