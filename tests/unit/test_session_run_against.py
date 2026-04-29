"""Unit tests for MigratorSession.run_against()."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from confiture.core._migrator.session import MigratorSession
from confiture.exceptions import ConfigurationError


def _make_session(conn=None):
    """Return a MigratorSession wired to a mock connection."""
    if conn is None:
        conn = MagicMock()
    session = MigratorSession.__new__(MigratorSession)
    session._config = None
    session._migrations_dir = Path("db/migrations")
    session._database_url_override = "postgresql://localhost/preflight"
    session._migration_table_override = "tb_confiture"
    session._conn = conn
    session._migrator = MagicMock()
    return session, conn


def _mock_migration_class(
    version="20260428000000",
    name="test_mig",
    fail=False,
    exc=None,
    transactional=True,
    missing_transactional=False,
):
    """Return a migration class whose up() either succeeds or raises."""

    class _M:
        def __init__(self, connection):
            self.version = version
            self.name = name
            if not missing_transactional:
                self.transactional = transactional

        def up(self):
            if fail:
                raise exc or Exception("mock failure")

    return _M


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_run_against_all_pass():
    session, mock_conn = _make_session()
    with patch("confiture.core.migrator.load_migration_class") as mock_lmc:
        mock_lmc.return_value = _mock_migration_class(fail=False)
        result = session.run_against(
            [Path("db/migrations/20260428000000_a.up.sql")],
            against_url="postgresql://localhost/preflight",
        )
    assert result.all_passed is True
    assert len(result.migrations) == 1
    assert result.migrations[0].success is True


def test_run_against_no_commits():
    """up() is called directly; connection.commit() must never be called."""
    session, mock_conn = _make_session()
    with patch("confiture.core.migrator.load_migration_class") as mock_lmc:
        mock_lmc.return_value = _mock_migration_class(fail=False)
        session.run_against(
            [Path("db/migrations/20260428000000_a.up.sql")],
            against_url="postgresql://localhost/preflight",
        )
    mock_conn.commit.assert_not_called()


def test_run_against_outer_rollback():
    """ROLLBACK TO SAVEPOINT preflight_run is called exactly once in finally."""
    session, mock_conn = _make_session()
    with patch("confiture.core.migrator.load_migration_class") as mock_lmc:
        mock_lmc.return_value = _mock_migration_class(fail=False)
        session.run_against(
            [Path("db/migrations/20260428000000_a.up.sql")],
            against_url="postgresql://localhost/preflight",
        )
    rollback_calls = [
        c
        for c in mock_conn.execute.call_args_list
        if "ROLLBACK TO SAVEPOINT preflight_run" in str(c)
    ]
    assert len(rollback_calls) == 1


# ---------------------------------------------------------------------------
# Continues past failure
# ---------------------------------------------------------------------------


def test_run_against_continues_past_failure():
    session, mock_conn = _make_session()
    files = [
        Path("db/migrations/20260428000001_fail.up.sql"),
        Path("db/migrations/20260428000002_pass.up.sql"),
    ]
    call_count = 0

    def lmc_side_effect(migration_file):
        nonlocal call_count
        call_count += 1
        fail = call_count == 1
        return _mock_migration_class(
            version=f"2026042800000{call_count}",
            name=f"m{call_count}",
            fail=fail,
        )

    with patch("confiture.core.migrator.load_migration_class", side_effect=lmc_side_effect):
        result = session.run_against(files, against_url="postgresql://localhost/preflight")

    assert result.all_passed is False
    assert len(result.migrations) == 2
    assert result.migrations[0].success is False
    assert result.migrations[1].success is True
    assert result.migrations[0].error is not None


# ---------------------------------------------------------------------------
# Empty list
# ---------------------------------------------------------------------------


def test_run_against_empty_returns_empty_result():
    session, _ = _make_session()
    result = session.run_against([], against_url="postgresql://localhost/preflight")
    assert result.all_passed is True
    assert result.migrations == []
    assert result.against_url == "postgresql://localhost/preflight"


# ---------------------------------------------------------------------------
# Outside context manager
# ---------------------------------------------------------------------------


def test_run_against_outside_context_raises():
    session = MigratorSession(
        None,
        Path("db/migrations"),
        database_url_override="postgresql://localhost/preflight",
    )
    with pytest.raises(ConfigurationError):
        session.run_against([], against_url="postgresql://localhost/preflight")


# ---------------------------------------------------------------------------
# Non-transactional: skipped by default
# ---------------------------------------------------------------------------


def test_non_transactional_skipped_by_default():
    """Non-transactional migration is skipped when allow_non_transactional=False."""
    session, mock_conn = _make_session()
    with patch("confiture.core.migrator.load_migration_class") as mock_lmc:
        mock_lmc.return_value = _mock_migration_class(
            version="20260428000000",
            name="add_idx",
            transactional=False,
        )
        result = session.run_against(
            [Path("db/migrations/20260428000000_add_idx.up.sql")],
            against_url="postgresql://localhost/preflight",
        )
    assert len(result.migrations) == 1
    m = result.migrations[0]
    assert m.skipped is True
    assert m.success is False
    assert m.skipped_reason is not None
    assert "non-transactional" in m.skipped_reason
    assert result.all_passed is True
    assert result.db_consumed is False
    mock_conn.commit.assert_not_called()


def test_missing_transactional_attr_treated_as_transactional():
    """Migration without transactional attribute defaults to True (safe path)."""
    session, mock_conn = _make_session()
    with patch("confiture.core.migrator.load_migration_class") as mock_lmc:
        mock_lmc.return_value = _mock_migration_class(missing_transactional=True, fail=False)
        result = session.run_against(
            [Path("db/migrations/20260428000000_a.up.sql")],
            against_url="postgresql://localhost/preflight",
        )
    # Should run inside SAVEPOINT (not skipped), and succeed
    assert result.migrations[0].skipped is False
    assert result.migrations[0].success is True
    mock_conn.commit.assert_not_called()


# ---------------------------------------------------------------------------
# Non-transactional: allowed
# ---------------------------------------------------------------------------


def test_non_transactional_runs_when_allowed():
    """Non-transactional migration runs in autocommit when allow_non_transactional=True."""
    session, mock_conn = _make_session()
    with patch("confiture.core.migrator.load_migration_class") as mock_lmc:
        mock_lmc.return_value = _mock_migration_class(
            version="20260428000000",
            name="add_idx",
            transactional=False,
            fail=False,
        )
        result = session.run_against(
            [Path("db/migrations/20260428000000_add_idx.up.sql")],
            against_url="postgresql://localhost/preflight",
            allow_non_transactional=True,
        )
    assert len(result.migrations) == 1
    m = result.migrations[0]
    assert m.skipped is False
    assert m.success is True
    assert result.db_consumed is True
    # Outer SAVEPOINT is released via commit — no ROLLBACK TO preflight_run
    rollback_calls = [
        c
        for c in mock_conn.execute.call_args_list
        if "ROLLBACK TO SAVEPOINT preflight_run" in str(c)
    ]
    assert len(rollback_calls) == 0
    mock_conn.commit.assert_called_once()


def test_non_transactional_failure_when_allowed():
    """Non-transactional migration that fails is recorded; db_consumed still True."""
    session, mock_conn = _make_session()
    with patch("confiture.core.migrator.load_migration_class") as mock_lmc:
        mock_lmc.return_value = _mock_migration_class(
            version="20260428000000",
            name="add_idx",
            transactional=False,
            fail=True,
        )
        result = session.run_against(
            [Path("db/migrations/20260428000000_add_idx.up.sql")],
            against_url="postgresql://localhost/preflight",
            allow_non_transactional=True,
        )
    m = result.migrations[0]
    assert m.skipped is False
    assert m.success is False
    assert m.error is not None
    assert result.db_consumed is True


# ---------------------------------------------------------------------------
# Per-migration SAVEPOINT mechanics
# ---------------------------------------------------------------------------


def test_per_migration_savepoint_set_and_released_on_success():
    """SAVEPOINT sp_{version} is set and RELEASED when migration succeeds."""
    session, mock_conn = _make_session()
    with patch("confiture.core.migrator.load_migration_class") as mock_lmc:
        mock_lmc.return_value = _mock_migration_class(version="20260428000000", fail=False)
        session.run_against(
            [Path("db/migrations/20260428000000_a.up.sql")],
            against_url="postgresql://localhost/preflight",
        )
    calls = [str(c) for c in mock_conn.execute.call_args_list]
    assert any("SAVEPOINT sp_20260428000000" in c for c in calls)
    assert any("RELEASE SAVEPOINT sp_20260428000000" in c for c in calls)


def test_per_migration_savepoint_rolled_back_on_failure():
    """ROLLBACK TO SAVEPOINT + RELEASE are called when migration fails."""
    session, mock_conn = _make_session()
    with patch("confiture.core.migrator.load_migration_class") as mock_lmc:
        mock_lmc.return_value = _mock_migration_class(version="20260428111111", fail=True)
        session.run_against(
            [Path("db/migrations/20260428111111_bad.up.sql")],
            against_url="postgresql://localhost/preflight",
        )
    calls = [str(c) for c in mock_conn.execute.call_args_list]
    assert any("ROLLBACK TO SAVEPOINT sp_20260428111111" in c for c in calls)
    assert any("RELEASE SAVEPOINT sp_20260428111111" in c for c in calls)


def test_outer_rollback_runs_even_on_first_migration_failure():
    """ROLLBACK TO SAVEPOINT preflight_run fires in finally even if first migration fails."""
    session, mock_conn = _make_session()
    with patch("confiture.core.migrator.load_migration_class") as mock_lmc:
        mock_lmc.return_value = _mock_migration_class(fail=True)
        session.run_against(
            [Path("db/migrations/20260428000000_bad.up.sql")],
            against_url="postgresql://localhost/preflight",
        )
    rollback_calls = [
        c
        for c in mock_conn.execute.call_args_list
        if "ROLLBACK TO SAVEPOINT preflight_run" in str(c)
    ]
    assert len(rollback_calls) == 1


def test_up_called_not_apply():
    """migration.up() is called directly — migrator.apply() must never be called."""
    session, mock_conn = _make_session()
    up_called = []

    class _TrackedMigration:
        version = "20260428000000"
        name = "tracked"
        transactional = True

        def __init__(self, connection):
            pass

        def up(self):
            up_called.append(True)

    with patch("confiture.core.migrator.load_migration_class", return_value=_TrackedMigration):
        session.run_against(
            [Path("db/migrations/20260428000000_tracked.up.sql")],
            against_url="postgresql://localhost/preflight",
        )

    assert len(up_called) == 1
    # _migrator is a MagicMock — verify apply() was never called on it
    session._migrator.apply.assert_not_called()


def test_outer_sp_active_false_skips_rollback_in_finally():
    """When allow_non_transactional=True triggers a commit, no ROLLBACK TO preflight_run."""
    session, mock_conn = _make_session()
    with patch("confiture.core.migrator.load_migration_class") as mock_lmc:
        mock_lmc.return_value = _mock_migration_class(transactional=False, fail=False)
        session.run_against(
            [Path("db/migrations/20260428000000_idx.up.sql")],
            against_url="postgresql://localhost/preflight",
            allow_non_transactional=True,
        )
    rollback_calls = [
        c
        for c in mock_conn.execute.call_args_list
        if "ROLLBACK TO SAVEPOINT preflight_run" in str(c)
    ]
    assert len(rollback_calls) == 0
