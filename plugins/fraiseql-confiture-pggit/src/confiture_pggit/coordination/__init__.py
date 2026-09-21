"""Multi-agent coordination module for pgGit.

Enables multiple agents/developers to work in parallel with automatic
conflict detection and coordination.

Usage:
    from confiture_pggit.coordination import (
        IntentRegistry,
        Intent,
        ConflictReport,
        IntentStatus,
    )

    registry = IntentRegistry(connection)
    intent = registry.register(
        agent_id="claude-payments",
        feature_name="stripe_integration",
        schema_changes=["ALTER TABLE users ADD COLUMN stripe_id TEXT"],
        tables_affected=["users"],
    )

    # Check for conflicts
    conflicts = registry.get_conflicts(intent.id)
    for conflict in conflicts:
        print(f"Conflict detected: {conflict.conflict_type}")
"""

from confiture_pggit.coordination.detector import ConflictDetector
from confiture_pggit.coordination.models import (
    ConflictReport,
    ConflictSeverity,
    ConflictType,
    Intent,
    IntentStatus,
    IntentStatusChange,
    RiskLevel,
)
from confiture_pggit.coordination.registry import IntentRegistry

__all__ = [
    # Detector
    "ConflictDetector",
    "ConflictReport",
    "ConflictSeverity",
    "ConflictType",
    # Models
    "Intent",
    # Registry
    "IntentRegistry",
    "IntentStatus",
    "IntentStatusChange",
    "RiskLevel",
]
