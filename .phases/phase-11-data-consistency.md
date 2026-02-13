# Phase 11: Data Consistency Validation

**Status**: 🚀 Starting
**Version**: 0.4.2+
**Last Updated**: February 13, 2026

---

## Objective

Detect data integrity problems in seed files before deployment by validating that seed data matches the database schema and business rules. This catches data problems that PostgreSQL's parser doesn't detect until execution time.

---

## Success Criteria

- ✅ Foreign key depth validation (all FK references exist in seed data)
- ✅ Unique constraint validation (no duplicate values in UNIQUE columns)
- ✅ NOT NULL constraint validation (required columns have values)
- ✅ Completeness validation (required tables are seeded)
- ✅ Cross-environment comparison reports
- ✅ 70+ comprehensive tests (all passing)
- ✅ CLI integration: `confiture seed validate --consistency-check`
- ✅ Documentation with real examples
- ✅ Zero regressions in existing 3,804+ tests

---

## Architecture Overview

### Data Flow
```
SQL Seed File
    ↓
Parse INSERT/SELECT statements
    ↓
Extract: Tables, Columns, Values, Foreign Keys
    ↓
Validate Against Schema:
  - Foreign Key Depth Checker
  - Unique Constraint Checker
  - NOT NULL Constraint Checker
  - Completeness Checker
    ↓
Cross-Environment Comparator
    ↓
Report: Violations + Warnings
```

### New Components

1. **DataExtractor** - Parse seed data, extract structured information
   - Table references
   - Column names and values
   - Foreign key references
   - Constraint metadata

2. **ForeignKeyDepthValidator** - Verify all FK references exist
   - Cross-table reference validation
   - Report missing parents
   - Identify orphaned rows

3. **UniqueConstraintValidator** - Detect duplicate values
   - Check UNIQUE columns for duplicates
   - Check composite unique constraints
   - Within-file validation only

4. **NotNullValidator** - Verify required columns have values
   - Identify NULL values in NOT NULL columns
   - Report by table and column

5. **CompletenessValidator** - Check all required tables are seeded
   - Compare seed files to schema
   - Warn on missing tables
   - Report empty tables

6. **EnvironmentComparator** - Compare seed data across environments
   - Structure consistency
   - Data coverage comparison
   - Divergence reports

7. **ConsistencyReport** - Structured output
   - Violations (errors)
   - Warnings
   - Statistics (row counts, coverage)
   - Environment comparison data

---

## TDD Cycles

### Cycle 1: DataExtractor - Parse Seed Data

**RED Phase**: Write failing tests for data extraction
```python
def test_extracts_table_name_from_insert():
    """Test extracting table name from INSERT statement."""
    extractor = DataExtractor()
    sql = "INSERT INTO users (id, name) VALUES ('1', 'Alice')"
    tables = extractor.extract_tables(sql)
    assert tables == ["users"]

def test_extracts_column_names_from_insert():
    """Test extracting column names."""
    extractor = DataExtractor()
    sql = "INSERT INTO users (id, name, email) VALUES ('1', 'Alice', 'alice@example.com')"
    columns = extractor.extract_columns(sql, "users")
    assert columns == ["id", "name", "email"]

def test_extracts_values_from_multirow_insert():
    """Test extracting all values from multi-row INSERT."""
    extractor = DataExtractor()
    sql = """INSERT INTO users (id, name) VALUES
      ('1', 'Alice'),
      ('2', 'Bob')"""
    rows = extractor.extract_rows(sql, "users")
    assert len(rows) == 2
    assert rows[0]["id"] == "'1'"
    assert rows[0]["name"] == "'Alice'"

def test_extracts_foreign_key_references():
    """Test identifying foreign key references."""
    extractor = DataExtractor()
    sql = "INSERT INTO orders (id, customer_id) VALUES ('order-1', 'cust-1')"
    refs = extractor.extract_foreign_keys(sql, "orders")
    # Requires schema context to identify FK relationships
    assert refs == [("orders", "customer_id", "customers", "id")]

def test_handles_union_queries():
    """Test extracting data from UNION queries."""
    extractor = DataExtractor()
    sql = """INSERT INTO data (id, name)
    SELECT '1'::uuid, 'Alice'
    UNION ALL SELECT '2'::uuid, 'Bob'"""
    rows = extractor.extract_rows(sql, "data")
    assert len(rows) == 2

def test_handles_select_from_with_cte():
    """Test extracting data from CTE and subqueries."""
    extractor = DataExtractor()
    sql = """WITH cte AS (SELECT '1'::uuid as id, 'Alice' as name)
    INSERT INTO users (id, name) SELECT * FROM cte"""
    rows = extractor.extract_rows(sql, "users")
    assert len(rows) == 1

def test_ignores_non_data_statements():
    """Test that DDL and other statements are ignored."""
    extractor = DataExtractor()
    sqls = [
        "CREATE TABLE users (id UUID)",
        "ALTER TABLE users ADD COLUMN email TEXT",
        "DROP TABLE old_users"
    ]
    for sql in sqls:
        tables = extractor.extract_tables(sql)
        assert tables == []  # Should ignore DDL
```

