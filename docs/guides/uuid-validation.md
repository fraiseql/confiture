# Phase 10: UUID Validation in Seed Data

**Status**: Complete ✅
**Version**: 0.1
**Last Updated**: February 2026

## Overview

UUID validation is a comprehensive system for detecting malformed UUIDs and validating seed-specific UUID patterns in seed data files. This guide covers the three UUID patterns commonly found in seed data and how to validate them.

## Three UUID Patterns

### 1. RFC 4122 Random UUIDs (70% of data)

Standard randomly-generated UUIDs following RFC 4122 specification.

**Format**: `xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx` (8-4-4-4-12 hex digits)

**Example**:
```sql
INSERT INTO prep_seed.orders (id, customer_id)
VALUES (
    '2422ffde-753e-4645-836d-4d0499a96465',  -- Random RFC 4122 UUID
    '8c7d65a4-3e2f-4901-b8c2-7a9d1e4c6f2b'
);
```

**Validation**: Ensures proper hex-digit format and segment lengths.

### 2. Seed Enumerated UUIDs (15% of data)

Hierarchical UUIDs that encode the table structure within their format. Used in seed files for reproducible, enumerated data.

**Format**: `{entity:6}{directory:2}-{function:4}-{scenario:4}-0000-{increment:12}`

**Components**:
- **Entity** (6 hex digits): Canonical schema table number
  - Example: `014211` (from db/0_schema/01_write_side/014_dim/0142_org/01421_org_unit/014211_tb.sql)
- **Directory** (2 digits): First 2 digits of seed materialized path
  - Backend: `21` (from db/2_seed_backend/21_write_side/...)
  - Frontend: `31` (from db/3_seed_frontend/31_write_side/...)
  - Common: `11` (from db/1_seed_common/11_write_side/...)
  - ETL: `61` (from db/6_seed_etl/61_write_side/...)
- **Function** (4 hex digits): Test function identifier
  - `0000` for read-only seeds (no test function)
  - `4211` or other 4-digit hex values for test functions
- **Scenario** (4 digits): Test scenario variant
  - `0000` for no scenario
  - `1000` for scenario 1
  - `2000` for scenario 2
  - `3000` for scenario 3
- **Segment 4** (4 digits): Always `0000`
- **Increment** (12 decimal digits): Sequential counter

**Examples**:

Read seed (backend dimension data):
```sql
-- Schema entity: 014211, Directory: 21, No function/scenario
INSERT INTO prep_seed.tb_dimension_data (id, name)
VALUES ('01421121-0000-0000-0000-000000000001', 'Dimension Record 1');
```

Test function with scenario (backend fact data):
```sql
-- Schema entity: 031211, Directory: 21, Function: 4211, Scenario: 1
INSERT INTO prep_seed.tb_fact_data (id, code)
VALUES ('03121121-4211-1000-0000-000000000001', 'TEST-FACT-001');
```

Same entity, different environments:
```sql
-- Backend: Directory 21
INSERT INTO prep_seed.tb_dimension_data (id, name)
VALUES ('01421121-0000-0000-0000-000000000001', 'Record1');

-- Frontend: Directory 31 (same entity 014211)
INSERT INTO prep_seed.tb_dimension_data (id, name)
VALUES ('01421131-0000-0000-0000-000000000001', 'Record1');

-- Common: Directory 11 (same entity 014211)
INSERT INTO prep_seed.tb_dimension_data (id, name)
VALUES ('01421111-0000-0000-0000-000000000001', 'Record1');
```

### 3. Test Placeholder UUIDs (5% of data)

Simple repeating-digit UUIDs used as placeholders in test data.

**Format**: All segments contain the same digit

**Examples**:
```sql
INSERT INTO prep_seed.test_users (id, profile_id)
VALUES (
    '11111111-1111-1111-1111-111111111111',  -- All ones (test placeholder)
    '22222222-2222-2222-2222-222222222222'   -- All twos (test placeholder)
);
```

## Validation Usage

### Programmatic Validation

#### Basic RFC 4122 Validation

