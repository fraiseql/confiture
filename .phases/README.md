# Prep-Seed Transformation Pattern Validation

**Project**: Confiture - PostgreSQL Migrations, Sweetly Done 🍓
**Feature**: Prep-Seed Schema Validation (5-level system)
**Status**: 🟢 Phase 1 Complete → Phase 2 Ready

---

## Overview

Implementing a 5-level validation system to prevent schema drift incidents (like the 360-test-failure when `tb_postal_code` moved from `tenant` → `catalog` schema).

### The Problem

PrintOptim backend uses `prep_seed` schema with UUID FKs that transform to BIGINT FKs in final tables via resolution functions. When a table moves schemas, the resolution function isn't updated, causing silent failures (NULL foreign keys instead of valid BIGINT values).

### The Solution

5-level validation extending existing `SeedValidator`:
- **Level 1**: Seed file validation (static)
- **Level 2**: Schema consistency (static + SQL parse)
- **Level 3**: Resolution function validation (detects schema drift) ⭐ CRITICAL
- **Level 4**: Runtime validation (database dry-run)
- **Level 5**: Full seed execution (integration test)

---

## Phases

### ✅ Phase 1: Core Models & Level 3 (COMPLETE)

**Status**: [x] Complete

**What was implemented:**

✅ Core Models (13 tests)
- `PrepSeedPattern` enum with 10 prep-seed violation patterns
- `ViolationSeverity` enum (INFO, WARNING, ERROR, CRITICAL)
- `PrepSeedViolation` dataclass with severity, impact, and suggestions
- `PrepSeedReport` with grouping by severity and JSON serialization

✅ Level 3: Schema Drift Detection (7 tests)
- `Level3ResolutionValidator` detects schema drift in resolution functions
- Catches the 360-test-failure bug: `tenant.tb_x` → `catalog.tb_x` changes
- Detects missing FK transformations (missing JOINs)
- Provides impact descriptions: "Will cause NULL FKs in X dependent tables"
- Auto-fix available for schema drift issues

✅ Auto-Fixer (5 tests)
- `PrepSeedFixer.fix_schema_drift()` updates schema references
- Preserves `prep_seed` schema references
- Case-insensitive replacement
- Handles multiple occurrences

**Test Results**: 25/25 passing ✅
**Code Quality**: Ruff clean ✅, Type hints complete ✅

**Key Achievement**: **PREVENTS THE 360-TEST-FAILURE BUG**
- Before: Schema drift silently caused NULL FKs
- After: Detected at Level 3 with auto-fix available

### Phase 2: Levels 1 & 2
**Status**: [ ] Not Started

Seed file + schema consistency validation

**Blockers**: None (Phase 1 complete)
**Blocks**: Phase 3, 4

### Phase 3: Levels 4 & 5
**Status**: [ ] Not Started

Runtime validation + full execution (integration tests)

**Blockers**: Phase 2 (needs schema validation)
**Blocks**: Phase 4

### Phase 4: CLI Integration & Documentation
**Status**: [ ] Not Started

Wire up CLI command + docs + polish

**Blockers**: Phase 1, 2, 3
**Blocks**: None

---

## New Files

### Implementation Files
- `python/confiture/core/seed_validation/prep_seed/__init__.py` - Module exports
- `python/confiture/core/seed_validation/prep_seed/models.py` - Core data models (230 lines)
- `python/confiture/core/seed_validation/prep_seed/level_3_resolvers.py` - Schema drift detection (126 lines)
- `python/confiture/core/seed_validation/prep_seed/fixer.py` - Auto-fixer (48 lines)

### Test Files
- `tests/unit/seed_validation/prep_seed/test_models.py` - 13 model tests (150 lines)
- `tests/unit/seed_validation/prep_seed/test_level_3_resolvers.py` - 7 validator tests (168 lines)
- `tests/unit/seed_validation/prep_seed/test_fixer.py` - 5 fixer tests (90 lines)

### Planning Files
- `.phases/README.md` - This file
- `.phases/phase-01-level-3.md` - Phase 1 details

---

## Next Steps (Phase 2)

Implement Levels 1 & 2 for complete seed file validation:

**Level 1**: Seed file validation
- Ensure seeds target `prep_seed`, not final tables
- Validate FK columns use `_id` suffix in prep_seed
- Validate UUID format in seed data

**Level 2**: Schema consistency
- Verify `prep_seed.tb_*` has corresponding final table
- Validate FK mapping: `fk_manufacturer_id UUID` → `fk_manufacturer BIGINT`
- Verify trinity pattern in final tables
- Detect self-references (need two-pass resolution)

---

## Success Criteria

- ✅ Level 3 detects schema drift (tenant→catalog bug)
- ✅ Auto-fix corrects schema references
- ⏳ Pre-commit hook runs in <5s (levels 1-3)
- ⏳ All tests pass (unit, integration, E2E)
- ⏳ Documentation complete

---

**Last Updated**: 2026-01-31
**Phase 1 Complete**: Phase 1 committed with 25 passing tests
**Commit**: f5c03ab
