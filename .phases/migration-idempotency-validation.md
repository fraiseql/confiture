# Migration Idempotency Validation

**Issue**: #17
**Status**: [x] Complete (CLI integration done)

## Objective

Add a validation command that checks migrations for idempotency patterns, helping developers catch non-idempotent migrations before they cause failures during disaster recovery or re-runs.

## Background

Migrations that aren't idempotent can fail when re-run. Common non-idempotent patterns include:

```sql
-- Fails if column already exists
ALTER TABLE users ADD COLUMN email TEXT;

-- Fails if function exists without OR REPLACE
CREATE FUNCTION fn_calc_total(...);

-- Fails if index already exists
CREATE INDEX idx_users_email ON users(email);
```

## Success Criteria

- [x] `confiture migrate validate --idempotent` command exists
- [x] Detects non-idempotent patterns in SQL migrations
- [x] Provides actionable suggestions for fixes
- [x] Optional auto-fix mode (`confiture migrate fix --idempotent`)
- [ ] Configurable via `confiture.yaml`
- [x] Integrates with CI/CD (exit code reflects violations)
- [x] Unit tests cover all idempotency patterns (93 tests)
- [ ] Documentation updated

## Architecture

### New Files

```
python/confiture/
├── core/
│   └── idempotency/
│       ├── __init__.py
│       ├── validator.py      # IdempotencyValidator class
│       ├── patterns.py       # Pattern definitions
│       └── fixer.py          # Auto-fix transformations
├── cli/
│   └── migrate.py            # Add validate/fix subcommands
└── models/
    └── idempotency.py        # IdempotencyViolation, IdempotencyReport
```

### Pattern Detection

| Statement | Non-Idempotent Pattern | Idempotent Pattern | Fix |
|-----------|------------------------|--------------------|----|
| CREATE TABLE | `CREATE TABLE x` | `CREATE TABLE IF NOT EXISTS x` | Add IF NOT EXISTS |
| CREATE INDEX | `CREATE INDEX` | `CREATE INDEX IF NOT EXISTS` | Add IF NOT EXISTS |
| CREATE FUNCTION | `CREATE FUNCTION` | `CREATE OR REPLACE FUNCTION` | Add OR REPLACE |
| CREATE VIEW | `CREATE VIEW` | `CREATE OR REPLACE VIEW` | Add OR REPLACE |
| CREATE TYPE | `CREATE TYPE` | DO block with check | Wrap in DO block |
| ALTER TABLE ADD COLUMN | `ADD COLUMN x` | DO block with exception handler | Wrap in DO block |
| DROP TABLE | `DROP TABLE x` | `DROP TABLE IF EXISTS x` | Add IF EXISTS |
| DROP INDEX | `DROP INDEX x` | `DROP INDEX IF EXISTS x` | Add IF EXISTS |
| DROP FUNCTION | `DROP FUNCTION` | `DROP FUNCTION IF EXISTS` | Add IF EXISTS |

### Configuration

```yaml
# confiture.yaml
migrations:
  validation:
    idempotency:
      enabled: true
      severity: warning  # error | warning | info
      require_idempotent: false  # If true, non-idempotent = error
      suggest_fixes: true
      patterns:
        create_table: true
        create_index: true
        create_function: true
        create_view: true
        create_type: true
        alter_table_add: true
        drop_statements: true
```

## TDD Cycles

### Phase 1: Core Models

#### Cycle 1.1: IdempotencyViolation Model
- **RED**: Write test for `IdempotencyViolation` dataclass
- **GREEN**: Create dataclass with fields: `pattern`, `location`, `line_number`, `suggestion`, `fix_available`
- **REFACTOR**: Add `__str__` method for nice formatting
- **CLEANUP**: Lint, commit

#### Cycle 1.2: IdempotencyReport Model
- **RED**: Write test for `IdempotencyReport` with add_violation, has_violations
- **GREEN**: Create dataclass with violations list, add helper methods
- **REFACTOR**: Add `to_dict()` for JSON serialization
- **CLEANUP**: Lint, commit

