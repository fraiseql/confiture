"""Intent registry for multi-agent coordination.

Tracks agent intentions and manages conflict detection, branch allocation,
and coordination workflow.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import uuid4

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

if TYPE_CHECKING:
    from psycopg import Connection


class IntentRegistry:
    """Registry for tracking and coordinating agent intents.

    Provides:
    - Intent registration with automatic conflict detection
    - Branch allocation per intent
    - Status tracking with history
    - Conflict detection and resolution
    - Multi-agent coordination

    Example:
        >>> registry = IntentRegistry(connection)
        >>> intent = registry.register(
        ...     agent_id="claude-payments",
        ...     feature_name="stripe_integration",
        ...     schema_changes=["ALTER TABLE users ADD COLUMN stripe_id TEXT"],
        ...     tables_affected=["users"],
        ... )
        >>> conflicts = registry.get_conflicts(intent.id)
        >>> registry.mark_in_progress(intent.id)
    """

    def __init__(self, connection: Connection):
        """Initialize registry with database connection.

        Args:
            connection: PostgreSQL connection (psycopg3)
        """
        self._connection = connection
        self._detector = ConflictDetector()
        self._ensure_tables()

    def _ensure_tables(self) -> None:
        """Create registry tables if they don't exist."""
        with self._connection.cursor() as cursor:
            # Main intent registry
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS tb_pggit_intent (
                    id VARCHAR(64) PRIMARY KEY,
                    agent_id VARCHAR(255) NOT NULL,
                    feature_name VARCHAR(255) NOT NULL,
                    branch_name VARCHAR(255) NOT NULL UNIQUE,
                    schema_changes JSONB NOT NULL DEFAULT '[]',
                    tables_affected JSONB NOT NULL DEFAULT '[]',
                    estimated_duration_ms INTEGER,
                    risk_level VARCHAR(50) DEFAULT 'low',
                    status VARCHAR(50) NOT NULL DEFAULT 'registered',
                    conflicts_with JSONB NOT NULL DEFAULT '[]',
                    metadata JSONB NOT NULL DEFAULT '{}',
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)

            # Conflict tracking
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS tb_pggit_conflict (
                    id SERIAL PRIMARY KEY,
                    intent_a VARCHAR(64) NOT NULL REFERENCES tb_pggit_intent(id) ON DELETE CASCADE,
                    intent_b VARCHAR(64) NOT NULL REFERENCES tb_pggit_intent(id) ON DELETE CASCADE,
                    conflict_type VARCHAR(50) NOT NULL,
                    affected_objects JSONB NOT NULL DEFAULT '[]',
                    severity VARCHAR(50) NOT NULL,
                    resolution_suggestions JSONB NOT NULL DEFAULT '[]',
                    reviewed BOOLEAN DEFAULT FALSE,
                    reviewed_at TIMESTAMPTZ,
                    resolution_notes TEXT,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)

            # Intent history for audit
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS tb_pggit_intent_history (
                    id SERIAL PRIMARY KEY,
                    intent_id VARCHAR(64) NOT NULL REFERENCES tb_pggit_intent(id) ON DELETE CASCADE,
                    old_status VARCHAR(50),
                    new_status VARCHAR(50) NOT NULL,
                    reason TEXT,
                    changed_by VARCHAR(255) DEFAULT 'system',
                    changed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)

            # Create indexes
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_pggit_intent_agent ON tb_pggit_intent(agent_id)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_pggit_intent_status ON tb_pggit_intent(status)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_pggit_intent_tables ON tb_pggit_intent USING GIN(tables_affected)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_pggit_conflict_intents ON tb_pggit_conflict(intent_a, intent_b)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_pggit_conflict_severity ON tb_pggit_conflict(severity)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_pggit_intent_history_id ON tb_pggit_intent_history(intent_id)
            """)

            self._connection.commit()

    def register(
        self,
        agent_id: str,
        feature_name: str,
        schema_changes: list[str],
        tables_affected: list[str] | None = None,
        estimated_duration_ms: int = 0,
        risk_level: str = "low",
        metadata: dict[str, Any] | None = None,
    ) -> Intent:
        """Register a new intent.

        Automatically allocates a branch and detects conflicts with existing intents.

        Args:
            agent_id: Identifier for the agent (e.g., "claude-payments")
            feature_name: Human-readable feature name (e.g., "stripe_integration")
            schema_changes: List of DDL statements planned
            tables_affected: List of table names that will be modified (optional)
            estimated_duration_ms: Estimated time to complete
            risk_level: Risk assessment ("low", "medium", "high")
            metadata: Custom metadata dict

        Returns:
            Created Intent object

        Raises:
            ValueError: If parameters are invalid
        """
        if not agent_id or not feature_name or not schema_changes:
            raise ValueError("agent_id, feature_name, and schema_changes are required")

        if tables_affected is None:
            # Try to extract from schema changes
            tables_affected = list(self._detector._extract_tables_from_changes(schema_changes))

        # Create intent
        intent_id = str(uuid4())
        branch_name = self.allocate_branch(feature_name)
        now = datetime.now()

        intent = Intent(
            id=intent_id,
            agent_id=agent_id,
            feature_name=feature_name,
            branch_name=branch_name,
            schema_changes=schema_changes,
            tables_affected=tables_affected,
            estimated_duration_ms=estimated_duration_ms,
            risk_level=RiskLevel[risk_level.upper()] if isinstance(risk_level, str) else risk_level,
            status=IntentStatus.REGISTERED,
            created_at=now,
            updated_at=now,
            metadata=metadata or {},
        )

        # Detect conflicts with existing intents
        existing_intents = self.list_intents(status=IntentStatus.IN_PROGRESS)
        existing_intents.extend(self.list_intents(status=IntentStatus.REGISTERED))

        conflicts: list[str] = []
        for existing_intent in existing_intents:
            detected = self._detector.detect_conflicts(intent, existing_intent)
            if detected:
                conflicts.append(existing_intent.id)

        if conflicts:
            intent.conflicts_with = conflicts
            intent.status = IntentStatus.CONFLICTED

        # Store in database
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO tb_pggit_intent
                (id, agent_id, feature_name, branch_name, schema_changes, tables_affected,
                 estimated_duration_ms, risk_level, status, conflicts_with, metadata,
                 created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    intent.id,
                    intent.agent_id,
                    intent.feature_name,
                    intent.branch_name,
                    json.dumps(intent.schema_changes),
                    json.dumps(intent.tables_affected),
                    intent.estimated_duration_ms,
                    intent.risk_level.value,
                    intent.status.value,
                    json.dumps(intent.conflicts_with),
                    json.dumps(intent.metadata),
                    intent.created_at,
                    intent.updated_at,
                ),
            )

            # Store conflict reports
            for existing_id in conflicts:
                existing_intent = self.get_intent(existing_id)
                detected = self._detector.detect_conflicts(intent, existing_intent)

                for conflict_report in detected:
                    cursor.execute(
                        """
                        INSERT INTO tb_pggit_conflict
                        (intent_a, intent_b, conflict_type, affected_objects, severity, resolution_suggestions)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        """,
                        (
                            conflict_report.intent_a,
                            conflict_report.intent_b,
                            conflict_report.conflict_type.value,
                            json.dumps(conflict_report.affected_objects),
                            conflict_report.severity.value,
                            json.dumps(conflict_report.resolution_suggestions),
                        ),
                    )

            self._connection.commit()

        return intent

    def get_intent(self, intent_id: str) -> Intent | None:
        """Get an intent by ID.

        Args:
            intent_id: Intent ID

        Returns:
            Intent object or None if not found
        """
        with self._connection.cursor() as cursor:
            cursor.execute(
                "SELECT * FROM tb_pggit_intent WHERE id = %s",
                (intent_id,),
            )
            row = cursor.fetchone()

            if not row:
                return None

            return self._row_to_intent(row)

    def list_intents(
        self,
        status: IntentStatus | None = None,
        agent_id: str | None = None,
    ) -> list[Intent]:
        """List intents with optional filtering.

        Args:
            status: Filter by status
            agent_id: Filter by agent ID

        Returns:
            List of Intent objects
        """
        query = "SELECT * FROM tb_pggit_intent WHERE 1=1"
        params: list[Any] = []

        if status:
            query += " AND status = %s"
            params.append(status.value if isinstance(status, IntentStatus) else status)

        if agent_id:
            query += " AND agent_id = %s"
            params.append(agent_id)

        query += " ORDER BY created_at DESC"

        with self._connection.cursor() as cursor:
            cursor.execute(query, params)
            rows = cursor.fetchall()

            return [self._row_to_intent(row) for row in rows]

    def mark_in_progress(
        self,
        intent_id: str,
        reason: str = "Agent started work",
        changed_by: str = "agent",
    ) -> None:
        """Mark an intent as in progress.

        Args:
            intent_id: Intent ID
            reason: Reason for state change
            changed_by: Who is making the change
        """
        self._update_intent_status(
            intent_id,
            IntentStatus.IN_PROGRESS,
            reason,
            changed_by,
        )

    def mark_completed(
        self,
        intent_id: str,
        reason: str = "Changes completed",
        changed_by: str = "agent",
    ) -> None:
        """Mark an intent as completed.

        Args:
            intent_id: Intent ID
            reason: Reason for state change
            changed_by: Who is making the change
        """
        self._update_intent_status(
            intent_id,
            IntentStatus.COMPLETED,
            reason,
            changed_by,
        )

    def mark_merged(
        self,
        intent_id: str,
        reason: str = "Changes merged to main",
        changed_by: str = "agent",
    ) -> None:
        """Mark an intent as merged.

        Args:
            intent_id: Intent ID
            reason: Reason for state change
            changed_by: Who is making the change
        """
        self._update_intent_status(
            intent_id,
            IntentStatus.MERGED,
            reason,
            changed_by,
        )

    def mark_abandoned(
        self,
        intent_id: str,
        reason: str = "Intent abandoned",
        changed_by: str = "agent",
    ) -> None:
        """Mark an intent as abandoned.

        Args:
            intent_id: Intent ID
            reason: Reason for state change
            changed_by: Who is making the change
        """
        self._update_intent_status(
            intent_id,
            IntentStatus.ABANDONED,
            reason,
            changed_by,
        )

    def allocate_branch(self, feature_name: str) -> str:
        """Allocate a unique branch name for a feature.

        Args:
            feature_name: Feature name

        Returns:
            Unique branch name
        """
        # Sanitize feature name
        safe_name = feature_name.lower().replace(" ", "_").replace("/", "_")
        base_name = f"feature/{safe_name}"

        # Check for existing branches with same name
        with self._connection.cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) FROM tb_pggit_intent WHERE branch_name LIKE %s",
                (f"{base_name}%",),
            )
            count = cursor.fetchone()[0]

        if count == 0:
            return base_name

        # Add suffix to make unique
        return f"{base_name}_{count:03d}"

    def get_conflicts(self, intent_id: str) -> list[ConflictReport]:
        """Get all conflicts for an intent.

        Args:
            intent_id: Intent ID

        Returns:
            List of ConflictReport objects
        """
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT * FROM tb_pggit_conflict
                WHERE intent_a = %s OR intent_b = %s
                ORDER BY created_at DESC
                """,
                (intent_id, intent_id),
            )
            rows = cursor.fetchall()

            return [self._row_to_conflict(row) for row in rows]

    def resolve_conflict(
        self,
        conflict_id: int,
        reviewed: bool = True,
        resolution_notes: str = "",
    ) -> None:
        """Mark a conflict as reviewed/resolved.

        Args:
            conflict_id: Conflict ID
            reviewed: Whether conflict was reviewed
            resolution_notes: Notes on resolution
        """
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE tb_pggit_conflict
                SET reviewed = %s, reviewed_at = %s, resolution_notes = %s
                WHERE id = %s
                """,
                (reviewed, datetime.now() if reviewed else None, resolution_notes, conflict_id),
            )
            self._connection.commit()

    def _update_intent_status(
        self,
        intent_id: str,
        new_status: IntentStatus,
        reason: str,
        changed_by: str,
    ) -> None:
        """Update intent status and record history.

        Args:
            intent_id: Intent ID
            new_status: New status
            reason: Reason for change
            changed_by: Who made the change
        """
        intent = self.get_intent(intent_id)
        if not intent:
            raise ValueError(f"Intent {intent_id} not found")

        old_status = intent.status

        with self._connection.cursor() as cursor:
            # Update intent
            cursor.execute(
                """
                UPDATE tb_pggit_intent
                SET status = %s, updated_at = %s
                WHERE id = %s
                """,
                (new_status.value, datetime.now(), intent_id),
            )

            # Record history
            cursor.execute(
                """
                INSERT INTO tb_pggit_intent_history
                (intent_id, old_status, new_status, reason, changed_by)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (
                    intent_id,
                    old_status.value if old_status else None,
                    new_status.value,
                    reason,
                    changed_by,
                ),
            )

            self._connection.commit()

    def _row_to_intent(self, row: Any) -> Intent:
        """Convert database row to Intent object."""
        return Intent(
            id=row[0],
            agent_id=row[1],
            feature_name=row[2],
            branch_name=row[3],
            schema_changes=json.loads(row[4]),
            tables_affected=json.loads(row[5]),
            estimated_duration_ms=row[6],
            risk_level=RiskLevel[row[7].upper()] if isinstance(row[7], str) else row[7],
            status=IntentStatus[row[8].upper()] if isinstance(row[8], str) else row[8],
            created_at=row[11],
            updated_at=row[12],
            conflicts_with=json.loads(row[9]),
            metadata=json.loads(row[10]),
        )

    def _row_to_conflict(self, row: Any) -> ConflictReport:
        """Convert database row to ConflictReport object."""
        return ConflictReport(
            id=row[0],
            intent_a=row[1],
            intent_b=row[2],
            conflict_type=ConflictType[row[3].upper()] if isinstance(row[3], str) else row[3],
            affected_objects=json.loads(row[4]),
            severity=ConflictSeverity[row[5].upper()] if isinstance(row[5], str) else row[5],
            resolution_suggestions=json.loads(row[6]),
            reviewed=row[7],
            reviewed_at=row[8],
            resolution_notes=row[9],
            created_at=row[11],
        )
