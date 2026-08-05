"""``migrate preflight`` must probe the configured ledger, not the default (#190).

Two defects lived here. The probe ran ``SELECT 1 FROM tb_confiture LIMIT 1``
against whatever database ``--against`` pointed at, which raises
``UndefinedTable`` on any project that renamed its ledger; and the session was
built with ``migration_table_override="tb_confiture"``.

These are direct unit tests on the two helpers rather than end-to-end
assertions, because the end-to-end path swallows probe failures by design (the
hint is advisory). That is exactly what let a ``NameError`` inside the resolver
go unnoticed while every higher-level test stayed green — the broad ``except``
returned the default and the output looked right.
"""

from __future__ import annotations

from pathlib import Path

import psycopg
import pytest
import yaml

from confiture.cli.commands.migrate_analysis import (
    _preflight_tracking_table,
    _target_tracking_table_state,
)


def _write(tmp_path: Path, name: str, migration: dict | None) -> Path:
    payload: dict = {
        "name": "test",
        "database_url": "postgresql://localhost/x",
        "include_dirs": ["db/schema"],
    }
    if migration is not None:
        payload["migration"] = migration
    p = tmp_path / name
    p.write_text(yaml.safe_dump(payload))
    return p


# ---------------------------------------------------------------------------
# Name resolution
# ---------------------------------------------------------------------------


def test_configured_table_is_resolved(tmp_path: Path) -> None:
    cfg = _write(tmp_path, "env.yaml", {"tracking_table": "audit.tb_migrations"})
    assert _preflight_tracking_table(cfg) == "audit.tb_migrations"


def test_unset_tracking_table_falls_back_to_default(tmp_path: Path) -> None:
    cfg = _write(tmp_path, "env.yaml", None)
    assert _preflight_tracking_table(cfg) == "tb_confiture"


def test_no_config_falls_back_to_default() -> None:
    assert _preflight_tracking_table(None) == "tb_confiture"


def test_missing_config_file_falls_back_to_default(tmp_path: Path) -> None:
    assert _preflight_tracking_table(tmp_path / "nope.yaml") == "tb_confiture"


def test_malformed_config_falls_back_rather_than_raising(tmp_path: Path) -> None:
    """A bad config fails loudly later in preflight; this probe just defaults."""
    cfg = tmp_path / "broken.yaml"
    cfg.write_text("name: [unclosed\n")
    assert _preflight_tracking_table(cfg) == "tb_confiture"


# ---------------------------------------------------------------------------
# The probe itself
# ---------------------------------------------------------------------------


class _Cursor:
    def __init__(self, rows: list[tuple[int]] | None, raiser: Exception | None) -> None:
        self._rows = rows
        self._raiser = raiser
        self.executed: list[object] = []

    def __enter__(self) -> _Cursor:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def execute(self, query: object, params: object = None) -> None:
        self.executed.append(query)
        if self._raiser is not None:
            raise self._raiser

    def fetchone(self) -> tuple[int] | None:
        return self._rows[0] if self._rows else None


class _Conn:
    def __init__(
        self, rows: list[tuple[int]] | None = None, raiser: Exception | None = None
    ) -> None:
        self.cur = _Cursor(rows, raiser)

    def cursor(self) -> _Cursor:
        return self.cur

    def rollback(self) -> None:
        return None


class _Session:
    def __init__(self, conn: object) -> None:
        self._conn = conn


@pytest.fixture
def patched_ledger(monkeypatch):
    """Control `ledger_exists` without a database."""

    def _set(present: bool) -> None:
        monkeypatch.setattr("confiture.core.ledger.ledger_exists", lambda conn, table: present)

    return _set


def test_absent_ledger_reports_not_exists_and_empty(patched_ledger) -> None:
    patched_ledger(False)
    exists, empty = _target_tracking_table_state(
        _Session(_Conn()),  # type: ignore[arg-type]
        "audit.tb_migrations",
    )
    assert (exists, empty) == (False, True)


def test_present_but_empty_ledger_is_distinguished(patched_ledger) -> None:
    """The whole point of the split: absent and empty are different states."""
    patched_ledger(True)
    exists, empty = _target_tracking_table_state(
        _Session(_Conn(rows=[])),  # type: ignore[arg-type]
        "audit.tb_migrations",
    )
    assert (exists, empty) == (True, True)


def test_populated_ledger_is_not_empty(patched_ledger) -> None:
    patched_ledger(True)
    exists, empty = _target_tracking_table_state(
        _Session(_Conn(rows=[(1,)])),  # type: ignore[arg-type]
        "audit.tb_migrations",
    )
    assert (exists, empty) == (True, False)


def test_configured_table_reaches_the_query(patched_ledger) -> None:
    """The literal `tb_confiture` must never appear in the emitted SQL."""
    patched_ledger(True)
    conn = _Conn(rows=[(1,)])
    _target_tracking_table_state(_Session(conn), "audit.tb_migrations")  # type: ignore[arg-type]

    rendered = str(conn.cur.executed[0])
    assert "audit" in rendered and "tb_migrations" in rendered
    assert "tb_confiture" not in rendered


def test_probe_error_degrades_to_absent_and_empty(patched_ledger) -> None:
    """Advisory probe: a permission error must not break the preflight run."""
    patched_ledger(True)
    exists, empty = _target_tracking_table_state(
        _Session(_Conn(raiser=psycopg.errors.InsufficientPrivilege("permission denied"))),  # type: ignore[arg-type]
        "audit.tb_migrations",
    )
    assert (exists, empty) == (False, True)


def test_no_connection_reports_nothing_to_hint_about() -> None:
    exists, empty = _target_tracking_table_state(
        _Session(None),  # type: ignore[arg-type]
        "audit.tb_migrations",
    )
    assert (exists, empty) == (False, False)