### Phase 2: Pattern Detection

#### Cycle 2.1: CREATE TABLE Detection
- **RED**: Write test: `detect_create_table_without_if_not_exists`
- **GREEN**: Regex pattern to detect `CREATE TABLE` without `IF NOT EXISTS`
- **REFACTOR**: Extract regex to `patterns.py`
- **CLEANUP**: Lint, commit

#### Cycle 2.2: CREATE INDEX Detection
- **RED**: Write test: `detect_create_index_without_if_not_exists`
- **GREEN**: Regex pattern for CREATE INDEX
- **REFACTOR**: Consolidate similar patterns
- **CLEANUP**: Lint, commit

#### Cycle 2.3: CREATE FUNCTION Detection
- **RED**: Write test: `detect_create_function_without_or_replace`
- **GREEN**: Regex pattern for CREATE FUNCTION
- **REFACTOR**: Handle CREATE OR REPLACE correctly
- **CLEANUP**: Lint, commit

#### Cycle 2.4: CREATE VIEW Detection
- **RED**: Write test: `detect_create_view_without_or_replace`
- **GREEN**: Regex pattern for CREATE VIEW
- **REFACTOR**: Share logic with function detection
- **CLEANUP**: Lint, commit

#### Cycle 2.5: CREATE TYPE Detection
- **RED**: Write test: `detect_create_type_non_idempotent`
- **GREEN**: Regex pattern for CREATE TYPE (always non-idempotent without DO block)
- **REFACTOR**: Document PostgreSQL limitation
- **CLEANUP**: Lint, commit

#### Cycle 2.6: ALTER TABLE ADD COLUMN Detection
- **RED**: Write test: `detect_alter_table_add_column_non_idempotent`
- **GREEN**: Regex pattern for ALTER TABLE ADD COLUMN
- **REFACTOR**: Handle multi-column ADD
- **CLEANUP**: Lint, commit

#### Cycle 2.7: DROP Statement Detection
- **RED**: Write test: `detect_drop_without_if_exists`
- **GREEN**: Regex patterns for DROP TABLE/INDEX/FUNCTION/VIEW
- **REFACTOR**: Consolidate DROP patterns
- **CLEANUP**: Lint, commit

### Phase 3: Validator Class

#### Cycle 3.1: Basic Validator
- **RED**: Write test: `validator_scans_sql_file_for_violations`
- **GREEN**: Create `IdempotencyValidator` class that scans SQL content
- **REFACTOR**: Accept both file path and SQL string
- **CLEANUP**: Lint, commit

#### Cycle 3.2: Line Number Tracking
- **RED**: Write test: `validator_reports_correct_line_numbers`
- **GREEN**: Track line numbers during pattern matching
- **REFACTOR**: Handle multi-line statements
- **CLEANUP**: Lint, commit

#### Cycle 3.3: Suggestion Generation
- **RED**: Write test: `validator_provides_suggestions_for_each_violation`
- **GREEN**: Map each pattern to its idempotent alternative
- **REFACTOR**: Make suggestions configurable
- **CLEANUP**: Lint, commit

### Phase 4: Auto-Fix

#### Cycle 4.1: Fix CREATE TABLE
- **RED**: Write test: `fixer_adds_if_not_exists_to_create_table`
- **GREEN**: String transformation to add IF NOT EXISTS
- **REFACTOR**: Handle edge cases (schema-qualified names)
- **CLEANUP**: Lint, commit

#### Cycle 4.2: Fix CREATE INDEX
- **RED**: Write test: `fixer_adds_if_not_exists_to_create_index`
- **GREEN**: String transformation
- **REFACTOR**: Handle UNIQUE INDEX, CONCURRENTLY
- **CLEANUP**: Lint, commit

