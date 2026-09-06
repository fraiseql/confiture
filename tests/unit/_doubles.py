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


def connection_double(dbname: str = "unit_test_db") -> MagicMock:
    """A psycopg connection stand-in that answers ``SELECT current_database()``.

    ``MigrationLock`` derives its advisory-lock key from the database name, so
    a session double has to carry one — a bare ``MagicMock`` makes the lock hash
    a mock and fail with "object supporting the buffer API required".
    """
    conn = MagicMock(name="connection")
    conn.info.dbname = dbname
    row = (dbname,)
    conn.execute.return_value.fetchone.return_value = row
    cursor = conn.cursor.return_value
    cursor.fetchone.return_value = row
    cursor.__enter__.return_value.fetchone.return_value = row
    return conn
