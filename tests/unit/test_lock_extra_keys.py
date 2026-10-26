"""``migration.locking.extra_keys``: the model, the order, the release (#768).

The real-PostgreSQL behaviour is ``tests/integration/test_lock_extra_keys.py``;
these pin what a stand-in connection can show.
"""

from pathlib import Path
from unittest.mock import MagicMock

import psycopg
import pytest
import yaml
from pydantic import ValidationError

from confiture.config.environment import Environment, LockingConfig
from confiture.core._migrator.session import MigratorSession
from confiture.core.locking import (
    LockAcquisitionError,
    LockConfig,
    LockMode,
    MigrationLock,
    resolve_extra_lock_keys,
)
from confiture.sql_text import rendered

FRAISEQL_KEY = 0x4652414953450001


class TestLockingConfig:
    def test_defaults_to_no_extra_key(self) -> None:
        assert LockingConfig().extra_keys == []

    @pytest.mark.parametrize("key", [FRAISEQL_KEY, 0, -1, -(2**63), 2**63 - 1])
    def test_accepts_every_int8(self, key: int) -> None:
        assert LockingConfig(extra_keys=[key]).extra_keys == [key]

    @pytest.mark.parametrize("key", [2**63, -(2**63) - 1])
    def test_refuses_a_key_outside_int8(self, key: int) -> None:
        with pytest.raises(ValidationError):
            LockingConfig(extra_keys=[key])

    @pytest.mark.parametrize("key", [True, False, "1", 1.0])
    def test_refuses_a_key_that_is_not_an_integer(self, key: object) -> None:
        with pytest.raises(ValidationError):
            LockingConfig.model_validate({"extra_keys": [key]})

    def test_a_hex_key_in_yaml_reads_as_the_integer(self, tmp_path: Path) -> None:
        path = tmp_path / "env.yaml"
        path.write_text(
            "name: t\ndatabase_url: postgresql://localhost/x\ninclude_dirs: []\n"
            "migration:\n  locking:\n    extra_keys: [0x4652414953450001]\n"
        )
        env = Environment.model_validate(yaml.safe_load(path.read_text()))
        assert env.migration.locking.extra_keys == [FRAISEQL_KEY]

    def test_resolves_to_a_tuple_or_nothing(self) -> None:
        assert resolve_extra_lock_keys(LockingConfig(extra_keys=[1, 2])) == (1, 2)
        assert resolve_extra_lock_keys(None) == ()


def _lock(config: LockConfig, fetches: list[tuple[object]]) -> tuple[MigrationLock, MagicMock]:
    conn = MagicMock()
    cursor = MagicMock()
    cursor.fetchone.side_effect = [("test_db",), *fetches]
    conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
    conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    return MigrationLock(conn, config), cursor


def _advisory_calls(cursor: MagicMock) -> list[str]:
    return [
        text
        for text in (rendered(c.args[0]) for c in cursor.execute.call_args_list)
        if "advisory" in text
    ]


class TestOrderAndRelease:
    def test_taken_after_confiture_s_lock_and_released_in_reverse(self) -> None:
        lock, cursor = _lock(LockConfig(extra_keys=(FRAISEQL_KEY, -7)), [(True,)] * 4)
        with lock.acquire():
            pass
        calls = _advisory_calls(cursor)
        assert calls[0].startswith("SELECT pg_advisory_lock(") and "::bigint" not in calls[0]
        assert "pg_advisory_lock" in calls[1] and "::bigint" in calls[1]
        assert "pg_advisory_lock" in calls[2] and "::bigint" in calls[2]
        assert "pg_advisory_unlock" in calls[3] and "::bigint" in calls[3]
        assert "pg_advisory_unlock" in calls[4] and "::bigint" in calls[4]
        assert "pg_advisory_unlock" in calls[5] and "::bigint" not in calls[5]
        keys = [
            c.args[0].interpolations[0].value
            for c in cursor.execute.call_args_list
            if "::bigint" in rendered(c.args[0])
        ]
        assert keys == [FRAISEQL_KEY, -7, -7, FRAISEQL_KEY]

    def test_non_blocking_refusal_releases_what_was_taken(self) -> None:
        lock, cursor = _lock(
            LockConfig(mode=LockMode.NON_BLOCKING, extra_keys=(1, 2)),
            [(True,), (True,), (False,), (True,)],
        )
        with pytest.raises(LockAcquisitionError) as caught, lock.acquire():
            pytest.fail("acquired")
        assert caught.value.timeout is False
        assert "advisory lock 2" in str(caught.value)
        calls = _advisory_calls(cursor)
        assert next(c for c in calls if "unlock" in c).endswith("::bigint)")  # key 1 first
        assert sum("unlock" in c for c in calls) == 2  # key 1, then confiture's own
        assert lock.lock_held is False

    def test_a_failed_release_does_not_stop_the_others(self) -> None:
        lock, cursor = _lock(LockConfig(extra_keys=(1, 2)), [(True,)])
        executed: list[str] = []

        def execute(query, *_args):
            text = rendered(query)
            executed.append(text)
            if (
                "pg_advisory_unlock" in text
                and "::bigint" in text
                and not any("pg_advisory_unlock" in e for e in executed[:-1])
            ):
                raise psycopg.OperationalError("connection lost")

        cursor.execute.side_effect = execute
        with lock.acquire():
            pass
        assert sum("pg_advisory_unlock" in e for e in executed) == 3

    def test_no_extra_key_means_one_lock(self) -> None:
        lock, cursor = _lock(LockConfig(), [(True,)])
        with lock.acquire():
            pass
        assert len(_advisory_calls(cursor)) == 2


class TestEveryVerbTakesThemThroughTheSession:
    def _session(self, **kwargs: object) -> MigratorSession:
        session = MigratorSession(**kwargs)  # type: ignore[arg-type]
        session._conn = MagicMock()
        return session

    def test_from_the_environment(self, tmp_path: Path) -> None:
        env = Environment.model_validate(
            {
                "name": "t",
                "database_url": "postgresql://localhost/x",
                "include_dirs": [],
                "migration": {"locking": {"extra_keys": [FRAISEQL_KEY]}},
            }
        )
        session = self._session(config=env, migrations_dir=tmp_path)
        lock = session._migration_lock(no_lock=False, lock_timeout=10)
        assert lock.config.extra_keys == (FRAISEQL_KEY,)

    def test_given_keys_win(self, tmp_path: Path) -> None:
        session = self._session(config=None, migrations_dir=tmp_path, extra_lock_keys=[3])
        assert session._migration_lock(no_lock=False, lock_timeout=10).config.extra_keys == (3,)

    def test_none_without_a_setting(self, tmp_path: Path) -> None:
        session = self._session(config=None, migrations_dir=tmp_path)
        assert session._migration_lock(no_lock=False, lock_timeout=10).config.extra_keys == ()
