# Confiture - Required Fixes for Production

**Generated**: January 16, 2026
**Based on**: Independent Code Review
**Urgency**: CRITICAL (blocks Phase 6 production release)

---

## Priority 1: CRITICAL (Fix Before Any Production Use)

### Fix 1.1: Update Coverage Documentation

**Issue**: CLAUDE.md claims 82% coverage, actual is 52.60%

**Current State**:
```markdown
# From CLAUDE.md:
- **Test Coverage**: 81.68% (332 tests passing, 0 skipped)
```

**Reality**:
```bash
$ pytest --cov=confiture --cov-report=term
TOTAL: 52.60% coverage (899 tests passing, 0 skipped)
```

**Fix Required**:
- [ ] Update CLAUDE.md line with actual coverage (52.60%)
- [ ] Document coverage by component
- [ ] Set realistic targets for Phase 6 (80% minimum)

**Effort**: 2 hours
**Files to Update**: CLAUDE.md

---

### Fix 1.2: Fix SchemaLinter API Design

**Issue**: API doesn't match documentation or user expectations

**Current Broken Code**:
```python
# From schema_linter.py line 48:
def lint(self) -> LintReport:
    """Lint schema and return violations."""
    # NO SCHEMA PARAMETER!
```

**Problem**: No way to pass schema to linter
- Constructor doesn't take schema: `SchemaLinter()` (no args)
- `lint()` method doesn't take schema: `.lint()` (no args)
- **Question**: How is schema provided? Database? Files? Unknown!

**Fix Required** (Choose one design):

**Option A: Schema in Constructor** (RECOMMENDED)
```python
# New design:
linter = SchemaLinter(schema=my_schema)
result = linter.lint()

# Changes needed:
1. Add schema parameter to __init__
2. Store schema as instance variable
3. Update lint() to use self.schema
4. Update all documentation and examples
5. Update all tests to use new API
```

**Option B: Schema as Parameter**
```python
# Alternative design:
linter = SchemaLinter()
result = linter.lint(schema=my_schema)

# Changes needed:
1. Add schema parameter to lint()
2. Update documentation
3. Update all tests
```

**Effort**: 4-8 hours (design + implementation + tests)
**Files to Modify**:
- `python/confiture/core/linting/schema_linter.py`
- All tests using SchemaLinter
- All documentation examples

**Verification**:
```bash
# After fix, this should work:
from confiture.core.linting import SchemaLinter
schema = {"tables": {...}}
linter = SchemaLinter(schema=schema)
result = linter.lint()
assert result is not None
assert len(result.violations) >= 0
```

---

### Fix 1.3: Test Linting System (0% Coverage)

**Issue**: 141 lines of linting code are completely untested

```
python/confiture/core/linting.py    141    141   0.00%
```

**Required Tests** (20+ minimum):

1. **Basic Linting** (5 tests)
   ```python
   def test_lint_empty_schema():
   def test_lint_schema_with_tables():
   def test_lint_schema_with_violations():
   def test_lint_with_naming_rule():
   def test_lint_with_security_rule():
   ```

2. **Compliance Libraries** (5 tests)
   ```python
   def test_lint_with_gdpr_library():
   def test_lint_with_hipaa_library():
   def test_lint_with_sox_library():
   def test_lint_with_pci_dss_library():
   def test_lint_with_general_library():
   ```

3. **Schema Complexity** (3 tests)
   ```python
   def test_lint_complex_schema_100_tables():
   def test_lint_schema_with_circular_fks():
   def test_lint_schema_with_deep_inheritance():
   ```

4. **Error Handling** (5 tests)
   ```python
   def test_lint_invalid_schema():
   def test_lint_missing_required_columns():
   def test_lint_rule_conflict():
   def test_lint_version_mismatch():
   def test_lint_with_deprecated_rule():
   ```

5. **Performance** (2 tests)
   ```python
   def test_lint_performance_baseline():
   def test_lint_with_1000_rules():
   ```

**Effort**: 1-2 weeks
**Files to Create/Modify**:
- `tests/unit/test_linting_system.py` (NEW)
- `tests/integration/test_linting_integration.py` (NEW)

**Target Coverage**: 80%+ on linting.py

---

## Priority 2: IMPORTANT (Fix Before Phase 6 Production)

### Fix 2.1: Test Hook Registry Execution (35% Not Covered)

**Issue**: 22 lines of hook execution sequencing completely untested

```
python/confiture/core/hooks/registry.py    107     38  64.49%
  Uncovered: 156-176 (22 lines - HOOK EXECUTION)
  Uncovered: 281-305 (25 lines - ERROR HANDLING)
```

