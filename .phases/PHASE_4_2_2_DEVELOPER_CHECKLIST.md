# Phase 4.2.2: Developer Implementation Checklist

**Status**: 🎯 Ready to Code
**Phase**: Phase 4.2.2 - Schema Linting
**Duration**: 3-4 working days
**Start Date**: 2025-12-26

---

## Pre-Implementation Checklist

### Preparation (15 minutes)

- [ ] Read **PHASE_4_2_2_EXECUTIVE_SUMMARY.md** (overview)
- [ ] Read **PHASE_4_2_2_SCHEMA_LINTING_PLAN.md** (detailed implementation)
- [ ] Ensure Phase 4.2.1 tests still pass:
  ```bash
  uv run pytest tests/ -v | grep -E "(PASSED|FAILED|ERROR)"
  ```
- [ ] Verify test database is running:
  ```bash
  psql postgresql://localhost/confiture_test -c "SELECT 1"
  ```
- [ ] Create feature branch:
  ```bash
  git checkout -b feature/phase-4.2.2-schema-linting
  ```

---

## Day 1: Models Implementation

### Phase 1.1: Create Test File (RED)

```bash
# Create tests/unit/test_linting_models.py with failing tests
touch tests/unit/test_linting_models.py
```

**Copy-paste test skeleton**:
```python
import pytest
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

# These should FAIL before implementation
def test_violation_creation():
    """Violation should store all information."""
    from confiture.models.lint import Violation, LintSeverity

    violation = Violation(
        rule_name="TestRule",
        severity=LintSeverity.ERROR,
        message="Test message",
        location="test_location"
    )
    assert violation.rule_name == "TestRule"
    assert violation.severity == LintSeverity.ERROR

def test_lint_config_default():
    """LintConfig.default() should have all rules."""
    from confiture.models.lint import LintConfig

    config = LintConfig.default()
    assert config is not None
    assert "naming_convention" in config.rules

# ... 8 more test cases (see PLAN for full list)
```

**Run tests to confirm they FAIL**:
```bash
uv run pytest tests/unit/test_linting_models.py -v
# Expected: 10 FAILED tests
```

**Commit**:
```bash
git add tests/unit/test_linting_models.py
git commit -m "test: linting models [RED]"
```

### Phase 1.2: Implement Models (GREEN)

```bash
# Create models/lint.py
touch python/confiture/models/lint.py
```

**Implement these classes** (see PLAN for full code):

1. **LintSeverity** (Enum)
   - ERROR
   - WARNING
   - INFO

2. **Violation** (Dataclass)
   - rule_name: str
   - severity: LintSeverity
   - message: str
   - location: str
   - suggested_fix: str | None

3. **LintConfig** (Dataclass)
   - enabled: bool
   - rules: dict
   - fail_on_error: bool
   - fail_on_warning: bool
   - exclude_tables: list
   - from_yaml() classmethod
   - default() classmethod

4. **LintReport** (Dataclass)
   - violations: list
   - schema_name: str
   - tables_checked: int
   - columns_checked: int
   - errors_count: int
   - warnings_count: int
   - info_count: int
   - execution_time_ms: int
   - Properties: has_errors, has_warnings
   - Methods: violations_by_severity()

**Run tests to confirm they PASS**:
```bash
uv run pytest tests/unit/test_linting_models.py -v
# Expected: 10 PASSED tests
```

**Commit**:
```bash
git add python/confiture/models/lint.py
git commit -m "feat: linting models (Violation, Config, Report) [GREEN]"
```

### Phase 1.3: Refactor & Polish (REFACTOR)

```python
# In models/lint.py:
# - Add __str__ and __repr__ methods
# - Add type hints throughout
# - Add docstrings to classes and methods
# - Ensure PEP 8 compliance
```

**Quality checks**:
```bash
uv run ruff check python/confiture/models/lint.py
uv run ruff format python/confiture/models/lint.py
uv run mypy python/confiture/models/lint.py
```

**Run tests again**:
```bash
uv run pytest tests/unit/test_linting_models.py -v
# Expected: 10 PASSED tests (still)
```

**Commit**:
```bash
git commit -m "refactor: improve linting models code quality [REFACTOR]"
```

