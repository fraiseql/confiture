# Phase 4.2 Implementation Plan

**Status**: Ready to Start
**Date**: 2025-12-26
**Total Effort**: ~40-48 hours (1 week)
**Approach**: TDD (RED → GREEN → REFACTOR → QA)

---

## Overview

Phase 4.2 implements 4 major deliverables building on Phase 4.1's solid foundation:

1. **Interactive Wizard** - Guide users through complex migrations safely
2. **Schema Linting** - Validate schemas against best practices
3. **Entry Points Support** - Third-party hook discovery via setuptools
4. **Structured Logging** - Production observability for hooks and dry-runs

---

## Architecture Decision Summary

### Deliverable 1: Interactive Wizard

**Components**:
- `RiskAssessmentEngine` - Analyze migrations and assign risk scores
- `MigrationPreview` - Display SQL, estimated time, hooks
- `WizardUI` - Interactive Typer CLI interface
- `RiskScores` - Data models for risk assessment

**Files to Create**:
- `python/confiture/core/wizard.py` (RiskAssessmentEngine, MigrationPreview)
- `python/confiture/models/risk.py` (RiskScores, RiskCategory)
- `tests/unit/test_wizard.py` (unit tests)
- `tests/integration/test_wizard_interactive.py` (integration tests)

**Dependencies**:
- Uses `DryRunExecutor.run()` for metrics
- Uses `HookExecutor.execute_phase()` for hook analysis
- Uses `SchemaDiffer` for change analysis

**Integration**:
- Add `confiture migrate --interactive` CLI option
- Hook into existing migrator flow

### Deliverable 2: Schema Linting

**Components**:
- `SchemaLinter` - Main linter orchestrator
- `LintRule` - Abstract base for lint rules
- 6 Built-in rules:
  - `NamingConventionRule` (snake_case for tables/columns)
  - `PrimaryKeyRule` (all tables need PK)
  - `DocumentationRule` (tables need comments)
  - `MultiTenantRule` (tenant_id in multi-tenant tables)
  - `MissingIndexRule` (FK columns should be indexed)
  - `SecurityRule` (password handling, etc)
- `LintConfig` - Configuration via YAML
- `LintReport` - Violations and severity tracking

**Files to Create**:
- `python/confiture/core/linting.py` (SchemaLinter, LintRule, built-in rules)
- `python/confiture/models/lint.py` (LintConfig, LintReport, Violation)
- `tests/unit/test_linting.py` (unit tests)
- `tests/integration/test_linting_rules.py` (integration tests)

**Dependencies**:
- Uses `SchemaBuilder` to load DDL
- Uses `SchemaDiffer` to query schema metadata
- Uses psycopg for schema introspection

**Integration**:
- Add `confiture lint` CLI command
- Add `confiture.yaml` config support for lint rules
- Optional: pre-migration linting check

### Deliverable 3: Entry Points Support

**Components**:
- Update `HookRegistry._load_entry_points()` method
- Add importlib.metadata integration
- Python 3.9+ compatibility handling

**Files to Modify**:
- `python/confiture/core/hooks.py` (HookRegistry class)

**Files to Create**:
- `tests/unit/test_entry_points.py` (unit tests)
- `tests/integration/test_entry_points_loading.py` (integration tests)

**Dependencies**:
- Standard library: importlib.metadata
- Backward compatible with current registry.register()

**Integration**:
- HookRegistry automatically discovers entry points on init
- No CLI changes needed
- Users configure via their pyproject.toml

### Deliverable 4: Structured Logging

**Components**:
- Logger instances in hooks.py and dry_run.py
- Structured logging calls at key points:
  - `executing_hooks` (phase start)
  - `hook_start` (individual hook start)
  - `hook_completed` (hook success)
  - `hook_failed` (hook error with traceback)
  - `phase_completed` (phase end)
  - `dry_run_start` (dry-run start)
  - `dry_run_completed` (dry-run success)
  - `dry_run_failed` (dry-run error)

**Files to Modify**:
- `python/confiture/core/hooks.py` (HookExecutor class)
- `python/confiture/core/dry_run.py` (DryRunExecutor class)

**Files to Create**:
- `tests/unit/test_logging.py` (logging output verification)
- `docs/logging.md` (logging configuration guide)

