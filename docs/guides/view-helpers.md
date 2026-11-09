# View Helpers

[← Back to Guides](../index.md) · [Hooks](hooks.md) · [Dry-Run →](dry-run.md)

Manage dependent views in a hand-written migration that alters columns, renames view columns, or changes column types.

---

## The Problem

PostgreSQL rejects `CREATE OR REPLACE VIEW` when column names or positions change:

```
ERROR: cannot change name of view column "allocation_id" to "id"
HINT: Use ALTER VIEW ... RENAME COLUMN ... to change name of view column instead.
```

Similarly, `ALTER COLUMN TYPE` fails when views depend on the column being altered. Without tooling, migration authors must manually `DROP VIEW ... CASCADE` every dependent view (including transitive dependencies like views-on-views), run their DDL, then recreate every view in the correct order. This is error-prone and verbose.

`confiture migrate diff --generate` already writes this for you: a generated column
change drops the views that read the column and creates them again after it, as plain
DDL in the migration. The **view helpers** are for a migration you write by hand: they
save every dependent view's definition, drop them, let your DDL run, then recreate them
in dependency order.

---

## Quick Start

Install them once per database:

```bash
confiture install-helpers --env production
```

This creates two PL/pgSQL functions in a `confiture` schema. Nothing else installs them:
`migrate up` writes nothing into a database but its ledger. Then use them in any migration:

```sql
-- 20260329120000_rename_allocation_column.up.sql

SELECT confiture.save_and_drop_dependent_views(ARRAY['public']);

ALTER TABLE public.tb_allocation RENAME COLUMN allocation_id TO id;

SELECT confiture.recreate_saved_views();
```

That's it. All dependent views are dropped before the ALTER and recreated after it, with indexes and comments restored.

---

## Where they live

The `confiture` schema the helpers live in (`saved_views`, `saved_view_indexes` and the two
functions) is confiture's own, like the tracking table: `confiture.core.ledger.bookkeeping_schemas()`
names it beside `bookkeeping_tables()`. A comparison of a migrated database with a freshly built
one leaves both out, e.g. `pg_dump --exclude-schema=confiture --exclude-table=tb_confiture …`.

`install-helpers` refuses (`CONFIG_017`, exit 5) when that schema would be on the connecting
role's `search_path`: a role itself named `confiture` under PostgreSQL's default
`"$user", public`, or a path that names `confiture`. Every unqualified table or view a
migration creates would then land in the helpers' schema instead of `public`. Connect as
another role, or pin the role's path: `ALTER ROLE confiture SET search_path = public`.

---

## How It Works

### What installing does

`confiture install-helpers` creates:

- A `confiture` schema (idempotent)
- Two PL/pgSQL functions: `confiture.save_and_drop_dependent_views()` and `confiture.recreate_saved_views()`
- Two support tables: `confiture.saved_views` and `confiture.saved_view_indexes`

Installing does not wrap any migration with view save/drop/recreate: you call the functions
explicitly in the migrations that need them, so views are only dropped when you say so.

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
confiture install-helpers --env local

# Check what SQL would run (dry-run)
confiture install-helpers --env local --dry-run

# Reinstall (e.g., after upgrade)
confiture install-helpers --env local --force
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
Dependent views block this column change. Drop them before the ALTER and create them
again after it, as `confiture migrate diff --generate` writes; or install the helpers
once (`confiture install-helpers`) and call confiture.save_and_drop_dependent_views()
before the ALTER and confiture.recreate_saved_views() after it
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
