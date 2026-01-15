# Confiture Migration Testing Suite

Comprehensive testing framework for PostgreSQL database migrations in Confiture.

## Overview

This test suite provides 200+ tests validating all aspects of database migrations:

- **Forward Migrations**: Schema changes, DDL validation, data preservation
- **Rollback Migrations**: Safe rollback, data recovery, transaction safety
- **Edge Cases**: Schema conflicts, concurrent operations, large datasets
- **Performance**: Migration timing, regression detection, load testing
- **Advanced Scenarios**: Real-world patterns, complex transformations

## Quick Start

### Prerequisites

```bash
# Ensure testing dependencies are installed
uv pip install ".[dev,testing]"
```

### Run All Migration Tests

```bash
# Run complete migration test suite
uv run pytest tests/migration_testing/ -v

# Run with coverage reporting
uv run pytest tests/migration_testing/ \
  --cov=confiture.testing \
  --cov-report=html \
  -v
```

### Run Specific Test Categories

```bash
# Forward migration tests
uv run pytest tests/migration_testing/test_forward_migrations.py -v

# Rollback migration tests
uv run pytest tests/migration_testing/test_rollback_migrations.py -v

# Edge case tests
uv run pytest tests/migration_testing/test_edge_cases.py -v

# Performance tests
uv run pytest tests/migration_testing/test_performance.py -v

# Load testing
uv run pytest tests/migration_testing/test_load_testing.py -v

# Advanced scenarios
uv run pytest tests/migration_testing/test_advanced_scenarios.py -v
```

## Test Suite Structure

### 1. Forward Migration Tests (36 tests)

Validates forward migration functionality.

**Test Categories:**

- **Basic Forward Migration** (5 tests): File structure, naming, DDL
  - `test_migration_file_structure()`
  - `test_migration_naming_conventions()`
  - `test_schema_ddl_structure()`
  - `test_simple_sql_migration()`
  - `test_migration_execution_time_tracked()`

- **Schema Validation** (8 tests): Organization, dependencies, format
  - `test_schema_file_extensions()`
  - `test_schema_directory_organization()`
  - `test_schema_section_organization()`
  - `test_migration_file_independence()`
  - `test_comment_preservation()`
  - etc.

- **Data Preservation** (6 tests): Type safety, constraints, indexes
  - `test_schema_creates_valid_ddl()`
  - `test_column_type_validation()`
  - `test_constraint_enforcement()`
  - `test_index_preservation()`
  - `test_foreign_key_validity()`
  - `test_data_truncation_prevention()`

- **Edge Cases** (6 tests): Empty migrations, duplicates, special chars
  - `test_empty_migration_handling()`
  - `test_duplicate_migration_detection()`
  - `test_special_characters_in_names()`
  - `test_large_file_handling()`
  - `test_multiple_statements()`
  - `test_comments_and_whitespace()`

- **Performance** (5 tests): Execution timing and optimization
  - `test_schema_execution_completion()`
  - `test_multiple_file_execution()`
  - `test_index_creation_performance()`
  - `test_constraint_creation_performance()`
  - `test_view_creation_performance()`

- **Idempotency** (5 tests): Safe re-execution of migrations
  - `test_schema_execution_idempotency()`
  - `test_index_idempotency()`
  - `test_view_idempotency()`
  - `test_extension_idempotency()`
  - `test_constraint_idempotency()`

**Example Test:**

```python
def test_column_type_validation(test_db_connection, sample_confiture_schema):
    """Validate that column types are preserved in migrations."""
    with test_db_connection.cursor() as cur:
        # Execute migration
        users_sql = sample_confiture_schema["users"].read_text()
        cur.execute(users_sql)
        test_db_connection.commit()

        # Query information schema to validate types
        cur.execute("""
            SELECT column_name, data_type FROM information_schema.columns
            WHERE table_name = 'users'
            ORDER BY ordinal_position
        """)

        columns = {row[0]: row[1] for row in cur.fetchall()}

        # Verify expected column types
        assert columns['id'] == 'uuid'
        assert columns['username'] in ['character varying', 'varchar']
        assert columns['email'] in ['character varying', 'varchar']
```

### 2. Rollback Migration Tests (48 tests)

Validates safe rollback and data recovery.

**Test Categories:**

- **Basic Rollback Operations** (5 tests): Reversing DDL operations
  - Table, column, index, constraint, view removal

- **Data Restoration** (8 tests): Preserving data during rollback
  - Column removal, modifications, constraint restoration, cascade delete

- **Rollback Safety** (8 tests): Transaction integrity and ordering
  - Invalid SQL handling, view dependencies, concurrent safety