```python
from confiture.core.seed_validation.uuid_validator import UUIDValidator

validator = UUIDValidator()

# Validate format
assert validator.is_valid_uuid('2422ffde-753e-4645-836d-4d0499a96465')
assert not validator.is_valid_uuid('invalid-uuid')

# Extract UUIDs from SQL
sql = "INSERT INTO users (id) VALUES ('2422ffde-753e-4645-836d-4d0499a96465');"
uuids = validator.extract_uuid_literals(sql)
# Returns: ['2422ffde-753e-4645-836d-4d0499a96465']
```

#### Seed Enumerated Validation

```python
from pathlib import Path
from confiture.core.seed_validation.seed_pattern_validator import (
    SchemaEntityExtractor,
    DirectoryExtractor,
    SeedEnumeratedValidator,
)

schema_extractor = SchemaEntityExtractor()
dir_extractor = DirectoryExtractor()
seed_validator = SeedEnumeratedValidator()

# Extract schema context from file path
seed_path = Path("db/2_seed_backend/21_write_side/214_dim/2142_category/21421_subcategory/214211_tb_data.sql")
schema_entity = schema_extractor.extract_schema_entity(seed_path)  # "014211"
directory = dir_extractor.extract_directory(seed_path)  # "21"

# Validate UUID matches pattern
uuid = "01421121-0000-0000-0000-000000000001"
assert seed_validator.is_valid_pattern(uuid, schema_entity, directory)

# UUID with test function and scenario
uuid_with_func = "01421121-4211-1000-0000-000000000001"
assert seed_validator.is_valid_pattern(uuid_with_func, schema_entity, directory)
```

#### Pattern Detection

```python
from confiture.core.seed_validation.uuid_patterns import (
    UUIDPatternDetector,
    UUIDPatternType,
)

detector = UUIDPatternDetector()

# Detect random RFC 4122
pattern = detector.detect_type('2422ffde-753e-4645-836d-4d0499a96465')
assert pattern == UUIDPatternType.RFC4122_RANDOM

# Detect seed enumerated (requires context)
pattern = detector.detect_type(
    '01421121-0000-0000-0000-000000000001',
    schema_entity='014211',
    directory='21',
    is_seed_file=True
)
assert pattern == UUIDPatternType.SEED_ENUMERATED

# Detect test placeholder
pattern = detector.detect_type('11111111-1111-1111-1111-111111111111')
assert pattern == UUIDPatternType.TEST_PLACEHOLDER
```

### CLI Validation

#### Enable UUID Validation

```bash
# Show UUID validation support (directs to prep-seed Level 1)
confiture seed validate --uuid-validation

# Run full static validation (RFC 4122 + seed patterns)
confiture seed validate --prep-seed --static-only

# Run full validation with database (Levels 1-5)
confiture seed validate --prep-seed --full-execution \
  --database-url postgresql://localhost/test
```

#### Validate Specific Directory

```bash
# Validate backend seeds with UUID validation
confiture seed validate \
  --seeds-dir db/seeds/backend \
  --prep-seed --static-only

# Output as JSON
confiture seed validate \
  --seeds-dir db/seeds/backend \
  --prep-seed --static-only \
  --format json \
  --output uuid-report.json
```

## Example Seed Structure

### Backend Seeds (db/2_seed_backend/)

**Directory**: `21_write_side`

```sql
-- Read seed: Reference data for backend
INSERT INTO prep_seed.tb_reference_data (id, code, name, status) VALUES
  ('01421121-0000-0000-0000-000000000001', 'REF-001', 'Reference 1', 'active'),
  ('01421121-0000-0000-0000-000000000002', 'REF-002', 'Reference 2', 'active');

-- Test data: Variant scenarios (function 4211, scenario 1)
INSERT INTO prep_seed.tb_variant_data (id, reference_id, code, name) VALUES
  ('03121121-4211-1000-0000-000000000001', '03121121-0000-0000-0000-000000000001', 'VAR-001', 'Variant 1'),
  ('03121121-4211-1000-0000-000000000002', '03121121-0000-0000-0000-000000000001', 'VAR-002', 'Variant 2');
```

### Frontend Seeds (db/3_seed_frontend/)

**Directory**: `31_write_side` (same entities as backend, different directory)

