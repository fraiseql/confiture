# Hook API Reference

[← Back to API Reference](index.md)

**Stability**: Library API (callback-driven) 🧩

---

## Overview

The Hook API lets you run custom logic at points in a migration's lifecycle —
back up before a migration, audit after one, notify on completion, or fail a
migration when a post-condition doesn't hold.

A hook is a small **class** you register on a `Migrator`. It is a **library
API**: there is no CLI surface and no config-file registration — you register
hooks in Python on the migrator instance you drive.

**Tagline**: *Extend migrations with custom logic at critical points*

---

## Built-in hooks

Confiture ships two ready-to-use lifecycle hooks. Both are **opt-in** — they do
nothing until you register them on a `Migrator` instance, so the default
migration path is unchanged.

- **`BackupHook`** — runs `pg_dump` (optionally gzip-compressed, with a retention
  cap) *before* each migration. Registers on `HookPhase.BEFORE_EXECUTE`.
- **`AuditHook`** — appends an HMAC-SHA256-signed audit row *after* each
  migration for tamper-evident history. Registers on `HookPhase.AFTER_EXECUTE`.

Register them via the real instance API — `Migrator.register_hook(phase, hook)`:

<!-- doctest:builtin-hooks-imports -->
```python
from pathlib import Path

from confiture import (
    AuditConfig,
    AuditHook,
    BackupConfig,
    BackupHook,
    HookPhase,
    Migrator,
)

with Migrator.from_config("db/environments/prod.yaml") as m:
    dsn = "postgresql://localhost/prod"

    # Back up before every migration (runs first, priority 1)
    m.register_hook(
        HookPhase.BEFORE_EXECUTE,
        BackupHook(BackupConfig(backup_dir=Path("backups"), database_url=dsn)),
    )

    # Record a signed audit trail after every migration (runs late, priority 8)
    m.register_hook(
        HookPhase.AFTER_EXECUTE,
        AuditHook(AuditConfig(database_url=dsn, signing_key="…", environment="prod")),
    )

    m.up()
```

> `BackupConfig` accepts `compress` (default `True`) and `max_backups` (default
> `10`). `AuditConfig` accepts an `environment` label (default `"unknown"`).

---

## What is a hook?

A hook is a class that subclasses `Hook[T]` and implements one **async** method,
`execute`, returning a `HookResult`:

<!-- doctest:hook-shape -->
```python
from confiture.core.hooks import Hook, HookContext, HookResult
from confiture.core.hooks.context import ExecutionContext


class MyHook(Hook[ExecutionContext]):
    def __init__(self) -> None:
        super().__init__(hook_id="my.hook", name="My Hook", priority=5)

    async def execute(self, context: HookContext[ExecutionContext]) -> HookResult:
        data = context.get_data()  # the phase payload (ExecutionContext here)
        ...
        return HookResult(success=True)
```

- `Hook[T]` is generic over the **phase payload type** `T`. For the execute
  phases that payload is `ExecutionContext`.
- `__init__` sets a stable `hook_id`, a human `name`, and a `priority`
  (`1`–`10`, **lower runs first**; default `5`). An optional `depends_on` lists
  hook ids that must have run first.