**GREEN Phase**: Minimal implementation
```python
class DataExtractor:
    """Extract structured data from seed SQL files."""

    def extract_tables(self, sql: str) -> list[str]:
        """Extract table names from INSERT statements."""
        # Simple regex: INSERT INTO {table_name}
        match = re.search(r'INSERT\s+INTO\s+(\w+)', sql, re.IGNORECASE)
        return [match.group(1)] if match else []

    def extract_columns(self, sql: str, table: str) -> list[str]:
        """Extract column names from INSERT statement."""
        # Parse: INSERT INTO table (col1, col2, ...) VALUES ...
        # Return in order
        pass

    def extract_rows(self, sql: str, table: str) -> list[dict]:
        """Extract all rows and their values."""
        # Parse VALUES, UNION, SELECT ...
        # Return as list of dicts: {col: value, ...}
        pass

    def extract_foreign_keys(self, sql: str, table: str) -> list[tuple]:
        """Extract foreign key references (requires schema context)."""
        # Return: [(table, fk_col, ref_table, ref_col), ...]
        pass
```

**REFACTOR Phase**: Improve design
- Extract regex patterns to separate module
- Separate concerns: parsing, validation, reporting
- Add error handling for malformed SQL
- Support both simple and complex queries

**CLEANUP Phase**:
- Run ruff: `uv run ruff check --fix`
- Format: `uv run ruff format`
- Type check: `uv run ty check`
- Commit with message: "feat(consistency): add DataExtractor for seed parsing"

**Tests**: 7 tests in `tests/unit/seed_validation/test_data_extractor.py`

---

### Cycle 2: ForeignKeyDepthValidator - Verify FK References

**RED Phase**: Write failing tests
```python
def test_validates_existing_foreign_key():
    """Test validation passes when FK exists."""
    validator = ForeignKeyDepthValidator()

    # Seed data defines both orders and customers
    orders = [{"id": "order-1", "customer_id": "cust-1"}]
    customers = [{"id": "cust-1", "name": "Alice"}]

    seed_data = {"orders": orders, "customers": customers}
    schema_context = {
        "orders": {"columns": {"customer_id": {"foreign_key": ("customers", "id")}}}
    }

    violations = validator.validate(seed_data, schema_context)
    assert len(violations) == 0

def test_detects_missing_foreign_key():
    """Test detection of non-existent FK reference."""
    validator = ForeignKeyDepthValidator()

    orders = [{"id": "order-1", "customer_id": "cust-999"}]
    customers = [{"id": "cust-1", "name": "Alice"}]

    seed_data = {"orders": orders, "customers": customers}
    schema_context = {
        "orders": {"columns": {"customer_id": {"foreign_key": ("customers", "id")}}}
    }

    violations = validator.validate(seed_data, schema_context)
    assert len(violations) == 1
    assert violations[0].type == "MISSING_FOREIGN_KEY"
    assert "order-1" in violations[0].message
    assert "cust-999" in violations[0].message

def test_handles_multiple_foreign_keys():
    """Test validation with multiple FK columns."""
    # Table orders with both customer_id and address_id foreign keys
    pass

def test_handles_composite_foreign_keys():
    """Test validation of composite (multi-column) FKs."""
    pass

def test_ignores_null_foreign_keys():
    """Test that NULL values in optional FK columns are allowed."""
    validator = ForeignKeyDepthValidator()
    orders = [{"id": "order-1", "customer_id": None}]  # NULL is ok
    violations = validator.validate({"orders": orders}, {})
    # Should not report violation for NULL
    pass

def test_reports_fk_chain_violations():
    """Test detecting violations in FK chains (A→B→C)."""
    # orders.customer_id → customers.id
    # customers.region_id → regions.id
    # If regions.id missing, should report both directly and transitively
    pass
```

