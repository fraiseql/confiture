# Prep-Seed Transformation Pattern Validation

**Project**: Confiture - PostgreSQL Migrations, Sweetly Done 🍓
**Feature**: Prep-Seed Schema Validation (5-level system)
**Status**: 🟡 In Planning → Phase 1

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

### Phase 1: Core Models & Level 3
**Status**: [~] In Progress

Core infrastructure + schema drift detection (prevents 360-test-failure bug)

**Blockers**: None
**Blocks**: Phase 2, 3, 4

### Phase 2: Levels 1 & 2
**Status**: [ ] Not Started

Seed file + schema consistency validation

**Blockers**: Phase 1
**Blocks**: Phase 3, 4

### Phase 3: Levels 4 & 5
**Status**: [ ] Not Started

Runtime validation + full execution (integration tests)

**Blockers**: Phase 1, 2
**Blocks**: Phase 4

### Phase 4: CLI Integration & Documentation
**Status**: [ ] Not Started

Wire up CLI command + docs + polish

**Blockers**: Phase 1, 2, 3
**Blocks**: None

---

## Key Files

### New Modules
- `python/confiture/core/seed_validation/prep_seed/` - New prep_seed validation module
  - `models.py` - PrepSeedViolation, PrepSeedReport, SchemaMapping
  - `level_3_resolvers.py` - Resolution function validation (CRITICAL)
  - `level_5_execution.py` - Full seed execution validation
  - Other levels as needed

### Modified Files
- `python/confiture/cli/seed.py` - Add `--prep-seed` flag
- `python/confiture/core/seed_validation/__init__.py` - Export prep_seed module

---

## Success Criteria

- ✅ Level 3 detects schema drift (tenant→catalog bug)
- ✅ Auto-fix corrects schema references
- ✅ Pre-commit hook runs in <5s (levels 1-3)
- ✅ All tests pass
- ✅ Documentation complete

---

**Last Updated**: 2026-01-31
**Current Phase**: Phase 1 (Core Models & Level 3)
