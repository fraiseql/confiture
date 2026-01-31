# Prep-Seed Validation Guide

## Overview

The **prep-seed pattern** is a sophisticated data seeding strategy used when transforming UUID foreign keys into BIGINT integer keys. This guide explains how to validate your prep-seed implementation using Confiture's 5-level validation system.

### The Pattern

In the prep-seed pattern:
1. **Prep seed tables** in the `prep_seed` schema contain data with UUID foreign keys
2. **Resolution functions** transform the prep seed data into final tables with BIGINT foreign keys
3. This enables referential integrity without depending on final table IDs

Example flow:
```sql
-- 1. Prep seed phase (your seed files)
INSERT INTO prep_seed.tb_manufacturer (id, name, fk_organization_id)
VALUES ('550e8400-e29b-41d4-a716-446655440000', 'Acme Corp', '...uuid...');

-- 2. Resolution phase (fn_resolve_tb_manufacturer runs)
INSERT INTO catalog.tb_manufacturer (id, name, fk_organization_id)
SELECT
  gen_bigint_from_uuid(prep.id),
  prep.name,
  final.id  -- Join to get actual BIGINT FK
FROM prep_seed.tb_manufacturer prep
LEFT JOIN catalog.tb_organization final ON final.id = gen_bigint_from_uuid(prep.fk_organization_id);
```

### Why Validation Matters

Missing or incorrect prep-seed validation led to the **360-test-failure incident** where:
- Resolution functions referenced the wrong schema (schema drift)
- FK transformations were missing (NULLs in final table)
- This wasn't caught until runtime in production-like environments

The 5-level validation system catches these issues early.

---

## Five Validation Levels

### Level 1: Seed File Validation ⚡ (~1s)

**What it checks:**
- Seed files target `prep_seed` schema, not final tables
- FK columns use `_id` suffix (e.g., `fk_organization_id`)
- UUID format is valid in seed data

**When to use:** Pre-commit hook

**Example violations:**
```
❌ Seed INSERT targets catalog.tb_x but should target prep_seed
❌ FK column 'fk_organization' missing _id suffix (should be 'fk_organization_id')
✅ FIXABLE with --fix
```

**Command:**
```bash
confiture seed validate --prep-seed --level 1
```

---

### Level 2: Schema Consistency ⚡ (~2s)

**What it checks:**
- Final table exists for each prep_seed table
- FK columns map correctly (UUID columns → BIGINT columns)
- Trinity pattern in final tables (id UUID, pk_* BIGINT, fk_* BIGINT)
- Self-references handled correctly

**When to use:** Pre-commit hook

**Example violations:**
```
❌ prep_seed.tb_x has no corresponding final table catalog.tb_x
❌ FK type mismatch: prep_seed.tb_x.fk_org_id (UUID) but final table expects BIGINT
✅ FIXABLE with --fix
```

**Command:**
```bash
confiture seed validate --prep-seed --level 2
```

---

### Level 3: Resolution Function Validation 🔴 CRITICAL (~3s)

**What it checks:**
- **Schema drift**: Functions reference correct schema (e.g., `catalog.tb_x`, not `tenant.tb_x`)
- FK transformations: JOINs correctly transform UUID to BIGINT
- NULL handling: Non-NULL FKs don't become NULL after resolution

**When to use:** Pre-commit hook, mandatory check

**Example violations:**
```
🔴 CRITICAL: Function refs tenant.tb_x but table in catalog.tb_x
🔴 CRITICAL: Missing JOIN for FK transformation in resolution function
```

**This is the most important level** - detects the schema drift that caused 360 test failures.

**Command:**
```bash
confiture seed validate --prep-seed --level 3
```

---

### Level 4: Runtime Validation 🔧 (~10s)

**What it checks:**
- Tables exist in target database
- Column types match expectations
- Dry-run resolution without loading data
- No SQL errors in resolution logic

**When to use:** CI/CD (requires database)

