# Phase 5: Dry-Run Mode CLI Integration

**Objective**: Integrate Feature 4 (dry-run mode) into the Confiture CLI, making it accessible to users through command-line options.

**Duration**: 2-3 days
**Complexity**: Medium
**Dependencies**: Feature 4 (Days 1-5) ✅ COMPLETE

---

## 📋 Context

Feature 4 (Migration Dry-Run Mode) is complete with:
- ✅ SAVEPOINT-based transaction system
- ✅ Statement classification
- ✅ Impact analysis
- ✅ Concurrency analysis
- ✅ Cost estimation
- ✅ Report generation
- ✅ Comprehensive documentation

**Current State**: Feature 4 is accessible via Python API only. Users need CLI access.

**Goal**: Make dry-run analysis available through CLI with multiple modes and output formats.

---

## 🎯 Acceptance Criteria

### Functional Requirements
1. **Command**: `confiture migrate up --dry-run`
   - Analyzes pending migrations without executing them
   - Shows impact, risk, and cost estimates
   - Works with existing --target, --config options

2. **Command**: `confiture migrate up --dry-run --execute`
   - Executes migrations in SAVEPOINT (guaranteed rollback)
   - Shows actual execution metrics vs estimates
   - Helps validate estimates accuracy

3. **Command**: `confiture migrate down --dry-run`
   - Analyzes rollback impact
   - Shows what will be rolled back

4. **Output Options**
   - `--verbose`: Detailed statement analysis
   - `--format text` (default): Human-readable report
   - `--format json`: Programmatic output
   - `--output file.txt`: Save report to file

5. **Integration**
   - Works with all existing migrate commands
   - Respects configuration files
   - Compatible with existing flags (--target, --config, etc.)

### Quality Requirements
- ✅ All existing tests still pass (no regressions)
- ✅ New CLI tests for dry-run commands (8-12 tests)
- ✅ Code quality: A+ (ruff checks pass)
- ✅ Documentation updated
- ✅ Examples provided

### Supported Workflows
1. **Quick Analysis**: `confiture migrate up --dry-run`
2. **Detailed Analysis**: `confiture migrate up --dry-run --verbose`
3. **Realistic Testing**: `confiture migrate up --dry-run --execute`
4. **Machine Processing**: `confiture migrate up --dry-run --format json --output report.json`
5. **Rollback Analysis**: `confiture migrate down --dry-run --steps 3`

---

## 🏗️ Architecture

### Current CLI Structure (from main.py)
```
confiture/
├── init              # Initialize project
├── build             # Build schema
├── lint              # Lint schema
└── migrate/          # Migration commands
    ├── up            # Apply migrations
    ├── down          # Rollback migrations
    ├── status        # Show status
    ├── generate      # Generate migration
    └── diff          # Compare schemas
```

### Proposed Integration
```
confiture/
└── migrate/
    ├── up            # Apply migrations
    │   ├── --dry-run           (NEW)
    │   ├── --dry-run --execute (NEW)
    │   ├── --verbose           (EXISTING)
    │   ├── --format text|json  (NEW)
    │   └── --output file       (NEW)
    │
    └── down          # Rollback migrations
        ├── --dry-run           (NEW)
        ├── --format text|json  (NEW)
        └── --output file       (NEW)
```

### Implementation Plan

#### Day 1: CLI Command Extensions

**Changes to `python/confiture/cli/main.py`:**

1. **Add `--dry-run` flag to `migrate_up`**
   ```python
   @migrate_app.command("up")
   def migrate_up(
       ...existing options...,
       dry_run: bool = typer.Option(
           False,
           "--dry-run",
           help="Analyze migrations without executing (metadata only)",
       ),
       dry_run_execute: bool = typer.Option(
           False,
           "--dry-run-execute",
           help="Execute migrations in SAVEPOINT (guaranteed rollback)",
       ),
       verbose: bool = typer.Option(
           False,
           "--verbose",
           "-v",
           help="Show detailed analysis in dry-run report",
       ),
       format_output: str = typer.Option(
           "text",
           "--format",
           "-f",
           help="Report format: text or json",
       ),
       output_file: Path | None = typer.Option(
           None,
           "--output",
           "-o",
           help="Save report to file",
       ),
   ) -> None:
   ```

