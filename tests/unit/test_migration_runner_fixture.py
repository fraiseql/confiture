"""``MigrationRunner`` must not conflate "no ledger" with "something broke" (#190).

``get_applied_migrations`` queried the literal ``tb_confiture`` and wrapped the
whole thing in ``except Exception: return []``. Two defects in three lines:

* a project whose ``tracking_table`` is ``audit.tb_migrations`` got ``[]``
  rather than its applied migrations;
* a dropped connection, a permission error, or a typo in the query was
  indistinguishable from an un-initialised database.

The second is the one that costs debugging time — this is *test* infrastructure,
so a silent ``[]`` turns into a green test suite asserting against nothing. It
is also exactly the absent-vs-error conflation ``core/ledger.py`` was introduced
in 0.37.0 to eliminate.
"""

from __future__ import annotations

from typing import Any

import psycopg
import pytest

from confiture.testing.fixtures.migration_runner import MigrationRunner


class _Cursor:
    def __init__(self, raiser: Exception | None, rows: list[tuple[str]]) -> None:
        self._raiser = raiser
        self._rows = rows
        self.executed: list[Any] = []

    def __enter__(self) -> _Cursor:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def execute(self, query: Any, params: Any = None) -> None:
        self.executed.append(query)
        if self._raiser is not None:
            raise self._raiser

    def fetchall(self) -> list[tuple[str]]:
        return self._rows


class _Connection:
    """Minimal psycopg-shaped stub: one cursor, one scripted outcome."""

    def __init__(
        self, raiser: Exception | None = None, rows: list[tuple[str]] | None = None
    ) -> None:
        self.cursor_obj = _Cursor(raiser, rows or [])
        self.rolled_back = False

    def cursor(self) -> _Cursor:
        return self.cursor_obj

    def rollback(self) -> None:
        self.rolled_back = True


def test_absent_ledger_returns_empty_list() -> None:
    """An un-initialised database is a legitimate empty result, not an error."""
    conn = _Connection(raiser=psycopg.errors.UndefinedTable("relation does not exist"))
    runner = MigrationRunner(connection=conn)  # type: ignore[arg-type]

    assert runner.get_applied_migrations() == []


def test_operational_error_is_raised_not_swallowed() -> None:
    """A dropped connection must surface, not masquerade as "nothing applied"."""
    conn = _Connection(raiser=psycopg.OperationalError("server closed the connection"))
    runner = MigrationRunner(connection=conn)  # type: ignore[arg-type]

    with pytest.raises(psycopg.OperationalError):
        runner.get_applied_migrations()


def test_programming_error_is_raised_not_swallowed() -> None:
    """A malformed query is a defect in this fixture — it must not read as empty."""
    conn = _Connection(raiser=psycopg.errors.SyntaxError("syntax error at or near"))
    runner = MigrationRunner(connection=conn)  # type: ignore[arg-type]

    with pytest.raises(psycopg.Error):
        runner.get_applied_migrations()


def test_configured_tracking_table_is_queried() -> None:
    """A non-default ``tracking_table`` must reach the query."""
    conn = _Connection(rows=[("001_init",)])
    runner = MigrationRunner(
        connection=conn,  # type: ignore[arg-type]
        tracking_table="audit.tb_migrations",
    )

    assert runner.get_applied_migrations() == ["001_init"]
    rendered = str(conn.cursor_obj.executed[0])
    assert "audit" in rendered and "tb_migrations" in rendered
    assert "tb_confiture" not in rendered


def test_defaults_to_tb_confiture() -> None:
    """The default is unchanged for callers that never configured one."""
    conn = _Connection(rows=[])
    runner = MigrationRunner(connection=conn)  # type: ignore[arg-type]

    runner.get_applied_migrations()
    assert "tb_confiture" in str(conn.cursor_obj.executed[0])