### Phase 1.4: Quality Assurance (QA)

```bash
# Full quality checks
uv run pytest tests/unit/test_linting_models.py -v --cov=confiture.models.lint
uv run ruff check python/confiture/models/lint.py
uv run mypy confiture/
```

**Expected Results**:
- ✅ 10/10 tests passing
- ✅ >90% coverage on lint.py
- ✅ No ruff errors
- ✅ No type errors

**Final commit** (if needed for cleanup):
```bash
git commit -m "test: linting models - all QA checks passing [QA]"
```

---

## Day 2: SchemaLinter & Rules Implementation

### Phase 2.1: Create Test File (RED)

```bash
# Create tests/unit/test_linting_core.py
touch tests/unit/test_linting_core.py

# Create tests/unit/test_linting_rules.py
touch tests/unit/test_linting_rules.py
```

**Test skeleton** (30 tests total):
- 10 tests for SchemaLinter core
- 20 tests for individual rules (3-4 per rule)

**Run tests to confirm they FAIL**:
```bash
uv run pytest tests/unit/test_linting_core.py tests/unit/test_linting_rules.py -v
# Expected: 30 FAILED tests
```

**Commit**:
```bash
git add tests/unit/test_linting_*.py
git commit -m "test: schema linting core and rules [RED]"
```

### Phase 2.2: Implement SchemaLinter & Rules (GREEN)

```bash
# Create core/linting.py
touch python/confiture/core/linting.py
```

**Implement** (see PLAN for full code):

1. **LintRule** (Abstract Base)
   - name: str
   - description: str
   - enabled_by_default: bool
   - lint() method (abstract)

2. **SchemaLinter** (Orchestrator)
   - __init__(env, config, conn)
   - _register_rules()
   - lint() → LintReport

3. **Six Rules** (in order):
   - NamingConventionRule
   - PrimaryKeyRule
   - DocumentationRule
   - MultiTenantRule
   - MissingIndexRule
   - SecurityRule

**Run tests**:
```bash
uv run pytest tests/unit/test_linting_core.py tests/unit/test_linting_rules.py -v
# Expected: 30 PASSED tests
```

**Quick check for existing tests**:
```bash
uv run pytest tests/unit/test_hooks.py -v  # Should still pass (Phase 4.1)
uv run pytest tests/unit/test_dry_run.py -v  # Should still pass (Phase 4.1)
```

**Commit**:
```bash
git add python/confiture/core/linting.py
git commit -m "feat: schema linting with 6 rules [GREEN]"
```

### Phase 2.3: Refactor & Polish (REFACTOR)

```python
# In core/linting.py:
# - Extract helper methods (_is_valid_name, _suggest_name, etc.)
# - Improve code organization
# - Simplify complex logic
# - Add docstrings to all methods
```

**Quality checks**:
```bash
uv run ruff check python/confiture/core/linting.py
uv run ruff format python/confiture/core/linting.py
uv run mypy python/confiture/core/linting.py
```

**Run all tests**:
```bash
uv run pytest tests/unit/test_linting*.py -v
# Expected: 40 PASSED tests (30 + 10 from Day 1)
```

**Commit**:
```bash
git commit -m "refactor: improve linting code organization and clarity [REFACTOR]"
```

### Phase 2.4: Quality Assurance (QA)

```bash
# Full validation
uv run pytest tests/unit/test_linting*.py -v --cov=confiture.core.linting,confiture.models.lint
uv run ruff check python/confiture/
uv run mypy confiture/
```

**Expected Results**:
- ✅ 40/40 tests passing
- ✅ >85% coverage on linting.py
- ✅ No ruff errors
- ✅ No type errors
- ✅ Zero regressions in Phase 4.1 tests

**Commit** (if needed):
```bash
git commit -m "test: schema linting - all QA checks passing [QA]"
```

---

## Day 3: CLI Integration & Integration Tests

### Phase 3.1: Add CLI Command

```bash
# Edit cli/main.py - add @app.command() for lint
```

**Implement** (see PLAN for full code):
- `lint()` command function
- Helper functions: format_report_table(), format_report_json(), format_report_csv()
- Integration with SchemaLinter
- Error handling and exit codes

