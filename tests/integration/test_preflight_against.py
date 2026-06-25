"""Integration tests for MigratorSession.run_against() against a real PostgreSQL database."""

import uuid

import psycopg
import pytest

from confiture.core._migrator.session import MigratorSession

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def preflight_db():
    """Create and tear down a temporary PostgreSQL database."""
    db_name = f"confiture_preflight_test_{uuid.uuid4().hex[:8]}"

    # Try createdb; fall back to psycopg direct if unavailable.
    import subprocess

    try:
        subprocess.run(["createdb", db_name], check=True, capture_output=True)
        use_subprocess = True
    except (FileNotFoundError, subprocess.CalledProcessError):
        try:
            conn = psycopg.connect("postgresql://localhost/postgres", autocommit=True)
            conn.execute(f'CREATE DATABASE "{db_name}"')
            conn.close()
            use_subprocess = False
        except psycopg.OperationalError as e:
            pytest.skip(f"PostgreSQL not available: {e}")

    db_url = f"postgresql://localhost/{db_name}"
    yield db_url

    if use_subprocess:
        subprocess.run(["dropdb", db_name], capture_output=True)
    else:
        try:
            conn = psycopg.connect("postgresql://localhost/postgres", autocommit=True)
            conn.execute(f'DROP DATABASE IF EXISTS "{db_name}"')
            conn.close()
        except psycopg.OperationalError:
            pass  # best-effort cleanup


@pytest.fixture()
def valid_migrations_dir(tmp_path):
    """Two valid migrations with no inter-dependency."""
    (tmp_path / "20260401000001_create_foo.up.sql").write_text(
        "CREATE TABLE foo (id SERIAL PRIMARY KEY);"
    )
    (tmp_path / "20260401000001_create_foo.down.sql").write_text("DROP TABLE foo;")
    (tmp_path / "20260401000002_create_bar.up.sql").write_text(
        "CREATE TABLE bar (id SERIAL PRIMARY KEY);"
    )
    (tmp_path / "20260401000002_create_bar.down.sql").write_text("DROP TABLE bar;")
    return tmp_path


@pytest.fixture()
def bad_migrations_dir(tmp_path):
    """Three migrations: 001 valid, 002 invalid SQL, 003 valid (independent of 002)."""
    (tmp_path / "20260401000001_create_foo.up.sql").write_text(
        "CREATE TABLE foo (id SERIAL PRIMARY KEY);"
    )
    (tmp_path / "20260401000001_create_foo.down.sql").write_text("DROP TABLE foo;")
    (tmp_path / "20260401000002_bad_syntax.up.sql").write_text("THIS IS NOT VALID SQL;")
    (tmp_path / "20260401000002_bad_syntax.down.sql").write_text("SELECT 1;")
    # 003 does NOT depend on 002 — creates an independent table.
    (tmp_path / "20260401000003_create_baz.up.sql").write_text(
        "CREATE TABLE baz (id SERIAL PRIMARY KEY);"
    )
    (tmp_path / "20260401000003_create_baz.down.sql").write_text("DROP TABLE baz;")
    return tmp_path


@pytest.fixture()
def interdependent_migrations_dir(tmp_path):
    """Two inter-dependent migrations: 002 creates a view over 001's table."""
    (tmp_path / "20260401000001_create_widgets.up.sql").write_text(
        "CREATE TABLE public.widgets (id BIGINT PRIMARY KEY);"
    )
    (tmp_path / "20260401000001_create_widgets.down.sql").write_text("DROP TABLE public.widgets;")
    (tmp_path / "20260401000002_add_widgets_view.up.sql").write_text(
        "CREATE OR REPLACE VIEW public.v_widgets AS SELECT id FROM public.widgets;"
    )
    (tmp_path / "20260401000002_add_widgets_view.down.sql").write_text(
        "DROP VIEW public.v_widgets;"
    )
    return tmp_path


