"""Contract test pinning the Python symbols confiture's consumers import.

Two projects import confiture as a library, and neither is visible to this
repository's CI:

- **fraisier** probes its import surface in
  ``tests/test_confiture_dependency_floor.py`` with ``importlib.import_module`` +
  ``hasattr`` — nothing stronger, so a symbol rebound to a different kind of object,
  or a method whose parameters narrowed, passes its probe and fails a deploy.
- **printoptim_backend** names what it imports in a ``pyproject.toml`` comment, and
  runs every one of its migrations through ``models.migration.Migration``.

Confiture is the side that knows what the shape was, so the shape is pinned here.
Each row names the consumer file and line it was read from: removing or narrowing a
symbol is then an edit to a table that says who it breaks, never a surprise in
someone else's CI.

A call shape pins the parameters the consumer passes. The signature has *narrowed*
when one of them is gone, when one the consumer may omit became required, or when a
new required parameter appeared that the consumer does not pass. Widening — a new
optional parameter — is always allowed.
"""

from __future__ import annotations

import dataclasses
import importlib
import inspect
from typing import Any, NamedTuple

import pytest


class Symbol(NamedTuple):
    """One attribute a consumer imports by name."""

    consumer: str
    module: str
    attribute: str
    source: str
    """The consumer's own ``file:line`` that imports it."""
    pinned_since: str


class CallShape(NamedTuple):
    """The parameters a consumer passes to one callable."""

    consumer: str
    target: str
    """``module:Attr.member`` — the callable, reached through its import path."""
    passes: tuple[str, ...]
    """Parameter names the consumer supplies, positionally or by keyword."""
    source: str
    pinned_since: str


class Members(NamedTuple):
    """Fields, properties or methods a consumer reads off an object it receives."""

    consumer: str
    target: str
    names: tuple[str, ...]
    source: str
    pinned_since: str


_FLOOR = "fraisier:tests/test_confiture_dependency_floor.py"

# fraisier's floor probe (`CONFITURE_IMPORT_SURFACE`), row for row, plus the one
# symbol fraisier imports and its probe does not list.
FRAISIER_SYMBOLS: tuple[Symbol, ...] = (
    Symbol("fraisier", "confiture", "MigrateUpResult", f"{_FLOOR}:45", "1.14.0"),
    Symbol("fraisier", "confiture", "MigrateDownResult", f"{_FLOOR}:45", "1.14.0"),
    Symbol("fraisier", "confiture.config.environment", "Environment", f"{_FLOOR}:46", "1.14.0"),
    Symbol("fraisier", "confiture.core.builder", "SchemaBuilder", f"{_FLOOR}:47", "1.14.0"),
    Symbol(
        "fraisier", "confiture.error_codes", "EXIT_CODE_SEMANTIC_CLASS", f"{_FLOOR}:51", "1.14.0"
    ),
    Symbol("fraisier", "confiture.error_codes", "NO_LEDGER_ERROR_CODE", f"{_FLOOR}:51", "1.14.0"),
    Symbol("fraisier", "confiture.core.hooks", "HookPhase", f"{_FLOOR}:52", "1.14.0"),
    Symbol("fraisier", "confiture.core.hooks.builtin", "BackupHook", f"{_FLOOR}:55", "1.14.0"),
    Symbol("fraisier", "confiture.core.locking", "LockAcquisitionError", f"{_FLOOR}:56", "1.14.0"),
    Symbol("fraisier", "confiture.core.migrator", "Migrator", f"{_FLOOR}:57", "1.14.0"),
    Symbol("fraisier", "confiture.core.restorer", "DatabaseRestorer", f"{_FLOOR}:58", "1.14.0"),
    Symbol("fraisier", "confiture.core.restorer", "RestoreOptions", f"{_FLOOR}:58", "1.14.0"),
    Symbol("fraisier", "confiture.core.view_manager", "ViewManager", f"{_FLOOR}:59", "1.14.0"),
    Symbol("fraisier", "confiture.exceptions", "MigrationError", f"{_FLOOR}:60", "1.14.0"),
    Symbol("fraisier", "confiture.exceptions", "RestoreError", f"{_FLOOR}:60", "1.14.0"),
    Symbol("fraisier", "confiture.models.migration", "Migration", f"{_FLOOR}:61", "1.14.0"),
    # Imported at module level and caught around `m.up(...)`; the probe omits it.
    Symbol(
        "fraisier",
        "confiture.exceptions",
        "ValidationError",
        "fraisier:fraisier/dbops/confiture.py:29",
        "1.14.0",
    ),
)