**Test the command manually**:
```bash
# Should work (default config)
uv run confiture lint

# Should work (custom env)
uv run confiture lint --env production

# Should work (different formats)
uv run confiture lint --format json
uv run confiture lint --format csv

# Should work (fail on warning)
uv run confiture lint --fail-on-warning
```

**Commit**:
```bash
git add python/confiture/cli/main.py
git commit -m "feat: confiture lint CLI command [GREEN]"
```

### Phase 3.2: Integration Tests

```bash
# Create tests/integration/test_linting_rules.py
touch tests/integration/test_linting_rules.py
```

**Implement** (15+ tests):
- test_linting_real_schema (5 tests)
- test_linting_with_config (5 tests)
- test_cli_lint_command (5 tests)

**Run integration tests**:
```bash
uv run pytest tests/integration/test_linting_rules.py -v
# Expected: 15+ PASSED tests
```

**Commit**:
```bash
git add tests/integration/test_linting_rules.py
git commit -m "test: integration tests for linting [GREEN]"
```

### Phase 3.3: Full Test Suite

```bash
# Run ALL tests (phases 4.2.1 + 4.2.2)
uv run pytest tests/ -v --cov=confiture --cov-report=term-missing
```

**Expected Results**:
- ✅ 55+ new tests (40 unit + 15 integration)
- ✅ 330+ total tests passing (Phase 4.1 + Phase 4.2.2)
- ✅ >85% coverage
- ✅ Zero regressions

**Quality checks**:
```bash
uv run ruff check .
uv run mypy confiture/
```

**Commit**:
```bash
git commit -m "test: complete linting test suite [QA]"
```

---

## Day 4: Documentation & Polish

### Phase 4.1: Create Documentation

```bash
# Create docs/linting.md
touch docs/linting.md
```

**Include sections**:
1. Quick Start (3 examples)
2. Configuration (confiture.yaml format)
3. Rules Reference (all 6 rules explained)
4. Output Formats (table, JSON, CSV)
5. CLI Reference (all flags)
6. Integration Examples (CI/CD, pre-commit hooks)
7. Troubleshooting (common issues)

**Documentation template** (see PLAN for full content):
```markdown
# Schema Linting

## Quick Start

confiture lint                    # Check with defaults
confiture lint --env production   # Check production
confiture lint --format json      # JSON output

## Configuration

```yaml
linting:
  fail_on_error: true
  rules:
    naming_convention:
      style: snake_case
    # ... more rules
```

## Rules

### 1. NamingConventionRule
...

### 2. PrimaryKeyRule
...

# ... etc for all 6 rules
```

**Commit**:
```bash
git add docs/linting.md
git commit -m "docs: schema linting guide and reference"
```

### Phase 4.2: Update README

```bash
# Edit README.md - add linting feature to features list
```

**Add to feature checklist**:
```markdown
## Features

- ✅ Build from DDL (Medium 1)
- ✅ Incremental migrations (Medium 2)
- ✅ Schema diff detection
- ✅ **Schema Linting** (6 rules, best practices) ← NEW
- ✅ Production sync (Medium 3)
- ✅ Zero-downtime migrations (Medium 4)
```

**Commit**:
```bash
git add README.md
git commit -m "docs: add linting to feature list"
```

### Phase 4.3: Final Quality Checks

```bash
# Full validation suite
uv run pytest tests/ -v --cov=confiture --cov-report=html
uv run ruff check . --fix
uv run mypy confiture/
uv run pytest --maxfail=1  # Stop on first failure
```

**Checklist**:
- [ ] All 330+ tests passing
- [ ] >85% coverage maintained
- [ ] No ruff errors
- [ ] No type errors
- [ ] No deprecation warnings

**Commit** (if any fixes):
```bash
git commit -m "chore: final quality checks and polish"
```

---

## File Checklist

### New Files Created

- [ ] `python/confiture/models/lint.py` (~150 lines)
- [ ] `python/confiture/core/linting.py` (~500 lines)
- [ ] `tests/unit/test_linting_models.py` (~150 lines)
- [ ] `tests/unit/test_linting_core.py` (~150 lines)
- [ ] `tests/unit/test_linting_rules.py` (~200 lines)
- [ ] `tests/integration/test_linting_rules.py` (~200 lines)
- [ ] `docs/linting.md` (~300 lines)

