# UUID Validation Example: PrintOptim Seed Data

This example demonstrates UUID validation for the PrintOptim application's seed data structure.

## Project Structure

```
db/
├── 0_schema/           # Canonical schema definitions (entity source)
│   ├── 01_write_side/
│   │   ├── 014_dim/
│   │   │   ├── 0142_org/
│   │   │   │   ├── 01421_org_unit/
│   │   │   │   │   └── 014211_tb_organizational_unit_info.sql
│   │   │   │   └── 014221_tb_organization_info.sql
│   │   │   └── 0143_product/
│   │   │       └── 014311_tb_product_info.sql
│   │   └── ...
│
├── 1_seed_common/      # Common seed data (directory: 11)
│   ├── 11_write_side/
│   │   └── 011211_tb_currency_codes.sql
│
├── 2_seed_backend/     # Backend write-side data (directory: 21)
│   ├── 21_write_side/
│   │   ├── 214_dim/
│   │   │   ├── 2142_org/
│   │   │   │   ├── 21421_org_unit/
│   │   │   │   │   └── 214211_tb_organizational_unit_info.sql
│   │   │   │   └── 214221_tb_organization_info.sql
│   │   │   └── 2143_product/
│   │   │       └── 214311_tb_product_info.sql
│   │   └── ...
│
├── 3_seed_frontend/    # Frontend dimensional data (directory: 31)
│   ├── 31_write_side/
│   │   ├── 314_dim/
│   │   │   └── 3143_product/
│   │   │       └── 314311_tb_product_catalog.sql
│   │   └── ...
│
└── 6_seed_etl/         # ETL seed data (directory: 61)
    ├── 61_catalog/
    │   └── 614211_tb_org_unit_history.sql
    └── ...
```

## Entity Mapping

The entity number is derived from the schema path:

| Schema Path | Entity | Backend (21) | Frontend (31) | Common (11) | ETL (61) |
|-------------|--------|--------------|--------------|------------|----------|
| 014211 | 014211 | 214211 | 314211 | 114211 | 614211 |
| 014221 | 014221 | 214221 | 314221 | 114221 | 614221 |
| 014311 | 014311 | 214311 | 314311 | 114311 | 614311 |

## Real Seed Files

### Organizational Units (014211)

**Schema**: `db/0_schema/01_write_side/014_dim/0142_org/01421_org_unit/014211_tb_organizational_unit_info.sql`

**Backend Seed**: `db/2_seed_backend/21_write_side/214_dim/2142_org/21421_org_unit/214211_tb_organizational_unit_info.sql`

```sql
-- Read seed: Basic organizational units
INSERT INTO prep_seed.tb_organizational_unit_info (id, name, parent_id, status) VALUES
  -- Entity: 014211, Directory: 21, Function: 0000, Scenario: 0000
  ('01421121-0000-0000-0000-000000000001', 'Headquarters', NULL, 'active'),
  ('01421121-0000-0000-0000-000000000002', 'Engineering', '01421121-0000-0000-0000-000000000001', 'active'),
  ('01421121-0000-0000-0000-000000000003', 'Sales', '01421121-0000-0000-0000-000000000001', 'active'),
  ('01421121-0000-0000-0000-000000000004', 'Backend Team', '01421121-0000-0000-0000-000000000002', 'active');

-- Test data: Alternative organizational structure (test function 4211, scenario 1)
INSERT INTO prep_seed.tb_organizational_unit_info (id, name, parent_id, status) VALUES
  -- Function: 4211, Scenario: 1000 (for testing regional organization)
  ('01421121-4211-1000-0000-000000000001', 'EMEA Region', NULL, 'active'),
  ('01421121-4211-1000-0000-000000000002', 'UK Office', '01421121-4211-1000-0000-000000000001', 'active'),
  ('01421121-4211-1000-0000-000000000003', 'EU Office', '01421121-4211-1000-0000-000000000001', 'active');
```

**Frontend Seed**: Same entity, different directory (31)

```sql
-- Same organizational units for frontend display
INSERT INTO prep_seed.tb_organizational_unit_info (id, name, parent_id, status) VALUES
  -- Directory: 31 (frontend)
  ('01421131-0000-0000-0000-000000000001', 'Headquarters', NULL, 'active'),
  ('01421131-0000-0000-0000-000000000002', 'Engineering', '01421131-0000-0000-0000-000000000001', 'active'),
  ('01421131-0000-0000-0000-000000000003', 'Sales', '01421131-0000-0000-0000-000000000001', 'active');
```

**Common Seed**: Shared organization codes

```sql
-- Common reference with directory 11
INSERT INTO prep_seed.tb_organizational_unit_info (id, name, parent_id, status) VALUES
  ('01421111-0000-0000-0000-000000000001', 'Corporate', NULL, 'active');
```

