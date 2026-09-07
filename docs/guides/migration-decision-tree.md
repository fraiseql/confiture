# Migration Decision Tree

[← Back to Guides](../index.md) · [Build from DDL](01-build-from-ddl.md)

**Which migration strategy should I use?**

This guide helps you choose the right migration strategy ("medium") for your specific scenario. Confiture provides 4 migration strategies, each optimized for different use cases.

## Quick Decision Flowchart

```
QUESTION:         Fresh       Prod        Simple      Complex
                  DB?         Data?       Change?     Change?
                  │           │           │           │
ANSWER:       ┌───┴───┐   ┌──┴──┐    ┌──┴──┐    ┌───┴───┐
              │ YES   │   │ YES │    │ YES │    │ YES   │
              └───┬───┘   └──┬──┘    └──┬──┘    └───┬───┘
                  │          │         │ └─ Downtime OK?
                  │          │         │    ├─ YES → M2
                  │          │         │    └─ NO → M4
                  ↓          ↓         ↓
              Medium 1   Medium 3  Medium 2/4
              (Build)    (Sync)    (Varies)
```

**MEDIUM SELECTION GUIDE:**

| Question | Answer | Use Medium |
|----------|--------|-----------|
| Building fresh database? | YES | Medium 1: Build from DDL |
| Need production data? | YES | Medium 3: Production Data Sync |
| Making simple schema change? | YES | Medium 2: Incremental Migrations |
| Large table + zero downtime? | YES | Medium 4: Schema-to-Schema |

**QUICK SUMMARY:**

┌──────────────────────────────────────────────────┐
│ Medium 1: Build from DDL                         │
│ • Fresh databases: <1 second                    │
│ • Best for: Onboarding, CI/CD, dev setup       │
└──────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────┐
│ Medium 2: Incremental Migrations                │
│ • Simple ALTERs: 1-30s downtime                 │
│ • Best for: Small schema updates                │
└──────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────┐
│ Medium 3: Production Data Sync                  │
│ • Copy data: 70K rows/sec                       │
│ • Best for: Debug production locally            │
└──────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────┐
│ Medium 4: Schema-to-Schema (FDW/COPY)          │
│ • Zero-downtime: 0-5s cutover                  │
│ • Best for: Major refactoring, 10M+ rows       │
└──────────────────────────────────────────────────┘
```

---

## The Four Mediums at a Glance

| Medium | Use Case | Speed | Downtime | Best For |
|--------|----------|-------|----------|----------|
| **1. Build from DDL** | Fresh databases | <1s | N/A | Development, CI/CD |
| **2. Incremental** | Simple changes | Fast | 1-30s | Small schema updates |
| **3. Production Sync** | Data copying | Medium | 0s | Dev/staging data |
| **4. Schema-to-Schema** | Complex migrations | Slow | 0-5s | Production refactoring |

---

## Detailed Decision Guide

### Scenario 1: Setting Up Development Environment

**Situation**: New developer joining team needs a working database

**Choose**: Medium 1 (Build from DDL)

```bash
confiture build --env local
```

**Why**:
- Fastest way to get a working database (<1 second)
- No migration replay needed
- Fresh start ensures consistency
- Perfect for onboarding

**Don't Use**:
- ❌ Medium 2 (slower - replays all migrations)
- ❌ Medium 3 (unnecessary - dev data in seeds)
- ❌ Medium 4 (overkill - no existing database)

---

### Scenario 2: Adding a New Column

**Situation**: Add `bio TEXT` column to `users` table (1M rows)

**Choose**: Medium 2 (Incremental Migrations)

```bash
# Edit schema
vim db/schema/10_tables/users.sql

# Generate migration
confiture migrate generate --name add_user_bio

