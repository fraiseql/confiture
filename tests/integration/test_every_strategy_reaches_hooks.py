"""Every strategy runs a migration between its hooks, after its preconditions.

``migrate up --online`` applies a rewrite as expand → backfill → contract stages.
The apply loop used to hand such a migration straight to the step runner and
return, past the engine's ``apply`` — which is where the hooks run and the
preconditions are asked. So a ``BEFORE_EXECUTE`` hook never fired for it, and a
precondition that would have stopped the classic apply let the online one run.
Each test runs the three strategies — transactional, autocommit (``CREATE INDEX
CONCURRENTLY``) and online — and asserts the same thing of each.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import psycopg
import pytest

from confiture.core.hooks import Hook, HookResult
from confiture.core.hooks.context import ExecutionContext, HookContext
from confiture.core.hooks.phases import HookPhase
from confiture.core.migrator import MigratorSession

VERSION = "20260101000000"


class _Recorder(Hook[ExecutionContext]):
    def __init__(self) -> None:
        super().__init__(hook_id="test.recorder", name="Recorder")
        self.phases: list[str] = []

    async def execute(self, context: HookContext[ExecutionContext]) -> HookResult:
        self.phases.append(str(context.phase.value))
        return HookResult(success=True)


_WIDEN = (
    "ALTER TABLE orders ALTER COLUMN total TYPE bigint;\n",
    "ALTER TABLE orders ALTER COLUMN total TYPE integer;\n",
)
_INDEX = (
    "CREATE INDEX CONCURRENTLY orders_total_ix ON orders (total);\n",
    "DROP INDEX CONCURRENTLY orders_total_ix;\n",
)
#: strategy → (up and down SQL, run it ``--online``)
STRATEGIES: dict[str, tuple[tuple[str, str], bool]] = {
    "transactional": (_WIDEN, False),
    "autocommit": (_INDEX, False),
    "online": (_WIDEN, True),
}


def _project(
    tmp_path: Path, sql: tuple[str, str], *, precondition_table: str | None = None
) -> Path:
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / f"{VERSION}_change_orders.up.sql").write_text(sql[0])
    (migrations / f"{VERSION}_change_orders.down.sql").write_text(sql[1])
    if precondition_table is not None:
        (migrations / f"{VERSION}_change_orders.yaml").write_text(
            f"up_preconditions:\n  - type: TableExists\n    table: {precondition_table}\n"
        )
    return migrations


def _database(make_database: Callable[[str], str]) -> str:
    url = make_database("confiture_online_hooks")
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute("CREATE TABLE orders (id integer PRIMARY KEY, total integer NOT NULL)")
        conn.execute("INSERT INTO orders SELECT g, g FROM generate_series(1, 50) g")
    return url


def _state(url: str) -> tuple[str, bool, list[tuple[str, ...]], list[tuple[str, ...]]]:
    with psycopg.connect(url) as conn:
        data_type = conn.execute(
            "SELECT data_type FROM information_schema.columns "
            "WHERE table_name = 'orders' AND column_name = 'total'"
        ).fetchone()
        indexed = conn.execute("SELECT to_regclass('orders_total_ix') IS NOT NULL").fetchone()
        ledger = (
            conn.execute("SELECT version FROM tb_confiture").fetchall()
            if conn.execute("SELECT to_regclass('tb_confiture')").fetchone()[0]
            else []
        )
        steps = (
            conn.execute("SELECT stage FROM tb_confiture_steps ORDER BY updated_at").fetchall()
            if conn.execute("SELECT to_regclass('tb_confiture_steps')").fetchone()[0]
            else []
        )
    assert data_type is not None
    assert indexed is not None
    return data_type[0], indexed[0], ledger, steps


@pytest.mark.parametrize("strategy", STRATEGIES)
def test_the_hooks_run(
    strategy: str, fresh_database_factory: Callable[[str], str], tmp_path: Path
) -> None:
    sql, online = STRATEGIES[strategy]
    url = _database(fresh_database_factory)
    recorder = _Recorder()
    with MigratorSession(None, _project(tmp_path, sql), database_url_override=url) as session:
        session.migrator.register_hook(HookPhase.BEFORE_EXECUTE, recorder)
        session.migrator.register_hook(HookPhase.AFTER_EXECUTE, recorder)
        result = session.up(online=online, allow_destructive=True)

    assert result.success, result.error_summary
    assert recorder.phases == ["before_execute", "after_execute"]
    data_type, indexed, ledger, steps = _state(url)
    assert ledger == [(VERSION,)]
    assert (data_type, indexed) == (("integer", True) if sql is _INDEX else ("bigint", False))
    assert steps == ([("expand",), ("backfill",), ("contract",)] if online else [])


@pytest.mark.parametrize("strategy", STRATEGIES)
def test_a_failing_precondition_stops_it(
    strategy: str, fresh_database_factory: Callable[[str], str], tmp_path: Path
) -> None:
    sql, online = STRATEGIES[strategy]
    url = _database(fresh_database_factory)
    migrations = _project(tmp_path, sql, precondition_table="no_such_table")
    with MigratorSession(None, migrations, database_url_override=url) as session:
        result = session.up(online=online, allow_destructive=True)

    assert not result.success
    assert "no_such_table" in str(result.failure)
    data_type, indexed, ledger, _ = _state(url)
    assert (data_type, indexed, ledger) == ("integer", False, [])