**GREEN Phase**: Minimal implementation
```python
class ForeignKeyDepthValidator:
    """Validate foreign key references in seed data."""

    def __init__(self) -> None:
        """Initialize validator."""
        self.violations: list[Violation] = []

    def validate(
        self,
        seed_data: dict[str, list[dict]],
        schema_context: dict
    ) -> list[Violation]:
        """Validate all foreign keys in seed data."""
        violations = []

        for table, rows in seed_data.items():
            for row in rows:
                for col, value in row.items():
                    # Check if column is FK
                    if schema_context.get(table, {}).get("columns", {}).get(col, {}).get("foreign_key"):
                        # Verify FK reference exists
                        ref_table, ref_col = ...
                        if value and value not in seed_data.get(ref_table, []):
                            violations.append(...)

        return violations
```

**REFACTOR Phase**:
- Extract FK lookup logic
- Add caching for reference lookups
- Support constraint depth checking
- Add detailed error context

**CLEANUP Phase**:
- Type hints
- Docstrings
- Ruff clean
- Commit: "feat(consistency): add ForeignKeyDepthValidator"

**Tests**: 8 tests in `tests/unit/seed_validation/test_foreign_key_validator.py`

---

### Cycle 3: UniqueConstraintValidator - Detect Duplicates

**RED Phase**: Write failing tests
```python
def test_detects_duplicate_in_unique_column():
    """Test detection of duplicate values in UNIQUE column."""
    validator = UniqueConstraintValidator()

    users = [
        {"id": "1", "email": "alice@example.com"},
        {"id": "2", "email": "alice@example.com"}  # Duplicate email
    ]

    schema_context = {
        "users": {"unique_columns": ["email"]}
    }

    violations = validator.validate({"users": users}, schema_context)
    assert len(violations) == 1
    assert "duplicate" in violations[0].message.lower()
    assert "email" in violations[0].message

def test_detects_duplicate_in_primary_key():
    """Test detection of duplicate primary keys."""
    validator = UniqueConstraintValidator()

    users = [
        {"id": "1", "name": "Alice"},
        {"id": "1", "name": "Bob"}  # Duplicate id (primary key)
    ]

    violations = validator.validate({"users": users}, {})
    assert len(violations) == 1

def test_allows_null_in_unique_column():
    """Test that NULL values are allowed in UNIQUE columns."""
    validator = UniqueConstraintValidator()

    users = [
        {"id": "1", "nickname": None},
        {"id": "2", "nickname": None}  # Multiple NULLs allowed
    ]

    schema_context = {"users": {"unique_columns": ["nickname"]}}

    violations = validator.validate({"users": users}, schema_context)
    assert len(violations) == 0  # NULL doesn't violate UNIQUE

def test_detects_composite_unique_constraint():
    """Test detection of composite (multi-column) UNIQUE constraints."""
    # (category, sku) must be unique
    pass

def test_reports_exact_duplicate_rows():
    """Test detection when entire row is duplicated."""
    pass
```

**GREEN Phase**: Minimal implementation
```python
class UniqueConstraintValidator:
    """Validate unique constraints in seed data."""

    def validate(
        self,
        seed_data: dict[str, list[dict]],
        schema_context: dict
    ) -> list[Violation]:
        """Validate unique constraints."""
        violations = []

        for table, rows in seed_data.items():
            unique_cols = schema_context.get(table, {}).get("unique_columns", [])

            for col in unique_cols:
                values = [row.get(col) for row in rows if row.get(col) is not None]
                duplicates = [v for v in values if values.count(v) > 1]

                if duplicates:
                    violations.append(...)

        return violations
```

