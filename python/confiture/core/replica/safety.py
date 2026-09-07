"""Replica-safety verdicts for classified DDL operations (issue #139).

Maps each :class:`DdlOperation` to a forward-compatibility verdict under
streaming replication, with the exact multi-step remediation when unsafe. The
verdict table is the single source the rule, the preflight surface, and the docs
all read from — no copy-paste between code and the "why replicas need this" guide.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from confiture.core.replica.classifier import (
    AddColumn,
    AddConstraint,
    AddEnumValue,
    Benign,
    ChangeColumnType,
    CreateIndex,
    CreateTable,
    DdlOperation,
    DropColumn,
    DropObject,
    DropTable,
    Other,
    RenameColumn,
    RenameObject,
    ReplaceObject,
    Revoke,
    SetNotNull,
    Truncate,
)

# Severity policy threshold: replicas declared → unsafe ops are errors.
# (Pure policy; see replica_severity below.)


@dataclass(frozen=True)
class ReplicaVerdict:
    """The replica-safety verdict for a single operation."""

    safety: str  # "safe" | "unsafe" | "depends"
    reason: str | None = None
    multi_step: str | None = None


def _add_column(op: Any) -> ReplicaVerdict:
    if op.nullable and not op.has_default:
        return ReplicaVerdict("safe")
    return ReplicaVerdict(
        "unsafe",
        reason="NOT NULL and/or DEFAULT breaks readers still on the old schema",
        multi_step="add the column nullable → backfill → SET NOT NULL in a later release",
    )


def _add_constraint(op: Any) -> ReplicaVerdict:
    if op.not_valid:
        return ReplicaVerdict("safe")
    return ReplicaVerdict(
        "unsafe",
        reason="immediate validation locks and may reject existing rows",
        multi_step="ADD CONSTRAINT ... NOT VALID → backfill → VALIDATE CONSTRAINT later",
    )


def _create_index(op: Any) -> ReplicaVerdict:
    if op.concurrently:
        return ReplicaVerdict("safe")
    return ReplicaVerdict(
        "unsafe",
        reason="a non-concurrent index blocks writes; the lock propagates to replicas",
        multi_step="use CREATE INDEX CONCURRENTLY in its own non-transactional migration",
    )


def _unsafe(reason: str, multi_step: str) -> Callable[[Any], ReplicaVerdict]:
    return lambda _op: ReplicaVerdict("unsafe", reason=reason, multi_step=multi_step)


def _drop_object(op: Any) -> ReplicaVerdict:
    return ReplicaVerdict(
        "unsafe",
        reason=f"readers on the old version still reference the {op.kind or 'object'}",
        multi_step=f"stop using the {op.kind or 'object'} → wait one release → drop it",
    )


def _rename_object(op: Any) -> ReplicaVerdict:
    return ReplicaVerdict(
        "unsafe",
        reason=f"readers reference the old {op.kind or 'object'} name during the lag window",
        multi_step="add the new name → migrate readers → retire the old name",
    )


def _replace_object(op: Any) -> ReplicaVerdict:
    # A replacement body can be identical, additive, or a signature change;
    # nothing in the statement says which, so this is `depends` (a warning)
    # rather than a guess in either direction.
    return ReplicaVerdict(
        "depends",
        reason=(
            f"CREATE OR REPLACE {op.kind or 'object'}: confiture cannot tell whether the "
            "new definition stays compatible with readers on the old version; review manually"
        ),
    )


def _other(op: Any) -> ReplicaVerdict:
    return ReplicaVerdict(
        "depends",
        reason=f"could not classify ({op.reason or 'unrecognized'}); review manually",
    )


# Operation type → verdict, in the order the classifier tries them.
_VERDICTS: tuple[tuple[type, Callable[[Any], ReplicaVerdict]], ...] = (
    (AddColumn, _add_column),
    (
        DropColumn,
        _unsafe(
            "readers on the old schema still SELECT the column",
            "deprecate (stop using) → wait one release → drop the column",
        ),
    ),
    (
        RenameColumn,
        _unsafe(
            "readers reference the old column name during the lag window",
            "add the new column → dual-write → migrate readers → drop the old column",
        ),
    ),
    (
        ChangeColumnType,
        _unsafe(
            "readers on the old type break when the column type changes",
            "add a new column → backfill → swap readers → drop the old column",
        ),
    ),
    (AddConstraint, _add_constraint),
    (CreateIndex, _create_index),
    (CreateTable, lambda _op: ReplicaVerdict("safe")),
    (
        DropTable,
        _unsafe(
            "readers on the old version still SELECT from the table",
            "stop reading the table → wait one release → drop it",
        ),
    ),
    (DropObject, _drop_object),
    (
        Truncate,
        _unsafe(
            "the rows readers on the old version expect are removed",
            "stop reading the table → wait one release → truncate it",
        ),
    ),
    (
        Revoke,
        _unsafe(
            "a privilege readers on the old version still rely on may be withdrawn",
            "migrate readers off the privilege → wait one release → revoke it",
        ),
    ),
    (
        SetNotNull,
        _unsafe(
            "writers on the old version still insert NULL into the column",
            "backfill → migrate writers → SET NOT NULL in a later release",
        ),
    ),
    (RenameObject, _rename_object),
    (ReplaceObject, _replace_object),
    (AddEnumValue, lambda _op: ReplicaVerdict("safe")),
    (Benign, lambda _op: ReplicaVerdict("safe")),
    (Other, _other),
)


def classify_replica_safety(op: DdlOperation) -> ReplicaVerdict:
    """Verdict for one operation, per the issue's replica-safety matrix.

    The lag window is the crux: a replica serving reads on the *old* schema
    while the primary already has the *new* one. ``ADD COLUMN NOT NULL`` /
    ``DEFAULT`` stays unsafe regardless of PG's fast-default optimization
    (OD-13) — a reader on the old schema still errors on the new column.
    """
    for op_type, verdict in _VERDICTS:
        if isinstance(op, op_type):
            return verdict(op)
    return ReplicaVerdict("depends", reason="unclassified operation; review manually")


def replica_severity(verdict: ReplicaVerdict, *, has_replicas: bool, bypass: bool) -> str:
    """Severity an unsafe verdict should carry, per OD-12 (owner-accepted).

    Precedence: ``bypass`` always wins (downgrade to warning); otherwise replicas
    being declared decides error-vs-warning. ``depends`` is always a warning
    (never a hard block on SQL the parser couldn't classify).

    Returns one of "error" | "warning".
    """
    if verdict.safety == "depends":
        return "warning"
    if bypass:
        return "warning"
    return "error" if has_replicas else "warning"
