# Phase 5 Day 3: Tests & Documentation - Implementation Plan

**Date**: December 27, 2025
**Scope**: Write comprehensive tests and documentation for dry-run CLI features
**Objective**: Achieve >85% test coverage for dry-run functionality and create user-friendly documentation

---

## 🎯 Day 3 Objectives

1. **Unit Tests** (8-12 tests)
   - Test dry-run flag combinations
   - Test report formatting (text & JSON)
   - Test file output
   - Test error handling

2. **Integration Tests** (4-6 tests)
   - Test with actual migrations
   - Test database interaction
   - Test rollback scenarios

3. **Documentation**
   - User guide for dry-run commands
   - Examples with output samples
   - Troubleshooting guide
   - Integration patterns

---

## 📋 Test Plan

### Test File: `tests/unit/test_cli_dry_run.py`

**Goal**: ~50 lines per test × 8-12 tests = 400-600 lines total

#### Category 1: migrate_up Dry-Run Tests (4 tests)

**Test 1: test_migrate_up_dry_run_analyzes_without_execution**
- Setup: Mock migrator with 2 pending migrations
- Action: Call `migrate_up --dry-run`
- Assert:
  - Report displays with 2 migrations
  - Migrator.apply NOT called
  - Connection closed
  - Output contains migration info

**Test 2: test_migrate_up_dry_run_json_format**
- Setup: Mock migrator with migrations
- Action: Call `migrate_up --dry-run --format json`
- Assert:
  - Output is valid JSON
  - Contains required fields: migration_id, migrations, summary
  - Each migration has: version, name, estimates
  - summary has: unsafe_count, estimated_time_ms, etc.

**Test 3: test_migrate_up_dry_run_saves_to_file**
- Setup: Mock migrator, temp file path
- Action: Call `migrate_up --dry-run --output report.txt`
- Assert:
  - File created at specified path
  - File contains migration report
  - Console shows file saved message

**Test 4: test_migrate_up_dry_run_execute_with_confirmation**
- Setup: Mock migrator, user confirms
- Action: Call `migrate_up --dry-run-execute`, user enters 'y'
- Assert:
  - Report displayed first
  - Confirmation prompt shown
  - Migrator.apply called after confirmation
  - Migrations executed

#### Category 2: migrate_down Dry-Run Tests (3 tests)

**Test 5: test_migrate_down_dry_run_analyzes_without_rollback**
- Setup: Mock migrator with 2 applied migrations
- Action: Call `migrate_down --dry-run --steps 2`
- Assert:
  - Report shows 2 migrations to rollback
  - Migrator.rollback NOT called
  - Output contains version and names

**Test 6: test_migrate_down_dry_run_json_output**
- Setup: Mock migrator with applied migrations
- Action: Call `migrate_down --dry-run --format json`
- Assert:
  - Valid JSON output
  - Contains: migration_id, migrations (for rollback), summary

**Test 7: test_migrate_down_dry_run_saves_to_file**
- Setup: Mock migrator, temp file path
- Action: Call `migrate_down --dry-run --output rollback.txt`
- Assert:
  - File created with rollback report
  - Contains migration info

#### Category 3: Error Handling Tests (2 tests)

**Test 8: test_dry_run_with_invalid_format**
- Setup: Dry-run command with --format invalid_format
- Action: Call migrate_up --dry-run --format csv
- Assert:
  - Command fails with exit code 1
  - Error message: "Invalid format 'csv'. Use 'text' or 'json'"

**Test 9: test_dry_run_execute_user_cancels**
- Setup: Mock migrator, user cancels
- Action: Call `migrate_up --dry-run-execute`, user enters 'n'
- Assert:
  - Report displayed
  - Confirmation prompt shown
  - Migrator.apply NOT called
  - "Cancelled" message displayed

#### Category 4: Validation Tests (2 tests)

**Test 10: test_dry_run_and_dry_run_execute_mutually_exclusive**
- Setup: Both flags specified
- Action: Call `migrate_up --dry-run --dry-run-execute`
- Assert:
  - Command fails with exit code 1
  - Error message about mutually exclusive flags

**Test 11: test_dry_run_with_force_not_allowed**
- Setup: Both --dry-run and --force
- Action: Call `migrate_up --dry-run --force`
- Assert:
  - Command fails with exit code 1
  - Error message about incompatible flags

---

## 📚 Documentation Plan

### File 1: `docs/guides/cli-dry-run.md` (~500 lines)

**Sections**:

1. **Overview** (50 lines)
   - What is dry-run?
   - When to use each mode
   - Quick start example

2. **Analyze Without Execution** (150 lines)
   - `confiture migrate up --dry-run`
   - Example output (text + JSON)
   - What information is shown
   - Interpreting estimates
   - Saving to file

3. **Test in SAVEPOINT** (150 lines)
   - `confiture migrate up --dry-run-execute`
   - How SAVEPOINT works
   - Guaranteed rollback
   - User confirmation flow
   - Example with confirmation

4. **Rollback Analysis** (100 lines)
   - `confiture migrate down --dry-run`
   - --steps option
   - What gets rolled back
   - Examples

5. **Output Formats** (50 lines)
   - Text format (default)
   - JSON format (structured)
   - When to use each

6. **Troubleshooting** (50 lines)
   - Common issues
   - Error messages
   - Solutions

---

### File 2: Update `README.md`