2. **Add `--dry-run` flag to `migrate_down`**
   ```python
   @migrate_app.command("down")
   def migrate_down(
       ...existing options...,
       dry_run: bool = typer.Option(
           False,
           "--dry-run",
           help="Analyze rollback without executing",
       ),
       format_output: str = typer.Option(
           "text",
           "--format",
           "-f",
           help="Report format: text or json",
       ),
       output_file: Path | None = typer.Option(
           None,
           "--output",
           "-o",
           help="Save report to file",
       ),
   ) -> None:
   ```

#### Day 2: Implementation

**Dry-run logic for `migrate_up`:**

```python
# In migrate_up() function:

if dry_run or dry_run_execute:
    from confiture.core.migration.dry_run.dry_run_mode import DryRunMode
    from confiture.core.migration.dry_run.report import DryRunReportGenerator

    # Get statements to analyze
    statements = get_statements_from_migrations(migrations_to_apply)

    # Create dry-run mode
    dry_run_mode = DryRunMode(
        analyze_impact=True,
        analyze_concurrency=True,
        estimate_costs=True,
    )

    # Run analysis
    if dry_run_execute:
        report = await dry_run_mode.execute_and_analyze(
            statements=statements,
            connection=conn,
            migration_id=f"dry_run_{timestamp}",
        )
    else:
        report = await dry_run_mode.analyze(
            statements=statements,
            connection=conn,
            migration_id=f"dry_run_{timestamp}",
        )

    # Display results
    generator = DryRunReportGenerator(
        use_colors=True,
        verbose=verbose,
    )

    if format_output == "json":
        json_report = generator.generate_json_report(report)
        if output_file:
            save_json_report(json_report, output_file)
        else:
            print_json(json_report)
    else:
        text_report = generator.generate_text_report(report)
        if output_file:
            save_text_report(text_report, output_file)
        else:
            console.print(text_report)

    # Stop here if dry-run only
    if dry_run and not dry_run_execute:
        return

    # For dry_run_execute: ask for confirmation
    if dry_run_execute:
        if not typer.confirm("Execute migrations for real?"):
            console.print("Cancelled")
            return
        # Continue with actual execution
```

#### Day 3: Testing & Documentation

**Tests** (`tests/unit/test_cli_dry_run.py`):
1. Test `migrate up --dry-run` with multiple migrations
2. Test `migrate up --dry-run --verbose` shows details
3. Test `migrate up --dry-run --format json` outputs valid JSON
4. Test `migrate up --dry-run --output file` saves to file
5. Test `migrate up --dry-run --execute` works with confirmation
6. Test `migrate down --dry-run` with rollback scenarios
7. Test error handling (missing statements, connection issues)
8. Test output file creation with --output flag

**Documentation** (`docs/guides/cli-dry-run.md`):
1. Quick start examples
2. Each command option explained
3. Real-world usage scenarios
4. JSON report structure
5. Integration with CI/CD

---

## 📁 Files to Create/Modify

### Create
1. `python/confiture/cli/dry_run.py` (NEW - 200+ lines)
   - Helper functions for dry-run logic
   - Statement extraction from migrations
   - Report formatting and saving

2. `tests/unit/test_cli_dry_run.py` (NEW - 150+ lines)
   - CLI integration tests
   - Dry-run mode tests
   - Output format validation

3. `docs/guides/cli-dry-run.md` (NEW - 500+ lines)
   - User guide for dry-run CLI
   - Examples and use cases
   - Troubleshooting guide

### Modify
1. `python/confiture/cli/main.py` (MODIFY - ~80 lines added)
   - Add --dry-run options to migrate_up
   - Add --dry-run options to migrate_down
   - Add format/output options
   - Add dry-run execution logic