**REFACTOR Phase**:
- Support composite constraints
- Better error context
- Performance optimization for large datasets

**CLEANUP Phase**:
- Ruff, type hints, docstrings
- Commit: "feat(consistency): add UniqueConstraintValidator"

**Tests**: 6 tests in `tests/unit/seed_validation/test_unique_validator.py`

---

### Cycle 4: NotNullValidator - Verify Required Columns

**RED Phase**: Write failing tests
```python
def test_detects_null_in_not_null_column():
    """Test detection of NULL in NOT NULL column."""
    validator = NotNullValidator()

    users = [
        {"id": "1", "name": "Alice"},
        {"id": "2", "name": None}  # NULL in NOT NULL column
    ]

    schema_context = {
        "users": {"columns": {"name": {"nullable": False}}}
    }

    violations = validator.validate({"users": users}, schema_context)
    assert len(violations) == 1
    assert "NULL" in violations[0].message
    assert "name" in violations[0].message

def test_allows_null_in_nullable_column():
    """Test that NULL is allowed in nullable columns."""
    validator = NotNullValidator()

    users = [
        {"id": "1", "nickname": None}  # NULL allowed
    ]

    schema_context = {
        "users": {"columns": {"nickname": {"nullable": True}}}
    }

    violations = validator.validate({"users": users}, schema_context)
    assert len(violations) == 0

def test_detects_multiple_null_violations():
    """Test reporting all NULL violations."""
    pass
```

**GREEN Phase**: Minimal implementation
```python
class NotNullValidator:
    """Validate NOT NULL constraints."""

    def validate(
        self,
        seed_data: dict[str, list[dict]],
        schema_context: dict
    ) -> list[Violation]:
        """Validate NOT NULL constraints."""
        violations = []

        for table, rows in seed_data.items():
            columns = schema_context.get(table, {}).get("columns", {})

            for row_idx, row in enumerate(rows):
                for col, col_info in columns.items():
                    if not col_info.get("nullable") and row.get(col) is None:
                        violations.append(...)

        return violations
```

**REFACTOR Phase**:
- Better error positioning
- Multiple violation reporting

**CLEANUP Phase**:
- Commit: "feat(consistency): add NotNullValidator"

**Tests**: 5 tests in `tests/unit/seed_validation/test_not_null_validator.py`

---

### Cycle 5: CompletenessValidator - Check Required Tables

**RED Phase**: Write failing tests
```python
def test_detects_missing_required_table():
    """Test detection when required table has no seed data."""
    validator = CompletenessValidator()

    seed_data = {
        "products": [{"id": "1", "name": "Widget"}]
        # Missing "categories" table
    }

    schema_context = {
        "required_tables": ["categories", "products"]
    }

    violations = validator.validate(seed_data, schema_context)
    assert len(violations) == 1
    assert "categories" in violations[0].message

def test_warns_on_empty_table():
    """Test warning when table exists but is empty."""
    validator = CompletenessValidator()

    seed_data = {
        "categories": []  # Empty table
    }

    schema_context = {
        "required_tables": ["categories"]
    }

    violations = validator.validate(seed_data, schema_context)
    assert len(violations) == 1
    assert violations[0].severity == "WARNING"

def test_reports_table_row_counts():
    """Test generating statistics for each table."""
    pass
```

**GREEN Phase**: Minimal implementation
```python
class CompletenessValidator:
    """Validate seed data completeness."""

    def validate(
        self,
        seed_data: dict[str, list[dict]],
        schema_context: dict
    ) -> list[Violation]:
        """Validate required tables are present and seeded."""
        violations = []

        required = schema_context.get("required_tables", [])

        for table in required:
            if table not in seed_data:
                violations.append(...)  # Missing table
            elif len(seed_data[table]) == 0:
                violations.append(...)  # Empty table (warning)

        return violations
```

**REFACTOR Phase**:
- Add statistics gathering
- Configurable required tables

