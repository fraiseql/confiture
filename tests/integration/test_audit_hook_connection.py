"""The audit hook's connection, on a real server: who opens it decides what it reads."""

import psycopg
import pytest

from confiture.core.hooks.builtin.audit_hook import AUDIT_TABLE, AuditConfig, AuditHook
from confiture.core.hooks.context import ExecutionContext, HookContext
from confiture.core.hooks.phases import HookPhase


def _run(hook: AuditHook):
    return hook.execute(
        HookContext(
            phase=HookPhase.AFTER_EXECUTE,
            data=ExecutionContext(metadata={"migration_name": "006_audited", "direction": "up"}),
        )
    )


@pytest.mark.asyncio
async def test_a_connection_factory_keeps_the_ambient_environment_out(fresh_database, monkeypatch):
    """An ambient ``PGOPTIONS`` reaches psycopg's connection, not the factory's (#799)."""
    monkeypatch.setenv("PGOPTIONS", "-c default_transaction_read_only=on")

    control = await _run(AuditHook(AuditConfig(database_url=fresh_database, signing_key="k")))
    assert control.success is False
    assert "read-only transaction" in (control.error or "")

    opened: list[str] = []

    def pinned(url: str) -> psycopg.Connection:
        opened.append(url)
        return psycopg.connect(url, options="")

    config = AuditConfig(database_url=fresh_database, signing_key="k", connection_factory=pinned)
    result = await _run(AuditHook(config))

    assert result.success is True, result.error
    assert opened == [fresh_database]
    with psycopg.connect(fresh_database, options="") as conn:
        rows = conn.execute(t"SELECT migration, direction FROM {AUDIT_TABLE:i}").fetchall()
    assert rows == [("006_audited", "up")]