# printoptim_backend's `pyproject.toml:31` comment names these as the symbols it
# consumes; the `source` column is where each one is actually imported.
PRINTOPTIM_SYMBOLS: tuple[Symbol, ...] = (
    Symbol(
        "printoptim",
        "confiture.models.migration",
        "Migration",
        "printoptim:db/migrations/*.py (every Python migration)",
        "1.14.0",
    ),
    Symbol(
        "printoptim",
        "confiture.core.builder",
        "SchemaBuilder",
        "printoptim:tests/fixtures/database/setup.py:85",
        "1.14.0",
    ),
    Symbol(
        "printoptim",
        "confiture.core.test_db",
        "TestDbProvisioner",
        "printoptim:tests/fixtures/database/setup.py:86",
        "1.14.0",
    ),
    Symbol(
        "printoptim",
        "confiture.testing.worker_db",
        "resolve_worker_db_name",
        "printoptim:tests/conftest.py:27",
        "1.14.0",
    ),
    Symbol(
        "printoptim",
        "confiture.testing.worker_db",
        "is_ci",
        "printoptim:tests/fixtures/database/setup.py:87",
        "1.14.0",
    ),
    Symbol(
        "printoptim",
        "confiture",
        "Migrator",
        "printoptim:src/printoptim_backend/core/migration_runner.py:79",
        "1.14.0",
    ),
)

_FRAISIER_DBOPS = "fraisier:fraisier/dbops/confiture.py"
_PRINTOPTIM_SETUP = "printoptim:tests/fixtures/database/setup.py"
_PRINTOPTIM_RUNNER = "printoptim:src/printoptim_backend/core/migration_runner.py"

CALL_SHAPES: tuple[CallShape, ...] = (
    CallShape(
        "fraisier",
        "confiture.core.migrator:Migrator.from_config",
        ("config", "migrations_dir"),
        f"{_FRAISIER_DBOPS}:320",
        "1.14.0",
    ),
    CallShape(
        "fraisier",
        "confiture.core._migrator.session:MigratorSession.up",
        ("dry_run_execute", "lock_timeout", "require_reversible", "allow_destructive"),
        f"{_FRAISIER_DBOPS}:431",
        "1.14.0",
    ),
    CallShape(
        "fraisier",
        "confiture.core._migrator.session:MigratorSession.down",
        ("steps",),
        f"{_FRAISIER_DBOPS}:522",
        "1.14.0",
    ),
    CallShape(
        "fraisier",
        "confiture.core._migrator.session:MigratorSession.status",
        (),
        f"{_FRAISIER_DBOPS}:279",
        "1.14.0",
    ),
    CallShape(
        "fraisier",
        "confiture.core.builder:SchemaBuilder",
        ("env", "project_dir"),
        "fraisier:fraisier/strategies/_core.py:462",
        "1.14.0",
    ),
    CallShape(
        "fraisier",
        "confiture.core.builder:SchemaBuilder.build_split",
        ("output_dir",),
        "fraisier:fraisier/strategies/_core.py:466",
        "1.14.0",
    ),
    CallShape(
        "fraisier",
        "confiture.core.builder:SchemaBuilder.compute_hash",
        (),
        "fraisier:fraisier/testing/_manager.py:91",
        "1.14.0",
    ),
    CallShape(
        "fraisier",
        "confiture.core.restorer:RestoreOptions",
        (
            "backup_path",
            "target_db",
            "host",
            "port",
            "username",
            "jobs",
            "no_owner",
            "no_acl",
            "parallel_restore",
            "min_tables",
        ),
        "fraisier:fraisier/dbops/restore.py:195",
        "1.14.0",
    ),
    CallShape(
        "fraisier",
        "confiture.core.restorer:DatabaseRestorer",
        (),
        "fraisier:fraisier/dbops/restore.py:237",
        "1.14.0",
    ),
    CallShape(
        "fraisier",
        "confiture.core.restorer:DatabaseRestorer.restore",
        ("options",),
        "fraisier:fraisier/dbops/restore.py:237",
        "1.14.0",
    ),
    CallShape(
        "fraisier",
        "confiture.core.view_manager:ViewManager",
        ("connection",),
        f"{_FRAISIER_DBOPS}:327",
        "1.14.0",
    ),
    CallShape(
        "fraisier",
        "confiture.core.view_manager:ViewManager.helpers_installed",
        (),
        f"{_FRAISIER_DBOPS}:329",
        "1.14.0",
    ),
    CallShape(
        "fraisier",
        "confiture.core.view_manager:ViewManager.install_helpers",
        (),
        f"{_FRAISIER_DBOPS}:330",
        "1.14.0",
    ),
    CallShape(
        "printoptim",
        "confiture:Migrator.from_config",
        ("config", "migrations_dir"),
        f"{_PRINTOPTIM_RUNNER}:81",
        "1.14.0",
    ),
    CallShape(
        "printoptim",
        "confiture.core._migrator.session:MigratorSession.up",
        ("dry_run",),
        f"{_PRINTOPTIM_RUNNER}:142",
        "1.14.0",
    ),
    CallShape(
        "printoptim",
        "confiture.core._migrator.session:MigratorSession.down",
        ("steps",),
        f"{_PRINTOPTIM_RUNNER}:178",
        "1.14.0",
    ),
    CallShape(
        "printoptim",
        "confiture.core._migrator.session:MigratorSession.reinit",
        ("through",),
        f"{_PRINTOPTIM_RUNNER}:219",
        "1.14.0",
    ),
    CallShape(
        "printoptim",
        "confiture.models.migration:Migration.execute",
        ("sql", "params"),
        "printoptim:db/migrations/*.py (self.execute)",
        "1.14.0",
    ),
    CallShape(
        "printoptim",
        "confiture.core.builder:SchemaBuilder",
        ("env", "project_dir"),
        f"{_PRINTOPTIM_SETUP}:106",
        "1.14.0",
    ),
    CallShape(
        "printoptim",
        "confiture.core.builder:SchemaBuilder.build",
        (),
        f"{_PRINTOPTIM_SETUP}:110",
        "1.14.0",
    ),
    CallShape(
        "printoptim",
        "confiture.core.test_db:TestDbProvisioner",
        ("server_url",),
        f"{_PRINTOPTIM_SETUP}:94",
        "1.14.0",
    ),
    CallShape(
        "printoptim",
        "confiture.core.test_db:TestDbProvisioner.ensure_template",
        ("template", "schema_hash", "schema_sql"),
        f"{_PRINTOPTIM_SETUP}:107",
        "1.14.0",
    ),
    CallShape(
        "printoptim",
        "confiture.core.test_db:TestDbProvisioner.tablespace_usable",
        ("name",),
        f"{_PRINTOPTIM_SETUP}:113",
        "1.14.0",
    ),
    CallShape(
        "printoptim",
        "confiture.core.test_db:TestDbProvisioner.drop",
        ("target", "force"),
        f"{_PRINTOPTIM_SETUP}:118",
        "1.14.0",
    ),
    CallShape(
        "printoptim",
        "confiture.core.test_db:TestDbProvisioner.clone",
        ("template", "target", "tablespace"),
        f"{_PRINTOPTIM_SETUP}:119",
        "1.14.0",
    ),
    CallShape(
        "printoptim",
        "confiture.testing.worker_db:resolve_worker_db_name",
        ("base",),
        "printoptim:tests/conftest.py:31",
        "1.14.0",
    ),
    CallShape(
        "printoptim",
        "confiture.testing.worker_db:is_ci",
        (),
        f"{_PRINTOPTIM_SETUP}:97",
        "1.14.0",
    ),
)

