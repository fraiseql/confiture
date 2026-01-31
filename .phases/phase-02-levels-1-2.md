# Phase 2: Levels 1 & 2 - Seed File & Schema Validation

## Objective
Implement seed file validation (Level 1) and schema consistency validation (Level 2) to prevent misconfigurations in the prep_seed pattern.

## Success Criteria
- [ ] Level 1: Seed file validation (static)
- [ ] Level 2: Schema consistency (static + SQL parse)
- [ ] Auto-fix for correctable issues
- [ ] All unit tests passing
- [ ] Code passes linting (ruff check, format)

## TDD Cycles

### Cycle 1: Level 1 - Seed Schema Target Validation
- **RED**: Write test expecting detection of INSERTs targeting wrong schema
- **GREEN**: Implement seed file parser to detect INSERT targets
- **REFACTOR**: Extract schema detection logic
- **CLEANUP**: Format and lint

### Cycle 2: Level 1 - FK Naming Validation
- **RED**: Write test expecting FK _id suffix validation
- **GREEN**: Implement FK column naming check
- **REFACTOR**: Extract naming patterns
- **CLEANUP**: Lint

### Cycle 3: Level 1 - UUID Format Validation
- **RED**: Write test expecting UUID format validation
- **GREEN**: Implement UUID regex validation
- **REFACTOR**: Improve regex robustness
- **CLEANUP**: Lint

### Cycle 4: Level 2 - Table Mapping Validation
- **RED**: Write test expecting prep_seed ↔ final table mapping check
- **GREEN**: Implement basic table existence checking
- **REFACTOR**: Extract mapping logic
- **CLEANUP**: Lint

### Cycle 5: Level 2 - FK Column Type Mapping
- **RED**: Write test for FK mapping: UUID → BIGINT
- **GREEN**: Implement FK type checking
- **REFACTOR**: Improve type checking
- **CLEANUP**: Lint

### Cycle 6: Level 2 - Trinity Pattern Validation
- **RED**: Write test for trinity pattern (id UUID, pk_* BIGINT, fk_* BIGINT)
- **GREEN**: Implement pattern checking
- **REFACTOR**: Extract pattern validation
- **CLEANUP**: Lint

### Cycle 7: Level 2 - Self-Reference Detection
- **RED**: Write test for self-referencing FK detection
- **GREEN**: Implement self-reference detection
- **REFACTOR**: Improve detection logic
- **CLEANUP**: Lint

## Dependencies
- Requires: Phase 1 complete ✅
- Blocks: Phase 3, 4

## Status
[ ] Not Started | [ ] In Progress | [ ] Complete
