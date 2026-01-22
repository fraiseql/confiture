# Trinity Naming Pattern Refactor for Confiture

**Status**: Clean Implementation Plan (No Migration Needed)
**Scope**: Rename `confiture_migrations` → `tb_confiture` with corrected Trinity pattern
**Current Codebase Version**: 0.3.5 (pre-1.0, no production users)
**Breaking Change**: Yes (justified - pre-release)
**Date**: January 2026

---

## Executive Summary

Confiture's internal migration tracking table needs to adopt the correct Trinity naming pattern. Since the project is **pre-1.0 with no production users**, we can make a clean breaking change without needing migration utilities or backward compatibility layers.

### Correct Trinity Pattern
- **Table name**: `tb_confiture` (prefix `tb_`, singular entity)
- **Primary key (`id`)**: UUID - external-facing identifier
- **Internal key (`pk_confiture`)**: BIGINT GENERATED ALWAYS AS IDENTITY - sequential internal ID
- **Natural key (`slug`)**: TEXT - human-readable reference

---

## Current vs. Corrected Schema

### Original (Wrong)
```sql
CREATE TABLE confiture_migrations (
    id SERIAL PRIMARY KEY,  -- ❌ Sequential as primary, exposed to users
    version VARCHAR(255) NOT NULL UNIQUE,
    name VARCHAR(255) NOT NULL,
    applied_at TIMESTAMP NOT NULL DEFAULT NOW(),
    execution_time_ms INTEGER,
    checksum VARCHAR(64)
)
```

### Intermediate (Partially Correct)
Currently in `migrator.py::initialize()`:
```sql
CREATE TABLE confiture_migrations (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,  -- ❌ Wrong position
    pk_migration UUID NOT NULL DEFAULT uuid_generate_v4() UNIQUE,  -- ❌ Wrong name
    slug TEXT NOT NULL UNIQUE,  -- ✅ Good
    version VARCHAR(255) NOT NULL UNIQUE,
    name VARCHAR(255) NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    execution_time_ms INTEGER,
    checksum VARCHAR(64)
)
```

### Corrected Trinity Pattern
```sql
CREATE TABLE tb_confiture (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),  -- ✅ External identifier
    pk_confiture BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE,  -- ✅ Internal sequential
    slug TEXT NOT NULL UNIQUE,  -- ✅ Human-readable reference
    version VARCHAR(255) NOT NULL UNIQUE,
    name VARCHAR(255) NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    execution_time_ms INTEGER,
    checksum VARCHAR(64)
)
```

---

## Scope of Changes

**Total Code References**: ~71 occurrences

| File | Occurrences | Type |
|------|-------------|------|
| `python/confiture/core/migrator.py` | 12 | Core logic |
| `python/confiture/config/environment.py` | 1 | Config |
| `python/confiture/core/health.py` | 3 | Health checks |
| `python/confiture/core/locking.py` | 1 | Lock hash |
| `tests/conftest.py` | 1 | Fixture |
| `tests/unit/test_*.py` | 18 | Unit tests |
| `tests/integration/test_*.py` | 15 | Integration |
| `db/schema/00_common/01_confiture_migrations.sql` | 20 | SQL DDL |
| Documentation | 5+ | Docs |

---

## Implementation Plan (Single Phase)

Since this is **pre-1.0 with no production users**, we can make a clean breaking change.

### Step 1: Update SQL Schema File

**File**: Rename `db/schema/00_common/01_confiture_migrations.sql` → `db/schema/00_common/01_tb_confiture.sql`

```sql
-- Confiture migration tracking table (Trinity pattern)
-- External identifier: UUID, Internal sequence: BIGINT, Natural key: slug

CREATE TABLE IF NOT EXISTS tb_confiture (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    pk_confiture BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE,
    slug TEXT NOT NULL UNIQUE,
    version VARCHAR(255) NOT NULL UNIQUE,
    name VARCHAR(255) NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    execution_time_ms INTEGER,
    checksum VARCHAR(64)
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_tb_confiture_pk_confiture ON tb_confiture(pk_confiture);
CREATE INDEX IF NOT EXISTS idx_tb_confiture_slug ON tb_confiture(slug);
CREATE INDEX IF NOT EXISTS idx_tb_confiture_version ON tb_confiture(version);
CREATE INDEX IF NOT EXISTS idx_tb_confiture_applied_at ON tb_confiture(applied_at DESC);

-- Comments
COMMENT ON TABLE tb_confiture IS
    'Tracks all applied database migrations for Confiture. Trinity pattern: UUID external ID, BIGINT internal sequence.';
COMMENT ON COLUMN tb_confiture.id IS 'External UUID identifier, stable across contexts';
COMMENT ON COLUMN tb_confiture.pk_confiture IS 'Internal sequential ID for performance';
COMMENT ON COLUMN tb_confiture.slug IS 'Human-readable reference (migration_name + timestamp)';
COMMENT ON COLUMN tb_confiture.version IS 'Migration version prefix (e.g., "001")';
COMMENT ON COLUMN tb_confiture.name IS 'Human-readable migration name';
COMMENT ON COLUMN tb_confiture.applied_at IS 'Timestamp when applied';
COMMENT ON COLUMN tb_confiture.execution_time_ms IS 'Execution time in milliseconds';
COMMENT ON COLUMN tb_confiture.checksum IS 'SHA256 checksum for integrity verification';
```

### Step 2: Update Configuration Default

**File**: `python/confiture/config/environment.py` (line 138)