**Dependencies**:
- Standard library: logging, time
- Optional: python-json-logger for structured JSON logs

**Integration**:
- Transparent to existing code
- Users configure via Python logging config
- Works with any logging handler/formatter

---

## Implementation Sequence

### Phase 4.2.1: Foundation & Entry Points (Week 1, Days 1-2)

**Tasks**:
1. Add entry points support to HookRegistry
   - Implement `_load_entry_points()` method
   - Add Python 3.9+ compatibility handling
   - Add logging for load failures
   - Write tests for entry point discovery

2. Add structured logging to hooks.py and dry_run.py
   - Import logging module
   - Create logger instances
   - Add logging calls at all key points
   - Write tests for log output

**Why first**: Logging is non-invasive and entry points are simple. They unblock wizard and linting development.

**Files Changed**: 2 core modules
**Tests Added**: ~20 tests
**Time**: ~8-10 hours

### Phase 4.2.2: Schema Linting (Week 1, Days 2-4)

**Tasks**:
1. Create linting models
   - `LintConfig` - Configuration schema
   - `Violation` - Single violation record
   - `LintReport` - Aggregated violations

2. Create SchemaLinter and LintRule base
   - Abstract LintRule class
   - SchemaLinter orchestrator

3. Implement 6 built-in rules
   - NamingConventionRule
   - PrimaryKeyRule
   - DocumentationRule
   - MultiTenantRule
   - MissingIndexRule
   - SecurityRule

4. Add `confiture lint` CLI command
   - Configuration file support
   - Severity thresholds
   - Output formatting (table, JSON, etc)

5. Write comprehensive tests

**Why this order**: Linting is complex with 6 rules. Breaking into logical steps. Tests drive implementation via TDD.

**Files Created**: 3 new modules + tests
**Tests Added**: ~40 tests
**Time**: ~16-18 hours

### Phase 4.2.3: Interactive Wizard (Week 2, Days 1-3)

**Tasks**:
1. Create risk models
   - RiskCategory enum
   - RiskScore dataclass
   - RiskAssessment dataclass

2. Implement RiskAssessmentEngine
   - Analyze migration DDL changes
   - Detect risk factors (lock time, data loss, etc)
   - Generate risk scores per migration
   - Identify affected tables

3. Create MigrationPreview
   - Format SQL for display
   - Calculate estimated execution time
   - List hooks that will execute
   - Show rollback strategy

4. Build WizardUI
   - Interactive Typer interface
   - Risk display with emoji/colors
   - Recommendations display
   - Hook details display
   - Progress tracking

5. Integrate with CLI
   - Add `--interactive` flag to migrate command
   - Wire up DryRunExecutor for metrics
   - Live progress display

6. Write comprehensive tests

**Why this order**: Builds on linting and logging. RiskAssessmentEngine is the core complexity. WizardUI is presentation layer.

**Files Created**: 3 new modules + tests
**Tests Added**: ~35 tests
**Time**: ~14-16 hours

### Phase 4.2.4: Testing, Documentation, Validation (Week 2, Days 4-5)

**Tasks**:
1. Run full test suite
   - All Phase 4.2 tests passing
   - No regressions in Phase 4.1
   - Coverage >85%

2. Integration testing
   - Real database testing
   - End-to-end workflows

3. Documentation
   - Linting configuration guide
   - Wizard usage guide
   - Entry points plugin development guide
   - Logging configuration examples
   - Update PHASES.md

4. Performance verification
   - Linting performance on large schemas
   - Wizard responsiveness

5. Final quality checks
   - Code formatting (ruff)
   - Type checking (mypy)
   - No deprecation warnings

**Time**: ~8-10 hours

---

## Test-Driven Development (TDD) Approach

Each deliverable follows: RED → GREEN → REFACTOR → QA

### RED Phase
- Write failing test that specifies the feature
- Run test, confirm it fails
- Commit with message `test: [feature name] [RED]`

### GREEN Phase
- Write minimal code to pass the test
- Run test, confirm it passes
- No other tests should break
- Commit with message `feat: [feature name] [GREEN]`

### REFACTOR Phase
- Improve code quality, readability, efficiency
- All tests still pass
- Remove duplication, extract methods, simplify logic
- Commit with message `refactor: [feature name] [REFACTOR]`

