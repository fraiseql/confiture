# Prep-Seed Validation Example

This example demonstrates Confiture's **5-level prep-seed validation system** for catching data transformation issues before deployment.

## Scenario

You're building an e-commerce system with two schemas:
- **`prep_seed`**: Tables with UUID foreign keys (easier for seeding)
- **`catalog`**: Production tables with BIGINT foreign keys (for performance)

The **prep-seed pattern** uses resolution functions to transform data from prep-seed to catalog schema.

## Project Structure

```
db/
├── schema/
│   ├── prep_seed/
│   │   ├── tb_manufacturer.sql      # Prep-seed table DDL
│   │   └── tb_product.sql           # Prep-seed table DDL
│   ├── catalog/
│   │   ├── tb_manufacturer.sql      # Final table DDL
│   │   └── tb_product.sql           # Final table DDL
│   └── functions/
│       ├── fn_resolve_tb_manufacturer.sql
│       └── fn_resolve_tb_product.sql
│
└── seeds/
    └── prep/
        ├── 01_manufacturers.sql     # Seed data
        └── 02_products.sql          # Seed data
```

## Files in This Example

### Schema Files

**db/schema/prep_seed/tb_manufacturer.sql** - Prep-seed table with UUID FKs:
```sql
CREATE TABLE prep_seed.tb_manufacturer (
    id UUID PRIMARY KEY,
    name TEXT NOT NULL,
    country_code TEXT NOT NULL
);
```

**db/schema/catalog/tb_manufacturer.sql** - Final table with trinity pattern:
```sql
CREATE TABLE catalog.tb_manufacturer (
    id UUID NOT NULL,
    pk_manufacturer BIGINT PRIMARY KEY,
    name TEXT NOT NULL,
    country_code TEXT NOT NULL
);
```

### Resolution Functions

**db/schema/functions/fn_resolve_tb_manufacturer.sql**:
- Transforms prep_seed data to catalog schema
- Converts UUID IDs to BIGINT via hash function
- Joins with other tables to resolve foreign keys

### Seed Files

**db/seeds/prep/01_manufacturers.sql**:
```sql
INSERT INTO prep_seed.tb_manufacturer (id, name, country_code)
VALUES
  ('550e8400-e29b-41d4-a716-446655440000', 'Acme Corp', 'US'),
  ('550e8400-e29b-41d4-a716-446655440001', 'Widget Inc', 'CA');
```

## Running the Example

### 1. Install Dependencies

```bash
cd examples/06-prep-seed-validation
pip install confiture
```

### 2. Quick Test (Levels 1-3)

Run static validation without a database:

```bash
python validate_static.py
```

This checks:
- ✓ Seed files target prep_seed schema
- ✓ Schema consistency between prep_seed and catalog
- ✓ Resolution functions have proper transformations

### 3. Full Validation (Levels 4-5)

Requires a running PostgreSQL database:

```bash
# Start a test database (Docker example)
docker run --name test-db -e POSTGRES_PASSWORD=password -p 5432:5432 -d postgres:15

# Wait for it to be ready
sleep 3

# Create database
createdb -h localhost -U postgres test_db

# Run full validation
DATABASE_URL="postgresql://postgres:password@localhost/test_db" python validate_full.py
```

This additionally checks:
- ✓ Tables exist in database (Level 4)
- ✓ Column types match expectations (Level 4)
- ✓ Resolution functions execute (Level 4)
- ✓ Seed data loads correctly (Level 5)
- ✓ No NULL foreign keys after resolution (Level 5)
- ✓ Constraints are satisfied (Level 5)

## Validation Levels Explained

### Level 1: Seed File Validation (~1s)
- Checks seed files target `prep_seed` schema
- Validates UUID format in seed data
- Confirms FK columns use `_id` suffix