@pytest.fixture()
def non_transactional_migrations_dir(tmp_path):
    """Two migrations: 001 transactional (CREATE TABLE), 002 non-transactional (Python, CONCURRENTLY)."""
    (tmp_path / "20260401000001_create_foo.up.sql").write_text(
        "CREATE TABLE foo (id SERIAL PRIMARY KEY, val TEXT);"
    )
    (tmp_path / "20260401000001_create_foo.down.sql").write_text("DROP TABLE foo;")
    # Python migration that sets transactional=False.
    non_t = tmp_path / "20260401000002_add_idx.py"
    non_t.write_text(
        "from confiture.models.migration import Migration\n\n"
        "class AddIdx(Migration):\n"
        "    version = '20260401000002'\n"
        "    name = 'add_idx'\n"
        "    transactional = False\n\n"
        "    def up(self):\n"
        "        self.connection.execute(\n"
        "            'CREATE INDEX CONCURRENTLY idx_foo_val ON foo(val)'\n"
        "        )\n\n"
        "    def down(self):\n"
        "        self.connection.execute('DROP INDEX IF EXISTS idx_foo_val')\n"
    )
    return tmp_path


@pytest.fixture()
def sql_non_transactional_migrations_dir(tmp_path):
    """Issue #169 — a pure SQL-file migration with CREATE INDEX CONCURRENTLY.

    001 creates a table (transactional); 002 is a ``.up.sql`` file whose only
    statement is non-transactional.  Such a file cannot declare
    ``transactional = False`` — confiture must auto-detect it.
    """
    (tmp_path / "20260401000001_create_foo.up.sql").write_text(
        "CREATE TABLE foo (id SERIAL PRIMARY KEY, val TEXT);"
    )
    (tmp_path / "20260401000001_create_foo.down.sql").write_text("DROP TABLE foo;")
    (tmp_path / "20260401000002_add_idx.up.sql").write_text(
        "CREATE INDEX CONCURRENTLY idx_foo_val ON foo (val);"
    )
    (tmp_path / "20260401000002_add_idx.down.sql").write_text(
        "DROP INDEX CONCURRENTLY IF EXISTS idx_foo_val;"
    )
    return tmp_path


def _count_public_tables(db_url: str) -> int:
    conn = psycopg.connect(db_url)
    try:
        row = conn.execute("SELECT COUNT(*) FROM pg_tables WHERE schemaname = 'public'").fetchone()
        return row[0]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_preflight_against_all_pass(preflight_db, valid_migrations_dir):
    """Migrations that are valid execute cleanly; DB is rolled back afterward."""
    pending = sorted(valid_migrations_dir.glob("*.up.sql"))

    session = MigratorSession(
        config=None,
        migrations_dir=valid_migrations_dir,
        database_url_override=preflight_db,
    )
    with session:
        result = session.run_against(pending, against_url=preflight_db)

    assert result.all_passed is True
    assert len(result.migrations) == 2
    assert all(m.success for m in result.migrations)
    assert result.db_consumed is False

    # Rollback verified: no user tables remain.
    assert _count_public_tables(preflight_db) == 0


@pytest.mark.integration
def test_preflight_against_continues_past_failure(preflight_db, bad_migrations_dir):
    """A failing migration is recorded; execution continues with the next."""
    pending = sorted(bad_migrations_dir.glob("*.up.sql"))

    session = MigratorSession(
        config=None,
        migrations_dir=bad_migrations_dir,
        database_url_override=preflight_db,
    )
    with session:
        result = session.run_against(pending, against_url=preflight_db)

    assert result.all_passed is False
    assert len(result.migrations) == 3
    assert result.migrations[0].success is True  # create_foo — passed
    assert result.migrations[1].success is False  # bad_syntax — failed
    assert result.migrations[2].success is True  # create_baz — independent, passed
    assert result.migrations[1].error is not None

    # Even the passing migrations are rolled back.
    assert _count_public_tables(preflight_db) == 0


@pytest.mark.integration
def test_preflight_against_later_pending_sees_earlier_pending(
    preflight_db, interdependent_migrations_dir
):
    """A later pending migration sees an earlier pending migration's object.

    Regression guard for issue #250: ``run_against`` applies pending migrations
    cumulatively (success → ``RELEASE SAVEPOINT`` keeps the DDL within the outer
    envelope), so ``V2``'s view over ``V1``'s table resolves and both succeed.
    The complement to ``test_preflight_against_continues_past_failure`` (which
    proves failure isolation); this one proves cumulative success.
    """
    pending = sorted(interdependent_migrations_dir.glob("*.up.sql"))

    session = MigratorSession(
        config=None,
        migrations_dir=interdependent_migrations_dir,
        database_url_override=preflight_db,
    )
    with session:
        result = session.run_against(pending, against_url=preflight_db)

    assert result.all_passed is True
    assert len(result.migrations) == 2
    assert result.migrations[0].success is True  # create_widgets
    assert result.migrations[1].success is True  # add_widgets_view — sees widgets
    assert all(m.error is None for m in result.migrations)
    assert result.db_consumed is False

    # Outer rollback left no trace: neither the table nor the view remains.
    assert _count_public_tables(preflight_db) == 0