**CLEANUP Phase**:
- Commit: "feat(consistency): add CompletenessValidator"

**Tests**: 5 tests in `tests/unit/seed_validation/test_completeness_validator.py`

---

### Cycle 6: EnvironmentComparator - Cross-Environment Analysis

**RED Phase**: Write failing tests
```python
def test_compares_table_counts_across_environments():
    """Test comparing table row counts across environments."""
    comparator = EnvironmentComparator()

    dev_data = {"users": [{"id": "1"}, {"id": "2"}, {"id": "3"}]}
    staging_data = {"users": []}  # Empty!

    comparison = comparator.compare({
        "development": dev_data,
        "staging": staging_data
    })

    assert "users" in comparison.divergences
    assert comparison.divergences["users"]["development"] == 3
    assert comparison.divergences["users"]["staging"] == 0

def test_detects_missing_tables_in_environment():
    """Test detection of tables missing in one environment."""
    pass

def test_reports_significant_differences():
    """Test warning on significant data divergence."""
    pass

def test_generates_comparison_report():
    """Test structured comparison report output."""
    pass
```

**GREEN Phase**: Minimal implementation
```python
class EnvironmentComparator:
    """Compare seed data across environments."""

    def compare(self, env_data: dict[str, dict]) -> ComparisonReport:
        """Compare seed data structures and coverage."""
        divergences = {}

        # Count rows per table per environment
        for env, data in env_data.items():
            for table, rows in data.items():
                if table not in divergences:
                    divergences[table] = {}
                divergences[table][env] = len(rows)

        return ComparisonReport(divergences=divergences)
```

**REFACTOR Phase**:
- Add statistical analysis
- Percentage variance calculation
- Threshold-based warnings

**CLEANUP Phase**:
- Commit: "feat(consistency): add EnvironmentComparator"

**Tests**: 6 tests in `tests/unit/seed_validation/test_environment_comparator.py`

---

### Cycle 7: ConsistencyValidator - Orchestrator

**RED Phase**: Write failing tests
```python
def test_orchestrates_all_validators():
    """Test that ConsistencyValidator runs all checks."""
    validator = ConsistencyValidator()

    seed_files = ["db/seeds/users.sql", "db/seeds/orders.sql"]
    schema_context = {...}

    report = validator.validate(seed_files, schema_context)

    # Should have results from all validators
    assert report.foreign_key_violations
    assert report.unique_violations
    assert report.not_null_violations
    assert report.completeness_warnings

def test_aggregates_violations():
    """Test that all violations are aggregated in report."""
    pass

def test_returns_structured_report():
    """Test ConsistencyReport structure."""
    report = ConsistencyValidator().validate(...)

    assert hasattr(report, "violations")  # List of all violations
    assert hasattr(report, "warnings")    # List of all warnings
    assert hasattr(report, "statistics")  # Row counts, coverage %
    assert hasattr(report, "has_errors")  # Boolean
```

**GREEN Phase**: Minimal implementation
```python
class ConsistencyValidator:
    """Orchestrate all consistency validation checks."""

    def __init__(self) -> None:
        """Initialize with sub-validators."""
        self.fk_validator = ForeignKeyDepthValidator()
        self.unique_validator = UniqueConstraintValidator()
        self.not_null_validator = NotNullValidator()
        self.completeness_validator = CompletenessValidator()
        self.env_comparator = EnvironmentComparator()

    def validate(
        self,
        seed_files: list[str],
        schema_context: dict,
        environments: dict | None = None
    ) -> ConsistencyReport:
        """Run all consistency checks."""
        # Parse seed files
        seed_data = self._parse_seed_files(seed_files)

        # Run validators
        fk_violations = self.fk_validator.validate(seed_data, schema_context)
        unique_violations = self.unique_validator.validate(seed_data, schema_context)
        not_null_violations = self.not_null_validator.validate(seed_data, schema_context)
        completeness_warnings = self.completeness_validator.validate(seed_data, schema_context)

        # Optional: Compare environments
        env_comparison = None
        if environments:
            env_comparison = self.env_comparator.compare(environments)

        return ConsistencyReport(
            violations=fk_violations + unique_violations + not_null_violations,
            warnings=completeness_warnings,
            environment_comparison=env_comparison
        )
```