```diff
- migration_table: str = "confiture_migrations"
+ migration_table: str = "tb_confiture"
```

### Step 3: Update Migrator Core Logic

**File**: `python/confiture/core/migrator.py`

Replace all table name references. Key changes in `initialize()` method:

```python
def initialize(self) -> None:
    """Create tb_confiture tracking table with Trinity pattern.

    Identity:
    - id: UUID (external, stable)
    - pk_confiture: BIGINT (internal, sequential)
    - slug: TEXT (human-readable)
    """
    try:
        self._execute_sql('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')

        # Check if table exists
        with self.connection.cursor() as cursor:
            cursor.execute("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables
                    WHERE table_name = 'tb_confiture'
                )
            """)
            table_exists = cursor.fetchone()[0]

        if not table_exists:
            # Create new table with Trinity pattern
            self._execute_sql("""
                CREATE TABLE tb_confiture (
                    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
                    pk_confiture BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE,
                    slug TEXT NOT NULL UNIQUE,
                    version VARCHAR(255) NOT NULL UNIQUE,
                    name VARCHAR(255) NOT NULL,
                    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    execution_time_ms INTEGER,
                    checksum VARCHAR(64)
                )
            """)

            # Create indexes
            self._execute_sql("""
                CREATE INDEX idx_tb_confiture_pk_confiture
                    ON tb_confiture(pk_confiture)
            """)
            self._execute_sql("""
                CREATE INDEX idx_tb_confiture_slug
                    ON tb_confiture(slug)
            """)
            self._execute_sql("""
                CREATE INDEX idx_tb_confiture_version
                    ON tb_confiture(version)
            """)
            self._execute_sql("""
                CREATE INDEX idx_tb_confiture_applied_at
                    ON tb_confiture(applied_at DESC)
            """)

        self.connection.commit()
    except Exception as e:
        self.connection.rollback()
        raise MigrationError(f"Failed to initialize migrations table: {e}") from e
```

Update all queries:
- `_record_migration()` → `INSERT INTO tb_confiture`
- `_is_applied()` → `FROM tb_confiture WHERE version = %s`
- `get_applied_versions()` → `FROM tb_confiture ORDER BY applied_at`
- `_rollback_transactional()` → `DELETE FROM tb_confiture WHERE version = %s`
- `_rollback_non_transactional()` → `DELETE FROM tb_confiture WHERE version = %s`

### Step 4: Update Tests

**File**: `tests/conftest.py` (line 1)

```diff
- "migration_table": "confiture_migrations",
+ "migration_table": "tb_confiture",
```

**All test files**: Simple find & replace
- `confiture_migrations` → `tb_confiture`
- `idx_confiture_migrations_*` → `idx_tb_confiture_*`

### Step 5: Update Documentation

- Update README.md references
- Update ARCHITECTURE.md
- Update docstrings in migrator.py
- Update SQL examples

---

## Change Checklist

- [ ] **SQL Schema**: Rename file and update DDL (Trinity pattern)
- [ ] **Config**: Update default in `environment.py`
- [ ] **Migrator**: Update `initialize()` method (12 changes)
- [ ] **Migrator**: Update all queries (INSERT, SELECT, DELETE)
- [ ] **Tests**: Update fixture and all test references (36+ changes)
- [ ] **Documentation**: Update references

---

## Schema Comparison

### Old
```
confiture_migrations (SERIAL PK - wrong)
├── id (SERIAL PRIMARY KEY) ❌
├── version, name, etc.
```

### New
```
tb_confiture (UUID PK - correct)
├── id (UUID PRIMARY KEY) ✅ External
├── pk_confiture (BIGINT UNIQUE) ✅ Internal
├── slug (TEXT UNIQUE) ✅ Human-readable
├── version, name, etc.
```

**Benefits**:
- ✅ Aligns with Trinity pattern (your project standard)
- ✅ UUID as external ID (stable, not sequential)
- ✅ BIGINT as internal sequence (hidden from users)
- ✅ Better type safety (TIMESTAMPTZ vs TIMESTAMP)
- ✅ Clearer intent with slug for user-facing references

---

## Effort & Risk

| Aspect | Level | Notes |
|--------|-------|-------|
| **Complexity** | Low | Straightforward find & replace |
| **Risk** | Low | Pre-1.0, no production users |
| **Test Coverage** | Medium | ~36 test references to update |
| **Duration** | ~2-3 hours | Mostly mechanical |
| **Breaking** | Yes | Justified pre-release |

---

## Verification

After implementing:

```bash
uv run pytest --cov=confiture
uv run ty check python/confiture/
uv run ruff check python/confiture/
```

Expected new table structure:
```
Table "public.tb_confiture"
Column         | Type           | Nullable | Default
───────────────┼────────────────┼──────────┼──────────
id             | uuid           | not null | gen_random_uuid()
pk_confiture   | bigint         | not null | nextval(...)
slug           | text           | not null |
version        | varchar(255)   | not null |
name           | varchar(255)   | not null |
applied_at     | timestamptz    | not null | now()
execution_time | integer        |          |
checksum       | varchar(64)    |          |
```

---

## Recommendation

✅ **Proceed with implementation** - Clean, low-risk refactor that:
- Aligns with Trinity naming standard
- Improves schema design (UUID PK is better than SERIAL)
- Sets right pattern for future
- Takes only 2-3 hours to complete
- Makes sense to do now (pre-1.0, no production impact)

**Status**: Ready for implementation