# Apply
confiture migrate up
```

**Why**:
- Simple ALTER operation
- Fast execution (seconds)
- Reversible via down() method
- Low risk

**Don't Use**:
- ❌ Medium 1 (would drop existing data)
- ❌ Medium 3 (doesn't change schema)
- ❌ Medium 4 (overkill for simple change)

---

### Scenario 3: Debugging Production Issue

**Situation**: Need to reproduce production bug locally with real data

**Choose**: Medium 3 (Production Data Sync)

```bash
confiture sync \
    --from production \
    --to local \
    --tables users,posts,comments \
    --anonymize
```

**Why**:
- Get production data safely
- PII automatically anonymized
- Fast streaming with COPY
- No schema changes needed

**Don't Use**:
- ❌ Medium 1 (doesn't copy data)
- ❌ Medium 2 (for schema changes only)
- ❌ Medium 4 (for schema migrations, not data sync)

---

### Scenario 4: Changing Column Type

**Situation**: Change `user_id` from INTEGER to BIGINT (100M rows)

#### Option A: Small Downtime Acceptable

**Choose**: Medium 2 (Incremental Migrations)

```python
def up(self):
    self.execute("ALTER TABLE posts ALTER COLUMN user_id TYPE BIGINT")
```

**Tradeoff**:
- ✅ Simple implementation
- ✅ One SQL statement
- ❌ Table locked for ~30 seconds

#### Option B: Zero Downtime Required

**Choose**: Medium 4 (Schema-to-Schema)

```bash
confiture schema-to-schema \
    --source production \
    --target production_new \
    --strategy fdw
```

**Tradeoff**:
- ✅ Zero downtime
- ✅ Safe rollback
- ❌ More complex setup
- ❌ Requires 2x storage temporarily

---

### Scenario 5: Major Refactoring

**Situation**: Splitting `users.full_name` → `first_name` + `last_name` (10M rows)

**Choose**: Medium 4 (Schema-to-Schema)

```yaml
# db/schema_migration.yaml
tables:
  users:
    strategy: fdw
    custom_sql: |
      INSERT INTO production_new.users (id, first_name, last_name)
      SELECT
        id,
        split_part(full_name, ' ', 1) as first_name,
        split_part(full_name, ' ', 2) as last_name
      FROM old_schema.users
```

**Why**:
- Complex data transformation
- Large table
- Zero-downtime cutover
- Safe rollback plan

**Don't Use**:
- ❌ Medium 2 (would drop old column, lose data)
- Risk of data loss without careful backfill

---

### Scenario 6: CI/CD Pipeline

**Situation**: Automated tests need fresh database for each run

**Choose**: Medium 1 (Build from DDL)

```yaml
# .github/workflows/test.yml
- name: Setup database
  run: confiture build --env ci

- name: Run tests
  run: pytest tests/
```

**Why**:
- Fastest setup (<1s for 100 tables)
- Consistent state
- No migration replay overhead
- Perfect for CI/CD

**Don't Use**:
- ❌ Medium 2 (slower - replays migrations)

---

### Scenario 7: Creating Staging Environment

**Situation**: Need staging environment with production-like data

**Choose**: Combination of Medium 1 + Medium 3

```bash
# Step 1: Build schema
confiture build --env staging

# Step 2: Sync production data
confiture sync \
    --from production \
    --to staging \
    --anonymize