**Required Tests** (15+ minimum):

1. **Sequential Execution** (3 tests)
   ```python
   def test_sequential_hooks_execute_in_order():
   def test_sequential_hooks_pass_context():
   def test_sequential_hooks_context_mutations():
   ```

2. **Parallel Execution** (3 tests)
   ```python
   def test_parallel_hooks_all_execute():
   def test_parallel_hooks_context_isolation():
   def test_parallel_hooks_concurrency_safe():
   ```

3. **DAG Execution** (3 tests)
   ```python
   def test_dag_execution_respects_dependencies():
   def test_dag_execution_cycle_detection():
   def test_dag_execution_parallel_paths():
   ```

4. **Error Handling** (6 tests)
   ```python
   def test_hook_exception_stops_sequence():
   def test_hook_exception_is_caught():
   def test_hook_timeout_handled():
   def test_invalid_hook_rejected():
   def test_hook_conflict_detected():
   def test_hook_version_mismatch():
   ```

**Effort**: 3-5 days
**Files to Create/Modify**:
- `tests/unit/test_hook_registry_execution.py` (NEW)
- `tests/integration/test_hook_registry_integration.py` (NEW)

**Target Coverage**: 90%+ on registry.py

---

### Fix 2.2: Test Risk Predictor Edge Cases (38% Not Covered)

**Issue**: Historical data and confidence calculation untested

```
python/confiture/core/risk/predictor.py    61     23  62.30%
  Uncovered: 99-118 (20 lines - HISTORICAL DATA)
  Uncovered: 144-172 (29 lines - CONFIDENCE BOUNDS)
```

**Required Tests** (10+ minimum):

```python
def test_historical_data_small_dataset():
def test_historical_data_large_dataset():
def test_historical_data_no_matches():
def test_confidence_bounds_calculation():
def test_confidence_bounds_accuracy():
def test_anomaly_detection_integration():
def test_downtime_estimation_accuracy():
def test_prediction_with_missing_history():
def test_prediction_calibration():
def test_prediction_confidence_levels():
```

**Effort**: 3-4 days
**Files to Create/Modify**:
- `tests/unit/test_risk_predictor_advanced.py` (NEW)

**Target Coverage**: 85%+ on predictor.py

---

## Priority 3: IMPORTANT (Nice to Have)

### Fix 3.1: Fix Test Isolation Issues

**Issue**: Tests fail when run with `-x` flag (exit on first failure)

```bash
$ uv run pytest tests/e2e/test_cli.py -x --tb=short
# First run: FAILED (test_up_applies_pending_migrations)

$ uv run pytest tests/e2e/test_cli.py::TestMigrateUpCommand::test_up_applies_pending_migrations -v
# Run individually: PASSED
```

**Problem**: Tests have order dependencies

**Fix Required**:
1. Run tests in random order
   ```bash
   pytest --random-order
   ```
2. Verify all tests pass individually
3. Fix any test order dependencies found
4. Add `--random-order` to CI/CD

**Effort**: 2-3 hours
**Files to Modify**:
- `.github/workflows/ci.yml` (add --random-order flag)

---

### Fix 3.2: Test Linting Composer Conflicts (22% Not Covered)

**Issue**: Conflict detection and resolution untested

```
python/confiture/core/linting/composer.py    93     20  78.49%
  Uncovered: 89-97 (9 lines - CONFLICT DETECTION)
  Uncovered: 176-183 (8 lines - CONFLICT RESOLUTION)
```

**Required Tests** (8+ minimum):

```python
def test_compose_libraries_with_conflicts():
def test_conflict_detection_identifies_all():
def test_conflict_resolution_strategy():
def test_compose_gdpr_and_hipaa_no_conflicts():
def test_compose_three_libraries_with_conflicts():
def test_conflict_error_messaging():
def test_composed_rules_deduplicated():
def test_composed_rules_versioned():
```

**Effort**: 2-3 days
**Files to Create/Modify**:
- `tests/unit/test_linting_composer_advanced.py` (NEW)

---

### Fix 3.3: Test Version Enforcement Logic (37% Not Covered)

**Issue**: Version compatibility and deprecation untested

```
python/confiture/core/linting/versioning.py    72     27  62.50%
  Uncovered: 88-92 (5 lines - VERSION COMPATIBILITY)
  Uncovered: 96-100 (5 lines - DEPRECATION)
  Uncovered: 121-137 (17 lines - VERSION RESOLUTION)
  Uncovered: 145-149 (5 lines - RULE ENFORCEMENT)
```

**Required Tests** (8+ minimum):

