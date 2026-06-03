# Blue-Green Orchestration API Reference

[← Back to API Reference](index.md)

**Stability**: Library API (callback-driven) 🧩

---

## Overview

`BlueGreenOrchestrator` drives a structured, zero-downtime schema swap: stand up
a target schema beside the live one, sync data, run your health checks, then
perform an atomic switch (with rollback + optional cleanup). It is a **library
API** — the health checks and data-sync step are Python callables you register,
so it has no CLI surface.

```python
from confiture import BlueGreenOrchestrator, BlueGreenConfig
```

---

## Quick Start

```python
import psycopg
from confiture import BlueGreenOrchestrator, BlueGreenConfig

conn = psycopg.connect("postgresql://localhost/myapp")

config = BlueGreenConfig(
    source_schema="public",
    target_schema="public_v2",
    health_check_interval=5.0,
    health_check_retries=3,
    traffic_switch_delay=10.0,
)

orchestrator = BlueGreenOrchestrator(conn, config)

# Register a readiness probe (must return True before cutover proceeds)
orchestrator.add_health_check("api_health", lambda: my_app_is_healthy())

# Provide the data-sync step (FDW copy, dual-write drain, etc.)
orchestrator.set_data_sync_function(lambda: sync_public_to_public_v2())

# Observe phase transitions
orchestrator.on_phase_change(lambda old, new: print(f"{old.value} → {new.value}"))

state = orchestrator.execute()
print(f"Final phase: {state.phase.value}")
```

---

## Public Surface

| Symbol | Kind | Purpose |
|--------|------|---------|
| `BlueGreenOrchestrator` | class | Drives the blue-green migration lifecycle |
| `BlueGreenConfig` | dataclass | Schema names, health-check cadence, timeouts, cleanup |
| `TrafficController` | class | Read-only toggling + connection draining/termination |
| `MigrationPhase` | enum | The lifecycle phases (`state.phase`) |
| `MigrationState` | dataclass | Current state snapshot (`.to_dict()`) |
| `HealthCheckResult` | dataclass | Result of a single health-check round |

### `BlueGreenOrchestrator`

- `add_health_check(name: str, check: Callable[[], bool])` — register a probe.
- `set_data_sync_function(fn: Callable[[], None])` — the data-copy step.
- `on_phase_change(cb: Callable[[MigrationPhase, MigrationPhase], None])`.
- `execute() -> MigrationState` — run the full lifecycle.
- `rollback() -> bool` / `cleanup_backup() -> bool`.
- `current_phase` (property) → `MigrationPhase`.

### `TrafficController`

`set_read_only(connection, enabled)`, `is_read_only()`,
`get_active_connections(connection)`, `drain_connections(...)`,
`terminate_connections(...)` — for quiescing the source during cutover.

---

## See Also

- [Schema-to-Schema](schema-to-schema.md) — FDW-based zero-downtime data migration
- [Migrator](migrator.md) — incremental migrations