**Run:**
```bash
python -c "
from pathlib import Path
from confiture.core.seed_validation.prep_seed.orchestrator import (
    OrchestrationConfig, PrepSeedOrchestrator
)

config = OrchestrationConfig(
    max_level=1,
    seeds_dir=Path('db/seeds/prep'),
    schema_dir=Path('db/schema'),
)
report = PrepSeedOrchestrator(config).run()
print(f'Violations: {report.violation_count}')
"
```

### Level 2: Schema Consistency (~2s)
- Validates final table exists for each prep_seed table
- Checks FK column mappings (UUID → BIGINT)
- Verifies trinity pattern (id UUID, pk_*, fk_*)

**Run:**
```bash
python -c "
from pathlib import Path
from confiture.core.seed_validation.prep_seed.orchestrator import (
    OrchestrationConfig, PrepSeedOrchestrator
)

config = OrchestrationConfig(
    max_level=2,
    seeds_dir=Path('db/seeds/prep'),
    schema_dir=Path('db/schema'),
)
report = PrepSeedOrchestrator(config).run()
print(f'Schema issues: {report.violation_count}')
"
```

### Level 3: Resolution Functions (~3s)
- Detects schema drift (functions referencing wrong schema)
- Checks FK transformations are present
- Validates NULL handling

**Run:**
```bash
python -c "
from pathlib import Path
from confiture.core.seed_validation.prep_seed.orchestrator import (
    OrchestrationConfig, PrepSeedOrchestrator
)

config = OrchestrationConfig(
    max_level=3,
    seeds_dir=Path('db/seeds/prep'),
    schema_dir=Path('db/schema'),
)
report = PrepSeedOrchestrator(config).run()
print(f'Resolution issues: {report.violation_count}')
"
```

### Level 4: Runtime Validation (~10s)
- Requires database connection
- Validates tables exist
- Checks column types
- Dry-runs resolution functions (with SAVEPOINT)

**Run:**
```bash
DATABASE_URL="postgresql://localhost/test_db" python validate_full.py --level 4
```

### Level 5: Full Execution (~30s)
- Loads seed data
- Executes resolution functions
- Detects NULL FKs, duplicates, constraint violations
- Everything validated but rolled back (no data persists)

**Run:**
```bash
DATABASE_URL="postgresql://localhost/test_db" python validate_full.py --level 5
```

## Common Issues and How to Spot Them

### Issue 1: Missing FK Transformation

**Symptom**: NULL values in foreign key columns after resolution

**Detection**: Level 5 reports `NULL_FK_AFTER_RESOLUTION`

**Fix**: Ensure resolution function includes JOINs to resolve foreign keys

### Issue 2: Schema Drift

**Symptom**: Resolution function references wrong schema

**Detection**: Level 3 reports `SCHEMA_DRIFT_IN_RESOLVER`

**Example**:
```sql
-- ❌ WRONG: References tenant schema instead of catalog
INSERT INTO tenant.tb_manufacturer ...

-- ✅ CORRECT
INSERT INTO catalog.tb_manufacturer ...
```

### Issue 3: Missing Trinity Pattern

**Symptom**: Final table missing pk_* or id columns

**Detection**: Level 2 reports missing trinity pattern

**Fix**: Ensure final table has:
- `id UUID` - External identifier from prep_seed
- `pk_* BIGINT` - Internal primary key
- `fk_* BIGINT` - Foreign keys to other tables

## Next Steps

1. **Modify the example**: Try adding errors to test each validation level
2. **Run with violations**: Change table names to trigger schema issues
3. **Test with your data**: Use real seed files and resolution functions
4. **Integrate with CI/CD**: Use in GitHub Actions or your favorite CI system

## See Also

- [Prep-Seed Validation Guide](../../docs/guides/prep-seed-validation.md)
- [CLAUDE.md Seed Validation Section](../../CLAUDE.md)
- [Orchestrator API](../../python/confiture/core/seed_validation/prep_seed/orchestrator.py)