MEMBERS: tuple[Members, ...] = (
    Members(
        "fraisier",
        "confiture:MigrateUpResult",
        ("migrations_applied",),
        f"{_FRAISIER_DBOPS}:533",
        "1.14.0",
    ),
    # fraiseql/fraisier#417: a run that did not complete is named, not dropped —
    # `_incomplete_reason` branches on `success` (pinned since 1.14.0) and reads
    # the summary, the halted migration and what is left.
    Members(
        "fraisier",
        "confiture:MigrateUpResult",
        ("success", "error_summary", "skipped_superuser", "pending"),
        f"{_FRAISIER_DBOPS}:299",
        "1.24.0",
    ),
    Members(
        "fraisier",
        "confiture.models.results:SkippedMigration",
        ("version", "name", "reason"),
        f"{_FRAISIER_DBOPS}:299",
        "1.24.0",
    ),
    Members(
        "fraisier",
        "confiture:MigrateDownResult",
        ("success", "migrations_rolled_back"),
        f"{_FRAISIER_DBOPS}:545",
        "1.14.0",
    ),
    Members(
        "fraisier",
        "confiture.models.results:StatusResult",
        ("applied", "pending", "has_pending"),
        "fraisier:fraisier/strategies/_confiture.py:76",
        "1.14.0",
    ),
    # `migration_runner.py:145` also reads `MigrateUpResult.error`, which no
    # confiture release has declared (the field is `errors`); that is a defect
    # in the consumer, reported there, and deliberately not pinned here.
    Members(
        "printoptim",
        "confiture:MigrateUpResult",
        ("success", "errors", "migrations_applied"),
        f"{_PRINTOPTIM_RUNNER}:153",
        "1.14.0",
    ),
    Members(
        "printoptim",
        "confiture:MigrateDownResult",
        ("success", "error", "migrations_rolled_back"),
        f"{_PRINTOPTIM_RUNNER}:189",
        "1.14.0",
    ),
    Members(
        "printoptim",
        "confiture.models.results:MigrateReinitResult",
        ("success", "error", "migrations_marked"),
        f"{_PRINTOPTIM_RUNNER}:231",
        "1.14.0",
    ),
    Members(
        "printoptim",
        "confiture.models.results:StatusResult",
        ("migrations",),
        f"{_PRINTOPTIM_RUNNER}:103",
        "1.14.0",
    ),
    Members(
        "printoptim",
        "confiture.models.results:MigrationInfo",
        ("version", "name", "status"),
        f"{_PRINTOPTIM_RUNNER}:103",
        "1.14.0",
    ),
    # A printoptim migration is a subclass declaring `version` and `name` and
    # overriding `up`/`down`, calling `self.execute`.
    Members(
        "printoptim",
        "confiture.models.migration:Migration",
        ("version", "name", "up", "down", "execute"),
        "printoptim:pyproject.toml:31",
        "1.14.0",
    ),
)


