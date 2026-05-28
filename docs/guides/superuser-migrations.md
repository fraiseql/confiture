# Superuser Migrations

[← Back to Guides](../index.md) · [Incremental Migrations](02-incremental-migrations.md) · [Bootstrap](bootstrap.md)

Declaratively mark a migration as "must run as superuser" and let confiture skip it cleanly during routine `migrate up`, then resume the chain once an operator has applied it via `migrate apply-as`.

---

## The problem

Some migrations need privileges the migrator role doesn't have:

- `ALTER … OWNER TO migrator` on objects created by `postgres` (a one-time historical-ownership fix).
- `CREATE EXTENSION` for trusted-only extensions.
- `GRANT EXECUTE` on functions you didn't create.

Running such a migration as `migrator` fails mid-apply with `permission denied` — the worst discovery surface, because the chain stops in an inconsistent state.

The fix has two parts:

1. **Author-side:** declare the migration with `requires_superuser = True`.
2. **Operator-side:** when `migrate up` halts on it, run `confiture migrate apply-as <role> <version>` to apply that one migration explicitly as the named role.

---

## Authoring a superuser migration

Set the class attribute alongside the existing `transactional` toggle:

```python
from confiture.models.migration import Migration


class FixHistoricalOwnership(Migration):
    version = "20260528160002"
    name = "fix_historical_ownership"
    requires_superuser = True   # NEW

    def up(self) -> None:
        self.execute("ALTER TABLE tenant.tb_foo OWNER TO migrator")

    def down(self) -> None:
        self.execute("ALTER TABLE tenant.tb_foo OWNER TO postgres")
```

The attribute lives on instances (matches `transactional: bool = True` at `python/confiture/models/migration.py:142`), not as a `ClassVar` — so subclasses can override per-instance if they ever need to.

---

## What `migrate up` does

When `migrate up` encounters a migration with `requires_superuser=True`, it:

1. Prints a skip notice with a recovery hint pointing to `apply-as`.
2. **Halts the chain** at that migration.
3. Exits with code `1`.

```
⚡ Applying 20260528160001_first... ✅

⏸  Skipping migration 20260528160002_second:
  requires_superuser=True.  Apply this migration separately as a superuser:
    confiture migrate apply-as <role> 20260528160002
  Then re-run `confiture migrate up` to resume the chain.
```

### Why halt instead of skip-and-continue

The issue raised an open question about whether later migrations should silently continue past a skipped one.  Two reasons confiture **halts at first skip** in v1:

1. There is no `Migration.dependencies` field in the model.  Without a dependency graph there is no safe way to know whether migration N+1 silently depends on migration N's effect.  Continuing risks landing the schema in a state that no migration explicitly contemplates.

2. The recovery story is simple either way: operator runs `apply-as` for the skipped migration, then re-runs `migrate up` to resume.  No retry queue to manage; no partial-state surprises.

When the model gains a real dependency graph, this rule can be relaxed.  Until then, halt-and-resume is the safe default.

---

## Recovering with `migrate apply-as`

```bash
confiture migrate apply-as postgres 20260528160002 \
    --env production
```

`apply-as`:

- Connects with `apply_as.<role>.url` from the env config (env-var-expanded).
- Loads exactly the named version from `--migrations-dir`.
- Refuses if the version doesn't exist or is already applied (exit `2`).
- Runs `apply()` with `applied_by=<role>` so the `tb_confiture` row records who applied it.
- Returns exit `0` on success, `3` on SQL failure, `2` on configuration error.

### Config block

```yaml
# db/environments/production.yaml
apply_as:
  postgres:
    url: ${PROD_SUPERUSER_DATABASE_URL}
```

`${VAR}` expansion happens at use time.  We never silently fall back to the env's main `database_url` because the whole point of `apply-as` is to run as a *different* role.

### Full workflow

```bash
# 1. migrate up halts at the requires_superuser migration
confiture migrate up --env production
# → exit 1, "Skipping migration 20260528160002_second"

# 2. apply that one migration as postgres
confiture migrate apply-as postgres 20260528160002 --env production
# → exit 0

# 3. resume the chain
confiture migrate up --env production
# → exit 0, applies remaining migrations
```

---

## `applied_by` column

Starting in 0.17.0 the tracking table (`tb_confiture` by default) gains an `applied_by TEXT` column.

- **New installs** get the column at table-creation time.
- **Existing installs** auto-migrate via `ALTER TABLE … ADD COLUMN IF NOT EXISTS` the first time the migrator initializes against the database.
- **Pre-0.17.0 rows** keep `applied_by IS NULL` after the auto-migration — they were applied before the column existed, and we don't make up retroactive values.  **`applied_by IS NULL` means "applied before 0.17.0; role unknown."**  Treat this as a documented invariant; queries downstream must `COALESCE` or filter explicitly.
- For routine `migrate up`, `applied_by` is set to the connection's `current_user`.
- For `migrate apply-as`, `applied_by` is the explicit role argument.

---

## Comparison with the bootstrap workflow

`confiture bootstrap` (issue #137 part 1) handles the *systemic* version of the same problem — it fixes ownership at environment-provision time so subsequent migrations don't need to.

`requires_superuser` + `apply-as` handle the *per-migration* version, for one-off historical fixes that bootstrap didn't cover or that arrived later.

| Tool | Scope | Frequency | When to use |
|------|-------|-----------|-------------|
| `confiture bootstrap` | Environment-wide | Once per env (idempotent) | Initial provisioning, periodic drift check |
| `requires_superuser` + `apply-as` | Single migration | As needed | One-off historical fix during normal deploys |

Both can coexist.  If your team forgets to bootstrap and discovers wrong-owned objects in production, the `apply-as` path is the survival route.

---

## See Also

- [Bootstrap](bootstrap.md) — environment-wide setup
- [Ownership Coverage](ownership-coverage.md) — static + drift gates that complement these runtime tools
- [Incremental Migrations](02-incremental-migrations.md) — full migration authoring guide
- [CLI Reference](../reference/cli.md)
