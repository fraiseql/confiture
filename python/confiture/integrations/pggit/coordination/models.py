"""Data models for multi-agent coordination.

This module defines the core data structures for tracking agent intents,
conflicts, and coordination state.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any
from uuid import uuid4


class IntentStatus(Enum):
    """Status of a registered intent."""

    REGISTERED = "registered"  # Intent declared, not started
    IN_PROGRESS = "in_progress"  # Agent is working on it
    COMPLETED = "completed"  # Changes committed
    MERGED = "merged"  # Merged to main
    ABANDONED = "abandoned"  # Agent gave up
    CONFLICTED = "conflicted"  # Conflicts detected


class ConflictType(Enum):
    """Type of conflict detected."""

    TABLE = "table"  # Same table affected
    COLUMN = "column"  # Same column modification
    CONSTRAINT = "constraint"  # Constraint conflict
    FUNCTION = "function"  # Function conflict
    INDEX = "index"  # Index conflict
    TIMING = "timing"  # Temporal ordering issue
    DEPENDENCY = "dependency"  # Dependency conflict


class ConflictSeverity(Enum):
    """Severity level of a conflict."""

    WARNING = "warning"  # Can proceed with coordination
    ERROR = "error"  # Should not proceed


class RiskLevel(Enum):
    """Risk level assessment for an intent."""

    LOW = "low"  # Isolated changes, safe
    MEDIUM = "medium"  # Some coordination needed
    HIGH = "high"  # Complex changes, careful planning needed


@dataclass
class Intent:
    """Represents an agent's intention to make schema changes.

    Attributes:
        id: Unique identifier for this intent (UUID)
        agent_id: Identifier for the agent (e.g., "claude-payments")
        feature_name: Human-readable feature name (e.g., "stripe_integration")
        branch_name: Allocated pgGit branch name
        schema_changes: List of planned DDL statements
        tables_affected: Set of table names that will be modified
        estimated_duration_ms: Estimated time to complete in milliseconds
        risk_level: Assessment of change risk (LOW, MEDIUM, HIGH)
        status: Current status of the intent
        created_at: When the intent was registered
        updated_at: When the intent was last updated
        conflicts_with: List of intent IDs this conflicts with
        metadata: Custom metadata dict for agent-specific data
    """

    id: str = field(default_factory=lambda: str(uuid4()))
    agent_id: str = ""
    feature_name: str = ""
    branch_name: str = ""
    schema_changes: list[str] = field(default_factory=list)
    tables_affected: list[str] = field(default_factory=list)
    estimated_duration_ms: int = 0
    risk_level: RiskLevel = RiskLevel.LOW
    status: IntentStatus = IntentStatus.REGISTERED
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    conflicts_with: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "id": self.id,
            "agent_id": self.agent_id,
            "feature_name": self.feature_name,
            "branch_name": self.branch_name,
            "schema_changes": self.schema_changes,
            "tables_affected": self.tables_affected,
            "estimated_duration_ms": self.estimated_duration_ms,
            "risk_level": self.risk_level.value if isinstance(self.risk_level, RiskLevel) else self.risk_level,
            "status": self.status.value if isinstance(self.status, IntentStatus) else self.status,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "conflicts_with": self.conflicts_with,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Intent:
        """Create Intent from dictionary."""
        return cls(
            id=data.get("id", str(uuid4())),
            agent_id=data.get("agent_id", ""),
            feature_name=data.get("feature_name", ""),
            branch_name=data.get("branch_name", ""),
            schema_changes=data.get("schema_changes", []),
            tables_affected=data.get("tables_affected", []),
            estimated_duration_ms=data.get("estimated_duration_ms", 0),
            risk_level=RiskLevel[data.get("risk_level", "LOW").upper()] if isinstance(data.get("risk_level"), str) else data.get("risk_level", RiskLevel.LOW),
            status=IntentStatus[data.get("status", "REGISTERED").upper()] if isinstance(data.get("status"), str) else data.get("status", IntentStatus.REGISTERED),
            created_at=datetime.fromisoformat(data.get("created_at")) if isinstance(data.get("created_at"), str) else data.get("created_at", datetime.now()),
            updated_at=datetime.fromisoformat(data.get("updated_at")) if isinstance(data.get("updated_at"), str) else data.get("updated_at", datetime.now()),
            conflicts_with=data.get("conflicts_with", []),
            metadata=data.get("metadata", {}),
        )


@dataclass
class ConflictReport:
    """Details of a detected conflict between intents.

    Attributes:
        id: Unique identifier for this conflict record
        intent_a: ID of the first intent
        intent_b: ID of the second intent
        conflict_type: Type of conflict (TABLE, COLUMN, etc.)
        affected_objects: List of conflicting objects (table names, columns, etc.)
        severity: How serious is this conflict (WARNING, ERROR)
        resolution_suggestions: List of suggestions for resolving
        reviewed: Whether the conflict has been reviewed
        reviewed_at: When the conflict was reviewed
        resolution_notes: Notes on how conflict was resolved
        created_at: When the conflict was detected
    """

    id: int = 0
    intent_a: str = ""
    intent_b: str = ""
    conflict_type: ConflictType = ConflictType.TABLE
    affected_objects: list[str] = field(default_factory=list)
    severity: ConflictSeverity = ConflictSeverity.WARNING
    resolution_suggestions: list[str] = field(default_factory=list)
    reviewed: bool = False
    reviewed_at: datetime | None = None
    resolution_notes: str = ""
    created_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "id": self.id,
            "intent_a": self.intent_a,
            "intent_b": self.intent_b,
            "conflict_type": self.conflict_type.value if isinstance(self.conflict_type, ConflictType) else self.conflict_type,
            "affected_objects": self.affected_objects,
            "severity": self.severity.value if isinstance(self.severity, ConflictSeverity) else self.severity,
            "resolution_suggestions": self.resolution_suggestions,
            "reviewed": self.reviewed,
            "reviewed_at": self.reviewed_at.isoformat() if self.reviewed_at else None,
            "resolution_notes": self.resolution_notes,
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ConflictReport:
        """Create ConflictReport from dictionary."""
        return cls(
            id=data.get("id", 0),
            intent_a=data.get("intent_a", ""),
            intent_b=data.get("intent_b", ""),
            conflict_type=ConflictType[data.get("conflict_type", "TABLE").upper()] if isinstance(data.get("conflict_type"), str) else data.get("conflict_type", ConflictType.TABLE),
            affected_objects=data.get("affected_objects", []),
            severity=ConflictSeverity[data.get("severity", "WARNING").upper()] if isinstance(data.get("severity"), str) else data.get("severity", ConflictSeverity.WARNING),
            resolution_suggestions=data.get("resolution_suggestions", []),
            reviewed=data.get("reviewed", False),
            reviewed_at=datetime.fromisoformat(data.get("reviewed_at")) if isinstance(data.get("reviewed_at"), str) else data.get("reviewed_at"),
            resolution_notes=data.get("resolution_notes", ""),
            created_at=datetime.fromisoformat(data.get("created_at")) if isinstance(data.get("created_at"), str) else data.get("created_at", datetime.now()),
        )


@dataclass
class IntentStatusChange:
    """Record of an intent status change for history/audit.

    Attributes:
        intent_id: ID of the intent that changed
        old_status: Previous status
        new_status: New status
        reason: Why the status changed
        changed_by: Who/what made the change
        changed_at: When the change occurred
    """

    intent_id: str
    old_status: IntentStatus | None
    new_status: IntentStatus
    reason: str = ""
    changed_by: str = "system"
    changed_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "intent_id": self.intent_id,
            "old_status": self.old_status.value if self.old_status and isinstance(self.old_status, IntentStatus) else self.old_status,
            "new_status": self.new_status.value if isinstance(self.new_status, IntentStatus) else self.new_status,
            "reason": self.reason,
            "changed_by": self.changed_by,
            "changed_at": self.changed_at.isoformat(),
        }
