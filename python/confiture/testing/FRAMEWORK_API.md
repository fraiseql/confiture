# Confiture Testing Framework - API Reference

Complete API documentation for the Confiture migration testing framework.

## Package Structure

```
confiture.testing/
├── __init__.py
├── FRAMEWORK_API.md          (This file)
├── frameworks/
│   ├── __init__.py
│   ├── mutation.py           (Mutation testing framework)
│   └── performance.py        (Performance profiling framework)
└── fixtures/
    ├── __init__.py
    ├── migration_runner.py    (Migration execution)
    ├── schema_snapshotter.py  (Schema capture/comparison)
    └── data_validator.py      (Data integrity validation)
```

## Quick Reference

### Main Classes

| Class | Module | Purpose |
|-------|--------|---------|
| `MutationRegistry` | `frameworks.mutation` | Catalog of test-killing mutations |
| `MutationRunner` | `frameworks.mutation` | Execute mutations and track results |
| `MutationReport` | `frameworks.mutation` | Analyze mutation testing results |
| `MigrationPerformanceProfiler` | `frameworks.performance` | Profile operation timing |
| `PerformanceProfile` | `frameworks.performance` | Single operation metrics |
| `PerformanceBaseline` | `frameworks.performance` | Track performance over time |
| `MigrationRunner` | `fixtures.migration_runner` | Execute migrations |
| `SchemaSnapshotter` | `fixtures.schema_snapshotter` | Capture schema state |
| `DataValidator` | `fixtures.data_validator` | Validate data integrity |

## Mutation Testing Framework

### MutationRegistry

Provides catalog of mutations for test quality validation.

**Import:**
```python
from confiture.testing.frameworks.mutation import MutationRegistry
```

**Constructor:**
```python
registry = MutationRegistry()
```

**Properties:**

| Property | Type | Description |
|----------|------|-------------|
| `mutations` | `dict[str, list[Mutation]]` | All mutations organized by category |
| `schema_mutations` | `list[Mutation]` | SCHEMA category mutations |
| `data_mutations` | `list[Mutation]` | DATA category mutations |
| `rollback_mutations` | `list[Mutation]` | ROLLBACK category mutations |
| `performance_mutations` | `list[Mutation]` | PERFORMANCE category mutations |

**Methods:**

```python
# Get all mutations for a category
schema_mutations = registry.get_category_mutations("SCHEMA")
# Returns: list[Mutation]

# Get a specific mutation by ID
mutation = registry.get_mutation_by_id("SCH_001")
# Returns: Mutation or None

# Get all mutations
all_mutations = registry.get_all_mutations()
# Returns: list[Mutation]

# Check mutation availability
has_mutation = registry.has_mutation("SCH_001")
# Returns: bool

# Get mutations by severity
critical = registry.get_mutations_by_severity("CRITICAL")
# Returns: list[Mutation]
```

**Mutation Categories:**

| Category | Count | Purpose |
|----------|-------|---------|
| SCHEMA | 6 | DDL operation changes |
| DATA | 7 | Data manipulation changes |
| ROLLBACK | 5 | Rollback operation changes |
| PERFORMANCE | 6 | Performance threshold changes |

**Example Usage:**

```python
from confiture.testing.frameworks.mutation import MutationRegistry

registry = MutationRegistry()

# Get schema mutations
schema_mutations = registry.schema_mutations
for mutation in schema_mutations:
    print(f"{mutation.id}: {mutation.description}")

# Check specific mutation
if registry.has_mutation("SCH_002"):
    mutation = registry.get_mutation_by_id("SCH_002")
    print(f"Severity: {mutation.severity}")
    print(f"Category: {mutation.category}")
    print(f"Apply function: {mutation.apply_function}")
```

### Mutation

Represents a single mutation for test validation.

**Properties:**

```python
mutation.id              # str: Mutation identifier (e.g., "SCH_001")
mutation.description    # str: Human-readable description
mutation.category       # str: Category (SCHEMA, DATA, ROLLBACK, PERFORMANCE)
mutation.severity       # str: CRITICAL, HIGH, MEDIUM, LOW
mutation.apply_function # callable: Function to apply mutation
mutation.keywords       # list[str]: Keywords for filtering
```

**Example:**

```python
mutation = registry.get_mutation_by_id("SCH_001")

print(f"ID: {mutation.id}")
print(f"Description: {mutation.description}")
print(f"Category: {mutation.category}")
print(f"Severity: {mutation.severity}")

# Apply mutation
modified_sql = mutation.apply_function(original_sql)
```

### MutationRunner

Executes mutations and tracks test results.

**Import:**
```python
from confiture.testing.frameworks.mutation import MutationRunner
```

