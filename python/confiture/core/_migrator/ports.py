"""What each part of the migrator needs of the engine or the session it serves.

``MigrationEngine`` delegates to ``state``, ``apply``, ``rollback``, ``baseline``,
``discovery`` and ``policy``; ``MigratorSession`` to ``apply_loop``,
``rollback_loop``, ``replay`` and ``reporting``. Each takes its host as a parameter,
and each annotated it with the host's own class, imported under ``TYPE_CHECKING`` — a
back-edge from the part to the whole that the interpreter never checks and a reader
has to take on trust. :class:`EngineHost` and :class:`SessionHost` name what the
parts read, and nothing else. ``tests/unit/test_migrator_has_no_back_edges.py`` holds
each host to its protocol — every member there, with the protocol's parameters —
because ty does not check a protocol's conformance at these call sites. They are the
interface a Rust port writes as a trait.

The apply pipeline's own contract is here too: :class:`ApplyStage`, the
collaborators a strategy is handed, and :class:`Strategy`, what a strategy is.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar, Protocol

if TYPE_CHECKING:
    from psycopg import sql as pgsql

    from confiture.config.environment import Environment
    from confiture.core.hooks import HookRegistry
    from confiture.core.hooks.context import ExecutionContext
    from confiture.core.locking import MigrationLock
    from confiture.models.migration import Migration
    from confiture.models.results import (
        MigrateReinitResult,
        PreflightResult,
        StatusResult,
    )


@dataclass(frozen=True)
class ApplyStage:
    """What a strategy works with: the connection, the hooks, and the ledger's recorder.

    ``trigger_hook(phase, migration, execution_time_ms=, success=, error=)`` runs
    the hooks registered for *phase*; ``record(migration, execution_time_ms,
    migration_file, applied_by=)`` writes the ledger row.
    """

    connection: Any
    trigger_hook: Callable[..., None]
    record: Callable[..., None]


class Strategy(Protocol):
    """How a migration's body runs, between its hooks, and how it is recorded."""

    #: Whether the body runs inside the connection's transaction, so a caller's
    #: savepoint can hold it (``--dry-run-execute``).
    transactional: ClassVar[bool]

    def execute(
        self,
        stage: ApplyStage,
        migration: Migration,
        *,
        already_applied: bool,
        migration_file: Path | None,
        commit: bool,
        applied_by: str | None,
    ) -> None: ...


class EngineHost(Protocol):
    """The engine as its parts and the session's loops read it."""

    connection: Any
    migration_table: str
    hook_registry: HookRegistry[ExecutionContext]
    _table_schema: str | None
    _table_base: str

    @property
    def _table_ident(self) -> pgsql.Identifier: ...

    def _execute_sql(
        self, query: str | pgsql.Composable, params: tuple[str, ...] | None = None
    ) -> None: ...

    def _is_applied(self, version: str) -> bool: ...

    def _validate_preconditions(
        self, migration: Migration, direction: str, preconditions: list
    ) -> None: ...

    def _version_from_filename(self, filename: str) -> str: ...

    def _apply_ddl_string(self, ddl: str) -> tuple[int, list[str]]: ...

    def _backup_tracking_table(self) -> list[dict[str, Any]]: ...

    def _clear_tracking_table(self) -> int: ...

    def _discover_user_schemas(self) -> list[str]: ...

    def _drop_user_schemas(self, schemas: list[str]) -> list[str]: ...

    def initialize(self) -> None: ...

    def tracking_table_exists(self) -> bool: ...

    def get_applied_versions(self) -> list[str]: ...

    def get_applied_migrations_with_timestamps(self) -> list[dict[str, Any]]: ...

    def get_current_revision_row(self) -> dict[str, Any] | None: ...

    def find_migration_files(self, migrations_dir: Path | None = None) -> list[Path]: ...

    def find_orphaned_sql_files(self, migrations_dir: Path | None = None) -> list[Path]: ...

    def find_pending(self, migrations_dir: Path | None = None) -> list[Path]: ...

    def apply(
        self,
        migration: Migration,
        force: bool = False,
        migration_file: Path | None = None,
        skip_preconditions: bool = False,
        *,
        commit: bool = True,
        applied_by: str | None = None,
        strategy: Strategy | None = None,
    ) -> None: ...

    def rollback(self, migration: Migration, skip_preconditions: bool = False) -> None: ...

    def mark_applied(self, migration_file: Path, reason: str = "baseline") -> str: ...

    def baseline_through(self, through: str, migrations_dir: Path) -> list[str]: ...

    def reinit(
        self,
        through: str | None = None,
        dry_run: bool = False,
        migrations_dir: Path | None = None,
    ) -> MigrateReinitResult: ...


class SessionHost(Protocol):
    """The session as its loops read it."""

    _config: Environment | None
    _conn: Any
    _migrations_dir: Path
    _migrator: EngineHost | None

    @property
    def migration_loader(self) -> Callable[[Path], type]: ...

    def _migration_lock(
        self, *, no_lock: bool, lock_timeout: int, command: str | None = None
    ) -> MigrationLock: ...

    def preflight(self, *, versions: list[str] | None = None) -> PreflightResult: ...

    def status(self) -> StatusResult: ...
