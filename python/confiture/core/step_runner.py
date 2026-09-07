"""Drive an expand/contract plan stage by stage, with a checkpoint after each.

The checkpoints live in ``<tracking_table>_steps`` (``tb_confiture_steps`` by
default), created by the same initialiser as the ledger: one row per
(migration, plan, stage) with its ``state`` and, for a backfill, the batch
cursor and rows done. A run that dies between stages leaves the rows behind;
:func:`resume` continues from the first stage that is not ``done``. The
migration reaches the ledger only when its last ``contract`` stage has
finished — until then it is pending, and ``migrate steps`` says so.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import psycopg
from psycopg import sql as pgsql

from confiture.core._migrator.apply import record_migration
from confiture.core._migrator.discovery import discover_migration_files, parse_migration_filename
from confiture.core._migrator.events import UpObserver, emit
from confiture.core.backfill import BackfillExecutor, BackfillSettings
from confiture.core.checksum import compute_checksum
from confiture.core.expand_contract import BackfillSpec, StagedPlan, plannable
from confiture.core.ledger import table_identifier
from confiture.core.schema_facts import server_major
from confiture.exceptions import ConfiturError, MigrationError, ValidationError

STEPS_SUFFIX = "_steps"
DONE, RUNNING, FAILED = "done", "running", "failed"

Backfiller = Callable[[Any, BackfillSpec, "StepRecord | None", Callable[[int, int], None]], int]


def steps_table(tracking_table: str) -> str:
    """The checkpoint table beside ``tracking_table`` (``tb_confiture`` → ``tb_confiture_steps``)."""
    return f"{tracking_table}{STEPS_SUFFIX}"


@dataclass(frozen=True)
class StepRecord:
    """One checkpoint row."""

    migration: str
    plan_index: int
    stage: str
    state: str
    batch_cursor: int | None
    rows_done: int
    updated_at: datetime

    def to_dict(self) -> dict[str, Any]:
        return {
            "migration": self.migration,
            "plan_index": self.plan_index,
            "stage": self.stage,
            "state": self.state,
            "batch_cursor": self.batch_cursor,
            "rows_done": self.rows_done,
            "updated_at": self.updated_at.isoformat(),
        }


class CheckpointStore:
    """The ``<tracking_table>_steps`` table: what each stage of each online migration has done."""

    def __init__(self, connection: Any, table: str = "tb_confiture_steps") -> None:
        self.connection = connection
        self.table = table
        self._ident = table_identifier(table)

    def ensure(self) -> None:
        """Create the table when it is missing. Idempotent; commits."""
        with self.connection.cursor() as cur:
            cur.execute(
                pgsql.SQL(
                    """
                    CREATE TABLE IF NOT EXISTS {} (
                        migration VARCHAR(255) NOT NULL,
                        plan_index INTEGER NOT NULL DEFAULT 0,
                        stage TEXT NOT NULL,
                        state TEXT NOT NULL,
                        batch_cursor BIGINT,
                        rows_done BIGINT NOT NULL DEFAULT 0,
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        PRIMARY KEY (migration, plan_index, stage)
                    )
                    """
                ).format(self._ident)
            )
        self.connection.commit()

    def records(self, migration: str | None = None) -> list[StepRecord]:
        """Every checkpoint row, oldest first; ``migration`` narrows to one version."""
        query = pgsql.SQL(
            "SELECT migration, plan_index, stage, state, batch_cursor, rows_done, updated_at "
            "FROM {} {} ORDER BY migration, plan_index, updated_at"
        ).format(
            self._ident,
            pgsql.SQL("WHERE migration = %s") if migration is not None else pgsql.SQL(""),
        )
        with self.connection.cursor() as cur:
            cur.execute(query, (migration,) if migration is not None else ())
            return [StepRecord(*row) for row in cur.fetchall()]

    def get(self, migration: str, plan_index: int, stage: str) -> StepRecord | None:
        return next(
            (r for r in self.records(migration) if r.plan_index == plan_index and r.stage == stage),
            None,
        )

    def _upsert(self, migration: str, plan_index: int, stage: str, state: str, **cols: Any) -> None:
        names = ["migration", "plan_index", "stage", "state", *cols]
        values = [migration, plan_index, stage, state, *cols.values()]
        updates = pgsql.SQL(", ").join(
            pgsql.SQL("{0} = EXCLUDED.{0}").format(pgsql.Identifier(n)) for n in ["state", *cols]
        )
        query = pgsql.SQL(
            "INSERT INTO {} ({}) VALUES ({}) "
            "ON CONFLICT (migration, plan_index, stage) DO UPDATE SET {}, updated_at = NOW()"
        ).format(
            self._ident,
            pgsql.SQL(", ").join(map(pgsql.Identifier, names)),
            pgsql.SQL(", ").join(pgsql.Placeholder() * len(values)),
            updates,
        )
        with self.connection.cursor() as cur:
            cur.execute(query, values)
        self.connection.commit()

    def start(self, migration: str, plan_index: int, stage: str) -> None:
        self._upsert(migration, plan_index, stage, RUNNING)

    def progress(
        self, migration: str, plan_index: int, stage: str, *, batch_cursor: int, rows_done: int
    ) -> None:
        self._upsert(
            migration, plan_index, stage, RUNNING, batch_cursor=batch_cursor, rows_done=rows_done
        )

    def done(self, migration: str, plan_index: int, stage: str) -> None:
        self._upsert(migration, plan_index, stage, DONE)

    def failed(self, migration: str, plan_index: int, stage: str) -> None:
        self._upsert(migration, plan_index, stage, FAILED)


@contextmanager
def _autocommit(connection: Any) -> Iterator[None]:
    """Each statement in its own transaction: a lock is held no longer than its statement."""
    connection.commit()
    previous = connection.autocommit
    connection.autocommit = True
    try:
        yield
    finally:
        connection.autocommit = previous


@dataclass(frozen=True)
class RunOptions:
    """What a run may do and how it reports: the gate, the observer, the backfill settings."""

    allow_destructive: bool = False
    on_event: UpObserver | None = None
    settings: BackfillSettings | None = None
    backfill: Backfiller | None = None  # an executor to use instead of the batched one


def run(
    staged: StagedPlan,
    connection: Any,
    *,
    migration: str,
    store: CheckpointStore,
    plan_index: int = 0,
    options: RunOptions | None = None,
) -> list[StepRecord]:
    """Run ``staged`` stage by stage from its checkpoints; a stage already ``done`` is skipped.

    Every statement runs in its own transaction; a checkpoint is committed
    when a stage starts and when it finishes. An observer that raises stops
    the run with the checkpoint on record — that is the crash the next
    :func:`resume` recovers from.
    """
    options = options or RunOptions()
    on_event = options.on_event
    backfill = options.backfill or BackfillExecutor(
        options.settings, on_event=on_event, migration=migration
    )
    for stage in staged.stages:
        record = store.get(migration, plan_index, stage.name)
        if record is not None and record.state == DONE:
            continue
        if stage.destructive and not options.allow_destructive:
            raise ValidationError(
                f"Stage {stage.name} of {migration} drops the old column: data is lost when it applies",
                error_code="VALID_002",
                resolution_hint="Review the plan, then run again with --allow-destructive",
            )
        store.start(migration, plan_index, stage.name)
        emit(on_event, "stage_started", version=migration, name=stage.name)
        try:
            with _autocommit(connection):
                if stage.backfill is not None:
                    backfill(
                        connection,
                        stage.backfill,
                        record,
                        _progress_recorder(store, migration, plan_index, stage.name),
                    )
                for statement in stage.statements:
                    with connection.cursor() as cur:
                        cur.execute(statement)
        except (psycopg.Error, ConfiturError):
            store.failed(migration, plan_index, stage.name)
            raise
        store.done(migration, plan_index, stage.name)
        emit(on_event, "stage_done", version=migration, name=stage.name)
    return store.records(migration)


def _progress_recorder(
    store: CheckpointStore, migration: str, plan_index: int, stage: str
) -> Callable[[int, int], None]:
    """The callback a backfill executor reports each committed batch through."""

    def record(batch_cursor: int, rows_done: int) -> None:
        store.progress(migration, plan_index, stage, batch_cursor=batch_cursor, rows_done=rows_done)

    return record


def resume(
    migrator: Any,
    version: str,
    *,
    migrations_dir: Path,
    allow_destructive: bool = False,
    on_event: UpObserver | None = None,
    settings: BackfillSettings | None = None,
) -> list[StepRecord]:
    """Continue the online migration ``version`` from its checkpoints and, when its last
    contract stage is done, record it in the ledger."""
    up_file = _migration_file(migrations_dir, version)
    sql = up_file.read_text(encoding="utf-8")
    plans = plannable(sql, server_version=server_major(migrator.connection))
    if plans is None:
        raise ValidationError(
            f"Migration {version} is not an online migration: a statement in {up_file.name} has no staged plan",
            resolution_hint="Apply it with migrate up",
        )
    migrator.initialize()  # the ledger and, beside it, the checkpoint table — idempotent
    store = CheckpointStore(migrator.connection, steps_table(_tracking_table(migrator)))
    started = time.perf_counter()
    for index, staged in enumerate(plans):
        run(
            staged,
            migrator.connection,
            migration=version,
            store=store,
            plan_index=index,
            options=RunOptions(
                allow_destructive=allow_destructive, on_event=on_event, settings=settings
            ),
        )
    _, name = parse_migration_filename(up_file.name)
    record_migration(
        migrator,
        version=version,
        name=name,
        execution_time_ms=int((time.perf_counter() - started) * 1000),
        checksum=compute_checksum(up_file),
    )
    migrator.connection.commit()
    return store.records(version)


def _tracking_table(migrator: Any) -> str:
    return str(migrator.migration_table)


def _migration_file(migrations_dir: Path, version: str) -> Path:
    for path in discover_migration_files(migrations_dir):
        if path.name.endswith(".up.sql") and parse_migration_filename(path.name)[0] == version:
            return path
    raise MigrationError(
        f"No SQL migration with version {version} under {migrations_dir}",
        resolution_hint="Online migrations are .up.sql files; check --migrations-dir",
    )
