# Prep-Seed Transformation Pattern Validation

**Project**: Confiture - PostgreSQL Migrations, Sweetly Done 🍓
**Feature**: Prep-Seed Schema Validation (5-level system)
**Status**: 🟢 Phases 1-2 Complete → Phase 3 Ready

---

## Overview

Implementing a 5-level validation system to prevent schema drift incidents (like the 360-test-failure when `tb_postal_code` moved from `tenant` → `catalog` schema).

### The Problem

PrintOptim backend uses `prep_seed` schema with UUID FKs that transform to BIGINT FKs in final tables via resolution functions. When a table moves schemas, the resolution function isn't updated, causing silent failures (NULL foreign keys instead of valid BIGINT values).

### The Solution

5-level validation extending existing `SeedValidator`:
- **Level 1**: Seed file validation (static) ✅
- **Level 2**: Schema consistency (static + SQL parse) ✅
- **Level 3**: Resolution function validation (detects schema drift) ✅ CRITICAL
- **Level 4**: Runtime validation (database dry-run) TODO
- **Level 5**: Full seed execution (integration test) TODO

---

## Phases

### ✅ Phase 1: Core Models & Level 3 (COMPLETE)

**Status**: [x] Complete

**Deliverables**:
- Core data models (PrepSeedPattern, ViolationSeverity, violations, reports)
- Level 3: Schema drift detection in resolution functions
- Auto-fixer for schema reference updates
- 25 passing tests

**Key Achievement**: Prevents the 360-test-failure bug

### ✅ Phase 2: Levels 1 & 2 (COMPLETE)

**Status**: [x] Complete

**Deliverables**:

✅ **Level 1: Seed File Validation (8 tests)**
- Detects when seed INSERT targets wrong schema (must be prep_seed)
- Validates FK column naming (_id suffix required in prep_seed)
- Validates UUID format in seed data
- Auto-fix available for schema target violations

✅ **Level 2: Schema Consistency (9 tests)**
- Validates prep_seed ↔ final table mapping
- Checks FK type mapping (UUID → BIGINT)
- Validates trinity pattern (id UUID, pk_* BIGINT, fk_* BIGINT)
- Detects self-referencing FKs needing two-pass resolution
- Warns about missing FK mappings

**Test Results**: 17 new tests + 25 existing = 42 total passing ✅
**Code Quality**: Ruff clean ✅, Type hints complete ✅

**Combined Coverage**:
```
Level 1: Seed file validation ✅
├─ Schema target validation
├─ FK naming validation  
└─ UUID format validation

Level 2: Schema consistency ✅
├─ Final table existence
├─ FK column type mapping
├─ Trinity pattern validation
└─ Self-reference detection

Level 3: Resolution functions ✅
├─ Schema drift detection
└─ Missing FK transformation detection
```

### Phase 3: Levels 4 & 5
**Status**: [ ] Not Started

Runtime validation + full execution (integration tests)

**Blockers**: None (Phases 1-2 complete)
**Blocks**: Phase 4

### Phase 4: CLI Integration & Documentation
**Status**: [ ] Not Started

Wire up CLI command + docs + polish

**Blockers**: Phases 1-3
**Blocks**: None

---

## New Files (Phase 2)

### Implementation Files (387 lines)
- `level_1_seed_files.py` (195 lines) - Seed file validation
- `level_2_schema.py` (192 lines) - Schema consistency validation

### Test Files (376 lines)
- `test_level_1_seed_files.py` (161 lines) - 8 tests
- `test_level_2_schema.py` (215 lines) - 9 tests

---

## Architecture: Complete Static Validation

### Validation Pipeline

```
Seed Files
    ↓
Level 1: Seed File Validator
├─ Check INSERT schema target
├─ Check FK naming conventions
└─ Check UUID format
    ↓
Schema Definitions
    ↓
Level 2: Schema Consistency Validator
├─ Check final table exists
├─ Check FK mappings
├─ Check trinity pattern
└─ Detect self-references
    ↓
Resolution Functions
    ↓
Level 3: Resolution Validator
├─ Detect schema drift (tenant → catalog)
└─ Detect missing FK transformations
    ↓
Report Violations
├─ By severity (INFO, WARNING, ERROR, CRITICAL)
├─ With impact descriptions
└─ With auto-fix suggestions
```

### Usage Example

```python
from confiture.core.seed_validation.prep_seed import (
    Level1SeedValidator,
    Level2SchemaValidator,
    Level3ResolutionValidator,
)

# Level 1: Validate seed file
l1 = Level1SeedValidator()
violations = l1.validate_seed_file(
    sql="INSERT INTO prep_seed.tb_x ...",
    file_path="db/seeds/prep/test.sql"
)

# Level 2: Validate schema consistency
l2 = Level2SchemaValidator(get_final_table=lookup_fn)
violations = l2.validate_schema_mapping(prep_table)

# Level 3: Validate resolution functions
l3 = Level3ResolutionValidator(get_table_schema=lookup_fn)
violations = l3.validate_function(
    func_name="fn_resolve_tb_x",
    func_body="INSERT INTO ...",
    fk_columns=["fk_y_id"]
)
```

---

## Test Summary

| Phase | Level | Tests | Status |
|-------|-------|-------|--------|
| 1 | Models | 13 | ✅ PASS |
| 1 | Level 3 | 7 | ✅ PASS |
| 1 | Fixer | 5 | ✅ PASS |
| 2 | Level 1 | 8 | ✅ PASS |
| 2 | Level 2 | 9 | ✅ PASS |
| **Total** | **1-3** | **42** | **✅ PASS** |

---

## What's Next: Phase 3

### Level 4: Runtime Validation
- Requires database connection
- Dry-run resolution functions with SAVEPOINT
- Check target tables exist
- Validate column types match

### Level 5: Full Seed Execution
- Actually load seed data
- Execute transformation functions
- Detect NULL FKs after resolution
- Validate data integrity constraints

---

## Success Criteria Progress

- ✅ Level 3 detects schema drift (tenant→catalog bug)
- ✅ Auto-fix corrects schema references
- ✅ Level 1 validates seed files
- ✅ Level 2 validates schema consistency
- ⏳ Pre-commit hook runs in <5s (levels 1-3)
- ⏳ All tests pass (unit, integration, E2E)
- ⏳ Documentation complete

---

**Last Updated**: 2026-01-31
**Phase 2 Complete**: 42 tests passing, all static validation working
**Commits**: 
- f5c03ab Phase 1: Core models + Level 3
- 64cbb35 Phase 2: Levels 1 & 2