- **Idempotency** (8 tests): Safe repeated rollback execution
  - IF EXISTS patterns for all operations

- **Performance** (5 tests): Rollback timing and efficiency

**Example Test:**

```python
def test_rollback_preserves_data_on_column_removal(test_db_connection):
    """Ensure data in other columns survives rollback."""
    with test_db_connection.cursor() as cur:
        # Create table with data
        cur.execute("""
            CREATE TABLE rb_data (
                id UUID PRIMARY KEY,
                name VARCHAR(255),
                email VARCHAR(255)
            )
        """)
        cur.execute("""
            INSERT INTO rb_data VALUES
            (gen_random_uuid(), 'Alice', 'alice@example.com')
        """)
        test_db_connection.commit()

        # Remove column
        cur.execute("ALTER TABLE rb_data DROP COLUMN email")
        test_db_connection.commit()

        # Verify name still exists
        cur.execute("SELECT name FROM rb_data")
        assert cur.fetchone()[0] == 'Alice'
```

### 3. Edge Cases & Integration Tests (35 tests)

Real-world edge cases and integration scenarios.

**Test Categories:**

- **Schema Conflicts** (5 tests): Duplicate detection, naming collisions
- **Concurrent Operations** (4 tests): Parallel execution safety
- **Large Datasets** (5 tests): 10k-100k row operations
- **Constraint Violations** (5 tests): NOT NULL, UNIQUE, FK, CHECK, PK
- **View Dependencies** (4 tests): Base tables, cascading views, joins
- **Multi-Step Migrations** (3 tests): Sequential multi-table changes
- **Complex Transformations** (3 tests): UUID, ENUM, denormalization

### 4. Performance Profiling Tests (8 tests)

Framework for performance measurement and regression detection.

Tests validate:
- Simple migration timing
- Index/constraint/view creation performance
- Bulk insert performance measurement
- Large table index creation
- Regression detection against baselines

**Framework Integration:**

```python
from confiture.testing.frameworks.performance import (
    MigrationPerformanceProfiler,
    PerformanceProfile,
    PerformanceBaseline
)

# Measure migration performance
profiler = MigrationPerformanceProfiler()
profile = profiler.profile_operation(
    operation="CREATE TABLE",
    sql="CREATE TABLE test (id UUID PRIMARY KEY)"
)

# Check against baseline
baseline = PerformanceBaseline()
if profile.duration_seconds > baseline.get_threshold("CREATE TABLE"):
    print("Performance regression detected!")
```

### 5. Load Testing Tests (12 tests)

Validates performance with large datasets.

**Operations Tested:**

- 10k row bulk inserts
- 50k row bulk inserts
- 100k row aggregation queries
- Index creation on large tables
- Constraint addition to large tables
- Bulk updates/deletes
- View queries on large tables
- JOIN operations on large tables

**Performance Thresholds:**

- Bulk insert (10k): < 30 seconds
- Bulk insert (50k): < 60 seconds
- Index creation (50k): < 30 seconds
- Large aggregation (100k): < 10 seconds
- JOIN on large tables: < 10 seconds

### 6. Advanced Scenarios Tests (10 tests)

Real-world migration patterns.

**Scenarios:**

1. **Multi-table Dependencies**: Users → Posts → Comments
2. **Complex Constraints**: Multiple FK, CHECK, UNIQUE combinations
3. **Data Transformations**: Name splitting, type conversions
4. **Denormalization**: Schema normalization reversal
5. **Schema Versioning**: JSONB-based version management
6. **Partitioning**: Time-based or value-based partitioning
7. **Indexing Strategy**: Composite, partial, and specialized indexes
8. **Triggers & Functions**: PL/pgSQL-based automation
9. **Materialized Views**: Performance-optimized views
10. **Custom Types**: ENUM and custom data type handling

**Example Test:**

```python
def test_multi_table_migration_with_dependencies(test_db_connection):
    """Test creating dependent table hierarchy."""
    with test_db_connection.cursor() as cur:
        # Create users
        cur.execute("""
            CREATE TABLE adv_users (
                id UUID PRIMARY KEY,
                username VARCHAR(255) UNIQUE NOT NULL
            )
        """)

        # Create posts with FK to users
        cur.execute("""
            CREATE TABLE adv_posts (
                id UUID PRIMARY KEY,
                user_id UUID NOT NULL REFERENCES adv_users(id),
                title VARCHAR(500) NOT NULL
            )
        """)

        # Create comments with FKs to posts and users
        cur.execute("""
            CREATE TABLE adv_comments (
                id UUID PRIMARY KEY,
                post_id UUID NOT NULL REFERENCES adv_posts(id),
                author_id UUID NOT NULL REFERENCES adv_users(id),
                content TEXT NOT NULL
            )
        """)
        test_db_connection.commit()

        # Verify FK relationships
        for table in ['adv_users', 'adv_posts', 'adv_comments']:
            cur.execute("SELECT to_regclass(%s)", (table,))
            assert cur.fetchone()[0] is not None
```