```sql
-- Same reference data in frontend seed
INSERT INTO prep_seed.tb_reference_data (id, code, name, status) VALUES
  ('01421131-0000-0000-0000-000000000001', 'REF-001', 'Reference 1', 'active'),
  ('01421131-0000-0000-0000-000000000002', 'REF-002', 'Reference 2', 'active');
```

### Common Seeds (db/1_seed_common/)

**Directory**: `11_write_side`

```sql
-- Shared reference data
INSERT INTO prep_seed.tb_common_codes (id, code, name) VALUES
  ('01421111-0000-0000-0000-000000000001', 'CODE-001', 'Common Code 1'),
  ('01421111-0000-0000-0000-000000000002', 'CODE-002', 'Common Code 2');
```

## Architecture

### Components

1. **UUIDValidator**: RFC 4122 format validation and extraction
2. **SchemaEntityExtractor**: Maps seed table numbers to canonical schema entities
3. **DirectoryExtractor**: Extracts directory codes from file paths
4. **SeedEnumeratedValidator**: Validates seed enumerated pattern
5. **TestPlaceholderValidator**: Validates repeating-digit UUIDs
6. **UUIDPatternDetector**: Automatic pattern type detection
7. **Level 1 Integration**: Tests demonstrating full validation pipeline

### Validation Pipeline

```
SQL File → Extract UUIDs → Validate Format → Extract Context → Detect Pattern
                           ↓              ↓                         ↓
                        RFC 4122      Entity+Directory        Random/Seed/Test
```

## Common Issues & Solutions

### Issue: UUID Prefix Mismatch

**Problem**: Seed enumerated UUID doesn't match expected entity
```sql
-- Wrong: Entity should start with 014211, not 999999
INSERT INTO prep_seed.tb_org (id) VALUES ('99999999-0000-0000-0000-000000000001');
```

**Solution**: Extract entity from schema, use correct prefix
```sql
-- Correct: Extract 014211 from schema path
INSERT INTO prep_seed.tb_org (id) VALUES ('01421121-0000-0000-0000-000000000001');
```

### Issue: Directory Code Mismatch

**Problem**: Directory code doesn't match seed level
```sql
-- Wrong: File in 2_seed_backend (directory 21) but UUID has 31 (frontend)
-- Location: db/2_seed_backend/21_write_side/.../tb_org.sql
INSERT INTO prep_seed.tb_org (id) VALUES ('01421131-0000-0000-0000-000000000001');
```

**Solution**: Match directory to seed level
```sql
-- Correct: Directory 21 for backend
INSERT INTO prep_seed.tb_org (id) VALUES ('01421121-0000-0000-0000-000000000001');
```

### Issue: Invalid Function Segment

**Problem**: Function segment is invalid hex
```sql
-- Wrong: Function segment contains non-hex character
INSERT INTO prep_seed.tb_org (id) VALUES ('01421121-42z1-1000-0000-000000000001');
```

**Solution**: Use valid 4-digit hex
```sql
-- Correct: 4211 is valid hex
INSERT INTO prep_seed.tb_org (id) VALUES ('01421121-4211-1000-0000-000000000001');
```

## Best Practices

1. **Use Seed Enumerated for Reproducible Data**: Prefer seed enumerated UUIDs for dimension and reference data
2. **Use Random RFC 4122 for Product Data**: Random UUIDs for customer data, orders, transactions
3. **Use Test Placeholders for Tests**: Use repeating digits in test fixtures (11111..., 22222...)
4. **Validate in CI/CD**: Run `confiture seed validate --prep-seed --static-only` in pre-commit hooks
5. **Document Scenarios**: Add comments explaining test function and scenario numbers

## Performance

- **RFC 4122 Validation**: <1ms per UUID (regex pattern match)
- **Seed Enumerated Validation**: <2ms per UUID (hex conversion + comparison)
- **Full File Validation**: ~10ms for 100-line seed file
- **Directory Scanning**: ~100ms for 35,000 lines across 154 files

## See Also

- **Prep-Seed Validation Guide**: `docs/guides/prep-seed-validation.md`
- **Seed Files**: `db/2_seed_backend/`, `db/3_seed_frontend/`
- **Phase 10 Implementation**: Source at `python/confiture/core/seed_validation/`
- **CLI Reference**: `confiture seed validate --help`
