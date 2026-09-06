"""``run_against`` names its savepoints through ``sql.Identifier``.

A per-migration savepoint was ``f"SAVEPOINT sp_{migration.version}"``; a
version is whatever the migration class declares.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

from psycopg import sql as pgsql

from confiture.core._migrator.session import MigratorSession
from tests.unit._doubles import injected_loader


def _session() -> tuple[MigratorSession, MagicMock]:
    conn = MagicMock()
    session = MigratorSession(
        None,
        Path("db/migrations"),
        database_url_override="postgresql://localhost/preflight",
        migration_table_override="tb_confiture",
    )
    session._conn = conn  # entered by hand: the test drives run_against() directly
    session._migrator = MagicMock()
    return session, conn


class _Migration:
    def __init__(self, connection: Any) -> None:
        self.version = "20260101120000"
        self.name = "t"
        self.transactional = True

    def up(self) -> None:
        return None


def _text(sql: Any) -> str:
    return sql.as_string() if isinstance(sql, pgsql.Composable) else str(sql)


def test_savepoint_statements_are_composed() -> None:
    session, conn = _session()
    with injected_loader(return_value=_Migration):
        session.run_against(
            [Path("db/migrations/20260101120000_t.up.sql")],
            against_url="postgresql://localhost/preflight",
        )

    statements = [c.args[0] for c in conn.execute.call_args_list]
    savepoints = [s for s in statements if "SAVEPOINT" in _text(s)]
    assert savepoints, [_text(s) for s in statements]
    for statement in savepoints:
        assert isinstance(statement, pgsql.Composable), _text(statement)
    rendered = [" ".join(_text(s).split()) for s in savepoints]
    assert 'SAVEPOINT "sp_20260101120000"' in rendered
    assert 'RELEASE SAVEPOINT "sp_20260101120000"' in rendered
    assert 'ROLLBACK TO SAVEPOINT "preflight_run"' in rendered