2. `python/confiture/cli/__init__.py` (MODIFY)
   - Export new dry-run helpers

3. `README.md` (MODIFY)
   - Add dry-run section to usage examples

---

## 🧪 Testing Strategy

### Unit Tests (8-12 tests in test_cli_dry_run.py)

**Test categories:**
1. **Dry-run analysis** (2 tests)
   - Verify dry-run mode doesn't execute
   - Verify statements are analyzed correctly

2. **Report formats** (3 tests)
   - Text report includes all sections
   - JSON report has valid structure
   - Output file is created correctly

3. **CLI integration** (3 tests)
   - Flags parsed correctly
   - Options combined properly (--dry-run --verbose)
   - Error handling for invalid options

4. **Dry-run execute** (2 tests)
   - SAVEPOINT execution works
   - Rollback happens automatically
   - Results show actual vs estimated metrics

5. **Down rollback** (2 tests)
   - Rollback analysis works
   - Correct migrations identified

### Integration Tests
- Test with real migration files
- Test with actual database connection
- Test confirmation prompt

### Regression Tests
- All existing tests still pass
- migrate up/down commands unchanged
- No breaking changes to API

---

## 🔧 Implementation Details

### Helper Functions (cli/dry_run.py)

```python
def extract_statements_from_migrations(
    migration_files: list[Path],
    migrations_dir: Path,
) -> list[str]:
    """Extract SQL statements from migration files."""
    # Load migration modules and extract statements
    statements = []
    for mf in migration_files:
        module = load_migration_module(mf)
        migration_class = get_migration_class(module)
        migration = migration_class(connection=None)

        # Extract statements from migration object
        # (Need to inspect migration.up() method)
        statements.extend(migration.get_statements())

    return statements


def save_text_report(report: str, filepath: Path) -> None:
    """Save text report to file."""
    filepath.parent.mkdir(parents=True, exist_ok=True)
    filepath.write_text(report)


def save_json_report(report: dict, filepath: Path) -> None:
    """Save JSON report to file."""
    import json
    filepath.parent.mkdir(parents=True, exist_ok=True)
    filepath.write_text(json.dumps(report, indent=2))
```

### Error Handling

All errors should be caught and displayed clearly:
- Connection failures → Show with troubleshooting hints
- Invalid migrations → Show which migrations have issues
- Dry-run failures → Graceful degradation (try to show partial results)
- File write errors → Clear message with path

### User Confirmation

For `--dry-run-execute`, ask before proceeding:
```
Dry-run analysis complete. The above migrations executed successfully in SAVEPOINT (guaranteed rollback).

Metrics:
  - Total time: 500ms
  - Unsafe statements: 0
  - Estimated actual time: 1200ms

Proceed with real execution? [y/N]
```

---

## 📊 Success Metrics

### Code Quality
- ✅ All tests passing (801 existing + 8-12 new)
- ✅ Linting: 0 issues (ruff checks)
- ✅ Formatting: Proper indentation and style
- ✅ Type hints: Complete coverage

### User Experience
- ✅ Clear help text (`confiture migrate up --help`)
- ✅ Logical flag names
- ✅ Consistent with existing commands
- ✅ Readable output (with colors)

### Performance
- ✅ Analysis < 100ms per statement (metadata-only)
- ✅ SAVEPOINT execution < 1s per statement
- ✅ Report generation < 10ms

---

## 🔗 Dependencies & Integration

### Required
- Feature 4 components:
  - DryRunMode (orchestrator)
  - DryRunReportGenerator (formatting)
  - CostEstimator, ImpactAnalyzer, ConcurrencyAnalyzer (analysis)
  - DryRunTransaction (for execute_and_analyze)

### Existing
- psycopg3 (database connection)
- Typer (CLI framework)
- Rich (colored output)
- YAML (configuration)

### Future
- Feature 3 wizard (will use dry-run in Step 5)
- CI/CD integration (dry-run in pipelines)
- Advanced features (interactive UI, PDF reports)