def _resolve(target: str) -> Any:
    """``module:Attr.member`` → the object, walking attributes after the import."""
    module_name, _, path = target.partition(":")
    obj: Any = importlib.import_module(module_name)
    for part in path.split("."):
        obj = getattr(obj, part)
    return obj


def _row_id(row: NamedTuple) -> str:
    return f"{row[0]}:{row[1]}{'.' + row[2] if isinstance(row, Symbol) else ''}"


@pytest.mark.parametrize("row", FRAISIER_SYMBOLS + PRINTOPTIM_SYMBOLS, ids=_row_id)
def test_consumer_symbol_is_importable_by_name(row: Symbol) -> None:
    """Every symbol a consumer imports still exists where the consumer looks."""
    module = importlib.import_module(row.module)
    assert hasattr(module, row.attribute), (
        f"{row.module}.{row.attribute} is gone — {row.consumer} imports it at {row.source}"
    )


def _narrowing(signature: inspect.Signature, passes: tuple[str, ...]) -> list[str]:
    """Every way *signature* no longer accepts a call supplying exactly *passes*."""
    params = [p for p in signature.parameters.values() if p.name not in {"self", "cls"}]
    names = {p.name for p in params}
    takes_kwargs = any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params)
    problems = [
        f"parameter {name!r} is gone" for name in passes if name not in names and not takes_kwargs
    ]
    problems.extend(
        f"parameter {p.name!r} is now required and the consumer does not pass it"
        for p in params
        if p.default is inspect.Parameter.empty
        and p.kind not in {inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD}
        and p.name not in passes
    )
    return problems


@pytest.mark.parametrize("row", CALL_SHAPES, ids=lambda r: f"{r.consumer}:{r.target}")
def test_consumer_call_shape_has_not_narrowed(row: CallShape) -> None:
    """The parameters a consumer passes are still accepted, and nothing new is required."""
    target = _resolve(row.target)
    assert callable(target), f"{row.target} is no longer callable ({row.source})"
    problems = _narrowing(inspect.signature(target), row.passes)
    assert not problems, (
        f"{row.target} narrowed for {row.consumer} ({row.source}): {'; '.join(problems)}"
    )


def _has_member(cls: type, name: str) -> bool:
    if dataclasses.is_dataclass(cls) and name in {f.name for f in dataclasses.fields(cls)}:
        return True
    annotations = inspect.get_annotations(cls)
    return name in annotations or hasattr(cls, name)


@pytest.mark.parametrize("row", MEMBERS, ids=lambda r: f"{r.consumer}:{r.target}")
def test_consumer_reads_members_that_exist(row: Members) -> None:
    """The fields and methods a consumer reads off a result are still declared."""
    cls = _resolve(row.target)
    missing = [name for name in row.names if not _has_member(cls, name)]
    assert not missing, f"{row.target} lost {missing} — {row.consumer} reads them at {row.source}"


def test_narrowing_detects_each_breaking_change() -> None:
    """The narrowing rule is seen red on each shape it exists to catch."""

    def before(env, project_dir=None): ...
    def dropped(env): ...
    def now_required(env, project_dir): ...
    def new_required(env, project_dir=None, *, mode): ...
    def widened(env, project_dir=None, *, mode="x"): ...

    passes = ("env",)
    assert _narrowing(inspect.signature(before), passes) == []
    assert _narrowing(inspect.signature(widened), passes) == []
    assert _narrowing(inspect.signature(dropped), ("env", "project_dir"))
    assert _narrowing(inspect.signature(now_required), passes)
    assert _narrowing(inspect.signature(new_required), passes)
