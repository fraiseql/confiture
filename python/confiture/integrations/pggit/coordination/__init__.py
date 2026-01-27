"""Multi-agent coordination module for pgGit.

Enables multiple agents/developers to work in parallel with automatic
conflict detection and coordination.

Usage:
    from confiture.integrations.pggit.coordination import (
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

from confiture.integrations.pggit.coordination.detector import ConflictDetector
from confiture.integrations.pggit.coordination.models import (
    ConflictReport,
    ConflictSeverity,
    ConflictType,
    Intent,
    IntentStatus,
    IntentStatusChange,
    RiskLevel,
)
from confiture.integrations.pggit.coordination.registry import IntentRegistry

__all__ = [
    # Models
    "Intent",
    "ConflictReport",
    "IntentStatus",
    "IntentStatusChange",
    "ConflictType",
    "ConflictSeverity",
    "RiskLevel",
    # Detector
    "ConflictDetector",
    # Registry
    "IntentRegistry",
]