## Testing Patterns

### Connection Fixture

All tests use the `test_db_connection` fixture for PostgreSQL access:

```python
def test_example(test_db_connection):
    """Test using database connection fixture."""
    with test_db_connection.cursor() as cur:
        cur.execute("CREATE TABLE test (id UUID PRIMARY KEY)")
        test_db_connection.commit()

        cur.execute("SELECT to_regclass('test')")
        assert cur.fetchone()[0] is not None
```

### Schema Validation Pattern

Query PostgreSQL information schema to validate DDL:

```python
# Check table columns
cur.execute("""
    SELECT column_name, data_type FROM information_schema.columns
    WHERE table_name = 'users'
    ORDER BY ordinal_position
""")

# Check indexes
cur.execute("""
    SELECT indexname FROM pg_indexes
    WHERE tablename = 'users'
""")

# Check constraints
cur.execute("""
    SELECT constraint_name, constraint_type
    FROM information_schema.table_constraints
    WHERE table_name = 'users'
""")
```

### Data Integrity Pattern

Validate data preservation during schema changes:

```python
# Insert test data
cur.execute("INSERT INTO users (id, name) VALUES (gen_random_uuid(), 'Alice')")
test_db_connection.commit()

# Apply migration (e.g., add column)
cur.execute("ALTER TABLE users ADD COLUMN email VARCHAR(255)")
test_db_connection.commit()

# Verify data preservation
cur.execute("SELECT COUNT(*) FROM users WHERE name = 'Alice'")
assert cur.fetchone()[0] == 1
```

### Performance Measurement Pattern

Use Python's `time` module to measure operations:

```python
import time

start = time.time()
cur.execute("""
    INSERT INTO data (id, value)
    SELECT gen_random_uuid(), i FROM generate_series(1, 10000) i
""")
test_db_connection.commit()
duration = time.time() - start

assert duration < 30.0  # Performance threshold
```

## Framework Integration

### Mutation Testing

The mutation testing framework validates test quality:

```python
from confiture.testing.frameworks.mutation import (
    MutationRegistry,
    MutationRunner,
    MutationReport
)

# Load available mutations
registry = MutationRegistry()

# Mutations include:
# - Schema mutations (column type changes, constraint removal)
# - Data mutations (row insertion, value modification)
# - Rollback mutations (failed migration simulation)
# - Performance mutations (timing threshold adjustments)

# Run tests against mutations
runner = MutationRunner()
report = runner.run_mutation_suite(registry)

# Kill rate indicates test quality
kill_rate = report.calculate_kill_rate()
print(f"Test quality: {kill_rate}% of mutations killed")
```

### Performance Profiling

Track migration performance and detect regressions:

```python
from confiture.testing.frameworks.performance import (
    MigrationPerformanceProfiler,
    PerformanceBaseline
)

# Profile a migration
profiler = MigrationPerformanceProfiler()
profile = profiler.profile_operation(
    operation="CREATE INDEX",
    sql="CREATE INDEX idx_email ON users(email)"
)

# Compare against baseline
baseline = PerformanceBaseline()
baseline.add_profile("CREATE INDEX", 0.5)  # 500ms baseline

regression_pct = ((profile.duration_seconds / 0.5) - 1) * 100
if regression_pct > 20:  # 20% regression threshold
    print(f"Performance regression detected: {regression_pct}%")
```

## Configuration

### Database Connection

Tests use `DATABASE_URL` environment variable (default: localhost):

```bash
# Override database connection
export DATABASE_URL="postgresql://user:pass@host:5432/confiture_test"

uv run pytest tests/migration_testing/
```

### Test Database Setup

Tests use PostgreSQL 16 fixtures that automatically:
1. Create test databases
2. Initialize schemas
3. Clean up after tests
4. Handle transactions atomically

### Performance Baselines

Create baseline metrics for regression detection:

```bash
# Generate performance baselines
uv run pytest tests/migration_testing/test_performance.py \
  --benchmark-save=baseline
```

## GitHub Actions Integration

### Automated Testing

**migration-tests.yml**: Runs all tests on PR and main branch pushes

```yaml
- Runs 200+ migration tests
- PostgreSQL 16 service container
- Coverage reporting
- Test summary reporting
```

### Performance Monitoring

**migration-performance.yml**: Nightly performance profiling