@pytest.mark.integration
def test_preflight_non_transactional_skipped_by_default(
    preflight_db, non_transactional_migrations_dir
):
    """Non-transactional migration is skipped; DB is rolled back."""
    pending = sorted(
        list(non_transactional_migrations_dir.glob("*.up.sql"))
        + [f for f in non_transactional_migrations_dir.glob("*.py") if not f.name.startswith("_")]
    )

    session = MigratorSession(
        config=None,
        migrations_dir=non_transactional_migrations_dir,
        database_url_override=preflight_db,
    )
    with session:
        result = session.run_against(pending, against_url=preflight_db)

    assert len(result.migrations) == 2
    assert result.migrations[0].success is True
    assert result.migrations[1].skipped is True
    assert result.migrations[1].skipped_reason is not None
    assert result.all_passed is True  # skipped is neutral
    assert result.db_consumed is False

    # 001 DDL was also rolled back.
    assert _count_public_tables(preflight_db) == 0


@pytest.mark.integration
def test_preflight_sql_file_concurrently_skipped_by_default(
    preflight_db, sql_non_transactional_migrations_dir
):
    """Issue #169 — a SQL-file CREATE INDEX CONCURRENTLY migration is skipped,
    not reported as a failed replay.

    Before the fix it inherited ``transactional = True`` and failed to replay
    inside a SAVEPOINT ("cannot run inside a transaction block"), surfacing an
    error-severity ``PFLIGHT_REPLAY_FAILED`` and exit 7.
    """
    pending = sorted(sql_non_transactional_migrations_dir.glob("*.up.sql"))

    session = MigratorSession(
        config=None,
        migrations_dir=sql_non_transactional_migrations_dir,
        database_url_override=preflight_db,
    )
    with session:
        result = session.run_against(pending, against_url=preflight_db)

    assert len(result.migrations) == 2
    assert result.migrations[0].success is True  # create_foo (transactional)
    assert result.migrations[1].skipped is True  # CONCURRENTLY auto-detected
    assert result.migrations[1].error is None  # not a replay failure
    assert result.all_passed is True  # skipped is neutral → no exit 7
    assert result.failures == []
    assert result.db_consumed is False

    # Outer rollback left no trace.
    assert _count_public_tables(preflight_db) == 0


@pytest.mark.integration
def test_preflight_non_transactional_runs_when_allowed(
    preflight_db, non_transactional_migrations_dir
):
    """Non-transactional migration runs and DB is consumed when allow_non_transactional=True."""
    pending = sorted(
        list(non_transactional_migrations_dir.glob("*.up.sql"))
        + [f for f in non_transactional_migrations_dir.glob("*.py") if not f.name.startswith("_")]
    )

    session = MigratorSession(
        config=None,
        migrations_dir=non_transactional_migrations_dir,
        database_url_override=preflight_db,
    )
    with session:
        result = session.run_against(
            pending,
            against_url=preflight_db,
            allow_non_transactional=True,
        )

    assert len(result.migrations) == 2
    assert result.migrations[0].success is True  # create_foo
    assert result.migrations[1].success is True  # add_idx (CONCURRENTLY)
    assert result.migrations[1].skipped is False
    assert result.all_passed is True
    assert result.db_consumed is True

    # DB is consumed: foo table and idx_foo_val index both exist.
    conn = psycopg.connect(preflight_db)
    try:
        row = conn.execute(
            "SELECT COUNT(*) FROM pg_tables WHERE schemaname='public' AND tablename='foo'"
        ).fetchone()
        assert row[0] == 1, "foo table should exist (db_consumed)"
        row2 = conn.execute(
            "SELECT COUNT(*) FROM pg_indexes WHERE indexname='idx_foo_val'"
        ).fetchone()
        assert row2[0] == 1, "idx_foo_val index should exist"
    finally:
        conn.close()