**Example violations:**
```
❌ Table catalog.tb_x not found in database
❌ Column catalog.tb_x.fk_org_id type is INT, expected BIGINT
```

**Command:**
```bash
confiture seed validate --prep-seed --level 4 --database-url postgresql://localhost/test
```

---

### Level 5: Full Execution 🧪 (~30s)

**What it checks:**
- Actual seed data loads into prep_seed tables
- Resolution functions execute successfully
- Final data is valid (no NULLs where not allowed)
- Constraints satisfied (UNIQUE, FOREIGN KEY)
- Referential integrity maintained

**When to use:** CI/CD, integration tests (requires real database)

**Example violations:**
```
❌ NULL foreign key in catalog.tb_x.fk_org_id (row id=123)
❌ UNIQUE constraint violated after resolution (duplicate identifier)
❌ Self-referencing FK not handled with two-pass resolution
```

**Command:**
```bash
confiture seed validate --prep-seed --full-execution --database-url postgresql://localhost/test
```

---

## Quick Start

### For Pre-Commit Hook

Validate Levels 1-3 (static, ~3-5s, no database):

```bash
# One-time setup
# Add to .pre-commit-config.yaml:
- id: prep-seed-validate
  name: Validate prep-seed pattern
  entry: confiture seed validate --prep-seed --static-only
  language: system
  files: '^(db/seeds/prep|db/schema/functions/fn_resolve)'
  stages: [commit]
```

Run manually:
```bash
confiture seed validate --prep-seed --static-only
```

### For CI/CD Pipeline

#### Stage 1: Quick Check (Levels 1-3)
```bash
# Run before database tests
confiture seed validate --prep-seed --static-only --format json --output report-static.json

# Fail on violations
if [ $? -ne 0 ]; then
  echo "❌ Pre-seed validation failed"
  cat report-static.json | jq '.violations'
  exit 1
fi
```

#### Stage 2: Database Tests (Levels 4-5)
```bash
# After database is ready
export DATABASE_URL="postgresql://user:pass@localhost/test_db"

# Run full validation
confiture seed validate --prep-seed --full-execution \
  --database-url $DATABASE_URL \
  --format json \
  --output report-full.json

# Check for critical violations
CRITICALS=$(jq '.violations_by_severity.CRITICAL | length' report-full.json)
if [ $CRITICALS -gt 0 ]; then
  echo "❌ Critical violations found:"
  jq '.violations_by_severity.CRITICAL' report-full.json
  exit 1
fi
```

### Docker Example

```dockerfile
# In your test Dockerfile
FROM postgres:15

# Install confiture
COPY requirements.txt .
RUN pip install confiture

# Copy seed files
COPY db/ /app/db/

# Run tests
CMD ["sh", "-c", "
  # Start PostgreSQL
  postgres -D /var/lib/postgresql/data &
  sleep 2;

  # Create test database
  createdb test_db;

  # Validate prep-seed
  confiture seed validate --prep-seed --full-execution \
    --database-url postgresql://postgres@localhost/test_db;
"]
```

---

## Output Formats

### Text Format (Default)
```bash
confiture seed validate --prep-seed

# Output:
# Prep-Seed Validation Report
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Files scanned: 5
# Violations found: 2
#
# CRITICAL (1 found)
# ┏━━━━━━┳━━━━┳━━━━━━━━━━━┳━━━━━━━━━━━━━━┓
# ┃ File ┃ ... ┃ Message   ┃ Details     ┃
# ┣━━━━━━╋━━━━╋━━━━━━━━━━━╋━━━━━━━━━━━━━━┫
# ...
```

### JSON Format (For CI/CD)
```bash
confiture seed validate --prep-seed --format json --output report.json

# Output structure:
{
  "violations": [...],
  "violation_count": 2,
  "files_scanned": 5,
  "scanned_files": [...],
  "has_violations": true,
  "violations_by_severity": {
    "CRITICAL": [...],
    "ERROR": [...],
    "WARNING": [...],
    "INFO": [...]
  }
}
```