**REFACTOR Phase**:
- Error handling
- Progress reporting
- Caching for performance

**CLEANUP Phase**:
- Commit: "feat(consistency): add ConsistencyValidator orchestrator"

**Tests**: 8 tests in `tests/unit/seed_validation/test_consistency_validator.py`

---

### Cycle 8: CLI Integration

**RED Phase**: Write failing tests
```python
def test_cli_seed_validate_consistency_flag():
    """Test --consistency-check flag in seed validate command."""
    runner = CliRunner()

    result = runner.invoke(
        app,
        ["seed", "validate", "--seeds-dir", "db/seeds", "--consistency-check"]
    )

    assert result.exit_code in (0, 1)  # Should complete
    assert "consistency" in result.stdout.lower()

def test_cli_reports_violations_text():
    """Test text format output for violations."""
    pass

def test_cli_reports_violations_json():
    """Test JSON format output."""
    pass

def test_cli_exit_code_on_errors():
    """Test exit code when violations found."""
    # Should exit with code 1 for violations
    pass

def test_cli_with_all_environments():
    """Test --all-envs flag with environment comparison."""
    pass
```

**GREEN Phase**: Minimal CLI integration
```python
@seed_app.command("validate")
def validate(
    ...existing parameters...,
    consistency_check: bool = typer.Option(
        False,
        "--consistency-check",
        help="Enable data consistency validation (completeness, constraints, FKs)"
    ),
    all_envs: bool = typer.Option(
        False,
        "--all-envs",
        help="Compare consistency across all environments"
    ),
) -> None:
    """Validate seed files for data consistency."""

    if not consistency_check:
        # ... existing validation code ...
        return

    # New consistency check
    validator = ConsistencyValidator()

    if all_envs:
        # Validate all environments
        env_data = {...}
        report = validator.validate(seed_files, schema_context, environments=env_data)
    else:
        report = validator.validate(seed_files, schema_context)

    # Output report
    if format_ == "json":
        console.print(json.dumps(report.to_dict(), indent=2))
    else:
        _print_consistency_report(report, console)

    if report.has_errors:
        raise typer.Exit(1)
```

**REFACTOR Phase**:
- Better output formatting
- Progress indicators
- Error categorization in output

**CLEANUP Phase**:
- Commit: "feat(cli): add --consistency-check to seed validate"

**Tests**: 7 tests in `tests/unit/cli/test_seed_consistency_check.py`

---

### Cycle 9: Documentation & Examples

**RED Phase**: Create documentation tests
```python
def test_documentation_example_foreign_key_detection():
    """Test that documentation example works correctly."""
    # Example from guide showing FK violation detection
    pass

def test_documentation_example_unique_constraint():
    """Test unique constraint validation example."""
    pass

def test_documentation_example_completeness_check():
    """Test completeness validation example."""
    pass

def test_documentation_example_environment_comparison():
    """Test environment comparison example."""
    pass
```

**GREEN Phase**: Create documentation
- `docs/guides/data-consistency-validation.md`
- Real-world examples
- Common patterns
- Troubleshooting guide

**REFACTOR Phase**:
- Add diagrams/flows
- Cross-reference with related docs
- Add to API reference

**CLEANUP Phase**:
- Commit: "docs: add comprehensive data consistency guide"

**Tests**: 4 tests in `tests/unit/docs/test_consistency_examples.py`

---

### Cycle 10: Finalization & Integration

**RED Phase**: Write integration tests
```python
def test_full_workflow_with_consistency_check():
    """Test complete workflow: parse → validate → report."""
    pass

def test_consistency_check_with_prep_seed_levels():
    """Test consistency check alongside prep-seed validation."""
    pass

def test_performance_with_large_datasets():
    """Test consistency check doesn't timeout with 10k+ rows."""
    pass

def test_zero_regressions():
    """Verify all 3,804+ existing tests still pass."""
    pass
```

**GREEN Phase**: Integration
- Verify all tests pass
- Performance testing
- Regression testing

