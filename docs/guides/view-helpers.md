# View Helpers

[← Back to Guides](../index.md) · [Hooks](hooks.md) · [Dry-Run →](dry-run.md)

Automatically manage dependent views when migrations alter columns, rename view columns, or change column types.

---

## The Problem

PostgreSQL rejects `CREATE OR REPLACE VIEW` when column names or positions change:

```
ERROR: cannot change name of view column "allocation_id" to "id"
HINT: Use ALTER VIEW ... RENAME COLUMN ... to change name of view column instead.
```

Similarly, `ALTER COLUMN TYPE` fails when views depend on the column being altered. Without tooling, migration authors must manually `DROP VIEW ... CASCADE` every dependent view (including transitive dependencies like views-on-views), run their DDL, then recreate every view in the correct order. This is error-prone and verbose.

Confiture's **view helpers** automate this: save all dependent view definitions, drop them, let your DDL run, then recreate them in the correct dependency order.

---

## Quick Start

View helpers are enabled by default (`migration.view_helpers: auto`). On your first `confiture migrate up`, confiture installs two PL/pgSQL functions in the `confiture` schema. Use them in any migration:

```sql
-- 20260329120000_rename_allocation_column.up.sql

SELECT confiture.save_and_drop_dependent_views(ARRAY['public']);

ALTER TABLE public.tb_allocation RENAME COLUMN allocation_id TO id;

SELECT confiture.recreate_saved_views();
```

That's it. All dependent views are dropped before the ALTER and recreated after it, with indexes and comments restored.

---

## Configuration

In your environment YAML (`db/environments/local.yaml`):

```yaml
migration:
  view_helpers: auto    # default
```

| Value | Behavior |
|-------|----------|
| `auto` | Install helper functions automatically on first `migrate up` (default) |
| `manual` | You run `confiture admin install-helpers` yourself before using them |
| `off` | Disabled — manage views in your migration SQL manually |

To opt out, set `view_helpers: off`. Invalid values (typos) are rejected at config load time.

---

## How It Works

### What `auto` does

On `confiture migrate up`, if helpers are not yet installed in the database, confiture creates:

- A `confiture` schema (idempotent)
- Two PL/pgSQL functions: `confiture.save_and_drop_dependent_views()` and `confiture.recreate_saved_views()`
- Two support tables: `confiture.saved_views` and `confiture.saved_view_indexes`

This is a one-time setup. Once installed, the functions are available for any migration to call.

### What `auto` does NOT do

The `auto` setting does **not** wrap every migration with view save/drop/recreate. You still call the functions explicitly in migrations that need them. This keeps the behavior predictable — views are only dropped when you say so.

### The save/drop/recreate cycle

```
confiture.save_and_drop_dependent_views(ARRAY['public', 'catalog'])
    │
    ├─ Discover all views depending on tables in those schemas
    │   (recursive: views on views on views...)
    ├─ Save definitions, indexes, and comments
    └─ Drop in reverse dependency order (deepest first)

-- Your ALTER/RENAME/TYPE CHANGE statements run here --

confiture.recreate_saved_views()
    │
    ├─ Recreate in forward dependency order (shallowest first)
    ├─ Refresh materialized views
    ├─ Restore indexes on materialized views
    └─ Restore comments
```

---

## Usage in SQL Migrations

### Column rename

```sql
-- 20260329120000_rename_column.up.sql

SELECT confiture.save_and_drop_dependent_views(ARRAY['public']);
ALTER TABLE public.tb_order RENAME COLUMN order_id TO id;
SELECT confiture.recreate_saved_views();
```

### Column type change

```sql
-- 20260329130000_pk_to_bigint.up.sql

SELECT confiture.save_and_drop_dependent_views(ARRAY['public', 'catalog']);

ALTER TABLE catalog.tb_machine ALTER COLUMN pk_machine TYPE BIGINT;
ALTER TABLE catalog.tb_sensor ALTER COLUMN pk_sensor TYPE BIGINT;

SELECT confiture.recreate_saved_views();
```

### Multiple schemas

Pass all schemas whose tables have dependent views:

```sql
SELECT confiture.save_and_drop_dependent_views(ARRAY['public', 'catalog', 'reporting']);
-- ... DDL ...
SELECT confiture.recreate_saved_views();
```

### All user schemas

Pass `NULL` (or omit the argument) to scan every non-system schema:

```sql
SELECT confiture.save_and_drop_dependent_views(NULL);
-- ... DDL ...
SELECT confiture.recreate_saved_views();
```

---

## Usage in Python Migrations

The `ViewManager` Python class provides the same functionality:

```python
from confiture.core.view_manager import ViewManager
from confiture.models.migration import Migration


class UpgradePkToBigint(Migration):
    version = "20260329140000"
    name = "upgrade_pk_to_bigint"

    def up(self):
        vm = ViewManager(self.connection)
        vm.save_and_drop_dependent_views(schemas=["public", "catalog"])

        self.execute("ALTER TABLE catalog.tb_machine ALTER COLUMN pk_machine TYPE BIGINT")

        vm.recreate_saved_views()
```

### ViewManager API

| Method | Description |
|--------|-------------|
| `save_and_drop_dependent_views(schemas)` | Save definitions and drop all dependent views. Returns count. |
| `recreate_saved_views()` | Recreate all saved views in correct order. Returns count. |
| `discover_dependent_views(schemas)` | Discover without dropping (inspection only). |
| `get_saved_views()` | Return currently saved view list (for debugging). |
| `install_helpers()` | Install the SQL helper functions manually. |
| `helpers_installed()` | Check whether helpers are already installed. |

---

## Manual Installation

If you prefer `manual` mode:

```bash
# Install helper functions
confiture admin install-helpers --env local

# Check what SQL would run (dry-run)
confiture admin install-helpers --env local --dry-run

# Reinstall (e.g., after upgrade)
confiture admin install-helpers --env local --force
```

---

## What Gets Preserved

When views are saved and recreated, the following are preserved:

- View definitions (via `pg_get_viewdef`)
- Materialized view data (refreshed after recreation)
- Indexes on materialized views
- Comments on views and materialized views
- Dependency order (recreated shallowest-first)

---

## Error Handling

If a migration fails with "cannot change name of view column" and the helper functions were not called, confiture provides a resolution hint:

```
Dependent views block this column change. Ensure 'migration.view_helpers'
is not set to 'off' or 'manual' in your environment config, then call
confiture.save_and_drop_dependent_views() before the ALTER and
confiture.recreate_saved_views() after it
```

---

## FAQ

**Do I need to call the helpers for every migration?**
No. Only call them in migrations that alter columns referenced by views (renames, type changes, column reordering in `CREATE OR REPLACE VIEW`).

**Is it safe to call when no views exist?**
Yes. If no dependent views are found, both functions return 0 and do nothing.

**What happens if `recreate_saved_views()` fails?**
In transactional migrations, the entire migration (including the drops) is rolled back. Your views are restored to their original state.

**Can I inspect what would be dropped before running?**
Use `discover_dependent_views()` in Python, or query `pg_depend`/`pg_rewrite` directly. The `save_and_drop_dependent_views` function in SQL does not have a dry-run mode — use the Python API for inspection.