### CSV Format (For Analysis)
```bash
confiture seed validate --prep-seed --format csv --output violations.csv

# Columns: File, Line, Severity, Pattern, Message, Fix Available, Suggestion
```

---

## Common Issues and Solutions

### Issue 1: Schema Drift (Most Critical)

**Problem:**
```
🔴 CRITICAL: Function refs tenant.tb_manufacturer but table in catalog.tb_manufacturer
```

**Root Cause:**
Resolution function references wrong schema. Common with schema name changes or copy-paste errors.

**Fix:**
```bash
# Option 1: Fix automatically
confiture seed validate --prep-seed --level 3 --fix --dry-run
confiture seed validate --prep-seed --level 3 --fix

# Option 2: Manual fix in fn_resolve_tb_manufacturer.sql
# Change: INSERT INTO tenant.tb_manufacturer ...
# To:     INSERT INTO catalog.tb_manufacturer ...
```

**Validation:**
```bash
confiture seed validate --prep-seed --level 3  # Should pass now
```

---

### Issue 2: Missing FK Transformation

**Problem:**
```
❌ ERROR: Missing JOIN for FK transformation in resolution function
```

**Root Cause:**
Resolution function doesn't include JOINs to transform UUID FKs to BIGINT IDs.

**Example Fix:**
```sql
-- ❌ WRONG: Missing JOIN
CREATE OR REPLACE FUNCTION fn_resolve_tb_manufacturer() AS $$
INSERT INTO catalog.tb_manufacturer (id, name, fk_organization_id)
SELECT
  gen_bigint_from_uuid(prep.id),
  prep.name,
  prep.fk_organization_id  -- ❌ Still a UUID!
FROM prep_seed.tb_manufacturer prep;
$$ LANGUAGE SQL;

-- ✅ CORRECT: With JOIN
CREATE OR REPLACE FUNCTION fn_resolve_tb_manufacturer() AS $$
INSERT INTO catalog.tb_manufacturer (id, name, fk_organization_id)
SELECT
  gen_bigint_from_uuid(prep.id),
  prep.name,
  final.id  -- ✅ BIGINT from final table
FROM prep_seed.tb_manufacturer prep
LEFT JOIN catalog.tb_organization final
  ON final.id = gen_bigint_from_uuid(prep.fk_organization_id);
$$ LANGUAGE SQL;
```

---

### Issue 3: NULL Foreign Keys After Resolution

**Problem:**
```
❌ ERROR: NULL foreign key in catalog.tb_x.fk_org_id (row id=123)
```

**Root Cause:**
LEFT JOIN finds no matching record (UUID not found in final table).

**Debugging:**
```bash
# Run Level 5 with verbose output
confiture seed validate --prep-seed --full-execution --database-url $DB_URL

# Check manually
SELECT prep.id, prep.fk_organization_id, final.id
FROM prep_seed.tb_manufacturer prep
LEFT JOIN catalog.tb_organization final
  ON final.id = gen_bigint_from_uuid(prep.fk_organization_id)
WHERE final.id IS NULL;
```

**Solutions:**
1. Ensure referenced prep_seed data exists
2. Use COALESCE for optional FKs
3. Add error logging in resolution function

---

### Issue 4: Self-Referencing FK

**Problem:**
```
❌ ERROR: Self-referencing FK not handled with two-pass resolution
```

**Root Cause:**
Table references itself (e.g., tb_employee.fk_manager_id → tb_employee.id), but resolution tries single-pass.

