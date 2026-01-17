"""Audit trail for migration compliance.

Tracks who ran migrations, when, and the outcome for compliance purposes.
"""

import getpass
import json
import logging
import os
import socket
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import psycopg

logger = logging.getLogger(__name__)


@dataclass
class AuditConfig:
    """Configuration for audit trail."""

    enabled: bool = True
    table_name: str = "confiture_audit_log"


@dataclass
class AuditEntry:
    """A single audit log entry."""

    migration_version: str
    migration_name: str
    action: str  # "apply", "rollback", "dry_run"
    status: str  # "started", "completed", "failed"
    user: str
    hostname: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    duration_ms: int | None = None
    error_message: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "migration_version": self.migration_version,
            "migration_name": self.migration_name,
            "action": self.action,
            "status": self.status,
            "user": self.user,
            "hostname": self.hostname,
            "timestamp": self.timestamp.isoformat(),
            "duration_ms": self.duration_ms,
            "error_message": self.error_message,
            "metadata": self.metadata,
        }


class AuditTrail:
    """Records audit trail for compliance.

    Tracks who ran migrations, when, from which machine, and whether
    they succeeded or failed.

    Example:
        >>> audit = AuditTrail(conn, AuditConfig(enabled=True))
        >>> audit.initialize()
        >>> entry_id = audit.record_start("001", "create_users", "apply")
        >>> # ... run migration ...
        >>> audit.record_complete(entry_id, duration_ms=1500)
    """

    def __init__(
        self,
        connection: psycopg.Connection,
        config: AuditConfig | None = None,
    ):
        """Initialize audit trail.

        Args:
            connection: Database connection
            config: Audit configuration (optional)
        """
        self.connection = connection
        self.config = config or AuditConfig()
        self._initialized = False

    @property
    def is_enabled(self) -> bool:
        """Check if audit trail is enabled."""
        return self.config.enabled

    def initialize(self) -> None:
        """Create audit log table if it doesn't exist."""
        if not self.config.enabled:
            return

        with self.connection.cursor() as cur:
            cur.execute(f"""
                CREATE TABLE IF NOT EXISTS {self.config.table_name} (
                    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                    migration_version VARCHAR(255) NOT NULL,
                    migration_name VARCHAR(255) NOT NULL,
                    action VARCHAR(50) NOT NULL,
                    status VARCHAR(50) NOT NULL,
                    username VARCHAR(255) NOT NULL,
                    hostname VARCHAR(255) NOT NULL,
                    started_at TIMESTAMPTZ NOT NULL,
                    completed_at TIMESTAMPTZ,
                    duration_ms INTEGER,
                    error_message TEXT,
                    metadata JSONB DEFAULT '{{}}'::jsonb
                )
            """)

            cur.execute(f"""
                CREATE INDEX IF NOT EXISTS idx_{self.config.table_name}_version
                    ON {self.config.table_name}(migration_version)
            """)

            cur.execute(f"""
                CREATE INDEX IF NOT EXISTS idx_{self.config.table_name}_started
                    ON {self.config.table_name}(started_at DESC)
            """)

            cur.execute(f"""
                CREATE INDEX IF NOT EXISTS idx_{self.config.table_name}_action
                    ON {self.config.table_name}(action)
            """)

        self.connection.commit()
        self._initialized = True
        logger.info("Audit trail initialized")

    def record_start(
        self,
        migration_version: str,
        migration_name: str,
        action: str,
        metadata: dict[str, Any] | None = None,
    ) -> int:
        """Record migration start.

        Args:
            migration_version: Migration version
            migration_name: Migration name
            action: Action type ("apply", "rollback", "dry_run")
            metadata: Additional metadata (optional)

        Returns:
            Audit entry ID for later completion
        """
        if not self.config.enabled:
            return -1

        entry = AuditEntry(
            migration_version=migration_version,
            migration_name=migration_name,
            action=action,
            status="started",
            user=self._get_current_user(),
            hostname=self._get_hostname(),
            metadata=metadata or {},
        )

        with self.connection.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO {self.config.table_name}
                    (migration_version, migration_name, action, status,
                     username, hostname, started_at, metadata)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """,
                (
                    entry.migration_version,
                    entry.migration_name,
                    entry.action,
                    entry.status,
                    entry.user,
                    entry.hostname,
                    entry.timestamp,
                    json.dumps(entry.metadata),
                ),
            )
            result = cur.fetchone()
            entry_id = result[0] if result else -1

        self.connection.commit()
        return entry_id

    def record_complete(
        self,
        entry_id: int,
        duration_ms: int,
        error_message: str | None = None,
    ) -> None:
        """Record migration completion.

        Args:
            entry_id: Audit entry ID from record_start
            duration_ms: Duration in milliseconds
            error_message: Error message if failed (optional)
        """
        if not self.config.enabled or entry_id < 0:
            return

        status = "failed" if error_message else "completed"

        with self.connection.cursor() as cur:
            cur.execute(
                f"""
                UPDATE {self.config.table_name}
                SET status = %s,
                    completed_at = %s,
                    duration_ms = %s,
                    error_message = %s
                WHERE id = %s
            """,
                (
                    status,
                    datetime.now(UTC),
                    duration_ms,
                    error_message,
                    entry_id,
                ),
            )

        self.connection.commit()

    def get_history(
        self,
        migration_version: str | None = None,
        action: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Get audit history.

        Args:
            migration_version: Filter by version (optional)
            action: Filter by action (optional)
            limit: Maximum number of entries

        Returns:
            List of audit entries as dictionaries
        """
        if not self.config.enabled:
            return []

        conditions = []
        params: list[Any] = []

        if migration_version:
            conditions.append("migration_version = %s")
            params.append(migration_version)
        if action:
            conditions.append("action = %s")
            params.append(action)

        where_clause = ""
        if conditions:
            where_clause = "WHERE " + " AND ".join(conditions)

        params.append(limit)

        with self.connection.cursor() as cur:
            cur.execute(
                f"""
                SELECT id, migration_version, migration_name, action, status,
                       username, hostname, started_at, completed_at,
                       duration_ms, error_message, metadata
                FROM {self.config.table_name}
                {where_clause}
                ORDER BY started_at DESC
                LIMIT %s
            """,
                params,
            )

            columns = [desc[0] for desc in cur.description]
            return [dict(zip(columns, row, strict=True)) for row in cur.fetchall()]

    def get_recent_failures(self, limit: int = 10) -> list[dict[str, Any]]:
        """Get recent failed migrations.

        Args:
            limit: Maximum number of entries

        Returns:
            List of failed audit entries
        """
        if not self.config.enabled:
            return []

        with self.connection.cursor() as cur:
            cur.execute(
                f"""
                SELECT id, migration_version, migration_name, action,
                       username, hostname, started_at, error_message
                FROM {self.config.table_name}
                WHERE status = 'failed'
                ORDER BY started_at DESC
                LIMIT %s
            """,
                (limit,),
            )

            columns = [desc[0] for desc in cur.description]
            return [dict(zip(columns, row, strict=True)) for row in cur.fetchall()]

    def _get_current_user(self) -> str:
        """Get current username."""
        try:
            return getpass.getuser()
        except Exception:
            return os.environ.get("USER", "unknown")

    def _get_hostname(self) -> str:
        """Get current hostname."""
        try:
            return socket.gethostname()
        except Exception:
            return "unknown"
