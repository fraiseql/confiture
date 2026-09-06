"""Autospecced doubles for the core orchestration objects.

A double built here answers only the attributes the real class has, with the
real signatures — a renamed method or a changed parameter fails the test
instead of being swallowed by a bare ``MagicMock``. Instance attributes the
constructors set (which ``create_autospec`` cannot see) are declared here so
code under test that reads ``migrator.migration_table`` keeps working.

Usage::

    with patch("confiture.core.migrator.Migrator", return_value=migrator_double()):
        ...
    # or, when only the class needs replacing:
    with patch("confiture.core.migrator.Migrator", autospec=True) as cls:
        cls.return_value.find_pending.return_value = []
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, create_autospec

from confiture.core.builder import SchemaBuilder
from confiture.core.migrator import Migrator, MigratorSession


def migrator_double(**returns: Any) -> MagicMock:
    """An autospecced ``Migrator`` instance; ``**returns`` set ``<method>.return_value``."""
    double = create_autospec(Migrator, instance=True)
    double.connection = MagicMock(name="connection")
    double.migration_table = "tb_confiture"
    double._table_base = "tb_confiture"
    double._table_schema = None
    double.hook_registry = MagicMock(name="hook_registry")
    for name, value in returns.items():
        getattr(double, name).return_value = value
    return double


def session_double(**returns: Any) -> MagicMock:
    """An autospecced ``MigratorSession`` instance."""
    double = create_autospec(MigratorSession, instance=True)
    double._config = MagicMock(name="config")
    double._conn = MagicMock(name="conn")
    double._migrator = migrator_double()
    double._migrations_dir = None
    double._database_url_override = None
    double._migration_table_override = None
    for name, value in returns.items():
        getattr(double, name).return_value = value
    return double


def builder_double(**returns: Any) -> MagicMock:
    """An autospecced ``SchemaBuilder`` instance."""
    double = create_autospec(SchemaBuilder, instance=True)
    double.env_config = MagicMock(name="env_config")
    double.include_configs = []
    for name, value in returns.items():
        getattr(double, name).return_value = value
    return double


def connection_double(
    dbname: str = "confiture_test", *, view_helpers_installed: bool = True
) -> MagicMock:
    """A psycopg connection stand-in that answers the engine's bookkeeping queries.

    The advisory lock asks ``SELECT current_database()``; the view-helper policy
    counts functions in ``pg_proc``; the checksum verifier reads an (empty)
    ledger with ``fetchall()``. Anything else fetches ``(dbname,)``.
    """
    conn = MagicMock(name="connection")
    last: dict[str, str] = {"sql": ""}

    def _fetchone() -> tuple[Any, ...]:
        if "pg_proc" in last["sql"]:
            return (2 if view_helpers_installed else 0,)
        return (dbname,)

    def _wire(cursor: MagicMock) -> None:
        def _execute(sql: Any, *args: Any, **kwargs: Any) -> MagicMock:
            last["sql"] = str(sql)
            return cursor

        cursor.execute.side_effect = _execute
        cursor.fetchone.side_effect = _fetchone
        cursor.fetchall.return_value = []  # an empty ledger

    _wire(conn.execute.return_value)
    conn.execute.side_effect = lambda sql, *a, **k: (
        last.__setitem__("sql", str(sql)),
        conn.execute.return_value,
    )[1]
    cursor = conn.cursor.return_value
    _wire(cursor)
    _wire(cursor.__enter__.return_value)
    return conn