**Fix:**
```sql
-- ✅ Two-pass resolution
CREATE OR REPLACE FUNCTION fn_resolve_tb_employee() AS $$
BEGIN
  -- Pass 1: Insert without self-references
  INSERT INTO catalog.tb_employee (id, name, fk_manager_id)
  SELECT
    gen_bigint_from_uuid(prep.id),
    prep.name,
    NULL  -- Will be filled in Pass 2
  FROM prep_seed.tb_employee prep
  WHERE prep.fk_manager_id IS NULL;

  -- Pass 2: Update with resolved self-references
  UPDATE catalog.tb_employee target
  SET fk_manager_id = manager.id
  FROM prep_seed.tb_employee prep
  JOIN catalog.tb_employee manager
    ON manager.id = gen_bigint_from_uuid(prep.fk_manager_id)
  WHERE target.id = gen_bigint_from_uuid(prep.id)
    AND prep.fk_manager_id IS NOT NULL;
END;
$$ LANGUAGE PLPGSQL;
```

---

## Best Practices

### 1. **Run Levels Appropriately**

| Level | Environment | Speed | Use Case |
|-------|-------------|-------|----------|
| 1-3   | Pre-commit  | ~5s   | Catch basic issues before push |
| 4     | CI (build)  | ~10s  | Verify database compatibility |
| 5     | CI (test)   | ~30s  | Integration test after seeds load |

### 2. **Naming Conventions**

Use consistent naming to help validation:
- Seed files: `db/seeds/prep/*.sql` or `db/seeds/prep_seed/*.sql`
- Resolution functions: `db/schema/functions/fn_resolve_*.sql`
- Schema names: `prep_seed` for preparation, `catalog`/`tenant` for final

### 3. **Documentation**

Document non-obvious transformations:
```sql
-- fn_resolve_tb_manufacturer.sql
-- Transforms UUID identifiers in prep_seed.tb_manufacturer
-- to BIGINT identifiers in catalog.tb_manufacturer
--
-- Handles:
-- - UUID to BIGINT ID conversion via gen_bigint_from_uuid()
-- - FK transformation: fk_organization_id → LEFT JOIN catalog.tb_organization
-- - NULL handling: Non-required FKs can be NULL
--
-- Dependencies: prep_seed.tb_manufacturer, catalog.tb_organization
```

### 4. **Dry-Run Before Committing**

```bash
# Preview what would be fixed
confiture seed validate --prep-seed --level 3 --fix --dry-run

# Only commit if acceptable
git add db/
git commit -m "Fix prep-seed schema drift"
```

### 5. **Monitor in Production**

For production databases:
```bash
# After deployment
confiture seed validate --prep-seed --level 3 \
  --database-url "postgresql://prod-user:pass@prod-host/prod_db" \
  --format json \
  --output /var/log/prep-seed-check-$(date +%s).json

# Alert on CRITICAL violations
if grep -q "CRITICAL" *.json; then
  send_alert "Prep-seed validation failed in production"
fi
```

---

## Troubleshooting

### Validation passes locally but fails in CI

**Cause:** Different database schemas or missing tables in CI environment

**Solution:**
```bash
# Check what's different
confiture seed validate --prep-seed --level 4 \
  --database-url $CI_DB_URL \
  --database-url $LOCAL_DB_URL  # Compare outputs
```

### Memory issues with large seed files

**Cause:** Level 5 (execution) loads entire seed dataset into memory

**Solution:**
```bash
# Break large seeds into smaller files
# Each file < 10MB recommended for 4GB systems
split -l 100000 large_seed.sql chunk_

# Validate chunks individually
for chunk in chunk_*; do
  confiture seed validate --prep-seed --full-execution \
    --database-url $DB_URL \
    --seeds-dir $(dirname $chunk)
done
```

### Performance: Validation too slow

**Cause:** Running full validation (Level 5) unnecessarily

**Solution:**
```bash
# Use appropriate level
- Pre-commit:     --static-only (1-3, ~3s)
- Unit tests:     --level 3 (resolve functions, ~3s)
- Integration:    --level 4 (runtime, ~10s)
- Acceptance:     --level 5 (full execution, ~30s)
```

---

## See Also

- [Seed Validation Guide](./seed-validation.md) - General seed validation
- [Migration Strategies](./migration-decision-tree.md) - When to use prep-seed vs other patterns
- [ARCHITECTURE.md](../../ARCHITECTURE.md) - Technical design
