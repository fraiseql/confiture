# Schema-to-Schema Migration

[← Back to Guides](../index.md) · [Production Sync](03-production-sync.md) · [Hooks →](hooks.md)

**Zero-downtime migrations for major schema refactoring using FDW**

---

## Overview

Schema-to-Schema migration enables zero-downtime database migrations by running old and new schemas side-by-side, then seamlessly cutting over.

> **"Two schemas, zero downtime"**

Uses PostgreSQL's Foreign Data Wrapper (FDW) to connect new schema to old, allowing background data migration while the old schema remains operational.

### When to Use

| Use Case | Schema-to-Schema |
|----------|-----------------|
| Column renames | Perfect |
| Type changes | Perfect |
| Large tables (>10M rows) | Perfect |
| Table splits/merges | Perfect |
| Simple column add/drop | Use Medium 2 |
| Fresh databases | Use Medium 1 |

---

## Migration Process

```
1. SETUP      → Create new database with new schema
2. FDW SETUP  → Connect old DB to new DB via FDW
3. ANALYZE    → Auto-select strategy per table
4. MIGRATE    → Copy data in background (app keeps running)
5. VERIFY     → Compare row counts, verify integrity
6. CUTOVER    → Switch app to new database (0-5s)
7. CLEANUP    → Remove FDW after monitoring period
```

---

## Quick Start

```bash
# 1. Create new database
confiture build --env new_production --from-ddl

# 2. Setup FDW connection
confiture migrate schema-to-schema setup \
    --source old_production \
    --target new_production

# 3. Analyze tables
confiture migrate schema-to-schema analyze --target new_production

# 4. Migrate with column mapping
confiture migrate schema-to-schema migrate \
    --target new_production \
    --mapping db/migration/column_mapping.yaml

# 5. Verify
confiture migrate schema-to-schema verify --target new_production

# 6. Cutover (update app config to new_production)

# 7. Cleanup (after monitoring period)
confiture migrate schema-to-schema cleanup --target new_production
```

---

## Two Strategies

| Strategy | Speed | Best For |
|----------|-------|----------|
| **FDW** | 500K rows/sec | <10M rows, complex SQL |
| **COPY** | 6M rows/sec | ≥10M rows, bulk data |

Confiture auto-selects based on table size (threshold: 10M rows).

### Performance Comparison

| Table Size | FDW Time | COPY Time | Speedup |
|------------|----------|-----------|---------|
| 1M rows | 2.0s | 0.17s | 12x |
| 10M rows | 20s | 1.7s | 12x |
| 100M rows | 3.3min | 17s | 12x |

---

## Column Mapping

```yaml
# db/migration/column_mapping.yaml
users:
  source_table: old_users
  target_table: users
  columns:
    full_name: display_name  # Renamed
    email: email             # Same

posts:
  source_table: blog_posts
  target_table: posts
  columns:
    post_title: title
    post_body: content
    author_id: user_id
```

### Single Table Migration

```bash
confiture migrate schema-to-schema migrate-table \
    --target new_production \
    --source-table old_users \
    --target-table users \
    --mapping "full_name:display_name,email:email"
```

---

## Cutover Strategies

### Blue-Green (Recommended)

```bash
# Update app config
DATABASE_URL=postgresql://new-db.example.com/myapp_v2

# Rolling restart
kubectl rollout restart deployment/app
```

### Rollback

```bash
# Revert to old database
DATABASE_URL=postgresql://old-db.example.com/myapp

# Restart app
kubectl rollout restart deployment/app
```

---

## Best Practices

1. **Test on staging first** - Never migrate production without testing
2. **Use read-only source credentials** - Prevent accidental writes
3. **Migrate during low-traffic** - Reduces risk
4. **Monitor throughout** - Watch both databases
5. **Keep old DB warm** - 1-2 weeks for rollback safety
6. **Document mappings** - Add comments explaining renames

---

## Verification

```bash
# Row count comparison
confiture migrate schema-to-schema verify \
    --target new_production \
    --tables users,posts
```

```sql
-- Check foreign key integrity
SELECT COUNT(*) FROM posts p
LEFT JOIN users u ON p.user_id = u.id
WHERE u.id IS NULL;
-- Expected: 0
```

---

## Common Issues

### "extension postgres_fdw does not exist"
```sql
CREATE EXTENSION postgres_fdw;
```

### "could not connect to server"
Check firewall rules between databases. Verify pg_hba.conf allows connection.

### "column does not exist"
Verify column mapping matches actual source/target columns.

### "row count mismatch"
Data changed during migration. Truncate target and re-migrate.

---

## See Also

- [Incremental Migrations](./02-incremental-migrations.md) - For simple changes
- [Build from DDL](./01-build-from-ddl.md) - For creating new database
- [Dry-Run Guide](./dry-run.md) - Test migrations safely
- [CLI Reference](../reference/cli.md) - All schema-to-schema commands
