"""Tests for the replica-safety verdict matrix + policy (issue #139, Phase 2/3)."""

from __future__ import annotations

import pytest

from confiture.core.replica.classifier import (
    AddColumn,
    AddConstraint,
    ChangeColumnType,
    CreateIndex,
    CreateTable,
    DropColumn,
    Other,
    RenameColumn,
)
from confiture.core.replica.safety import (
    ReplicaVerdict,
    classify_replica_safety,
    replica_severity,
)

_MATRIX = [
    (AddColumn(nullable=True, has_default=False), "safe"),
    (AddColumn(nullable=False, has_default=True), "unsafe"),
    (AddColumn(nullable=True, has_default=True), "unsafe"),
    (DropColumn(), "unsafe"),
    (RenameColumn(), "unsafe"),
    (ChangeColumnType(), "unsafe"),
    (AddConstraint(kind="check", not_valid=False), "unsafe"),
    (AddConstraint(kind="check", not_valid=True), "safe"),
    (CreateIndex(concurrently=False), "unsafe"),
    (CreateIndex(concurrently=True), "safe"),
    (CreateTable(), "safe"),
    (Other(reason="dynamic"), "depends"),
]


@pytest.mark.parametrize(("op", "safety"), _MATRIX)
def test_matrix(op, safety: str) -> None:
    assert classify_replica_safety(op).safety == safety


@pytest.mark.parametrize(("op", "safety"), [(o, s) for o, s in _MATRIX if s == "unsafe"])
def test_unsafe_ops_carry_multi_step(op, safety: str) -> None:
    assert classify_replica_safety(op).multi_step  # remediation text present


def test_verdict_is_dataclass() -> None:
    v = ReplicaVerdict("safe")
    assert v.reason is None and v.multi_step is None


# ── severity policy (OD-12) ───────────────────────────────────────────────────


def test_severity_warns_by_default_no_replicas() -> None:
    v = classify_replica_safety(DropColumn())
    assert replica_severity(v, has_replicas=False, bypass=False) == "warning"


def test_severity_errors_when_replicas_declared() -> None:
    v = classify_replica_safety(DropColumn())
    assert replica_severity(v, has_replicas=True, bypass=False) == "error"


def test_bypass_downgrades_even_with_replicas() -> None:
    v = classify_replica_safety(DropColumn())
    assert replica_severity(v, has_replicas=True, bypass=True) == "warning"


def test_depends_is_always_warning() -> None:
    v = classify_replica_safety(Other(reason="dynamic"))
    assert replica_severity(v, has_replicas=True, bypass=False) == "warning"