**REFACTOR Phase**:
- Performance optimizations
- Error recovery improvements

**CLEANUP Phase**:
- Final ruff/type check
- Update CLAUDE.md with Phase 11 completion
- Update .phases/README.md
- Commit: "chore: Phase 11 complete - data consistency validation"

**Tests**: 10 integration tests in `tests/integration/test_consistency_workflow.py`

---

## Success Metrics

### Test Coverage
- ✅ 70+ new unit tests
- ✅ 10+ integration tests
- ✅ 4 documentation verification tests
- ✅ Zero regressions in existing 3,804+ tests

### Code Quality
- ✅ 100% type hint coverage
- ✅ Ruff clean (zero warnings)
- ✅ Comprehensive docstrings
- ✅ All modules documented

### User Experience
- ✅ Clear error messages with line numbers
- ✅ JSON and text output formats
- ✅ CLI integration with existing commands
- ✅ Documentation with real examples

---

## Dependencies

### Requires
- Phase 10 (UUID Validation) ✅ Complete
- Prep-Seed infrastructure (Levels 1-5) ✅ Exists
- Schema parsing capabilities ✅ Exists

### Blocks
- Phase 12 (COPY format support) - Validation framework provides foundation

---

## Implementation Notes

### SQL Parsing Strategy
- Reuse existing SQL parsing infrastructure where possible
- Use regex + sqlparse for INSERT/SELECT extraction
- Handle complex queries (UNION, CTE, subqueries)

### Performance Considerations
- Cache schema context to avoid repeated lookups
- Use set operations for FK validation (O(n) not O(n²))
- Stream large files instead of loading all into memory

### Schema Context
- Leverage existing schema extraction from `db/schema/`
- Use prep-seed Level 2 (schema consistency) data
- Build metadata index for FK lookups

### Error Reporting
```python
class ConsistencyViolation:
    """Structured violation report."""
    file: str           # Source seed file
    line: int           # Line number in file
    table: str          # Affected table
    column: str | None  # Affected column (if applicable)
    row_index: int      # Row number in INSERT
    violation_type: str # FK_MISSING, DUPLICATE, NULL_REQUIRED, etc.
    severity: str       # ERROR, WARNING
    message: str        # Human-readable message
    context: dict       # Additional context (value, expected, etc.)
    resolution: str     # Suggested fix
```

---

## Timeline Estimate

**Total Effort**: 10-15 days (TDD with comprehensive testing)

- Cycles 1-2: 3-4 days (data extraction + FK validation)
- Cycles 3-5: 4-5 days (unique/null/completeness)
- Cycle 6: 2 days (environment comparison)
- Cycle 7: 2-3 days (orchestrator)
- Cycle 8: 1-2 days (CLI integration)
- Cycle 9: 2-3 days (documentation)
- Cycle 10: 1-2 days (finalization)

---

## Phase Completion Criteria

✅ Phase 11 is COMPLETE when:

1. **All 10 TDD Cycles Finished**
   - Each cycle RED → GREEN → REFACTOR → CLEANUP
   - All cycles committed

2. **All Tests Passing**
   - 70+ new tests for Phase 11
   - Zero regressions (3,804+ existing tests)
   - All integration tests passing

3. **Code Quality**
   - `uv run ruff check` - clean
   - `uv run ruff format` - formatted
   - `uv run ty check` - type safe

4. **Documentation Complete**
   - `docs/guides/data-consistency-validation.md`
   - API reference updated
   - Examples verified

5. **Version Updated**
   - Bump to 0.4.2+ in `pyproject.toml`
   - Update CLAUDE.md with Phase 11 summary
   - Update .phases/README.md

6. **Final Commit**
   - Clean summary of what was built
   - All artifacts listed

---

## Status

[ ] Not Started
[ ] In Progress
[ ] Complete

**Last Updated**: February 13, 2026
**Maintainer**: Claude Code

---

## See Also

- **Issue #24**: Feature request for this phase
- **Phase 10**: UUID Validation (completed)
- **Phase 9**: Sequential Seed Execution (completed)
- **Prep-Seed Validation Guide**: `docs/guides/prep-seed-validation.md`
