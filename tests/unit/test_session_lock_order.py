"""The session plans under the lock.

``MigratorSession.up()`` used to discover pending migrations *before*
acquiring the migration lock. Two deployers starting together therefore both
saw the same pending list; the second waited for the lock, then tried to apply
what the first had just applied and failed with MIGR_101. Discovery — and the
ledger's ``initialize()`` — belong inside the lock: whoever holds it plans
against the ledger as it is at that moment.
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import ClassVar
from unittest.mock import patch

import pytest

from confiture.config.environment import Environment
from confiture.core.migrator import MigratorSession
from tests.unit._doubles import connection_double, injected_connection, migrator_double


def _env() -> Environment:
    return Environment.model_validate(
        {
            "name": "test",
            "database_url": "postgresql://localhost/test",
            "include_dirs": ["db/schema"],
        }
    )


class _RecordingLock:
    """Stands in for ``MigrationLock``; records when the lock is taken and released."""

    events: ClassVar[list[str]] = []

    def __init__(self, conn, config=None) -> None:
        self.config = config

    @contextmanager
    def acquire(self):
        _RecordingLock.events.append("acquire")
        try:
            yield
        finally:
            _RecordingLock.events.append("release")


@pytest.fixture
def events() -> list[str]:
    _RecordingLock.events = []
    return _RecordingLock.events


def _run_up(tmp_path: Path, events: list[str], **kwargs) -> None:
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "20260101000001_a.up.sql").write_text("SELECT 1;\n")
    (migrations / "20260101000001_a.down.sql").write_text("SELECT 1;\n")
    double = migrator_double(find_migration_files=[], find_pending=[])
    double.initialize.side_effect = lambda: events.append("initialize")
    double.find_pending.side_effect = lambda **_: events.append("find_pending") or []
    double.find_migration_files.side_effect = lambda **_: (
        events.append("find_migration_files") or []
    )
    with (
        injected_connection(connection_double()),
        patch("confiture.core.migrator.Migrator", autospec=True, return_value=double),
        patch("confiture.core.migrator.MigrationLock", _RecordingLock),
    ):
        with MigratorSession(_env(), migrations) as session:
            result = session.up(**kwargs)
    assert result.success is True, result.errors
    assert result.migrations_applied == []


def _order(events: list[str], first: str, later: str) -> None:
    assert first in events and later in events, events
    assert events.index(first) < events.index(later), events


def test_up_acquires_the_lock_before_initialize_and_discovery(tmp_path: Path, events) -> None:
    _run_up(tmp_path, events)
    _order(events, "acquire", "initialize")
    _order(events, "acquire", "find_pending")
    _order(events, "find_pending", "release")


def test_dry_run_execute_plans_under_the_lock_too(tmp_path: Path, events) -> None:
    _run_up(tmp_path, events, dry_run_execute=True)
    _order(events, "acquire", "initialize")
    _order(events, "acquire", "find_pending")


def test_no_lock_still_initializes_and_discovers(tmp_path: Path, events) -> None:
    _run_up(tmp_path, events, no_lock=True)
    assert "initialize" in events and "find_pending" in events