```

**Why**:
- Fresh schema (consistent with code)
- Real production data
- PII anonymized
- Fast setup

---

## Performance Comparison

### Medium 1: Build from DDL

| Database Size | Time |
|---------------|------|
| 10 tables | 0.3s |
| 50 tables | 0.8s |
| 100 tables | 1.2s |

**Use when**: Fresh database, speed matters

---

### Medium 2: Incremental Migrations

| Operation | 1M rows | 10M rows | 100M rows |
|-----------|---------|----------|-----------|
| Add column (nullable) | 0.1s | 0.5s | 2s |
| Add index | 5s | 30s | 5min |
| Change type | 10s | 1min | 10min |

**Use when**: Simple changes, tolerate downtime

---

### Medium 3: Production Data Sync

| Data Size | Speed | Duration |
|-----------|-------|----------|
| 1M rows | 70K rows/sec | 14s |
| 10M rows | 70K rows/sec | 2.3min |
| 100M rows | 70K rows/sec | 23min |

With anonymization (3 columns): 6.5K rows/sec

**Use when**: Need production data locally

---

### Medium 4: Schema-to-Schema

| Table Size | Strategy | Duration |
|------------|----------|----------|
| 1M rows | FDW | 5min |
| 10M rows | FDW | 30min |
| 100M rows | COPY | 2-3 hours |
| 1B rows | COPY | 2-3 days |

**Use when**: Zero-downtime + complex changes

---

## Risk Assessment

### Low Risk ✅

- Medium 1 on empty database
- Medium 2 adding nullable column
- Medium 3 with anonymization

### Medium Risk ⚠️

- Medium 2 with NOT NULL constraint
- Medium 2 on large tables (>10M rows)
- Medium 3 without anonymization review

### High Risk 🔴

- Medium 2 changing column type (large table)
- Medium 2 without rollback testing
- Medium 4 without validation phase

**Always**: Test in dev → staging → production

---

## Common Mistakes

### ❌ Using Medium 2 for Fresh Databases

**Wrong**:
```bash
# Slow: Replays 100 migrations
confiture migrate up --env local
```

**Right**:
```bash
# Fast: Builds from DDL
confiture build --env local
```

---

### ❌ Using Medium 4 for Simple Changes

**Wrong**:
```bash
# Overkill for adding a column
confiture schema-to-schema --add-column bio
```

**Right**:
```bash
# Simple migration
confiture migrate generate --name add_bio
confiture migrate up
```

---

### ❌ Not Anonymizing Production Data

**Wrong**:
```bash
# PII leaked to local!
confiture sync --from production --to local
```

**Right**:
```bash
# PII anonymized
confiture sync \
    --from production \
    --to local \
    --anonymize
```

---

## Best Practices Checklist

### Development Workflow
- ✅ Use Medium 1 for fresh databases
- ✅ Use Medium 2 for schema iterations
- ✅ Test migrations locally before staging

### Staging Workflow
- ✅ Apply migrations with Medium 2
- ✅ Verify with production-like data (Medium 3)
- ✅ Test rollback procedures

### Production Workflow
- ✅ Simple changes: Medium 2
- ✅ Complex changes: Medium 4
- ✅ Always have rollback plan
- ✅ Monitor during migration

---

## Quick Reference Table

| If you need to... | Use Medium | Command |
|-------------------|------------|---------|
| Set up new database | 1 | `confiture build` |
| Add column | 2 | `confiture migrate up` |
| Create index | 2 | `confiture migrate up` |
| Get production data | 3 | `confiture sync` |
| Change column type (small) | 2 | `confiture migrate up` |
| Change column type (large) | 4 | `confiture schema-to-schema` |
| Major refactoring | 4 | `confiture schema-to-schema` |
| CI/CD test database | 1 | `confiture build --env ci` |
| Debug production locally | 3 | `confiture sync --anonymize` |

---

## Still Not Sure?

1. **Start conservative**: Use Medium 2 for most changes
2. **Test in staging**: Validate performance before production
3. **Measure table size**: `SELECT pg_size_pretty(pg_total_relation_size('users'))`
4. **Check row count**: `SELECT COUNT(*) FROM users`
5. **Estimate downtime**: Run on copy of production data

If table is >10M rows OR zero-downtime required → Use Medium 4

Otherwise → Use Medium 2

---

## See Also

- [Build from DDL](./01-build-from-ddl.md) - Fresh databases in <1 second
- [Incremental Migrations](./02-incremental-migrations.md) - ALTER-based changes
- [Production Data Sync](./03-production-sync.md) - Copy and anonymize data
- [Schema-to-Schema](./04-schema-to-schema.md) - Zero-downtime migrations
- [Examples](https://github.com/fraiseql/confiture/tree/main/examples) - Working examples for each strategy

---

**Part of the Confiture documentation** 🍓

*Making migration decisions sweet and simple*