#### Cycle 4.3: Fix CREATE FUNCTION/VIEW
- **RED**: Write test: `fixer_adds_or_replace_to_create_function`
- **GREEN**: String transformation to add OR REPLACE
- **REFACTOR**: Handle both FUNCTION and VIEW
- **CLEANUP**: Lint, commit

#### Cycle 4.4: Fix ALTER TABLE ADD COLUMN
- **RED**: Write test: `fixer_wraps_add_column_in_do_block`
- **GREEN**: Wrap in DO block with exception handler
- **REFACTOR**: Handle multiple columns
- **CLEANUP**: Lint, commit

```sql
-- Before
ALTER TABLE users ADD COLUMN email TEXT;

-- After
DO $$ BEGIN
  ALTER TABLE users ADD COLUMN email TEXT;
EXCEPTION WHEN duplicate_column THEN NULL;
END $$;
```

#### Cycle 4.5: Fix DROP Statements
- **RED**: Write test: `fixer_adds_if_exists_to_drop`
- **GREEN**: String transformation
- **REFACTOR**: Handle all DROP variants
- **CLEANUP**: Lint, commit

### Phase 5: CLI Integration

#### Cycle 5.1: Validate Command
- **RED**: Write test: `cli_migrate_validate_idempotent_returns_violations`
- **GREEN**: Add `confiture migrate validate --idempotent` command
- **REFACTOR**: Add --json output format
- **CLEANUP**: Lint, commit

#### Cycle 5.2: Fix Command
- **RED**: Write test: `cli_migrate_fix_idempotent_transforms_file`
- **GREEN**: Add `confiture migrate fix --idempotent` command
- **REFACTOR**: Add --dry-run mode
- **CLEANUP**: Lint, commit

#### Cycle 5.3: Configuration Loading
- **RED**: Write test: `validator_respects_config_file_settings`
- **GREEN**: Load settings from confiture.yaml
- **REFACTOR**: Merge CLI flags with config file
- **CLEANUP**: Lint, commit

### Phase 6: Integration & Documentation

#### Cycle 6.1: Integration Tests
- **RED**: Write integration test with real migration files
- **GREEN**: Test full workflow: validate -> fix -> validate
- **REFACTOR**: Add edge case scenarios
- **CLEANUP**: Lint, commit

#### Cycle 6.2: Documentation
- **RED**: N/A (docs)
- **GREEN**: Write user guide for idempotency validation
- **REFACTOR**: Add examples and common patterns
- **CLEANUP**: Review, commit

### Phase 7: Finalize

- [ ] Remove all development comments
- [ ] Ensure 100% test coverage for new code
- [ ] Run full test suite
- [ ] Update CHANGELOG.md
- [ ] Update CLI help text

## CLI Output Examples

```bash
$ confiture migrate validate --idempotent

Scanning migrations for idempotency issues...

✅ 001_initial_schema.up.sql
   CREATE TABLE IF NOT EXISTS (idempotent)

✅ 002_add_function.up.sql
   CREATE OR REPLACE FUNCTION (idempotent)

⚠️ 003_add_column.up.sql:15
   ALTER TABLE ADD COLUMN (not idempotent)
   Suggestion: Wrap in DO block with EXCEPTION handler
   Fix available: confiture migrate fix --idempotent 003_add_column.up.sql

❌ 004_create_index.up.sql:8
   CREATE INDEX (not idempotent)
   Suggestion: Use CREATE INDEX IF NOT EXISTS
   Fix available: confiture migrate fix --idempotent 004_create_index.up.sql

Summary: 4 migrations scanned, 2 idempotency issues found
```

## Dependencies

- None (pure Python, regex-based)

## Estimated Complexity

- **Core**: Medium (regex patterns, string transformations)
- **CLI**: Low (extend existing migrate command)
- **Tests**: Medium (many pattern variations)

## Notes

- PostgreSQL-specific patterns (other databases may differ)
- Some patterns cannot be made fully idempotent (CREATE TYPE) - document workarounds
- Consider adding --strict mode for CI/CD that fails on any non-idempotent migration