**Constructor:**
```python
runner = MutationRunner(registry=None, verbose=True)
# registry: Optional MutationRegistry (creates new if None)
# verbose: bool - Enable detailed output
```

**Methods:**

```python
# Run mutation suite
report = runner.run_mutation_suite(registry)
# Returns: MutationReport

# Run single mutation
result = runner.run_mutation(mutation, test_function)
# mutation: Mutation
# test_function: callable(mutation) -> bool
# Returns: MutationTestResult

# Run with custom settings
report = runner.run_mutation_suite(
    registry,
    timeout_seconds=300,
    max_mutations=None  # None = all mutations
)
# Returns: MutationReport
```

**Example:**

```python
from confiture.testing.frameworks.mutation import MutationRunner

runner = MutationRunner()

# Define test function
def test_with_mutation(mutation):
    """Test that should be killed by mutation."""
    try:
        # Run migration with mutation applied
        result = execute_migration_with_mutation(mutation)

        # Test should detect the mutation
        assert result.schema_valid, "Mutation not detected!"
        return True  # Mutation killed
    except AssertionError:
        return False  # Mutation survived

# Run test suite
report = runner.run_mutation_suite(registry)
print(f"Kill rate: {report.kill_rate}%")
```

### MutationReport

Analysis of mutation testing results.

**Properties:**

```python
report.total_mutations      # int: Total mutations in suite
report.killed_mutations     # int: Mutations that failed tests
report.survived_mutations   # int: Mutations that passed tests
report.error_mutations      # int: Mutations with errors
report.results              # list[MutationResult]: Individual results
report.timestamp            # datetime: Report generation time
report.duration_seconds     # float: Total execution time
```

**Methods:**

```python
# Calculate kill rate (test quality metric)
kill_rate = report.calculate_kill_rate()
# Returns: float (0-100)

# Get statistics
stats = report.get_statistics()
# Returns: dict with metrics

# Find weak areas (survived mutations)
weak = report.get_survived_mutations()
# Returns: list[Mutation]

# Get summary
summary = report.get_summary()
# Returns: str - Human-readable summary

# Export results
json_data = report.to_json()
# Returns: str - JSON representation
```

**Example:**

```python
report = runner.run_mutation_suite(registry)

# Check kill rate
kill_rate = report.calculate_kill_rate()
print(f"Test quality: {kill_rate}%")

if kill_rate < 80:
    print("Tests need improvement - low mutation kill rate")

    # Find weak areas
    survived = report.get_survived_mutations()
    for mutation in survived:
        print(f"Weak test coverage: {mutation.description}")
```

## Performance Framework

### MigrationPerformanceProfiler

Profiles migration operation execution times.

**Import:**
```python
from confiture.testing.frameworks.performance import MigrationPerformanceProfiler
```

**Constructor:**
```python
profiler = MigrationPerformanceProfiler()
```

**Methods:**

```python
# Profile a migration operation
profile = profiler.profile_operation(
    operation="CREATE TABLE",
    sql="CREATE TABLE users (id UUID PRIMARY KEY)",
    db_connection=conn  # Optional
)
# Returns: PerformanceProfile

# Profile with custom timeout
profile = profiler.profile_operation(
    operation="Complex Migration",
    sql=complex_sql,
    timeout_seconds=60
)

# Get baseline
baseline = profiler.get_baseline()
# Returns: PerformanceBaseline or None
```

**Example:**

```python
from confiture.testing.frameworks.performance import MigrationPerformanceProfiler
import psycopg

profiler = MigrationPerformanceProfiler()

# Connect to database
conn = psycopg.connect("postgresql://localhost/confiture_test")

# Profile CREATE TABLE operation
profile = profiler.profile_operation(
    operation="CREATE TABLE users",
    sql="CREATE TABLE users (id UUID PRIMARY KEY, name VARCHAR(255))",
    db_connection=conn
)

print(f"Duration: {profile.duration_seconds}s")
print(f"Success: {profile.success}")

conn.close()
```

### PerformanceProfile

Single operation performance metrics.

**Properties:**

```python
profile.operation          # str: Operation name
profile.duration_seconds   # float: Execution duration
profile.timestamp          # str: ISO timestamp
profile.success            # bool: Operation succeeded
profile.memory_mb          # Optional[float]: Memory used
profile.query_plan         # Optional[str]: EXPLAIN output
```

**Methods:**

```python
# Check against threshold
is_slow = profile.is_regression(baseline_seconds=1.0, threshold_pct=20)
# Returns: bool

# Calculate regression percentage
regression = profile.calculate_regression(baseline_seconds=1.0)
# Returns: float (-50 to 100+)

# Get summary
summary = profile.get_summary()
# Returns: str - Human-readable summary
```

