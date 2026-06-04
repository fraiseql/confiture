# Migration Hooks

[← Back to Guides](../index.md) · [Schema-to-Schema](04-schema-to-schema.md) · [Anonymization →](anonymization.md)

Run custom code around migrations — back up before, audit after, validate
results, notify on completion.

A hook is a small **class** you register on a `Migrator` in Python. There is no
CLI flag and no YAML hook config: hooks are a **library API**, registered on the
migrator instance you drive. For the complete reference see the
[Hook API Reference](../api/hooks.md); this guide is the quick tour.

---

## Quick start — the built-in hooks

The fastest win is the two hooks Confiture ships. They are **opt-in** (nothing
runs until you register them):

<!-- doctest:guide-builtin -->
```python
from pathlib import Path

from confiture import BackupConfig, BackupHook, HookPhase, Migrator

with Migrator.from_config("db/environments/prod.yaml") as m:
    # pg_dump before every migration
    m.register_hook(
        HookPhase.BEFORE_EXECUTE,
        BackupHook(BackupConfig(backup_dir=Path("backups"),
                                database_url="postgresql://localhost/prod")),
    )
    m.up()
```

`AuditHook` (post-migration, HMAC-signed audit rows) registers the same way on
`HookPhase.AFTER_EXECUTE`. See [Built-in hooks](../api/hooks.md#built-in-hooks).

---

## Writing your own hook

Subclass `Hook[ExecutionContext]` and implement one **async** method,
`execute`, returning a `HookResult`:

<!-- doctest:guide-custom -->
```python
from confiture.core.hooks import Hook, HookContext, HookResult
from confiture.core.hooks.context import ExecutionContext


class LogMigration(Hook[ExecutionContext]):
    def __init__(self) -> None:
        super().__init__(hook_id="log.migration", name="Log Migration", priority=7)

    async def execute(self, context: HookContext[ExecutionContext]) -> HookResult:
        data = context.get_data()
        name = data.metadata.get("migration_name")
        ok = data.metadata.get("success")
        print(f"{name}: {'ok' if ok else 'FAILED'} in {data.elapsed_time_ms}ms")
        return HookResult(success=True)
```

Register the instance and run:

<!-- doctest:guide-register -->
```python
from confiture import HookPhase, Migrator

with Migrator.from_config("db/environments/local.yaml") as m:
    m.register_hook(HookPhase.AFTER_EXECUTE, LogMigration())
    m.up()
```

Hooks for the same phase run in **priority order** (lower number first).

---

## Lifecycle phases

```
confiture migrate up
    │
    ├─→ load pending migrations
    └─→ for each migration:
          ├─→ [BEFORE_EXECUTE]   hooks fire
          ├─→ execute SQL
          └─→ [AFTER_EXECUTE]    hooks fire (on success AND failure)
```

Phases are `HookPhase` enum members. **Today the migrator triggers only**
`HookPhase.BEFORE_EXECUTE` and `HookPhase.AFTER_EXECUTE` (on both `migrate up`
and `migrate down`). The enum defines further members for the wider hook
framework, but those are not emitted by the migrator yet — register on the two
execute phases for behaviour you can rely on.

`AFTER_EXECUTE` fires whether the migration succeeded or failed, so branch on
`context.get_data().metadata["success"]`.

---

## Failing a migration from a hook

Return `HookResult(success=False, error=...)` (or raise `HookError`) to **abort**
the run — useful for enforcing a post-condition:

<!-- doctest:guide-fail -->
```python
from confiture.core.hooks import Hook, HookContext, HookResult
from confiture.core.hooks.context import ExecutionContext


class RequireRowsChanged(Hook[ExecutionContext]):
    def __init__(self) -> None:
        super().__init__(hook_id="check.rows", name="Rows changed", priority=9)

    async def execute(self, context: HookContext[ExecutionContext]) -> HookResult:
        data = context.get_data()
        if data.metadata.get("success") and data.rows_affected == 0:
            return HookResult(success=False, error="expected rows to change")
        return HookResult(success=True)
```

A best-effort hook (logging, notifications) should instead return
`HookResult(success=True)` even on its own internal error, so a flaky webhook
doesn't fail your migration.

---

## Caveat: the event loop

`execute` is async; the migrator runs hooks on an internal asyncio loop it
creates per trigger. **If you call `up()` / `down()` from inside an already-running
event loop, hook triggering is skipped** to avoid nested-loop conflicts. Drive
migrations from synchronous code when you rely on hooks.

---

## Best practices

1. **Keep hooks fast** — they run inside the migration flow.
2. **Pick failure semantics deliberately** — `success=False` aborts; use it only
   for real post-conditions.
3. **Make hooks idempotent** — `AFTER_EXECUTE` fires on success and failure.
4. **Open your own connection** — a hook receives context metadata, not the
   migration's connection (the built-in `AuditHook` opens its own).

---

## See Also

- [Hook API Reference](../api/hooks.md) — full `Hook` / `HookContext` / `HookResult` surface
- [Built-in hooks](../api/hooks.md#built-in-hooks) — `AuditHook`, `BackupHook`