### Modified Files

- [ ] `python/confiture/cli/main.py` (+100 lines for lint command)
- [ ] `README.md` (+1 line in features)
- [ ] `python/confiture/models/__init__.py` (export LintConfig, LintReport, etc.)
- [ ] `python/confiture/core/__init__.py` (export SchemaLinter)

---

## Testing Checklist

### Unit Tests (40+)

- [ ] Models tests (10)
  - [x] Violation creation
  - [x] LintSeverity enum
  - [x] LintConfig defaults
  - [x] LintConfig.from_yaml()
  - [x] LintReport properties
  - [x] LintReport.violations_by_severity()
  - [x] ~4 more

- [ ] SchemaLinter tests (10)
  - [x] Initialization with default config
  - [x] Initialization with custom config
  - [x] lint() returns LintReport
  - [x] Excluded tables are skipped
  - [x] Rules are executed
  - [x] Violations are collected
  - [x] ~4 more

- [ ] Rule tests (20)
  - [x] NamingConventionRule detects CamelCase (3)
  - [x] PrimaryKeyRule detects missing PK (3)
  - [x] DocumentationRule detects missing COMMENT (3)
  - [x] MultiTenantRule detects missing tenant_id (3)
  - [x] MissingIndexRule detects unindexed FK (4)
  - [x] SecurityRule detects password columns (4)

### Integration Tests (15+)

- [ ] Real schema linting (5)
  - [x] Linting on test database
  - [x] Rule execution on actual tables
  - [x] Violation accuracy
  - [x] ~2 more

- [ ] Configuration loading (5)
  - [x] YAML config loading
  - [x] Config validation
  - [x] Rule enablement/disablement
  - [x] ~2 more

- [ ] CLI command (5)
  - [x] Basic lint command
  - [x] --format json
  - [x] --format csv
  - [x] --fail-on-error
  - [x] --fail-on-warning

### Quality Checks

- [ ] Coverage >85%
- [ ] All tests passing (330+)
- [ ] No ruff errors
- [ ] No type errors
- [ ] No deprecation warnings
- [ ] Zero regressions in Phase 4.1

---

## Code Quality Checklist

### Type Hints

- [ ] All functions have type hints
- [ ] All class attributes have type hints
- [ ] All return types specified
- [ ] `mypy` passes in strict mode

### Documentation

- [ ] All public classes have docstrings
- [ ] All public methods have docstrings
- [ ] All complex logic explained
- [ ] Examples in docstrings

### Code Style

- [ ] PEP 8 compliant
- [ ] snake_case for functions/variables
- [ ] PascalCase for classes
- [ ] `ruff format` applied
- [ ] No trailing whitespace

### Error Handling

- [ ] All exceptions caught specifically
- [ ] Error messages are helpful
- [ ] Graceful degradation where applicable

---

## Git Commit Checklist

### Commit Messages

```
# Day 1
test: linting models [RED]
feat: linting models (Violation, Config, Report) [GREEN]
refactor: improve linting models code quality [REFACTOR]
test: linting models - all QA checks passing [QA]

# Day 2
test: schema linting core and rules [RED]
feat: schema linting with 6 rules [GREEN]
refactor: improve linting code organization and clarity [REFACTOR]
test: schema linting - all QA checks passing [QA]

# Day 3
feat: confiture lint CLI command [GREEN]
test: integration tests for linting [GREEN]
test: complete linting test suite [QA]

# Day 4
docs: schema linting guide and reference
docs: add linting to feature list
chore: final quality checks and polish
```

### Branch Management

```bash
# Create feature branch
git checkout -b feature/phase-4.2.2-schema-linting

# During development
git add <files>
git commit -m "message"

# Before pushing
git pull origin main  # Ensure up to date
git rebase main       # Clean history (optional)

# Push when done
git push origin feature/phase-4.2.2-schema-linting

# Create PR
# - Title: "feat: Phase 4.2.2 - Schema Linting"
# - Description: [Use PR template]
# - Reviewers: [Assign if needed]
```

