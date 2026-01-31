# Phase 3: Levels 4 & 5 - Runtime & Full Execution Validation

## Objective
Implement runtime validation (Level 4) with database dry-run and full seed execution testing (Level 5) to catch runtime issues that static analysis can't detect.

## Success Criteria
- [ ] Level 4: Runtime validation (dry-run with SAVEPOINT)
- [ ] Level 5: Full execution test (load seeds and run transformations)
- [ ] Integration with database connection
- [ ] Detect NULL FKs after resolution
- [ ] Detect data integrity violations
- [ ] All unit + integration tests passing
- [ ] Code passes linting

## TDD Cycles

### Cycle 1: Level 4 - Database Connection & Target Validation
- **RED**: Write test for database connectivity check
- **GREEN**: Implement database connection validation
- **REFACTOR**: Extract connection logic
- **CLEANUP**: Format and lint

### Cycle 2: Level 4 - Table Existence Verification
- **RED**: Write test for target table existence in database
- **GREEN**: Implement table existence checking
- **REFACTOR**: Improve query efficiency
- **CLEANUP**: Lint

### Cycle 3: Level 4 - Column Type Validation
- **RED**: Write test for column type matching
- **GREEN**: Implement type checking against actual database schema
- **REFACTOR**: Extract type comparison logic
- **CLEANUP**: Lint

### Cycle 4: Level 4 - Dry-Run with SAVEPOINT
- **RED**: Write test for dry-run execution with rollback
- **GREEN**: Implement SAVEPOINT-based dry-run
- **REFACTOR**: Extract transaction management
- **CLEANUP**: Lint

### Cycle 5: Level 5 - Seed Loading
- **RED**: Write test for loading seed data into prep_seed
- **GREEN**: Implement seed file execution
- **REFACTOR**: Extract SQL execution logic
- **CLEANUP**: Lint

### Cycle 6: Level 5 - Resolution Execution
- **RED**: Write test for executing resolution functions
- **GREEN**: Implement function execution
- **REFACTOR**: Improve error handling
- **CLEANUP**: Lint

### Cycle 7: Level 5 - NULL FK Detection
- **RED**: Write test detecting NULL FKs after resolution
- **GREEN**: Implement NULL FK checking
- **REFACTOR**: Extract validation queries
- **CLEANUP**: Lint

### Cycle 8: Level 5 - Data Integrity Validation
- **RED**: Write test for constraint violations
- **GREEN**: Implement constraint checking
- **REFACTOR**: Extract constraint validation
- **CLEANUP**: Lint

## Dependencies
- Requires: Phase 1 & 2 complete ✅
- Blocks: Phase 4

## Status
[ ] Not Started | [ ] In Progress | [ ] Complete
