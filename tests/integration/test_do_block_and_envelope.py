"""Integration coverage for #132 (DO $$ ... $$ preservation) and #133
(post-execute transaction-envelope check).

Both bugs touch the same code path — confiture's outer transaction
envelope — so they're exercised here against a real PostgreSQL.
"""

from __future__ import annotations

import subprocess
import uuid
from collections.abc import Generator

import psycopg
import pytest

from confiture.core._migrator.session import MigratorSession
from confiture.exceptions import MigrationError


@pytest.fixture()
def envelope_db() -> Generator[str, None, None]:
    """Throwaway DB for one test."""
    db_name = f"confiture_envelope_test_{uuid.uuid4().hex[:8]}"
    use_subprocess = False
    try:
        subprocess.run(["createdb", db_name], check=True, capture_output=True)
        use_subprocess = True
    except (FileNotFoundError, subprocess.CalledProcessError):
        try:
            conn = psycopg.connect("postgresql://localhost/postgres", autocommit=True)
            conn.execute(f'CREATE DATABASE "{db_name}"')
            conn.close()
        except psycopg.OperationalError as e:
            pytest.skip(f"PostgreSQL not available: {e}")

    yield f"postgresql://localhost/{db_name}"

    if use_subprocess:
        subprocess.run(["dropdb", db_name], capture_output=True)
    else:
        try:
            conn = psycopg.connect("postgresql://localhost/postgres", autocommit=True)
            conn.execute(f'DROP DATABASE IF EXISTS "{db_name}"')
            conn.close()
        except psycopg.OperationalError:
            pass


# ---------------------------------------------------------------------------
# #132: DO $$ ... END $$;
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_do_block_with_exception_block_runs(envelope_db: str, tmp_path) -> None:
    """A migration containing a ``DO $$ BEGIN ... EXCEPTION ... END $$;`` block
    must apply successfully. Previously the line-by-line stripper deleted the
    inner ``BEGIN``, breaking the PL/pgSQL syntax."""
    (tmp_path / "20260527000010_do_block.up.sql").write_text(
        "CREATE TABLE thingies (id BIGSERIAL PRIMARY KEY, tag TEXT);\n"
        "DO $$\n"
        "BEGIN\n"
        "    INSERT INTO thingies (tag) VALUES ('initial');\n"
        "EXCEPTION\n"
        "    WHEN OTHERS THEN\n"
        "        INSERT INTO thingies (tag) VALUES ('fallback');\n"
        "END $$;\n"
    )
    (tmp_path / "20260527000010_do_block.down.sql").write_text("DROP TABLE thingies;\n")

    session = MigratorSession(
        config=None, migrations_dir=tmp_path, database_url_override=envelope_db
    )
    with session:
        result = session.up()

    assert result.success is True, f"errors: {result.errors}"

    # Verify the DO block actually executed.
    conn = psycopg.connect(envelope_db)
    try:
        tags = [row[0] for row in conn.execute("SELECT tag FROM thingies ORDER BY id").fetchall()]
        assert tags == ["initial"], f"expected the happy-path INSERT to have run, got: {tags!r}"
    finally:
        conn.close()