**Add new section**: "Dry-Run Analysis"
- Brief explanation of feature
- Link to full guide (docs/guides/cli-dry-run.md)
- Quick examples:
  ```bash
  confiture migrate up --dry-run
  confiture migrate up --dry-run --format json --output report.json
  confiture migrate up --dry-run-execute
  confiture migrate down --dry-run --steps 2
  ```

---

## 🏗️ Implementation Steps

### Step 1: Create Test File (1 hour)

```python
# tests/unit/test_cli_dry_run.py

import pytest
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
from typer.testing import CliRunner
import json

from confiture.cli.main import app

class TestMigrateUpDryRun:
    """Tests for migrate up --dry-run functionality"""

    def test_migrate_up_dry_run_analyzes_without_execution(self):
        """Test that --dry-run analyzes but doesn't execute"""
        runner = CliRunner()

        with patch("confiture.core.connection.create_connection") as mock_conn_factory:
            with patch("confiture.core.migrator.Migrator") as mock_migrator_class:
                # Setup mocks
                mock_conn = MagicMock()
                mock_conn_factory.return_value = mock_conn

                mock_migrator = MagicMock()
                mock_migrator_class.return_value = mock_migrator
                mock_migrator.get_pending_migrations.return_value = [
                    Path("db/migrations/001_init.py"),
                    Path("db/migrations/002_add_users.py"),
                ]

                # Execute
                result = runner.invoke(app, ["migrate", "up", "--dry-run"])

                # Assert
                assert result.exit_code == 0
                assert "Migration Analysis Summary" in result.stdout
                assert "001" in result.stdout
                assert "002" in result.stdout
                assert mock_migrator.apply.call_count == 0

    # ... additional tests follow same pattern
```

### Step 2: Write Documentation (1.5 hours)

Create comprehensive guide with:
- Real command examples
- Actual output samples
- Clear explanations
- Troubleshooting section

### Step 3: Run Tests (30 minutes)

```bash
# Run new tests
pytest tests/unit/test_cli_dry_run.py -v

# Check coverage
pytest --cov=confiture --cov-report=html

# Verify no regressions
pytest tests/unit/ -v
```

### Step 4: Final Verification (30 minutes)

- ✅ All tests passing (18 + 10-12 new = 28-30 total)
- ✅ No regressions
- ✅ Coverage > 85%
- ✅ Documentation complete
- ✅ Examples working

---

## 📊 Success Criteria

### Tests
- [ ] 8-12 new tests created
- [ ] All tests passing
- [ ] Test coverage > 85%
- [ ] No regressions (existing tests still pass)

### Documentation
- [ ] User guide created (docs/guides/cli-dry-run.md)
- [ ] README updated
- [ ] Examples with output
- [ ] Troubleshooting guide

### Code Quality
- [ ] 0 linting issues
- [ ] All tests green
- [ ] 100% of new code tested

---

## 📝 Test Coverage by Feature

| Feature | Tests | Coverage |
|---------|-------|----------|
| migrate up --dry-run | 3 | ✅ |
| migrate up --dry-run-execute | 1 | ✅ |
| migrate down --dry-run | 3 | ✅ |
| JSON format | 2 | ✅ |
| File output | 2 | ✅ |
| Error handling | 2 | ✅ |
| Validation | 2 | ✅ |
| **TOTAL** | **15** | **✅** |

---

## 🎬 Example Test Output

```bash
$ pytest tests/unit/test_cli_dry_run.py -v

tests/unit/test_cli_dry_run.py::TestMigrateUpDryRun::test_migrate_up_dry_run_analyzes_without_execution PASSED [  7%]
tests/unit/test_cli_dry_run.py::TestMigrateUpDryRun::test_migrate_up_dry_run_json_format PASSED [ 13%]
tests/unit/test_cli_dry_run.py::TestMigrateUpDryRun::test_migrate_up_dry_run_saves_to_file PASSED [ 20%]
tests/unit/test_cli_dry_run.py::TestMigrateUpDryRun::test_migrate_up_dry_run_execute_with_confirmation PASSED [ 27%]
tests/unit/test_cli_dry_run.py::TestMigrateDowDryRun::test_migrate_down_dry_run_analyzes_without_rollback PASSED [ 33%]
...
tests/unit/test_cli_dry_run.py::TestValidation::test_dry_run_with_force_not_allowed PASSED [100%]

============================== 15 passed in 2.34s ==============================
```

---

## 🚀 Next Steps After Day 3

Once tests and documentation are complete:

1. **Phase 5 Complete** ✅
   - CLI fully integrated
   - Tests comprehensive
   - Documentation complete

2. **Potential Enhancements**:
   - Full SQL statement extraction
   - Real resource impact analysis
   - Custom estimate functions
   - Report comparison tools
   - CI/CD integration examples

3. **Phase 6** (if planned):
   - Advanced features
   - User preferences
   - Integration with other tools

---

## 📋 Day 3 Checklist

- [ ] Create test file (test_cli_dry_run.py)
- [ ] Write 8-12 unit tests
- [ ] All tests passing
- [ ] No regressions
- [ ] Code coverage > 85%
- [ ] Create user guide (cli-dry-run.md)
- [ ] Update README.md
- [ ] Verify examples work
- [ ] Final linting check
- [ ] Day 3 summary document

---

**Version**: 1.0
**Date**: December 27, 2025
**Status**: 🟡 Ready to Start
**Estimated Time**: 3-4 hours