```yaml
- Scheduled runs at 2 AM UTC
- Captures detailed performance metrics
- Detects regressions against thresholds
- Uploads artifacts for analysis
```

### Deployment Safety Gates

**migration-deployment-gates.yml**: Pre-deployment validation

```yaml
1. Migration naming conventions
2. Rollback compatibility
3. Schema DDL validation
4. Data integrity checks
5. Breaking change detection
6. Documentation completeness
```

## Troubleshooting

### Database Connection Issues

```bash
# Verify PostgreSQL is running and accepting connections
pg_isready -h localhost -p 5432

# Test psycopg connection directly
python3 << 'EOF'
import psycopg
conn = psycopg.connect("postgresql://confiture:confiture@localhost:5432/confiture_test")
print("Connection successful")
conn.close()
EOF
```

### Test Isolation Issues

Each test should:
- Drop tables created with `DROP TABLE IF EXISTS`
- Use unique table names to avoid conflicts
- Commit transactions explicitly
- Use fixtures for shared setup

```python
def test_example(test_db_connection):
    with test_db_connection.cursor() as cur:
        # Always clean up before creating
        cur.execute("DROP TABLE IF EXISTS test CASCADE")
        cur.execute("CREATE TABLE test (id UUID PRIMARY KEY)")
        test_db_connection.commit()
```

### Performance Timeout

If tests timeout, check:
1. PostgreSQL performance (run separately)
2. System resources (CPU, disk I/O)
3. Individual test duration: `uv run pytest tests/migration_testing/ --durations=10`

```bash
# Run with longer timeout
uv run pytest tests/migration_testing/ --timeout=300
```

## Best Practices

### Writing New Migration Tests

1. **Test one aspect**: Each test should validate a single behavior
2. **Use descriptive names**: `test_<scenario>_<expected_result>`
3. **Follow patterns**: Use existing test patterns for consistency
4. **Document complex setup**: Comment non-obvious test initialization
5. **Clean up resources**: Always drop created objects in test

Example:

```python
def test_column_type_validation(test_db_connection):
    """Validate that VARCHAR columns preserve length constraints."""
    with test_db_connection.cursor() as cur:
        # Setup: Create table with VARCHAR constraint
        cur.execute("""
            CREATE TABLE test_table (
                id UUID PRIMARY KEY,
                name VARCHAR(255) NOT NULL
            )
        """)
        test_db_connection.commit()

        # Exercise: Query information schema
        cur.execute("""
            SELECT character_maximum_length
            FROM information_schema.columns
            WHERE table_name = 'test_table' AND column_name = 'name'
        """)

        # Verify: Check the constraint exists
        max_length = cur.fetchone()[0]
        assert max_length == 255

        # Cleanup: Drop table
        cur.execute("DROP TABLE test_table CASCADE")
        test_db_connection.commit()
```

### Migration Testing Checklist

When adding new migrations, test:

- [ ] **Structure**: Proper file naming and organization
- [ ] **Syntax**: Valid PostgreSQL DDL
- [ ] **Forward Path**: Schema creates correctly
- [ ] **Rollback**: Can be safely reversed
- [ ] **Data Safety**: No data loss on rollback
- [ ] **Constraints**: FK, CHECK, UNIQUE working
- [ ] **Indexes**: Correct indexes created
- [ ] **Views**: Dependent views update correctly
- [ ] **Performance**: Execution within thresholds
- [ ] **Idempotency**: Can run multiple times safely
- [ ] **Documentation**: Comments explain the migration

## Running Tests in CI/CD

Tests automatically run on:

1. **Every PR to main**: Full test suite validation
2. **Every push to main**: Full test suite + deployment gates
3. **Nightly schedule**: Performance monitoring
4. **Manual trigger**: Via `workflow_dispatch`

View test results in GitHub Actions:

```
https://github.com/your-org/confiture/actions
```

## Contributing

To add new migration tests:

1. Create test in appropriate file (`test_*.py`)
2. Follow naming conventions and patterns
3. Include docstring describing test
4. Run locally: `uv run pytest tests/migration_testing/test_new.py`
5. Verify all tests pass: `uv run pytest tests/migration_testing/`
6. Submit PR with test additions

## Additional Resources

- [PostgreSQL Documentation](https://www.postgresql.org/docs/)
- [psycopg3 Documentation](https://www.psycopg.org/)
- [pytest Documentation](https://docs.pytest.org/)
- [Confiture Testing Framework](../../../python/confiture/testing/)

## Support

For issues or questions about the migration testing suite:

1. Check this README first
2. Review existing test examples
3. Consult the Confiture documentation
4. Open an issue in the GitHub repository