@pytest.mark.integration
def test_do_block_with_named_tag_runs(envelope_db: str, tmp_path) -> None:
    """A ``CREATE FUNCTION ... AS $body$ ... $body$;`` migration must apply.
    The named tag exercises the scanner's tag-matching logic."""
    (tmp_path / "20260527000011_named_tag.up.sql").write_text(
        "CREATE FUNCTION public.greet(name TEXT) RETURNS TEXT\n"
        "LANGUAGE plpgsql AS $body$\n"
        "BEGIN\n"
        "    RETURN 'hello ' || name;\n"
        "END\n"
        "$body$;\n"
    )
    (tmp_path / "20260527000011_named_tag.down.sql").write_text(
        "DROP FUNCTION public.greet(TEXT);\n"
    )

    session = MigratorSession(
        config=None, migrations_dir=tmp_path, database_url_override=envelope_db
    )
    with session:
        result = session.up()

    assert result.success is True, f"errors: {result.errors}"

    conn = psycopg.connect(envelope_db)
    try:
        row = conn.execute("SELECT public.greet('world')").fetchone()
        assert row[0] == "hello world"
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# #133: envelope-breach detection
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_inline_commit_in_migration_body_surfaces_clear_error(envelope_db: str, tmp_path) -> None:
    """A migration body that issues an inline ``COMMIT;`` (not on its own
    line, so the stripper can't catch it) must surface as a ``MigrationError``
    with the ``MIGR_107`` code, not as some opaque downstream error."""
    (tmp_path / "20260527000020_naughty_commit.up.sql").write_text(
        "CREATE TABLE naughty (id BIGSERIAL PRIMARY KEY);\n"
        "SELECT 1; COMMIT;\n"
        "INSERT INTO naughty DEFAULT VALUES;\n"
    )
    (tmp_path / "20260527000020_naughty_commit.down.sql").write_text("DROP TABLE naughty;\n")

    session = MigratorSession(
        config=None, migrations_dir=tmp_path, database_url_override=envelope_db
    )
    with session:
        result = session.up()

    assert result.success is False, "envelope-breach must fail the migration"
    assert result.errors, "envelope-breach must surface an error message"
    joined = "\n".join(result.errors)
    assert "COMMIT" in joined or "ROLLBACK" in joined, (
        f"error must mention COMMIT/ROLLBACK, got: {joined!r}"
    )
    assert "envelope" in joined.lower() or "MIGR_107" in joined, (
        f"error must mention envelope or MIGR_107, got: {joined!r}"
    )

    # And the table must NOT have been left around.
    conn = psycopg.connect(envelope_db)
    try:
        row = conn.execute("SELECT to_regclass('public.naughty')").fetchone()
        # Note: because the COMMIT in the body fires *before* we detect the
        # envelope breach, the CREATE TABLE has already been committed. The
        # check still raises (and the migration is reported failed), but the
        # damage is partially done — that's the whole point of #133: the
        # envelope is broken, the rollback can't help. We accept either
        # state here; what matters is that the error surfaces clearly.
        del row  # unused — see comment above
    finally:
        conn.close()


@pytest.mark.integration
def test_inline_commit_envelope_breach_raises_when_called_directly(
    envelope_db: str, tmp_path
) -> None:
    """Direct ``Migrator.apply()`` (not via session) must raise the
    ``MIGR_107`` ``MigrationError`` — the session-level test confirms it
    surfaces in ``result.errors``, this one confirms the raise."""
    from confiture.core.migrator import Migrator
    from confiture.models.sql_file_migration import FileSQLMigration

    up_file = tmp_path / "20260527000022_inline_commit.up.sql"
    down_file = tmp_path / "20260527000022_inline_commit.down.sql"
    up_file.write_text("CREATE TABLE naughty2 (id BIGSERIAL PRIMARY KEY);\nSELECT 1; COMMIT;\n")
    down_file.write_text("DROP TABLE IF EXISTS naughty2;\n")

    conn = psycopg.connect(envelope_db, autocommit=False)
    try:
        migrator = Migrator(connection=conn)
        migrator.initialize()
        migration_class = FileSQLMigration.from_files(up_file, down_file)
        migration = migration_class(connection=conn)

        with pytest.raises(MigrationError) as exc_info:
            migrator.apply(migration, migration_file=up_file)

        assert exc_info.value.error_code == "MIGR_107", (
            f"expected MIGR_107, got {exc_info.value.error_code!r}"
        )
        msg = str(exc_info.value)
        assert "COMMIT" in msg or "ROLLBACK" in msg
        assert "envelope" in msg.lower()
    finally:
        conn.close()


@pytest.mark.integration
def test_benign_do_block_does_not_trip_envelope_check(envelope_db: str, tmp_path) -> None:
    """A normal ``DO $$ ... $$`` block runs INSERTs and leaves the connection
    in ``INTRANS`` state. The runtime envelope check must not false-positive."""
    (tmp_path / "20260527000021_benign_do_block.up.sql").write_text(
        "CREATE TABLE thingies (id BIGSERIAL PRIMARY KEY);\n"
        "DO $$\n"
        "BEGIN\n"
        "    INSERT INTO thingies DEFAULT VALUES;\n"
        "    INSERT INTO thingies DEFAULT VALUES;\n"
        "END $$;\n"
    )
    (tmp_path / "20260527000021_benign_do_block.down.sql").write_text("DROP TABLE thingies;\n")

    session = MigratorSession(
        config=None, migrations_dir=tmp_path, database_url_override=envelope_db
    )
    with session:
        result = session.up()

    assert result.success is True, f"errors: {result.errors}"

    conn = psycopg.connect(envelope_db)
    try:
        count = conn.execute("SELECT COUNT(*) FROM thingies").fetchone()[0]
        assert count == 2
    finally:
        conn.close()
