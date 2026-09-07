"""``migrate up --online``: apply a SQL migration as its expand/contract stages.

The apply loop hands a pending ``.up.sql`` here when the operator asked for
``--online`` and every statement of the file has a staged plan
(:func:`~confiture.core.expand_contract.plannable`). Each plan runs through
the step runner with a checkpoint per stage; the ledger row is written after
the last contract stage, by the same ``record_applied`` the classic path uses.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from confiture.core._migrator.apply import record_applied
from confiture.core.expand_contract import StagedPlan, plannable
from confiture.core.schema_facts import server_major
from confiture.core.step_runner import CheckpointStore, RunOptions, run, steps_table


def online_plans(migration_file: Path, connection: Any) -> list[StagedPlan] | None:
    """The staged plans for a ``.up.sql`` file, or ``None`` when it must apply the classic way."""
    if not migration_file.name.endswith(".up.sql"):
        return None
    sql = migration_file.read_text(encoding="utf-8")
    return plannable(sql, server_version=server_major(connection))


def apply_online(
    migrator: Any,
    migration: Any,
    migration_file: Path,
    plans: list[StagedPlan],
    options: RunOptions,
) -> int:
    """Run ``plans`` stage by stage, then record the migration; return the elapsed milliseconds."""
    store = CheckpointStore(migrator.connection, steps_table(str(migrator.migration_table)))
    store.ensure()
    started = time.perf_counter()
    for index, staged in enumerate(plans):
        run(
            staged,
            migrator.connection,
            migration=migration.version,
            store=store,
            plan_index=index,
            options=options,
        )
    elapsed = int((time.perf_counter() - started) * 1000)
    record_applied(migrator, migration, elapsed, migration_file)
    migrator.connection.commit()
    return elapsed
