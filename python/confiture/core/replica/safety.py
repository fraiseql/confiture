"""Replica-safety verdicts for classified DDL operations (issue #139).

Maps each :class:`DdlOperation` to a forward-compatibility verdict under
streaming replication, with the exact multi-step remediation when unsafe. The
verdict table is the single source the rule, the preflight surface, and the docs
all read from — no copy-paste between code and the "why replicas need this" guide.
"""

from __future__ import annotations

from dataclasses import dataclass

from confiture.core.replica.classifier import (
    AddColumn,
    AddConstraint,
    ChangeColumnType,
    CreateIndex,
    CreateTable,
    DdlOperation,
    DropColumn,
    Other,
    RenameColumn,
)

# Severity policy threshold: replicas declared → unsafe ops are errors.
# (Pure policy; see replica_severity below.)


@dataclass(frozen=True)
class ReplicaVerdict:
    """The replica-safety verdict for a single operation."""

    safety: str  # "safe" | "unsafe" | "depends"
    reason: str | None = None
    multi_step: str | None = None


def classify_replica_safety(op: DdlOperation) -> ReplicaVerdict:
    """Verdict for one operation, per the issue's replica-safety matrix.

    The lag window is the crux: a replica serving reads on the *old* schema
    while the primary already has the *new* one. ``ADD COLUMN NOT NULL`` /
    ``DEFAULT`` stays unsafe regardless of PG's fast-default optimization
    (OD-13) — a reader on the old schema still errors on the new column.
    """
    if isinstance(op, AddColumn):
        if op.nullable and not op.has_default:
            return ReplicaVerdict("safe")
        return ReplicaVerdict(
            "unsafe",
            reason="NOT NULL and/or DEFAULT breaks readers still on the old schema",
            multi_step="add the column nullable → backfill → SET NOT NULL in a later release",
        )
    if isinstance(op, DropColumn):
        return ReplicaVerdict(
            "unsafe",
            reason="readers on the old schema still SELECT the column",
            multi_step="deprecate (stop using) → wait one release → drop the column",
        )
    if isinstance(op, RenameColumn):
        return ReplicaVerdict(
            "unsafe",
            reason="readers reference the old column name during the lag window",
            multi_step="add the new column → dual-write → migrate readers → drop the old column",
        )
    if isinstance(op, ChangeColumnType):
        return ReplicaVerdict(
            "unsafe",
            reason="readers on the old type break when the column type changes",
            multi_step="add a new column → backfill → swap readers → drop the old column",
        )
    if isinstance(op, AddConstraint):
        if op.not_valid:
            return ReplicaVerdict("safe")
        return ReplicaVerdict(
            "unsafe",
            reason="immediate validation locks and may reject existing rows",
            multi_step="ADD CONSTRAINT ... NOT VALID → backfill → VALIDATE CONSTRAINT later",
        )
    if isinstance(op, CreateIndex):
        if op.concurrently:
            return ReplicaVerdict("safe")
        return ReplicaVerdict(
            "unsafe",
            reason="a non-concurrent index blocks writes; the lock propagates to replicas",
            multi_step="use CREATE INDEX CONCURRENTLY in its own non-transactional migration",
        )
    if isinstance(op, CreateTable):
        return ReplicaVerdict("safe")
    if isinstance(op, Other):
        return ReplicaVerdict(
            "depends",
            reason=f"could not classify ({op.reason or 'unrecognized'}); review manually",
        )
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
