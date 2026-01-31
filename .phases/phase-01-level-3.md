# Phase 1: Core Models & Level 3 - Schema Drift Detection

## Objective
Implement core data models and Level 3 resolution function validation to detect schema drift (the bug that caused 360 test failures).

## Success Criteria
- [x] PrepSeedViolation model created
- [x] PrepSeedPattern enum with prep-seed-specific patterns
- [x] Level 3 validator detects schema drift in resolution functions
- [x] Level 3 validator detects missing FK transformations
- [x] Auto-fixer can correct schema references
- [x] All unit tests pass (RED → GREEN → REFACTOR → CLEANUP cycles)
- [x] Code passes linting (ruff check, format)

## TDD Cycles

### Cycle 1: Core Models - PrepSeedViolation & Report
- **RED**: Write test expecting PrepSeedViolation with severity, pattern, message
- **GREEN**: Implement minimal PrepSeedViolation dataclass
- **REFACTOR**: Add to_dict() for serialization
- **CLEANUP**: Format and lint

### Cycle 2: PrepSeedPattern Enum
- **RED**: Write test for prep-seed-specific patterns (SCHEMA_DRIFT, MISSING_FK_TRANSFORMATION, etc.)
- **GREEN**: Create enum with basic patterns
- **REFACTOR**: Add descriptions and fix_available flags
- **CLEANUP**: Lint and format

### Cycle 3: Level 3 - Resolution Function Parser
- **RED**: Write test that parses resolution function and extracts key info
- **GREEN**: Implement FunctionParser class with basic SQL parsing
- **REFACTOR**: Extract methods for readability
- **CLEANUP**: Lint

### Cycle 4: Level 3 - Schema Drift Detection
- **RED**: Write test that detects when function references wrong schema
- **GREEN**: Implement schema drift detection using regex
- **REFACTOR**: Improve regex robustness
- **CLEANUP**: Lint and add comments

### Cycle 5: Level 3 - Missing FK Transformation Detection
- **RED**: Write test that detects missing JOINs for FK transformations
- **GREEN**: Implement FK transformation detection
- **REFACTOR**: Extract JOIN detection logic
- **CLEANUP**: Lint

### Cycle 6: Level 3 - Validator Integration
- **RED**: Write test that validates complete resolution function
- **GREEN**: Create Level3ResolutionValidator class
- **REFACTOR**: Add context managers for error handling
- **CLEANUP**: Lint

### Cycle 7: Auto-Fixer - Schema Reference Updates
- **RED**: Write test that fixes schema references (tenant.tb_x → catalog.tb_x)
- **GREEN**: Implement PrepSeedFixer.fix_schema_drift()
- **REFACTOR**: Improve regex for edge cases
- **CLEANUP**: Lint

## Dependencies
- Requires: Nothing (first phase)
- Blocks: Phases 2, 3, 4

## Status
[~] In Progress | Implementation underway