### Products (014311)

**Backend Seed**: `db/2_seed_backend/21_write_side/214_dim/2143_product/214311_tb_product_info.sql`

```sql
-- Read seed: Product catalog
INSERT INTO prep_seed.tb_product_info (id, sku, name, category_id) VALUES
  -- Entity: 014311, Directory: 21
  ('01431121-0000-0000-0000-000000000001', 'PROD-001', 'Product 1', '01431121-0000-0000-0000-000000000101'),
  ('01431121-0000-0000-0000-000000000002', 'PROD-002', 'Product 2', '01431121-0000-0000-0000-000000000101'),
  ('01431121-0000-0000-0000-000000000003', 'PROD-003', 'Product 3', '01431121-0000-0000-0000-000000000102');

-- Test variants: Alternative product mix (function 4321, scenario 2)
INSERT INTO prep_seed.tb_product_variant (id, product_id, sku, name) VALUES
  -- Function: 4321, Scenario: 2000 (for testing variant availability)
  ('01431121-4321-2000-0000-000000000001', '01431121-0000-0000-0000-000000000001', 'PROD-001-BLU', 'Product 1 - Blue'),
  ('01431121-4321-2000-0000-000000000002', '01431121-0000-0000-0000-000000000001', 'PROD-001-RED', 'Product 1 - Red'),
  ('01431121-4321-2000-0000-000000000003', '01431121-0000-0000-0000-000000000002', 'PROD-002-LGE', 'Product 2 - Large');
```

## Currency Codes (Common Seed)

**Common Seed**: `db/1_seed_common/11_write_side/111_crm/1112_currency/111211_tb_currency_codes.sql`

```sql
-- Shared reference data (directory 11)
INSERT INTO prep_seed.tb_currency_codes (id, code, name, symbol) VALUES
  ('01421111-0000-0000-0000-000000000001', 'USD', 'US Dollar', '$'),
  ('01421111-0000-0000-0000-000000000002', 'EUR', 'Euro', '€'),
  ('01421111-0000-0000-0000-000000000003', 'GBP', 'British Pound', '£'),
  ('01421111-0000-0000-0000-000000000004', 'JPY', 'Japanese Yen', '¥');
```

## Validation Examples

### Validate All Backend Seeds

```bash
# Run UUID validation on backend seeds (static, no database)
confiture seed validate \
  --seeds-dir db/2_seed_backend \
  --prep-seed \
  --static-only

# Output shows:
# ✓ RFC 4122 format validation: PASS
# ✓ Schema entity validation: PASS
# ✓ Directory code validation: PASS
# ✓ Function/scenario validation: PASS
# ✓ Test placeholder detection: PASS
```

### Validate Specific Seed Files

```bash
# Check organizational units
confiture seed validate \
  --seeds-dir db/2_seed_backend/21_write_side/214_dim/2142_org/21421_org_unit \
  --prep-seed --static-only

# Expected validations:
# - Entity 014211 is correct
# - Directory 21 is correct
# - Functions are either 0000 or valid hex
# - Scenarios are 0000, 1000, 2000, or 3000
```

### JSON Report for CI/CD

```bash
# Generate JSON report for integration testing
confiture seed validate \
  --seeds-dir db/2_seed_backend \
  --prep-seed --full-execution \
  --database-url postgresql://localhost/confiture_test \
  --format json \
  --output uuid-validation-report.json
```

Report structure:
```json
{
  "validation_level": 5,
  "total_violations": 0,
  "violations": [],
  "statistics": {
    "files_scanned": 154,
    "uuids_validated": 8423,
    "rfc4122_random": 5896,
    "seed_enumerated": 1527,
    "test_placeholder": 900
  }
}
```

## Key Learning Points

1. **Entity is from Schema**: Always extract the entity number from `db/0_schema`, not from seed files
2. **Directory from Seed Level**: Directory code depends on which seed directory
   - Backend (2_seed_backend) → 21
   - Frontend (3_seed_frontend) → 31
   - Common (1_seed_common) → 11
3. **Same Entity, Different Directories**: The same entity appears in multiple seed levels with different directories
4. **Test Functions Enable Variants**: Use function numbers to create alternative data scenarios (A/B testing)
5. **Scenarios Create Scenario Variants**: Scenario numbers (1000, 2000, 3000) allow testing different configurations

## Next Steps

1. Run validation on your seed data: `confiture seed validate --prep-seed --static-only`
2. Fix any validation errors using the troubleshooting guide
3. Integrate into CI/CD with Level 5 full validation
4. Monitor validation performance on large seed files

For more details, see [UUID Validation Guide](../../docs/guides/uuid-validation.md)
