# Replica-safe migrations

Confiture's replica-aware forward-compatibility lint (`replica_001`, issue #139)
flags DDL that is unsafe to apply as a single step while read replicas serve
traffic. This guide explains *why* the hazard exists and how to fix each case.

## Why replicas need this

Under PostgreSQL streaming replication, a replica replays the primary's WAL with
a small lag. During that **lag window**, the primary already has the *new*
schema while replicas still serve reads against the *old* one. Application code
deployed alongside the migration may hit either schema depending on which node
answers a read.

The crux: **"safe within one migration" ≠ "safe under replication."** A migration
that backfills a new `NOT NULL` column in the same transaction is internally
consistent, but a reader on a lagging replica during the rollout still queries
the pre-migration schema — and a writer on the primary already enforces the new
constraint. The fix is almost always to split the change into forward-compatible
steps spread across releases.

## The safety matrix

| Operation | Safe in one step? | Multi-step remediation |
|---|---|---|
| `ADD COLUMN` (nullable, no default) | ✅ yes | — |
| `ADD COLUMN` (NOT NULL and/or DEFAULT) | ❌ no | add nullable → backfill → `SET NOT NULL` in a later release |
| `DROP COLUMN` | ❌ no | deprecate (stop using) → wait one release → drop |
| `RENAME COLUMN` | ❌ no | add new → dual-write → migrate readers → drop old |
| `CHANGE TYPE` | ❌ no | add new column → backfill → swap readers → drop old |
| `ADD CONSTRAINT` (immediate) | ❌ no | `ADD ... NOT VALID` → backfill → `VALIDATE CONSTRAINT` |
| `ADD CONSTRAINT ... NOT VALID` | ✅ yes | — |
| `CREATE INDEX` | ❌ no | `CREATE INDEX CONCURRENTLY` in its own non-transactional migration |
| `CREATE INDEX CONCURRENTLY` | ✅ yes | — |
| `CREATE TABLE` | ✅ yes | — |

> **`ADD COLUMN NOT NULL DEFAULT` stays unsafe** even on PostgreSQL 11+ where the
> "fast default" optimization makes the *primary* change cheap. The fast-default
> optimization is orthogonal to the replica-lag concern: a reader on the old
> schema still errors on the new `NOT NULL` column. (OD-13.)

## Default severity policy

The lint is **active by default but soft** so it doesn't break non-replicated
projects on upgrade:

- **No replicas declared** → unsafe operations are **warnings** (visible in CI,
  non-blocking, exit 0).
- **Replicas declared** (`infrastructure.replicas` non-empty) → unsafe operations
  are **errors** (exit 7 in preflight; exit 1 in `lint`).
- Operations the parser can't classify (e.g. dynamic `EXECUTE format(...)`) are
  always **warnings** ("review manually") — never a hard block.

Declare replicas in the environment YAML:

```yaml
infrastructure:
  replicas:
    - read-replica-1
    - read-replica-2
```

### Bypassing (with documented risk)

```yaml
migration:
  allow_unsafe_under_replication: true
```

This downgrades replica errors to warnings everywhere — even with replicas
declared. **Risk**: you are accepting that a single-step DDL change may surface
errors on read replicas during the replication-lag window. Use only when you
control the rollout (e.g. you drain replica reads during the migration).

## Surfaces

- **`confiture migrate preflight --format json`** emits `PFLIGHT_REPLICA_*` issues
  in the [structured report](../reference/json-schemas.md) — the deploy-gate
  contract. Errors exit 7.
- **`confiture lint --replica-safe`** runs the rule (`replica_001`) over the
  migrations tree for standalone CI.

## Coordination

This static guarantee is the foundation for read-replica routing and replica-safe
plan generation in the broader stack: specql#13 (replica-safe migration plan
generation) and fraiseql#407 (read-replica read routing) rely on it; the deploy
tool (fraisier) owns the live replica topology and sets `infrastructure.replicas`.
