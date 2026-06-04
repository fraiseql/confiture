"""Post-migration audit logging with HMAC integrity."""

from __future__ import annotations

import hashlib
import hmac
import logging
from dataclasses import dataclass

import psycopg

from confiture.core.hooks.base import Hook, HookResult
from confiture.core.hooks.context import ExecutionContext, HookContext

logger = logging.getLogger(__name__)

AUDIT_TABLE = "confiture_audit_log"
AUDIT_DDL = f"""
CREATE TABLE IF NOT EXISTS {AUDIT_TABLE} (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    migration   TEXT NOT NULL,
    direction   TEXT NOT NULL,
    environment TEXT,
    executed_by TEXT,
    executed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    duration_ms DOUBLE PRECISION,
    success     BOOLEAN NOT NULL,
    error       TEXT,
    signature   TEXT NOT NULL
);
"""


@dataclass(frozen=True)
class AuditConfig:
    """Configuration for audit logging hook."""

    database_url: str
    signing_key: str  # HMAC-SHA256 key
    environment: str = "unknown"


class AuditHook(Hook[ExecutionContext]):
    """Log migration executions to an audit table with HMAC signatures.

    Registers on HookPhase.after_execute. Creates the audit table
    if it doesn't exist. Each entry is signed for tamper detection.
    """

    def __init__(self, config: AuditConfig) -> None:
        super().__init__(
            hook_id="builtin.audit",
            name="Audit Logger",
            priority=8,  # run late, after main work
        )
        self._config = config

    async def execute(
        self,
        context: HookContext[ExecutionContext],
    ) -> HookResult:
        ctx = context.get_data()

        # Build the audit record from context metadata
        record = {
            "migration": ctx.metadata.get("migration_name", "unknown"),
            "direction": ctx.metadata.get("direction", "unknown"),
            "environment": self._config.environment,
            "executed_by": ctx.metadata.get("executed_by", "system"),
            "duration_ms": ctx.elapsed_time_ms,
            "success": ctx.metadata.get("success", True),
            "error": ctx.metadata.get("error"),
        }

        signature = self._sign(record)

        try:
            with psycopg.connect(self._config.database_url) as conn:
                conn.execute(AUDIT_DDL)
                conn.execute(
                    f"""
                    INSERT INTO {AUDIT_TABLE}
                        (migration, direction, environment, executed_by,
                         duration_ms, success, error, signature)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,  # nosec B608 - AUDIT_TABLE is a module constant; all values are parameter-bound
                    (
                        record["migration"],
                        record["direction"],
                        record["environment"],
                        record["executed_by"],
                        record["duration_ms"],
                        record["success"],
                        record["error"],
                        signature,
                    ),
                )
                conn.commit()

            logger.info("Audit logged: %s (%s)", record["migration"], record["direction"])
            return HookResult(success=True, stats={"signature": signature})

        except Exception as exc:
            logger.warning("Audit logging failed: %s", exc)
            return HookResult(success=False, error=str(exc))

    def _sign(self, record: dict) -> str:
        """Create HMAC-SHA256 signature for tamper detection."""
        payload = "|".join(str(v) for v in record.values())
        return hmac.new(
            self._config.signing_key.encode(),
            payload.encode(),
            hashlib.sha256,
        ).hexdigest()

    @staticmethod
    def verify_signature(
        record: dict,
        signature: str,
        signing_key: str,
    ) -> bool:
        """Verify an audit entry's HMAC signature."""
        payload = "|".join(str(v) for v in record.values())
        expected = hmac.new(
            signing_key.encode(),
            payload.encode(),
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(expected, signature)