- `execute` is `async` and returns a `HookResult` — see
  [Returning a result](#returning-a-result-and-failing-a-migration).

---

## Lifecycle phases

Phases are members of the `HookPhase` enum (`from confiture.core.hooks import
HookPhase`), **not** strings:

| Phase | When |
|-------|------|
| `HookPhase.BEFORE_EXECUTE` | Immediately before a migration's SQL runs |
| `HookPhase.AFTER_EXECUTE`  | Immediately after a migration runs (success *or* failure — check `metadata["success"]`) |

> **What actually fires today:** `migrate up` / `migrate down` trigger only
> **`BEFORE_EXECUTE`** and **`AFTER_EXECUTE`** (once per migration, on both the
> up and down paths). The `HookPhase` enum defines further lifecycle members
> (`BEFORE_PLAN_MIGRATION`, `BEFORE_VALIDATE`, `BEFORE_ROLLBACK`, `*_REBUILD`,
> …) for the broader hook framework, but the migrator does not emit them yet.
> Register on the two execute phases for behavior you can rely on now.

---

## The context object

`execute` receives a `HookContext[T]`. The useful members:

| Member | Meaning |
|--------|---------|
| `context.get_data()` (or `context.data`) | The phase payload `T` (an `ExecutionContext` for the execute phases) |
| `context.phase` | The `HookPhase` that fired |
| `context.execution_id` | A `UUID` correlation id for this trigger (for tracing) |
| `context.timestamp` | UTC `datetime` the context was created |

For `BEFORE_EXECUTE` / `AFTER_EXECUTE` the payload is an `ExecutionContext`:

| Field | Meaning |
|-------|---------|
| `elapsed_time_ms` | Execution time so far (0 in `BEFORE_EXECUTE`) |
| `rows_affected` | Rows affected (when known) |
| `steps_completed` / `total_steps` | Progress counters |
| `metadata` | A `dict` the migrator fills with the keys below |

The migrator populates `metadata` with: `migration_name`, `migration_version`,
`direction` (`"up"`), `success` (`bool`), `error` (`str | None`), and
`executed_by`.

---

## Registering hooks

Register hook **instances** on a `Migrator` via `register_hook(phase, hook)`:

<!-- doctest:registering -->
```python
from confiture import HookPhase, Migrator

with Migrator.from_config("db/environments/prod.yaml") as m:
    m.register_hook(HookPhase.AFTER_EXECUTE, MyHook())
    # Register more than one for the same phase; they run in priority order
    # (lower number first), then registration order to break ties.
    m.register_hook(HookPhase.AFTER_EXECUTE, AnotherHook())
    m.up()
```

`MigratorSession` (the object yielded by `Migrator.from_config(...)`) exposes the
same `register_hook` — register before calling `up()` / `down()`.

---

## Returning a result, and failing a migration

`execute` returns a `HookResult`:

```python
HookResult(success=True, rows_affected=0, stats=None, error=None)
```

- `success=True` — the hook is done; `stats` may carry arbitrary diagnostics.
- `success=False` (or raising `HookError`) — the hook **failed**. Confiture
  raises a `HookError`, which **aborts the migration run**. Use this to enforce
  post-conditions.

<!-- doctest:failing -->
```python
from confiture.core.hooks import Hook, HookContext, HookResult
from confiture.core.hooks.context import ExecutionContext


class PostconditionHook(Hook[ExecutionContext]):
    def __init__(self) -> None:
        super().__init__(hook_id="check.rowcount", name="Row-count check", priority=9)

    async def execute(self, context: HookContext[ExecutionContext]) -> HookResult:
        data = context.get_data()
        if not data.metadata.get("success", False):
            # The migration itself failed — don't add noise.
            return HookResult(success=True)
        if data.rows_affected == 0:
            return HookResult(success=False, error="Expected rows to change")
        return HookResult(success=True, stats={"rows": data.rows_affected})
```

`HookError` carries `hook_id`, `hook_name`, `phase`, and the originating `cause`
for diagnostics (`from confiture.core.hooks import HookError`).

---

## Important caveat: the event loop

Hook `execute` methods are `async`. The migrator runs them on an internal
asyncio loop it creates per trigger. **If you drive `up()` / `down()` from inside
an already-running event loop, hook triggering is skipped** (to avoid nested-loop
conflicts) and a debug line is logged. Run migrations from synchronous code when
you rely on hooks.

---

## Examples

### Example 1 — audit to a file (`AFTER_EXECUTE`)

<!-- doctest:example-file-audit -->
```python
import logging
from pathlib import Path

from confiture.core.hooks import Hook, HookContext, HookResult
from confiture.core.hooks.context import ExecutionContext


class FileAuditHook(Hook[ExecutionContext]):
    def __init__(self, log_path: Path) -> None:
        super().__init__(hook_id="audit.file", name="File Audit", priority=8)
        self._log_path = log_path

    async def execute(self, context: HookContext[ExecutionContext]) -> HookResult:
        data = context.get_data()
        line = (
            f"{context.timestamp.isoformat()} "
            f"{data.metadata.get('migration_name')} "
            f"success={data.metadata.get('success')} "
            f"{data.elapsed_time_ms}ms\n"
        )
        try:
            with self._log_path.open("a", encoding="utf-8") as fh:
                fh.write(line)
        except OSError as exc:
            logging.getLogger(__name__).warning("audit write failed: %s", exc)
            return HookResult(success=False, error=str(exc))
        return HookResult(success=True)
```

### Example 2 — notify on completion (`AFTER_EXECUTE`)

Posting to a webhook needs an HTTP client (e.g. `httpx` / `requests`) — an
external dependency, not part of Confiture.

<!-- doctest:example-notify -->
```python
from confiture.core.hooks import Hook, HookContext, HookResult
from confiture.core.hooks.context import ExecutionContext


class NotifyHook(Hook[ExecutionContext]):
    def __init__(self, webhook_url: str) -> None:
        super().__init__(hook_id="notify.webhook", name="Notify", priority=7)
        self._url = webhook_url

    async def execute(self, context: HookContext[ExecutionContext]) -> HookResult:
        import httpx  # external dependency

        data = context.get_data()
        text = (
            f"Migration {data.metadata.get('migration_name')} "
            f"{'succeeded' if data.metadata.get('success') else 'FAILED'}"
        )
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                await client.post(self._url, json={"text": text})
        except Exception as exc:  # don't let a notification failure abort the run
            return HookResult(success=True, error=f"notify skipped: {exc}")
        return HookResult(success=True)
```

> Notice the difference from Example&nbsp;1: a *notification* failure returns
> `success=True` (best-effort), while a *post-condition* failure (the
> [failing example](#returning-a-result-and-failing-a-migration)) returns
> `success=False` to stop the run. Choose per hook whether a failure should
> block the migration.

### Example 3 — built-in audit & backup

For tamper-evident audit logging and pre-migration `pg_dump` backups, use the
shipped [built-in hooks](#built-in-hooks) rather than rolling your own.

---

## Best practices

- **Keep hooks fast.** They run inside the migration flow; slow hooks slow every
  migration.
- **Decide failure semantics per hook.** Return `success=False` only when the
  failure should abort the migration; return `success=True` for best-effort side
  effects (notifications, metrics).
- **Make hooks idempotent.** `AFTER_EXECUTE` fires on both success and failure —
  branch on `metadata["success"]`.
- **Don't assume an open transaction.** A hook gets context metadata, not the
  migration's connection; open your own connection if you need the database (as
  the built-in `AuditHook` does).

---

## See also

- [Migrator API](migrator.md) — `Migrator.from_config`, `MigratorSession`
- [Built-in hooks](#built-in-hooks) — `AuditHook`, `BackupHook`