---

## 🚀 Implementation Steps (Day-by-Day)

### Day 1: CLI Commands (4 hours)
- [ ] Add --dry-run flags to migrate_up
- [ ] Add --dry-run flags to migrate_down
- [ ] Add format/output options
- [ ] Implement basic dry-run logic
- [ ] Test command parsing

### Day 2: Full Implementation (4 hours)
- [ ] Complete dry-run analysis logic
- [ ] Implement report formatting (text & JSON)
- [ ] Add file output support
- [ ] Error handling and edge cases
- [ ] Manual testing

### Day 3: Testing & Documentation (3 hours)
- [ ] Write unit tests (8-12 tests)
- [ ] Integration testing
- [ ] Update CLI help text
- [ ] Create user guide
- [ ] Update README

---

## 🎬 Example Usage (After Implementation)

```bash
# Quick analysis - show what will happen
confiture migrate up --dry-run

# Detailed analysis with impact details
confiture migrate up --dry-run --verbose

# Test in SAVEPOINT (realistic test)
confiture migrate up --dry-run --execute

# Save report for review
confiture migrate up --dry-run --format json --output migration_report.json

# Analyze rollback
confiture migrate down --dry-run --steps 2

# Apply with extra verbosity
confiture migrate up --verbose
```

### Example Output

**Text Report:**
```
================================================================================
DRY-RUN MIGRATION ANALYSIS REPORT
================================================================================

SUMMARY
────────────────────────────────────────────────────────────────────────────
Statements analyzed: 2
Analysis duration: 128ms

Safety Analysis:
  Unsafe statements: 0 ✓ None

Cost Estimates:
  Total time: 1500ms
  Total disk: 5.2MB

RECOMMENDATIONS
────────────────────────────────────────────────────────────────────────────
✓ All checks passed!
  This migration appears safe to execute.

================================================================================
```

**JSON Report:**
```json
{
  "migration_id": "dry_run_20251227T163000",
  "summary": {
    "unsafe_count": 0,
    "total_estimated_time_ms": 1500,
    "total_estimated_disk_mb": 5.2,
    "has_unsafe_statements": false
  },
  "warnings": [],
  "analyses": [...]
}
```

---

## 📝 Deliverables Summary

| Item | Status | Lines | Tests |
|------|--------|-------|-------|
| CLI modifications | TODO | ~80 | - |
| Dry-run helpers | TODO | ~200 | - |
| CLI tests | TODO | ~150 | 8-12 |
| Documentation | TODO | ~500 | - |
| **TOTAL** | **TODO** | **~930** | **8-12** |

---

## ✅ Completion Checklist

- [ ] CLI commands implemented
- [ ] Dry-run logic working
- [ ] Report formatting (text & JSON)
- [ ] File output support
- [ ] Error handling
- [ ] All tests passing
- [ ] Linting/formatting clean
- [ ] Documentation complete
- [ ] README updated
- [ ] Examples provided
- [ ] Ready for Feature 3 wizard integration

---

## 🎯 Phase 5 Milestones

**Milestone 1**: CLI flags added & parsing works
- Estimate: 2 hours
- Acceptance: `--help` shows all new options

**Milestone 2**: Dry-run analysis integrated
- Estimate: 3 hours
- Acceptance: Reports display correctly

**Milestone 3**: All tests passing
- Estimate: 2 hours
- Acceptance: 801+ tests, 0 failures

**Milestone 4**: Documentation complete
- Estimate: 1 hour
- Acceptance: User can run examples from docs

---

## 📅 Timeline

- **Day 1**: Milestone 1 + Milestone 2 (6 hours)
- **Day 2**: Milestone 2 completion + Milestone 3 (4 hours)
- **Day 3**: Milestone 4 + final verification (3 hours)
- **Total**: ~13 hours of focused work (2-3 calendar days)

---

**Version**: 1.0
**Date**: December 27, 2025
**Status**: 🚧 Planning Phase
**Next**: Approval & Implementation