**Example:**

```python
# Check if operation is slow
if profile.duration_seconds > 5.0:
    print(f"⚠️  Slow operation: {profile.duration_seconds}s")

# Check regression against baseline
if profile.is_regression(baseline_seconds=1.0, threshold_pct=20):
    print("Performance regression detected!")
    regression_pct = profile.calculate_regression(1.0)
    print(f"  Increase: {regression_pct}%")
```

### PerformanceBaseline

Tracks performance metrics over time for regression detection.

**Import:**
```python
from confiture.testing.frameworks.performance import PerformanceBaseline
```

**Constructor:**
```python
baseline = PerformanceBaseline()
```

**Methods:**

```python
# Add a performance profile
baseline.add_profile(
    operation_name="CREATE TABLE",
    duration_seconds=0.5
)
# Returns: None

# Get baseline for operation
operation_baseline = baseline.get_baseline("CREATE TABLE")
# Returns: PerformanceProfile or None

# Check for regression
is_regression = baseline.detect_regression(
    operation="CREATE TABLE",
    current_seconds=0.6,
    threshold_pct=20  # 20% increase
)
# Returns: bool

# Get all baselines
baselines = baseline.get_all_baselines()
# Returns: dict[str, PerformanceProfile]

# Statistics
stats = baseline.get_statistics()
# Returns: dict with min, max, average times
```

**Example:**

```python
from confiture.testing.frameworks.performance import PerformanceBaseline

baseline = PerformanceBaseline()

# Load historical baselines
baseline.add_profile("CREATE TABLE", 0.5)
baseline.add_profile("CREATE INDEX", 1.2)
baseline.add_profile("Bulk Insert 10k", 8.5)

# Check if new operation is regression
if baseline.detect_regression("CREATE TABLE", 0.65, threshold_pct=20):
    print("Performance regression: CREATE TABLE now takes 30% longer")

# Get statistics
stats = baseline.get_statistics()
print(f"Average CREATE TABLE time: {stats['average']}s")
```

## Fixtures

### test_db_connection

Provides PostgreSQL database connection for tests.

**Usage:**
```python
def test_example(test_db_connection):
    """Test using database connection fixture."""
    with test_db_connection.cursor() as cur:
        cur.execute("CREATE TABLE test (id UUID PRIMARY KEY)")
        test_db_connection.commit()
```

**Database Details:**
```python
# Connection string
DATABASE_URL: postgresql://confiture:confiture@localhost:5432/confiture_test

# Auto-cleanup
# Connection automatically closes after test
```

### temp_project_dir

Provides temporary project directory for test files.

**Usage:**
```python
def test_with_files(temp_project_dir):
    """Test using temporary directory."""
    migration_file = temp_project_dir / "001_create_table.sql"
    migration_file.write_text("CREATE TABLE test (...)")

    assert migration_file.exists()
```

### sample_confiture_schema

Provides sample PostgreSQL schema files.

**Usage:**
```python
def test_with_schema(sample_confiture_schema, test_db_connection):
    """Test using sample schema."""
    with test_db_connection.cursor() as cur:
        # sample_confiture_schema is dict[str, Path]
        users_sql = sample_confiture_schema["users"].read_text()
        cur.execute(users_sql)
        test_db_connection.commit()
```

**Available Schemas:**
```python
sample_confiture_schema = {
    "extensions.sql": Path(...),    # PostgreSQL extensions
    "users.sql": Path(...),         # Users table
    "posts.sql": Path(...),         # Posts table
    "comments.sql": Path(...),      # Comments table
    "user_stats.sql": Path(...),    # User aggregates
}
```

### mutation_registry

Provides configured MutationRegistry for tests.

**Usage:**
```python
def test_with_mutations(mutation_registry):
    """Test using mutation framework."""
    # mutation_registry is pre-configured MutationRegistry

    schema_mutations = mutation_registry.schema_mutations
    for mutation in schema_mutations:
        # Test mutation killing
        pass
```

### performance_profiler

Provides configured PerformanceProfiler for tests.

**Usage:**
```python
def test_with_performance(performance_profiler, test_db_connection):
    """Test using performance profiling."""
    profile = performance_profiler.profile_operation(
        operation="CREATE TABLE",
        sql="CREATE TABLE test (...)",
        db_connection=test_db_connection
    )

    assert profile.duration_seconds < 5.0
```

## Common Patterns

### Testing Forward Migration

```python
def test_forward_migration(test_db_connection):
    """Test forward migration succeeds and validates schema."""
    with test_db_connection.cursor() as cur:
        # Create table
        cur.execute("""
            CREATE TABLE users (
                id UUID PRIMARY KEY,
                name VARCHAR(255) NOT NULL
            )
        """)
        test_db_connection.commit()

        # Validate schema
        cur.execute("""
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_name = 'users'
        """)

        columns = {row[0]: row[1] for row in cur.fetchall()}
        assert 'id' in columns
        assert 'name' in columns
```

