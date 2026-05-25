"""Models for the preflight dependent-objects check.

A `CorTarget` is a CREATE OR REPLACE statement in a pending migration that
the dependent-objects checker will resolve against the live preflight DB.
A `DependentObject` is a live object that depends on the target. A
`DependentEntry` groups a target with the dependents it has; the
`DependentAnalysisReport` is the aggregate result.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class CorTarget:
    """A CREATE OR REPLACE target extracted from a pending migration.

    Attributes:
        kind: ``"view"``, ``"matview"``, ``"function"``, or ``"procedure"``.
        schema: Schema name (defaults to ``"public"`` when not qualified).
        name: Object name.
        source_file: Migration file path (``.sql`` or ``.py``).
        source_line: Line within ``source_file`` where the statement was
            extracted (None for SQL when not tracked).
    """

    kind: str
    schema: str
    name: str
    source_file: Path | None
    source_line: int | None

    @property
    def qualified(self) -> str:
        return f"{self.schema}.{self.name}"


@dataclass(frozen=True)
class DependentObject:
    """A live object that depends on a CoR target."""

    kind: str
    schema: str
    name: str
    referenced_columns: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "schema": self.schema,
            "name": self.name,
            "referenced_columns": list(self.referenced_columns),
        }


@dataclass
class DependentEntry:
    """One CoR target plus the live dependents it has."""

    target: CorTarget
    dependents: list[DependentObject]
    severity: str = "error"

    def is_blocking(self) -> bool:
        """True if this entry should fail the gate.

        An entry is blocking when it has at least one dependent AND its
        severity is ``"error"``. ``severity == "info"`` (--check-dependents=warn)
        never fails the gate; severity stays info, only the gate's reaction
        shifts.
        """
        return self.severity == "error" and bool(self.dependents)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.target.kind,
            "schema": self.target.schema,
            "name": self.target.name,
            "qualified": self.target.qualified,
            "source_file": str(self.target.source_file) if self.target.source_file else None,
            "source_line": self.target.source_line,
            "severity": self.severity,
            "dependents": [d.to_dict() for d in self.dependents],
        }


@dataclass
class DependentAnalysisReport:
    """Aggregate result of the dependent-objects checker.

    Attributes:
        entries: One per CoR target found in the pending migrations.
        status: ``"ok"`` if the check ran, ``"skipped"`` if it could not
            (no preflight DB, or pglast not installed).
        skip_reason: Machine-readable identifier for the skip cause when
            ``status == "skipped"``.
    """

    entries: list[DependentEntry]
    status: str = "ok"
    skip_reason: str | None = None
    extras: dict[str, Any] = field(default_factory=dict)

    def has_blocking(self) -> bool:
        return any(e.is_blocking() for e in self.entries)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "status": self.status,
            "entries": [e.to_dict() for e in self.entries],
            "has_blocking": self.has_blocking(),
        }
        if self.skip_reason is not None:
            payload["skip_reason"] = self.skip_reason
        if self.extras:
            payload.update(self.extras)
        return payload
