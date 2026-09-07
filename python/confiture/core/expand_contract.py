"""The expand/contract plan: the classifier's online advice as explicit, costed stages.

The replica classifier (``core/replica``) tells an operator *that* a change
should run in steps — "add the column nullable → backfill → SET NOT NULL".
This module turns that advice into a :class:`StagedPlan` the runner can
drive: an ``expand`` stage of lock-cheap DDL, a ``backfill`` stage with a
batch spec, and a ``contract`` stage that finishes the change. Every stage
carries the lock profile of its statements (from the one table in
``core/lock_profile.py``) and the longest ACCESS EXCLUSIVE hold it takes —
the number an online run is measured by.

Three patterns, one per advisory:

* **add_not_null_column** — ``ADD COLUMN … NOT NULL DEFAULT …``: add it
  nullable with the default, add ``CHECK (col IS NOT NULL) NOT VALID``,
  backfill the NULLs, ``VALIDATE`` (no exclusive lock), ``SET NOT NULL``
  (metadata-only once a validated check exists, PostgreSQL ≥ 12), drop the
  check.
* **add_constraint_not_valid** — ``ADD CONSTRAINT … CHECK/FOREIGN KEY``:
  add it ``NOT VALID``, then ``VALIDATE``.
* **replace_column** — ``ALTER COLUMN … TYPE``: add a new column of the new
  type, dual-write through a trigger, backfill, swap the names, drop the old
  column (destructive: the contract stage is gated).

``plan`` is pure: text and a server version in, plans out, nothing touched.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from confiture.core.lock_profile import Duration, LockLevel, LockProfile, profile_for_kind
from confiture.core.replica.classifier import (
    AddColumn,
    AddConstraint,
    ChangeColumnType,
    DdlOperation,
    OperationClassifier,
)

StageName = Literal["expand", "backfill", "contract"]
Pattern = Literal["add_not_null_column", "add_constraint_not_valid", "replace_column"]

_LOCK_ORDER: dict[LockLevel, int] = {level: index for index, level in enumerate(LockLevel)}
_BACKFILL_PROFILE = LockProfile(
    lock=LockLevel.NONE,
    rewrites_table=False,
    blocks_reads=False,
    blocks_writes=False,
    duration=Duration.MINUTES_PLUS,
    note="row locks, one batch at a time",
)
_NOT_VALID_KINDS = frozenset({"check", "foreign_key"})


@dataclass(frozen=True)
class BackfillSpec:
    """What the backfill stage updates: ``UPDATE table SET column = expression WHERE where_clause``."""

    table: str
    column: str
    expression: str
    where_clause: str

    def to_dict(self) -> dict[str, str]:
        return {
            "table": self.table,
            "column": self.column,
            "expression": self.expression,
            "where_clause": self.where_clause,
        }


@dataclass(frozen=True)
class Stage:
    """One stage of a plan: its statements and what they cost."""

    name: StageName
    statements: tuple[str, ...]
    profiles: tuple[LockProfile, ...]
    backfill: BackfillSpec | None = None
    destructive: bool = False

    @property
    def lock(self) -> LockLevel:
        """The strongest lock any statement of the stage takes."""
        return max(
            (p.lock for p in self.profiles), key=_LOCK_ORDER.__getitem__, default=LockLevel.NONE
        )

    @property
    def duration(self) -> Duration:
        """The longest any statement of the stage runs."""
        return max((p.duration for p in self.profiles), default=Duration.METADATA)

    @property
    def exclusive_hold(self) -> Duration | None:
        """The longest ACCESS EXCLUSIVE hold in the stage, or ``None`` when it takes none."""
        holds = [p.duration for p in self.profiles if p.lock is LockLevel.ACCESS_EXCLUSIVE]
        return max(holds) if holds else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.name,
            "statements": list(self.statements),
            "lock": self.lock.value,
            "duration": self.duration.value,
            "exclusive_hold": None if self.exclusive_hold is None else self.exclusive_hold.value,
            "backfill": None if self.backfill is None else self.backfill.to_dict(),
            "destructive": self.destructive,
        }


@dataclass(frozen=True)
class StagedPlan:
    """The staged form of one multi-step operation."""

    pattern: Pattern
    table: str
    operation: DdlOperation = field(compare=False)
    stages: tuple[Stage, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "pattern": self.pattern,
            "table": self.table,
            "stages": [stage.to_dict() for stage in self.stages],
        }


def plan(sql: str, *, server_version: int | None = None) -> list[StagedPlan]:
    """The staged plans for every multi-step operation in ``sql``, in statement order.

    An operation the classifier does not mark multi-step — or one the plan
    cannot express (a NOT NULL column without a default has nothing to
    backfill with) — yields no plan; ``[]`` means "apply it the classic way".
    """
    plans: list[StagedPlan] = []
    for op in OperationClassifier().classify(sql):
        staged = _plan_operation(op, server_version)
        if staged is not None:
            plans.append(staged)
    return plans


def _plan_operation(op: DdlOperation, server_version: int | None) -> StagedPlan | None:
    if op.table is None:
        return None
    if isinstance(op, AddColumn) and not op.nullable and op.default_sql and op.column:
        return _add_not_null_column(op, op.table, server_version)
    if (
        isinstance(op, AddConstraint)
        and not op.not_valid
        and op.kind in _NOT_VALID_KINDS
        and op.name
        and op.definition
    ):
        return _add_constraint_not_valid(op, op.table, server_version)
    if isinstance(op, ChangeColumnType) and op.column and op.new_type:
        return _replace_column(op, op.table, server_version)
    return None


def _profile(kind: str, server_version: int | None, **facts: Any) -> LockProfile:
    return profile_for_kind(kind, server_version=server_version, **facts)


def _add_not_null_column(op: AddColumn, table: str, sv: int | None) -> StagedPlan:
    column, check = op.column, f"{table}_{op.column}_not_null"
    expand = Stage(
        "expand",
        (
            f"ALTER TABLE {table} ADD COLUMN {column} {op.type_sql} DEFAULT {op.default_sql}",
            f"ALTER TABLE {table} ADD CONSTRAINT {check} CHECK ({column} IS NOT NULL) NOT VALID",
        ),
        (
            _profile("add_column", sv, has_default=True, nullable=True),
            _profile("add_constraint", sv, not_valid=True),
        ),
    )
    backfill = Stage(
        "backfill",
        (),
        (_BACKFILL_PROFILE,),
        backfill=BackfillSpec(table, str(column), str(op.default_sql), f"{column} IS NULL"),
    )
    contract = Stage(
        "contract",
        (
            f"ALTER TABLE {table} VALIDATE CONSTRAINT {check}",
            f"ALTER TABLE {table} ALTER COLUMN {column} SET NOT NULL",
            f"ALTER TABLE {table} DROP CONSTRAINT {check}",
        ),
        (
            _profile("validate_constraint", sv),
            _profile("set_not_null", sv, proven_by_check=True),
            _profile("drop_constraint", sv),
        ),
    )
    return StagedPlan("add_not_null_column", table, op, (expand, backfill, contract))


def _add_constraint_not_valid(op: AddConstraint, table: str, sv: int | None) -> StagedPlan:
    expand = Stage(
        "expand",
        (f"ALTER TABLE {table} ADD CONSTRAINT {op.name} {op.definition} NOT VALID",),
        (_profile("add_constraint", sv, not_valid=True),),
    )
    contract = Stage(
        "contract",
        (f"ALTER TABLE {table} VALIDATE CONSTRAINT {op.name}",),
        (_profile("validate_constraint", sv),),
    )
    return StagedPlan("add_constraint_not_valid", table, op, (expand, contract))


def _replace_column(op: ChangeColumnType, table: str, sv: int | None) -> StagedPlan:
    column, new, old = op.column, f"{op.column}__new", f"{op.column}__old"
    function = f"{table}_{column}_dual_write"
    expand = Stage(
        "expand",
        (
            f"ALTER TABLE {table} ADD COLUMN {new} {op.new_type}",
            f"CREATE FUNCTION {function}() RETURNS trigger LANGUAGE plpgsql AS "
            f"$$ BEGIN NEW.{new} := NEW.{column}::{op.new_type}; RETURN NEW; END $$",
            f"CREATE TRIGGER {function} BEFORE INSERT OR UPDATE ON {table} "
            f"FOR EACH ROW EXECUTE FUNCTION {function}()",
        ),
        (
            _profile("add_column", sv, has_default=False, nullable=True),
            _profile("create_function", sv),
            _profile("create_trigger", sv),
        ),
    )
    backfill = Stage(
        "backfill",
        (),
        (_BACKFILL_PROFILE,),
        backfill=BackfillSpec(table, new, f"{column}::{op.new_type}", f"{new} IS NULL"),
    )
    contract = Stage(
        "contract",
        (
            f"DROP TRIGGER {function} ON {table}",
            f"DROP FUNCTION {function}()",
            f"ALTER TABLE {table} RENAME COLUMN {column} TO {old}",
            f"ALTER TABLE {table} RENAME COLUMN {new} TO {column}",
            f"ALTER TABLE {table} DROP COLUMN {old}",
        ),
        (
            _profile("drop_trigger", sv),
            _profile("drop_function", sv),
            _profile("rename_column", sv),
            _profile("rename_column", sv),
            _profile("drop_column", sv),
        ),
        destructive=True,
    )
    return StagedPlan("replace_column", table, op, (expand, backfill, contract))