### Testing Rollback Safety

```python
def test_rollback_safe(test_db_connection):
    """Test rollback preserves data integrity."""
    with test_db_connection.cursor() as cur:
        # Create and populate table
        cur.execute("CREATE TABLE data (id UUID PRIMARY KEY, value INT)")
        cur.execute("INSERT INTO data VALUES (gen_random_uuid(), 42)")
        test_db_connection.commit()

        # Simulate migration
        cur.execute("ALTER TABLE data ADD COLUMN new_col VARCHAR(255)")
        test_db_connection.commit()

        # Simulate rollback
        cur.execute("ALTER TABLE data DROP COLUMN new_col")
        test_db_connection.commit()

        # Verify original data intact
        cur.execute("SELECT COUNT(*) FROM data WHERE value = 42")
        assert cur.fetchone()[0] == 1
```

### Testing Performance

```python
def test_performance(test_db_connection, performance_profiler):
    """Test operation performance against threshold."""
    import time

    with test_db_connection.cursor() as cur:
        # Setup
        cur.execute("""
            CREATE TABLE perf_test (
                id UUID PRIMARY KEY,
                data BIGINT
            )
        """)
        test_db_connection.commit()

        # Measure bulk insert
        start = time.time()
        cur.execute("""
            INSERT INTO perf_test (id, data)
            SELECT gen_random_uuid(), i FROM generate_series(1, 10000) i
        """)
        test_db_connection.commit()
        duration = time.time() - start

        # Assert within threshold
        assert duration < 30.0, f"Bulk insert took {duration}s (> 30s)"
```

## Error Handling

### Database Errors

```python
def test_with_error_handling(test_db_connection):
    """Handle database errors gracefully."""
    try:
        with test_db_connection.cursor() as cur:
            # This will fail - table doesn't exist
            cur.execute("INSERT INTO nonexistent VALUES (1)")
            test_db_connection.commit()
    except Exception as e:
        test_db_connection.rollback()
        print(f"Expected error: {e}")
```

### Timeout Handling

```python
def test_with_timeout(test_db_connection):
    """Handle operation timeouts."""
    try:
        with test_db_connection.cursor() as cur:
            # Set timeout for long operation
            cur.execute("SET statement_timeout TO '5s'")

            # This might timeout
            cur.execute("SELECT * FROM generate_series(1, 1000000)")
    except TimeoutError:
        print("Operation timed out")
```

## Environment Variables

```bash
# PostgreSQL Connection
DATABASE_URL=postgresql://confiture:confiture@localhost:5432/confiture_test
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_USER=confiture
POSTGRES_PASSWORD=confiture
POSTGRES_DB=confiture_test

# Performance Thresholds
PERF_CREATE_TABLE_THRESHOLD=5.0      # seconds
PERF_CREATE_INDEX_THRESHOLD=10.0     # seconds
PERF_BULK_INSERT_10K_THRESHOLD=30.0  # seconds

# Mutation Testing
MUTATION_TIMEOUT=300    # seconds
MUTATION_VERBOSE=true   # Enable detailed output
```

## Best Practices

1. **Use Fixtures**: Always use provided fixtures for database access
2. **Clean Up**: Always drop tables created with `DROP TABLE IF EXISTS`
3. **Isolate Tests**: Each test should be independent
4. **Use Assertions**: Clear assertion messages for failures
5. **Document Tests**: Include docstrings explaining test purpose
6. **Handle Transactions**: Explicitly commit/rollback
7. **Check Performance**: Always assert performance thresholds
8. **Verify Data**: Validate data integrity after operations

## Troubleshooting

### "Database connection failed"

```bash
# Check PostgreSQL is running
pg_isready -h localhost -p 5432

# Verify credentials
psql -h localhost -U confiture -d confiture_test
```

### "Mutation not detected"

```python
# Make sure test actually validates the mutation
# Good:
assert migrated_schema.columns['id'].type == 'UUID'

# Bad:
assert True  # Always passes, mutation not detected
```

### "Performance regression detected"

```python
# Review recent commits for performance impacts
# Run test in isolation
uv run pytest tests/migration_testing/test_performance.py -v --durations=10
```

## Additional Resources

- [Confiture Documentation](https://github.com/your-org/confiture)
- [PostgreSQL Documentation](https://www.postgresql.org/docs/)
- [psycopg3 Documentation](https://www.psycopg.org/)
- [pytest Documentation](https://docs.pytest.org/)