### QA Phase
- Full test suite passes
- Coverage checks pass
- Linting passes (ruff)
- Type checking passes (mypy)
- No performance regressions
- Commit with message `test: [feature name] [QA]` or include in feature commit

---

## File Structure Summary

**New Files**:
```
python/confiture/
├── core/
│   ├── linting.py          # SchemaLinter, LintRule, 6 rules
│   ├── wizard.py           # RiskAssessmentEngine, MigrationPreview
│
├── models/
│   ├── lint.py             # LintConfig, Violation, LintReport
│   ├── risk.py             # RiskScore, RiskCategory, RiskAssessment
│
tests/
├── unit/
│   ├── test_linting.py     # 40 tests for linting
│   ├── test_wizard.py      # 35 tests for wizard
│   ├── test_entry_points.py # 10 tests for entry points
│   ├── test_logging.py     # 15 tests for logging
│
├── integration/
│   ├── test_linting_rules.py      # 15 tests with database
│   ├── test_wizard_interactive.py # 10 tests with database
│   ├── test_entry_points_loading.py # 5 tests
│
docs/
├── linting.md              # Linting configuration and rules
├── wizard.md               # Interactive wizard usage
├── entry-points.md         # Plugin development guide
├── logging.md              # Logging configuration examples
```

**Modified Files**:
```
python/confiture/
├── core/
│   ├── hooks.py            # Add logging to HookExecutor
│   ├── dry_run.py          # Add logging to DryRunExecutor
│
├── cli/
│   ├── main.py             # Add 'lint' command, '--interactive' flag

.phases/
├── PHASE_4_2_IMPLEMENTATION_PLAN.md  # This file
```

---

## Success Criteria

### Functionality
- ✅ All 4 deliverables working end-to-end
- ✅ 110+ new tests, all passing
- ✅ Zero regressions in Phase 4.1

### Code Quality
- ✅ Type hints on all new code
- ✅ Docstrings on all public methods
- ✅ ruff and mypy passing
- ✅ >85% code coverage

### Documentation
- ✅ User guides for all 4 features
- ✅ API documentation for developers
- ✅ Configuration examples
- ✅ Troubleshooting guide updates

### Performance
- ✅ Linting on 500+ table schemas < 5s
- ✅ Wizard UI responsive (<200ms)
- ✅ No logging performance overhead

---

## Risk Assessment

**Low Risk Areas**:
- Entry points support (simple, standard Python mechanism)
- Structured logging (non-invasive, no logic changes)
- Linting rules (self-contained, testable)

**Medium Risk Areas**:
- RiskAssessmentEngine (complex heuristics for risk scoring)
- WizardUI (interactive component, UX complexity)

**Mitigation**:
- Extensive unit tests for RiskAssessmentEngine
- Manual testing of WizardUI with real migrations
- Integration tests with real databases
- Fallback modes if risk assessment unavailable

---

## Dependencies

**Phase 4.2 requires**:
- ✅ Phase 4.1 complete (hooks, dry-run)
- ✅ HookRegistry with plugin pattern
- ✅ DryRunExecutor for metrics
- ✅ SchemaDiffer for analysis

**Phase 4.2 does NOT require**:
- ❌ Rust extensions (Phase 2)
- ❌ Database schema introspection libraries
- ❌ New external dependencies (uses stdlib logging, importlib.metadata)

---

## Next Steps

1. **Now**: Start Phase 4.2.1 (Entry Points + Logging)
   - Create test files with RED phase tests
   - Implement Entry Points support in HookRegistry
   - Add Structured Logging to hooks.py and dry_run.py

2. **Then**: Phase 4.2.2 (Schema Linting)
   - Create models (LintConfig, Violation, LintReport)
   - Create linting.py with SchemaLinter and rules
   - Add CLI command

3. **Then**: Phase 4.2.3 (Interactive Wizard)
   - Create models (RiskScore, RiskAssessment)
   - Create wizard.py with RiskAssessmentEngine
   - Build WizardUI with Typer integration

4. **Finally**: Phase 4.2.4 (Testing, Docs, Validation)
   - Full test suite execution
   - Documentation and examples
   - Final quality checks

---

**Ready to start Phase 4.2.1. Foundation is solid. 🍓**