---

## Troubleshooting Guide

### Issue: Tests Import Confiture Modules Incorrectly

```
ModuleNotFoundError: No module named 'confiture'
```

**Solution**:
```bash
# Ensure confiture is installed in editable mode
uv sync --all-extras

# Verify
uv run python -c "import confiture; print(confiture.__file__)"
```

### Issue: Test Database Connection Failed

```
psycopg.OperationalError: connection failed
```

**Solution**:
```bash
# Check database is running
psql postgresql://localhost/confiture_test -c "SELECT 1"

# If not exists, create it (see conftest.py for setup)
psql -U postgres -c "CREATE DATABASE confiture_test"
```

### Issue: Coverage Report Shows <85%

```
Coverage: 78% (below threshold)
```

**Solution**:
1. Check which lines are uncovered: `uv run pytest --cov-report=html`
2. Open `htmlcov/index.html` in browser
3. Add tests for uncovered branches

### Issue: Type Checking Fails

```
error: Incompatible types in assignment
```

**Solution**:
```bash
# Check specific file
uv run mypy python/confiture/models/lint.py

# See full error
uv run mypy python/confiture/models/lint.py --show-traceback
```

### Issue: Ruff Formatting Conflicts

```
error: 79 characters > 88 character limit
```

**Solution**:
```bash
# Auto-fix with ruff
uv run ruff format python/confiture/

# Check result
uv run ruff check python/confiture/
```

---

## Performance Targets

| Operation | Target | Acceptable | Fail |
|-----------|--------|-----------|------|
| Linting 50 tables | <500ms | <1000ms | >2000ms |
| Linting 500 tables | <5s | <10s | >20s |
| CLI startup | <200ms | <500ms | >1000ms |
| Rule execution (each) | <100ms | <200ms | >500ms |

**How to test**:
```bash
# Time a single lint run
time uv run confiture lint --env test

# Profile if slow
uv run pytest tests/performance/test_linting_perf.py -v -s
```

---

## Sign-Off Checklist

When Phase 4.2.2 is complete:

- [ ] All 55+ new tests passing (40 unit + 15 integration)
- [ ] All 330+ existing tests still passing (zero regressions)
- [ ] Coverage >85% on new code
- [ ] Code formatting: `ruff format` applied
- [ ] Code style: `ruff check` passing
- [ ] Type checking: `mypy` passing
- [ ] Documentation: complete and examples tested
- [ ] CLI command: working and tested
- [ ] All 6 rules: implemented and tested
- [ ] Git history: clean, descriptive commits
- [ ] Ready for code review

---

## Next Steps After Phase 4.2.2

Once Phase 4.2.2 is complete:

1. **Merge to main** (after code review)
2. **Tag release** (if releasing v0.4.0 or similar)
3. **Start Phase 4.2.3** (Interactive Wizard)
4. **Optional**: Phase 4.2.3 can run in parallel with Phase 4.2.2 reviews

---

## Quick Reference

### Commands (Copy-Paste Ready)

```bash
# Full test suite
uv run pytest tests/ -v --cov=confiture

# Just linting tests
uv run pytest tests/unit/test_linting*.py tests/integration/test_linting*.py -v

# With coverage report
uv run pytest tests/unit/test_linting*.py --cov=confiture.core.linting --cov=confiture.models.lint

# Code formatting
uv run ruff format python/confiture/
uv run ruff check python/confiture/

# Type checking
uv run mypy confiture/

# Manual test
uv run confiture lint --env test
uv run confiture lint --format json
```

### File Locations

```
python/confiture/
├── models/lint.py              # Data models
├── core/linting.py             # SchemaLinter + rules
└── cli/main.py                 # lint command (edit here)

tests/
├── unit/
│   ├── test_linting_models.py  # Model tests
│   ├── test_linting_core.py    # SchemaLinter tests
│   └── test_linting_rules.py   # Rule tests
└── integration/
    └── test_linting_rules.py   # Integration tests

docs/
└── linting.md                  # User guide
```

---

**Phase 4.2.2 is ready to build. Let's make it happen.** 🍓

*Implementation started: 2025-12-26*
*Estimated completion: 2025-12-29*
