"""A failed ``up`` says why: ``success=False`` always comes with at least one error.

A caller that branches on ``has_errors`` — fraisier's deploy did — must not read a
run that halted, or that failed with an empty exception message, as a success.
Every failing result is built here through ``MigratorSession.up``, for the real
run and for the ``dry_run_execute`` rehearsal both.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from confiture.config.environment import Environment
from confiture.core._migrator.session import MigratorSession
from confiture.models.results import (
    MigrateUpResult,
    MigrationPreflightInfo,
    PreflightResult,
)
from tests.unit._doubles import connection_double, injected_loader, injected_lock

MODES = pytest.mark.parametrize("rehearsal", [False, True], ids=["up", "dry_run_execute"])


def _session(tmp_path: Path, count: int = 3) -> tuple[MigratorSession, list[Path]]:
    env = MagicMock(spec=Environment)
    env.database_url = "postgresql://localhost/test"
    env.migration = MagicMock()
    env.migration.tracking_table = "tb_confiture"
    mdir = tmp_path / "migrations"
    mdir.mkdir()
    files = []
    for i in range(1, count + 1):
        path = mdir / f"00{i}_m{i}.up.sql"
        path.write_text(f"CREATE TABLE t{i} (id int);")
        files.append(path)
    session = MigratorSession(config=env, migrations_dir=mdir)
    session._conn = connection_double()
    session._migrator = MagicMock()
    session._migrator.migration_table = "tb_confiture"
    session._migrator.find_migration_files.return_value = files
    session._migrator.find_pending.return_value = files
    session._migrator._version_from_filename.side_effect = lambda name: name.split("_")[0]
    return session, files


def _migration(version: str, name: str, *, requires_superuser: bool = False) -> MagicMock:
    inst = MagicMock()
    inst.version, inst.name, inst.requires_superuser = version, name, requires_superuser
    return MagicMock(return_value=inst)


def _up(
    session: MigratorSession, loader: dict[Path, MagicMock] | None, **kwargs
) -> MigrateUpResult:
    classes = loader or {}
    with injected_lock(MagicMock()), injected_loader(side_effect=lambda f: classes[f]):
        return session.up(**kwargs)


def _assert_failed_with_errors(result: MigrateUpResult) -> None:
    assert result.success is False
    assert result.errors, "success=False with no errors"
    assert all(message.strip() for message in result.errors)
    assert result.has_errors is True


@MODES
def test_a_superuser_halt_names_the_migration_the_remedy_and_what_is_left(tmp_path, rehearsal):
    session, files = _session(tmp_path)
    classes = {
        files[0]: _migration("001", "m1"),
        files[1]: _migration("002", "m2", requires_superuser=True),
        files[2]: _migration("003", "m3"),
    }

    result = _up(session, classes, dry_run_execute=rehearsal)

    _assert_failed_with_errors(result)
    (message,) = result.errors
    assert "002_m2" in message
    assert "confiture migrate apply-as <role> 002" in message
    assert "1 migration left pending" in message
    assert result.pending == ["003"]
    assert not any("executed successfully" in w for w in result.warnings)


@MODES
def test_a_halt_at_the_last_migration_says_none_are_left(tmp_path, rehearsal):
    session, files = _session(tmp_path, count=1)
    classes = {files[0]: _migration("001", "m1", requires_superuser=True)}

    result = _up(session, classes, dry_run_execute=rehearsal)

    _assert_failed_with_errors(result)
    assert "0 migrations left pending" in result.errors[0]


@MODES
def test_a_migration_raising_an_empty_message_still_reports_an_error(tmp_path, rehearsal):
    session, files = _session(tmp_path, count=1)
    session._migrator.apply.side_effect = RuntimeError()

    result = _up(session, {files[0]: _migration("001", "m1")}, dry_run_execute=rehearsal)

    _assert_failed_with_errors(result)
    assert "RuntimeError" in result.errors[0]


@MODES
def test_a_migration_that_cannot_be_loaded_reports_an_error(tmp_path, rehearsal):
    """Past the destructive gate (which loads, and raises, first) the loop records it."""
    session, _ = _session(tmp_path, count=1)

    with injected_lock(MagicMock()), injected_loader(side_effect=ImportError("no module x")):
        result = session.up(dry_run_execute=rehearsal, allow_destructive=True)

    _assert_failed_with_errors(result)
    assert "no module x" in result.errors[0]


@MODES
def test_an_irreversible_migration_under_require_reversible_reports_an_error(tmp_path, rehearsal):
    session, _ = _session(tmp_path, count=1)
    preflight = PreflightResult(
        migrations=[MigrationPreflightInfo(version="001", name="m1", has_down=False)]
    )

    with patch.object(session, "preflight", return_value=preflight):
        result = _up(session, None, dry_run_execute=rehearsal, require_reversible=True)

    _assert_failed_with_errors(result)


def test_has_errors_is_the_failure_outcome_not_the_failure_channel() -> None:
    """A result a caller builds by hand with ``success=False`` has errors, listed or not."""
    result = MigrateUpResult(success=False, migrations_applied=[], total_duration_ms=1)

    assert result.has_errors is True


def test_a_rehearsal_that_halts_and_then_fails_to_release_reports_both(tmp_path):
    """The savepoint failure is added to the halt, not put in its place."""
    session, files = _session(tmp_path, count=2)
    classes = {
        files[0]: _migration("001", "m1", requires_superuser=True),
        files[1]: _migration("002", "m2"),
    }
    execute = session._conn.execute

    def release_fails(sql, *args, **kwargs):
        if str(sql).startswith("RELEASE"):
            raise RuntimeError("connection lost")
        return execute(sql, *args, **kwargs)

    session._conn.execute = MagicMock(side_effect=release_fails)

    result = _up(session, classes, dry_run_execute=True)

    _assert_failed_with_errors(result)
    assert len(result.errors) == 2
    assert "Halted at 001_m1" in result.errors[0]
    assert result.errors[1] == "connection lost"