```python
def test_version_compatibility_check():
def test_version_incompatibility_detected():
def test_deprecated_rule_warning():
def test_removed_rule_error():
def test_version_resolution_strategy():
def test_rule_enforcement_with_versions():
def test_mixed_version_composition():
def test_version_mismatch_error():
```

**Effort**: 2-3 days
**Files to Create/Modify**:
- `tests/unit/test_versioning_advanced.py` (NEW)

---

### Fix 3.4: Test or Remove Untested Modules

**Issue**: Scenarios (228 lines), Monitoring (96 lines), Performance (187 lines) completely untested

**Decision Needed**:
- **If production-ready**: Add tests, document, put in Phase 5 roadmap
- **If experimental**: Mark as such, move to examples/, remove from main code
- **If dead code**: Delete entirely

**Investigation Required**:

1. **Scenarios Module** (228 lines)
   - Are these used by real users?
   - Are they integration examples or actual features?
   - Decision: Test, document, or remove?

2. **Monitoring/Performance** (283 lines)
   - Is SLO tracking actually used?
   - Is performance baseline manager implemented?
   - Is query profiler functional?
   - Decision: Test, document, or mark experimental?

3. **Data Fixtures** (225 lines)
   - Test infrastructure should itself be tested
   - Should verify fixtures work as documented

**Effort**: 1-2 weeks (depends on decisions)

---

## Implementation Checklist

### Phase 1: Critical Fixes (Week 1)
- [ ] Update CLAUDE.md with correct coverage (52.60%)
- [ ] Fix SchemaLinter API design
- [ ] Add 20+ linting system tests
- [ ] Verify coverage reaches 80%+ on linting.py

### Phase 2: Important Fixes (Week 2)
- [ ] Add 15+ hook registry execution tests
- [ ] Add 10+ risk predictor edge case tests
- [ ] Fix test isolation issues
- [ ] Run tests with --random-order

### Phase 3: Nice-to-Have Fixes (Week 3-4)
- [ ] Add composer conflict resolution tests
- [ ] Add versioning enforcement tests
- [ ] Investigate/document/test/remove untested modules

---

## Verification Commands

After fixes, verify with:

```bash
# Full test suite
uv run pytest tests/ -v --random-order

# Coverage report
uv run pytest --cov=confiture --cov-report=term | tail -50

# Linting coverage specifically
uv run pytest --cov=confiture.core.linting --cov-report=term

# Hook registry coverage specifically
uv run pytest --cov=confiture.core.hooks --cov-report=term

# Risk predictor coverage specifically
uv run pytest --cov=confiture.core.risk --cov-report=term
```

**Success Criteria**:
- [ ] All tests pass
- [ ] Coverage >= 80% overall
- [ ] Coverage >= 90% on Phase 6 critical paths
- [ ] No test order dependencies (--random-order passes)
- [ ] All APIs documented and working

---

## Timeline Estimate

| Priority | Task | Effort | Timeline |
|----------|------|--------|----------|
| 1 | Update docs | 2h | Day 1 |
| 1 | Fix SchemaLinter API | 6h | Day 1-2 |
| 1 | Add linting tests | 40h | Week 1 |
| 2 | Add hook registry tests | 24h | Week 2 |
| 2 | Add risk predictor tests | 16h | Week 2 |
| 2 | Fix test isolation | 3h | Week 2 |
| 3 | Add composer tests | 16h | Week 3 |
| 3 | Add versioning tests | 16h | Week 3 |
| 3 | Investigate other modules | 8h | Week 3 |
| **Total** | | **131h** | **3-4 weeks** |

---

## Recommended Order

**Do NOT do all in parallel** - instead:

1. **Day 1-2**: Update docs + Fix SchemaLinter API
   - Low effort, unblocks other work
   - Gets documentation correct immediately

2. **Week 1**: Add linting tests
   - Critical issue (0% coverage)
   - Enables discovery of other linting bugs

3. **Week 2**: Add hook registry + risk predictor tests
   - Important for Phase 6 production
   - Can run in parallel

4. **Week 3**: Nice-to-have improvements
   - Lower priority
   - Can happen after Phase 6 approval

---

## Questions Blocking Implementation

Before starting fixes, team needs to decide:

1. **SchemaLinter API**: Constructor or parameter? (Blocks Fix 1.2)
2. **Scenarios Module**: Productionize or remove? (Affects Fix 3.4)
3. **Monitoring/Performance**: Needed or experimental? (Affects Fix 3.4)
4. **Phase 6 Timeline**: When needed for production? (Affects priority)

---

**Review Generated**: January 16, 2026
**Reviewer**: Independent Code Auditor
**Authority**: Can block production deployment

Contact with questions about specific fixes.

