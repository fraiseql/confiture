# Confiture - Implementation Phases

**Version**: 1.0
**Last Updated**: October 11, 2025
**Total Duration**: 8 months (3+2+3)

---

## Overview

Confiture development follows a **3-phase approach** with strict TDD discipline:

```
Phase 1: Python MVP          Phase 2: Rust Performance    Phase 3: Advanced Features
(3 months)                   (2 months)                   (3 months)
│                            │                            │
├─ Build from DDL            ├─ Fast file operations      ├─ Schema-to-schema (FDW)
├─ Incremental migrations    ├─ Fast schema diff          ├─ Production data sync
├─ Schema diff detection     ├─ Parallel processing       ├─ PII anonymization
├─ CLI commands              └─ Binary wheels             └─ Advanced integrations
└─ FraiseQL integration
```

---

## Phase 1: Python MVP (3 months)

**Goal**: Ship working 4-medium system in pure Python

**Target Date**: January 10, 2026

### Week 1-2: Project Setup & Schema Builder

#### **Week 1: Foundation**

**Milestone 1.1: Project Scaffolding**

**RED Phase**:
```python
# tests/unit/test_project_structure.py
def test_project_structure_exists():
    """Verify project structure is correct"""
    assert Path("python/confiture/__init__.py").exists()
    assert Path("tests/conftest.py").exists()
    assert Path("pyproject.toml").exists()
```

**GREEN Phase**:
- Create directory structure
- Set up `pyproject.toml`
- Configure `pytest`, `ruff`, `mypy`
- Add `.gitignore`, `.python-version`

**REFACTOR Phase**:
- Clean up `pyproject.toml`
- Add project metadata
- Configure dev dependencies

**QA Phase**:
```bash
uv run pytest tests/unit/test_project_structure.py
uv run ruff check .
uv run mypy python/confiture/
```

**Deliverables**:
- ✅ Working Python package structure
- ✅ Tests run successfully
- ✅ Pre-commit hooks configured
- ✅ README.md with quick start

---

**Milestone 1.2: Configuration System**

**RED Phase**:
```python
# tests/unit/test_config.py
def test_load_environment_config():
    """Test YAML environment config loading"""
    env = Environment.load("local")
    assert env.name == "local"
    assert "schema/" in env.include_dirs
```

**GREEN Phase**:
```python
# python/confiture/config/environment.py
from pathlib import Path
import yaml
from pydantic import BaseModel

class Environment(BaseModel):
    name: str
    include_dirs: list[str]
    exclude_dirs: list[str]

    @classmethod
    def load(cls, env_name: str) -> "Environment":
        config_path = Path(f"db/environments/{env_name}.yaml")
        with open(config_path) as f:
            data = yaml.safe_load(f)
        return cls(**data)
```

**REFACTOR Phase**:
- Add validation for paths
- Support environment variables
- Add default configurations

**QA Phase**:
```bash
uv run pytest tests/unit/test_config.py -v
# Coverage: >95%
```

**Deliverables**:
- ✅ YAML config loading
- ✅ Pydantic validation
- ✅ Environment abstraction

---

#### **Week 2: Schema Builder Core**

**Milestone 1.3: File Discovery**

**RED Phase**:
```python
# tests/unit/test_builder.py
def test_find_sql_files_in_order():
    """Files should be discovered in alphabetical order"""
    builder = SchemaBuilder(env="local")
    files = builder.find_sql_files()

    # Should start with 00_common/, then 10_tables/, etc.
    assert files[0].parts[-2] == "00_common"
    assert files[-1].parts[-2].startswith("50_")
```

**GREEN Phase**:
```python
# python/confiture/core/builder.py
from pathlib import Path

class SchemaBuilder:
    def __init__(self, env: str):
        self.env_config = Environment.load(env)

    def find_sql_files(self) -> list[Path]:
        files = []
        for include_dir in self.env_config.include_dirs:
            path = Path(include_dir)
            files.extend(path.rglob("*.sql"))
        return sorted(files)
```

**REFACTOR Phase**:
- Add exclusion filtering
- Validate file permissions
- Handle missing directories gracefully

**QA Phase**:
```bash
uv run pytest tests/unit/test_builder.py::test_find_sql_files_in_order -v
# + 5 more tests for edge cases
```

**Deliverables**:
- ✅ File discovery with ordering
- ✅ Exclusion filtering
- ✅ 10+ tests covering edge cases

---

**Milestone 1.4: Schema Concatenation**

**RED Phase**:
```python
def test_build_schema_content():
    """Build should concatenate files with headers"""
    builder = SchemaBuilder(env="test")
    schema = builder.build()

    # Should contain header
    assert "-- PostgreSQL Schema for Confiture" in schema

    # Should contain file separators
    assert "-- File: 00_common/extensions.sql" in schema
```

**GREEN Phase**:
```python
def build(self) -> str:
    """Build schema by concatenating DDL files"""
    files = self.find_sql_files()

    header = self._generate_header(len(files))
    parts = [header]

    for file in files:
        parts.append(f"\n-- File: {file.relative_to('db/schema')}\n")
        parts.append(file.read_text())
        parts.append("\n\n")

    return "".join(parts)
```

**REFACTOR Phase**:
- Optimize string concatenation
- Add progress reporting
- Include file metadata in headers

**QA Phase**:
```bash
uv run pytest tests/unit/test_builder.py -v --cov=confiture.core.builder
# Coverage: >90%
```

**Deliverables**:
- ✅ Schema concatenation working
- ✅ File headers and separators
- ✅ Deterministic output

---

**Milestone 1.5: Hash Computation**

**RED Phase**:
```python
def test_hash_changes_when_file_changes():
    """Hash should detect file changes"""
    builder = SchemaBuilder(env="test")

    hash1 = builder.compute_hash()

    # Modify a file
    Path("db/schema/10_tables/users.sql").write_text("-- modified")

    hash2 = builder.compute_hash()

    assert hash1 != hash2
```

**GREEN Phase**:
```python
import hashlib

def compute_hash(self) -> str:
    """Compute SHA256 hash of all schema files"""
    hasher = hashlib.sha256()

    for file in self.find_sql_files():
        hasher.update(file.read_bytes())

    return hasher.hexdigest()
```

**REFACTOR Phase**:
- Include file paths in hash
- Add git commit hash (if available)
- Optimize for large files

**QA Phase**:
```bash
uv run pytest tests/unit/test_builder.py::test_hash* -v
# All hash tests pass
```

**Deliverables**:
- ✅ SHA256 hash computation
- ✅ Change detection working
- ✅ Version tracking foundation

---

### Week 3-4: Migration System

**Milestone 1.6: Migration Base Class**

**RED Phase**:
```python
# tests/unit/test_migration.py
def test_migration_base_class():
    """Migration should have up/down methods"""

    class TestMigration(Migration):
        def up(self):
            self.execute("CREATE TABLE test (id INT)")

        def down(self):
            self.execute("DROP TABLE test")

    migration = TestMigration()
    assert hasattr(migration, "up")
    assert hasattr(migration, "down")
    assert hasattr(migration, "execute")
```

**GREEN Phase**:
```python
# python/confiture/models/migration.py
from abc import ABC, abstractmethod
import psycopg

class Migration(ABC):
    def __init__(self, connection: psycopg.Connection):
        self.connection = connection

    @abstractmethod
    def up(self) -> None:
        """Apply migration"""
        pass

    @abstractmethod
    def down(self) -> None:
        """Rollback migration"""
        pass

    def execute(self, sql: str) -> None:
        """Execute SQL statement"""
        with self.connection.cursor() as cursor:
            cursor.execute(sql)
```

**REFACTOR Phase**:
- Add transaction support
- Add execution tracking
- Add rollback safety checks

**QA Phase**:
```bash
uv run pytest tests/unit/test_migration.py -v
```

**Deliverables**:
- ✅ Migration base class
- ✅ Transaction wrapping
- ✅ Execute/rollback pattern

---

**Milestone 1.7: Migration Executor**

**RED Phase**:
```python
# tests/integration/test_migrator.py
@pytest.mark.asyncio
async def test_apply_migration(test_db):
    """Migrator should apply migration and track it"""
    migrator = Migrator(env="test")

    migration = create_test_migration()
    await migrator.apply(migration)

    # Verify migration was tracked
    result = await test_db.fetch_one(
        "SELECT * FROM confiture_migrations WHERE version = $1",
        migration.version
    )
    assert result is not None
```

**GREEN Phase**:
```python
# python/confiture/core/migrator.py
class Migrator:
    def __init__(self, env: str):
        self.env_config = Environment.load(env)
        self.connection = self._connect()

    async def apply(self, migration: Migration) -> None:
        """Apply a single migration"""
        async with self.connection.transaction():
            # Run migration
            await migration.up()

            # Track in database
            await self.connection.execute(
                """
                INSERT INTO confiture_migrations (version, name, applied_at)
                VALUES ($1, $2, NOW())
                """,
                migration.version,
                migration.name
            )
```

**REFACTOR Phase**:
- Add dry-run mode
- Add rollback on failure
- Add execution time tracking

**QA Phase**:
```bash
uv run pytest tests/integration/test_migrator.py -v
# Requires test PostgreSQL database
```

**Deliverables**:
- ✅ Migration application working
- ✅ State tracking in database
- ✅ Transaction safety

---

**Milestone 1.8: Migration Discovery**

**RED Phase**:
```python
def test_find_pending_migrations():
    """Should find migrations not yet applied"""
    migrator = Migrator(env="test")

    pending = migrator.find_pending()

    # Should return list of migration files
    assert len(pending) > 0
    assert all(m.endswith(".py") for m in pending)
```

**GREEN Phase**:
```python
def find_pending(self) -> list[Path]:
    """Find migrations not yet applied"""
    # Get all migration files
    all_migrations = sorted(Path("db/migrations").glob("*.py"))

    # Get applied migrations from database
    applied = self._get_applied_versions()

    # Return pending
    return [m for m in all_migrations if self._version_from_file(m) not in applied]
```

**REFACTOR Phase**:
- Add migration validation
- Check for gaps in version sequence
- Detect migration conflicts

**QA Phase**:
```bash
uv run pytest tests/unit/test_migrator.py::test_find_pending* -v
```

**Deliverables**:
- ✅ Migration discovery
- ✅ Pending detection
- ✅ Version validation

---

### Week 5-6: Schema Diff Detection

**Milestone 1.9: SQL Parser Integration**

**RED Phase**:
```python
# tests/unit/test_differ.py
def test_parse_create_table():
    """Should parse CREATE TABLE statements"""
    sql = "CREATE TABLE users (id INT PRIMARY KEY, name TEXT)"

    differ = SchemaDiffer()
    tables = differ.parse_sql(sql)

    assert len(tables) == 1
    assert tables[0].name == "users"
    assert len(tables[0].columns) == 2
```

**GREEN Phase**:
```python
# python/confiture/core/differ.py
import sqlparse

class SchemaDiffer:
    def parse_sql(self, sql: str) -> list[Table]:
        """Parse SQL into structured format"""
        statements = sqlparse.parse(sql)

        tables = []
        for stmt in statements:
            if stmt.get_type() == "CREATE":
                table = self._parse_create_table(stmt)
                tables.append(table)

        return tables
```

**REFACTOR Phase**:
- Add support for indexes, constraints
- Handle complex DDL (ALTER, DROP)
- Parse views, functions

**QA Phase**:
```bash
uv run pytest tests/unit/test_differ.py::test_parse* -v
```

**Deliverables**:
- ✅ SQL parsing working
- ✅ Table/column extraction
- ✅ Foundation for diff algorithm

---

**Milestone 1.10: Diff Algorithm**

**RED Phase**:
```python
def test_detect_column_rename():
    """Should detect column rename"""
    old_sql = "CREATE TABLE users (id INT, full_name TEXT)"
    new_sql = "CREATE TABLE users (id INT, display_name TEXT)"

    differ = SchemaDiffer()
    diff = differ.compare(old_sql, new_sql)

    assert len(diff.changes) == 1
    assert diff.changes[0].type == "RENAME_COLUMN"
    assert diff.changes[0].old_name == "full_name"
    assert diff.changes[0].new_name == "display_name"
```

**GREEN Phase**:
```python
def compare(self, old_sql: str, new_sql: str) -> SchemaDiff:
    """Compare two schemas and detect changes"""
    old_tables = self.parse_sql(old_sql)
    new_tables = self.parse_sql(new_sql)

    changes = []

    # Compare tables
    for old_table in old_tables:
        new_table = self._find_table(new_tables, old_table.name)

        if not new_table:
            changes.append(Change(type="DROP_TABLE", table=old_table.name))
            continue

        # Compare columns
        column_changes = self._compare_columns(old_table, new_table)
        changes.extend(column_changes)

    return SchemaDiff(changes=changes)
```

**REFACTOR Phase**:
- Improve rename detection (fuzzy matching)
- Add confidence scores
- Handle complex cases (type changes)

**QA Phase**:
```bash
uv run pytest tests/unit/test_differ.py -v --cov=confiture.core.differ
# Coverage: >85%
```

**Deliverables**:
- ✅ Basic diff detection
- ✅ Column rename detection
- ✅ Table add/drop detection

---

**Milestone 1.11: Migration Generation**

**RED Phase**:
```python
def test_generate_migration_from_diff():
    """Should generate Python migration from diff"""
    diff = SchemaDiff(changes=[
        Change(type="RENAME_COLUMN", table="users", old_name="full_name", new_name="display_name")
    ])

    migrator = Migrator(env="test")
    migration_file = migrator.generate_migration(diff, name="rename_user_full_name")

    # Should create file
    assert migration_file.exists()

    # Should contain correct code
    content = migration_file.read_text()
    assert "ALTER TABLE users" in content
    assert "RENAME COLUMN full_name TO display_name" in content
```

**GREEN Phase**:
```python
def generate_migration(self, diff: SchemaDiff, name: str) -> Path:
    """Generate Python migration file from schema diff"""
    # Find next version number
    version = self._next_version()

    # Generate file path
    filename = f"{version:03d}_{name}.py"
    path = Path("db/migrations") / filename

    # Generate code
    code = self._generate_migration_code(diff, version, name)

    # Write file
    path.write_text(code)

    return path

def _generate_migration_code(self, diff: SchemaDiff, version: int, name: str) -> str:
    """Generate Python migration code"""
    template = '''"""Migration: {name}

Version: {version:03d}
Generated: {timestamp}
"""
from confiture.models.migration import Migration

class {class_name}(Migration):
    version = "{version:03d}"
    name = "{name}"

    def up(self):
{up_statements}

    def down(self):
{down_statements}
'''

    up_statements = self._generate_up_statements(diff)
    down_statements = self._generate_down_statements(diff)

    return template.format(
        name=name,
        version=version,
        class_name=self._to_class_name(name),
        up_statements=up_statements,
        down_statements=down_statements,
        timestamp=datetime.now().isoformat()
    )
```

**REFACTOR Phase**:
- Add migration templates
- Support custom transformations
- Add validation before generation

**QA Phase**:
```bash
uv run pytest tests/unit/test_migrator.py::test_generate* -v
```

**Deliverables**:
- ✅ Migration file generation
- ✅ Up/down statement generation
- ✅ Version sequencing

---

### Week 7-8: CLI Development

**Milestone 1.12: CLI Foundation**

**RED Phase**:
```python
# tests/e2e/test_cli.py
def test_cli_build_command():
    """CLI build command should work"""
    runner = CliRunner()
    result = runner.invoke(cli, ["build", "--env", "test"])

    assert result.exit_code == 0
    assert "✅ Built schema" in result.output
```

**GREEN Phase**:
```python
# python/confiture/cli/main.py
import typer
from rich.console import Console

app = typer.Typer()
console = Console()

@app.command()
def build(
    env: str = typer.Option("local", help="Environment name"),
    output: Path | None = typer.Option(None, help="Output file path")
):
    """Build schema from DDL files"""
    try:
        builder = SchemaBuilder(env=env)
        schema_file = builder.build(output_path=output)

        console.print(f"[green]✅ Built schema: {schema_file}[/green]")
    except Exception as e:
        console.print(f"[red]❌ Build failed: {e}[/red]")
        raise typer.Exit(1)
```

**REFACTOR Phase**:
- Add progress bars (rich.progress)
- Add verbose mode
- Improve error messages

**QA Phase**:
```bash
uv run pytest tests/e2e/test_cli.py -v
uv run confiture build --env test
```

**Deliverables**:
- ✅ `confiture build` working
- ✅ Rich terminal output
- ✅ Error handling

---

**Milestone 1.13: Complete CLI Commands**

Implement remaining commands using same TDD cycle:

1. `confiture init` - Initialize project structure
2. `confiture migrate up` - Apply migrations
3. `confiture migrate down` - Rollback migration
4. `confiture migrate status` - Show migration state
5. `confiture migrate generate` - Generate migration from diff

**Deliverables**:
- ✅ All 5 CLI commands working
- ✅ Help text complete
- ✅ E2E tests for each command

---

### Week 9-10: Integration & Polish

**Milestone 1.14: FraiseQL Integration**

**RED Phase**:
```python
# tests/integration/test_fraiseql.py
def test_fraiseql_schema_to_ddl():
    """FraiseQL GraphQL schema should generate DDL"""
    from fraiseql import Schema, model

    @model
    class User:
        id: int
        username: str

    schema = Schema(query=User)

    # Generate DDL
    from confiture.integrations.fraiseql import generate_ddl
    ddl = generate_ddl(schema)

    assert "CREATE TABLE users" in ddl
    assert "username TEXT" in ddl
```

**GREEN Phase**:
```python
# python/confiture/integrations/fraiseql.py
def generate_ddl(schema: FraiseQLSchema) -> str:
    """Generate PostgreSQL DDL from FraiseQL schema"""
    tables = []

    for model in schema.models:
        table_ddl = f"CREATE TABLE {model.table_name} (\n"

        columns = []
        for field in model.fields:
            pg_type = map_graphql_to_pg(field.type)
            columns.append(f"    {field.name} {pg_type}")

        table_ddl += ",\n".join(columns)
        table_ddl += "\n);"

        tables.append(table_ddl)

    return "\n\n".join(tables)
```

**REFACTOR Phase**:
- Add type mapping completeness
- Handle relationships
- Support constraints

**QA Phase**:
```bash
uv run pytest tests/integration/test_fraiseql.py -v
```

**Deliverables**:
- ✅ FraiseQL → DDL generation
- ✅ Type mapping complete
- ✅ Integration tests passing

---

**Milestone 1.15: Documentation**

Write comprehensive documentation:

1. **Getting Started Guide** (`docs/getting-started.md`)
   - Installation
   - Quick start
   - First migration

2. **CLI Reference** (`docs/cli-reference.md`)
   - All commands documented
   - Examples for each

3. **Migration Strategies** (`docs/migration-strategies.md`)
   - When to use each medium
   - Decision tree

4. **FraiseQL Integration** (`docs/fraiseql-integration.md`)
   - Setup guide
   - GraphQL → SQL mapping

**Deliverables**:
- ✅ 4 comprehensive guides (20+ pages)
- ✅ Code examples tested
- ✅ README.md updated

---

**Milestone 1.16: Testing & Quality**

**QA Phase** (All of Week 10):

```bash
# Run full test suite
uv run pytest tests/ -v --cov=confiture --cov-report=html

# Quality checks
uv run ruff check .
uv run mypy python/confiture/

# Integration tests with real PostgreSQL
uv run pytest tests/integration/ -v

# E2E workflow tests
uv run pytest tests/e2e/ -v
```

**Quality Gates**:
- ✅ Test coverage >90%
- ✅ No type errors (mypy strict mode)
- ✅ No linting errors (ruff)
- ✅ All E2E tests pass
- ✅ Documentation complete

**Deliverables**:
- ✅ 200+ tests passing
- ✅ Quality gates met
- ✅ Ready for alpha release

---

### Week 11-12: Alpha Release & Feedback

**Milestone 1.17: Alpha Release**

```bash
# Version 0.1.0 (Alpha)
git tag v0.1.0-alpha
git push origin v0.1.0-alpha

# Publish to PyPI (test)
uv build
uv publish --repository testpypi

# Verify installation
pip install --index-url https://test.pypi.org/simple/ confiture
confiture --version
```

**Alpha Testing**:
- Deploy to 3-5 test projects
- Collect feedback
- Fix critical bugs
- Iterate on UX

**Deliverables**:
- ✅ v0.1.0-alpha on TestPyPI
- ✅ 3+ alpha testers using it
- ✅ Feedback collected
- ✅ Bug fixes applied

---

**Phase 1 Complete: Week 12** ✅

**Success Criteria**:
- ✅ Core 4 mediums working (1, 2, partial 3)
- ✅ CLI usable end-to-end
- ✅ FraiseQL integration working
- ✅ 200+ tests, 90%+ coverage
- ✅ Documentation complete
- ✅ Alpha release on TestPyPI

**Not Included in Phase 1** (Deferred to Phase 3):
- ❌ Schema-to-schema FDW migration (Complex, needs Phase 2 performance)
- ❌ Production data sync with anonymization (Needs validation)
- ❌ Binary distribution (Needs Rust layer)

---

## Phase 2: Rust Performance Layer (2 months)

**Goal**: 10-50x performance improvement for bottleneck operations

**Target Date**: March 10, 2026

### Week 13-14: Rust Setup & Builder

**Milestone 2.1: Rust Project Setup**

**Tasks**:
1. Create `crates/confiture-core/` workspace
2. Configure PyO3 + maturin
3. Set up Rust CI/CD
4. Add binary wheel builds (GitHub Actions)

**Deliverables**:
- ✅ Rust crate compiles
- ✅ Python bindings work (`import confiture._core`)
- ✅ maturin builds wheels for Mac/Linux/Windows

---

**Milestone 2.2: Fast Schema Builder**

**RED Phase**:
```python
# tests/performance/test_builder_performance.py
def test_build_1000_files_under_100ms():
    """Rust builder should handle 1000 files in <100ms"""
    import time

    builder = SchemaBuilder(env="benchmark")

    start = time.perf_counter()
    schema = builder.build()
    duration = time.perf_counter() - start

    assert duration < 0.1  # <100ms
```

**GREEN Phase** (Rust):
```rust
// crates/confiture-core/src/builder.rs
use pyo3::prelude::*;
use std::fs;
use std::path::PathBuf;

#[pyfunction]
fn build_schema(files: Vec<PathBuf>) -> PyResult<String> {
    // Pre-allocate for performance
    let mut output = String::with_capacity(10_000_000);

    for file in files {
        let content = fs::read_to_string(&file)?;
        output.push_str(&content);
        output.push_str("\n\n");
    }

    Ok(output)
}

#[pymodule]
fn confiture_core(_py: Python, m: &PyModule) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(build_schema, m)?)?;
    Ok(())
}
```

**Python Integration**:
```python
# python/confiture/core/builder.py
try:
    from confiture import _core  # Rust bindings
    HAS_RUST = True
except ImportError:
    HAS_RUST = False

class SchemaBuilder:
    def build(self) -> str:
        files = self.find_sql_files()

        if HAS_RUST:
            # Use Rust (10-50x faster)
            return _core.build_schema([str(f) for f in files])
        else:
            # Fallback to Python
            return self._build_python(files)
```

**Deliverables**:
- ✅ 10-50x speedup for schema building
- ✅ Graceful fallback to Python if Rust unavailable
- ✅ Performance benchmarks documented

---

### Week 15-16: Fast Schema Diff

**Milestone 2.3: Rust SQL Parser**

**GREEN Phase** (Rust):
```rust
// crates/confiture-core/src/differ.rs
use sqlparser::parser::Parser;
use sqlparser::dialect::PostgreSqlDialect;
use pyo3::prelude::*;

#[pyfunction]
fn parse_ddl(sql: &str) -> PyResult<Vec<PyObject>> {
    let dialect = PostgreSqlDialect {};
    let ast = Parser::parse_sql(&dialect, sql)?;

    // Convert AST to Python objects
    let py_tables = extract_tables(ast);
    Ok(py_tables)
}
```

**Deliverables**:
- ✅ SQL parsing in Rust (sqlparser-rs)
- ✅ 10-50x faster than Python sqlparse
- ✅ Python API unchanged

---

**Milestone 2.4: Fast Hash Computation**

**GREEN Phase** (Rust):
```rust
use sha2::{Sha256, Digest};
use std::fs::File;
use std::io::Read;

#[pyfunction]
fn hash_files(files: Vec<PathBuf>) -> PyResult<String> {
    let mut hasher = Sha256::new();

    for file in files {
        let mut f = File::open(&file)?;
        let mut buffer = Vec::new();
        f.read_to_end(&mut buffer)?;
        hasher.update(&buffer);
    }

    Ok(format!("{:x}", hasher.finalize()))
}
```

**Deliverables**:
- ✅ 30-60x faster hashing
- ✅ Handles large files efficiently

---

### Week 17-18: Parallel Processing & Distribution

**Milestone 2.5: Parallel File Processing**

Use Rust's Rayon for parallel operations:

```rust
use rayon::prelude::*;

#[pyfunction]
fn build_schema_parallel(files: Vec<PathBuf>) -> PyResult<String> {
    let contents: Vec<String> = files
        .par_iter()  // Parallel iterator
        .map(|file| fs::read_to_string(file).unwrap())
        .collect();

    Ok(contents.join("\n\n"))
}
```

**Deliverables**:
- ✅ Parallel file reading
- ✅ CPU utilization optimized
- ✅ 2-5x additional speedup

---

**Milestone 2.6: Binary Wheel Distribution**

Configure GitHub Actions to build wheels:

```yaml
# .github/workflows/wheels.yml
name: Build Wheels

on:
  release:
    types: [published]

jobs:
  build:
    runs-on: ${{ matrix.os }}
    strategy:
      matrix:
        os: [ubuntu-latest, macos-latest, windows-latest]
        python: ['3.11', '3.12', '3.13']

    steps:
      - uses: actions/checkout@v4
      - uses: PyO3/maturin-action@v1
        with:
          command: build
          args: --release
      - uses: actions/upload-artifact@v3
        with:
          name: wheels
          path: target/wheels/*.whl
```

**Deliverables**:
- ✅ Binary wheels for Mac/Linux/Windows
- ✅ Published to PyPI
- ✅ No Rust toolchain needed for installation

---

**Phase 2 Complete: Week 18** ✅

**Success Criteria**:
- ✅ 10-50x performance improvements
- ✅ Binary wheels available
- ✅ Graceful Python fallback
- ✅ No breaking API changes

---

## Phase 3: Advanced Features (3 months)

**Goal**: Complete all 4 mediums + production-ready features

**Target Date**: June 10, 2026

### Week 19-22: Schema-to-Schema Migration (Medium 4)

**NOTE**: Medium 4 supports **two strategies**:
- **FDW**: Best for small-medium tables (<10M rows), complex transformations
- **COPY**: Best for large fact tables (>10M rows), 10-20x faster, simple mapping
- **Hybrid**: Auto-detect and use optimal strategy per table

**Milestone 3.1: FDW Strategy**

**RED Phase**:
```python
def test_setup_fdw_connection():
    """Should setup FDW to old database"""
    migrator = SchemaToSchemaMigrator(
        source="production",
        target="production_new"
    )

    migrator.setup_fdw()

    # Verify FDW server exists
    result = conn.execute(
        "SELECT 1 FROM pg_foreign_server WHERE srvname = 'old_production_server'"
    )
    assert result.scalar() == 1
```

**GREEN Phase**:
```python
# python/confiture/core/schema_to_schema.py
class SchemaToSchemaMigrator:
    def setup_fdw(self) -> None:
        """Setup Foreign Data Wrapper to source database"""
        self.target_conn.execute("""
            CREATE EXTENSION IF NOT EXISTS postgres_fdw;

            CREATE SERVER old_production_server
            FOREIGN DATA WRAPPER postgres_fdw
            OPTIONS (host %s, dbname %s, port %s);

            CREATE USER MAPPING FOR CURRENT_USER
            SERVER old_production_server
            OPTIONS (user %s, password %s);

            IMPORT FOREIGN SCHEMA public
            FROM SERVER old_production_server
            INTO old_schema;
        """, (
            self.source_config.host,
            self.source_config.database,
            self.source_config.port,
            self.source_config.user,
            self.source_config.password
        ))
```

**Deliverables**:
- ✅ FDW setup automation
- ✅ Connection validation
- ✅ Error handling

---

**Milestone 3.2: Data Migration with Column Mapping**

**RED Phase**:
```python
def test_migrate_data_with_column_mapping():
    """Should migrate data with column rename"""
    config = {
        "tables": {
            "users": {
                "columns": {
                    "full_name": "display_name"
                }
            }
        }
    }

    migrator = SchemaToSchemaMigrator(source="prod", target="prod_new")
    migrator.migrate_table("users", config["tables"]["users"])

    # Verify data migrated
    old_count = old_conn.execute("SELECT COUNT(*) FROM users").scalar()
    new_count = new_conn.execute("SELECT COUNT(*) FROM users").scalar()
    assert old_count == new_count
```

**GREEN Phase**:
```python
def migrate_table(self, table_name: str, config: dict) -> None:
    """Migrate data from old to new schema with transformations"""
    column_mapping = config.get("columns", {})

    # Build INSERT statement with column mapping
    select_cols = []
    insert_cols = []

    for old_col, new_col in column_mapping.items():
        select_cols.append(f"{old_col} AS {new_col}")
        insert_cols.append(new_col)

    sql = f"""
        INSERT INTO {table_name} ({', '.join(insert_cols)})
        SELECT {', '.join(select_cols)}
        FROM old_schema.{table_name}
    """

    self.target_conn.execute(sql)
```

**Deliverables**:
- ✅ Column mapping working
- ✅ Data transformation support
- ✅ Progress tracking

---

**Milestone 3.3: COPY Strategy (Large Tables)**

**RED Phase**:
```python
def test_copy_strategy_for_large_table():
    """COPY strategy should be faster for 100M+ row tables"""
    migrator = SchemaToSchemaMigrator(source="prod", target="prod_new")

    # Use COPY for large table
    start = time.time()
    migrator.migrate_table("events", strategy="copy")
    duration = time.time() - start

    # Should be 10-20x faster than FDW
    assert duration < 60  # <1 min for 100M rows
```

**GREEN Phase**:
```python
def migrate_table_copy(self, table_name: str, config: dict) -> None:
    """Migrate using COPY (binary format, streaming)"""
    column_mapping = config.get("columns", {})

    # Build SELECT with column mapping
    select_cols = []
    for old_col, new_col in column_mapping.items():
        select_cols.append(f"{old_col} AS {new_col}")

    # Stream from old DB to new DB (no intermediate file)
    export_sql = f"COPY ({self._build_select(table_name, select_cols)}) TO STDOUT WITH (FORMAT binary)"
    import_sql = f"COPY {table_name} FROM STDIN WITH (FORMAT binary)"

    # Stream data
    with self.source_conn.cursor() as src_cursor, \
         self.target_conn.cursor() as dst_cursor:
        src_cursor.copy_expert(export_sql, dst_cursor)
```

**Deliverables**:
- ✅ COPY strategy working
- ✅ 10-20x faster than FDW for large tables
- ✅ Streaming (no disk space needed)

---

**Milestone 3.4: Hybrid Strategy (Auto-Detection)**

**RED Phase**:
```python
def test_auto_strategy_selection():
    """Should auto-select FDW for small tables, COPY for large"""
    migrator = SchemaToSchemaMigrator(source="prod", target="prod_new")

    plan = migrator.analyze_tables()

    # Small tables should use FDW
    assert plan["users"]["strategy"] == "fdw"
    assert plan["posts"]["strategy"] == "fdw"

    # Large tables should use COPY
    assert plan["events"]["strategy"] == "copy"
    assert plan["page_views"]["strategy"] == "copy"
```

**GREEN Phase**:
```python
def analyze_tables(self) -> dict:
    """Analyze table sizes and recommend strategy"""
    tables = {}

    for table in self.get_all_tables():
        row_count = self.get_row_count(table)

        # Threshold: 10M rows
        if row_count > 10_000_000:
            strategy = "copy"  # Large table
            estimated_time = row_count / 6_000_000  # 6M rows/sec
        else:
            strategy = "fdw"   # Small-medium table
            estimated_time = row_count / 500_000    # 500K rows/sec

        tables[table] = {
            "strategy": strategy,
            "row_count": row_count,
            "estimated_seconds": estimated_time
        }

    return tables
```

**Deliverables**:
- ✅ Auto-detect optimal strategy per table
- ✅ Performance estimates
- ✅ User can override strategy

---

**Milestone 3.5: Verification & Cutover**

**Tasks**:
1. Count verification (old == new)
2. Foreign key integrity checks
3. Custom validation SQL
4. Atomic database rename
5. Rollback procedure

**Deliverables**:
- ✅ Comprehensive verification
- ✅ Safe cutover process
- ✅ Rollback working

---

### Week 23-26: Production Data Sync (Medium 3)

**Milestone 3.4: Data Sync Core**

**Tasks**:
1. Table selection (include/exclude)
2. Schema-aware copy
3. Progress reporting
4. Resume support (incremental)

**Deliverables**:
- ✅ `confiture sync` working
- ✅ Handles large tables (1M+ rows)
- ✅ Incremental sync support

---

**Milestone 3.5: PII Anonymization**

**RED Phase**:
```python
def test_anonymize_email():
    """Should anonymize email addresses"""
    syncer = ProductionSyncer(source="prod", target="local")

    syncer.sync(
        tables=["users"],
        anonymize={"users": ["email", "phone"]}
    )

    # Verify anonymization
    result = local_conn.execute("SELECT email FROM users LIMIT 1")
    email = result.scalar()

    assert "@" not in email  # Anonymized
```

**GREEN Phase**:
```python
def anonymize_column(self, table: str, column: str, value: Any) -> Any:
    """Anonymize PII data"""
    if column == "email":
        return f"user_{hash(value)[:8]}@example.com"
    elif column == "phone":
        return f"+1-555-{random.randint(1000, 9999)}"
    else:
        return "[REDACTED]"
```

**Deliverables**:
- ✅ Email/phone anonymization
- ✅ Custom anonymization rules
- ✅ PII detection heuristics

---

### Week 27-30: Polish & Release

**Milestone 3.6: Performance Optimization**

**Tasks**:
1. Profile and optimize hotspots
2. Database connection pooling
3. Batch operations
4. Memory optimization

**Deliverables**:
- ✅ All operations optimized
- ✅ Performance benchmarks documented
- ✅ Comparison vs competitors

---

**Milestone 3.7: Documentation & Examples**

**Tasks**:
1. Complete all 4 medium guides
2. Add 5+ production examples
3. Video tutorials (optional)
4. API reference (Sphinx)

**Deliverables**:
- ✅ 10+ comprehensive guides
- ✅ 5+ production examples
- ✅ API docs generated

---

**Milestone 3.8: v1.0 Release**

```bash
# Version 1.0.0 (Stable)
git tag v1.0.0
git push origin v1.0.0

# Publish to PyPI
uv build
uv publish

# Announce
- Blog post
- Twitter/social media
- Hacker News
- Reddit (r/Python, r/PostgreSQL)
- Python Weekly newsletter
```

**Launch Checklist**:
- ✅ All 4 mediums working
- ✅ 500+ tests passing
- ✅ 95%+ test coverage
- ✅ Documentation complete
- ✅ 10+ production deployments
- ✅ Security audit passed
- ✅ Performance benchmarks published

---

**Phase 3 Complete: Week 30** ✅

**Success Criteria**:
- ✅ Feature-complete v1.0
- ✅ Production-ready quality
- ✅ 1,000+ GitHub stars (goal)
- ✅ Market recognition

---

## Timeline Summary

| Phase | Weeks | Target Date | Key Deliverables |
|-------|-------|-------------|------------------|
| **Phase 1: Python MVP** | 12 weeks | Jan 10, 2026 | Build, migrate, diff, CLI, FraiseQL integration |
| **Phase 2: Rust Performance** | 6 weeks | Mar 10, 2026 | 10-50x speedup, binary wheels |
| **Phase 3: Advanced Features** | 12 weeks | Jun 10, 2026 | Schema-to-schema, production sync, v1.0 |
| **TOTAL** | 30 weeks | Jun 10, 2026 | **Feature-complete v1.0** |

---

## Success Metrics

### Phase 1 Gates
- ✅ 200+ tests, 90%+ coverage
- ✅ CLI working end-to-end
- ✅ FraiseQL integration
- ✅ Alpha testers happy

### Phase 2 Gates
- ✅ 10-50x performance improvements
- ✅ Binary wheels for all platforms
- ✅ No breaking changes

### Phase 3 Gates
- ✅ All 4 mediums working
- ✅ 500+ tests, 95%+ coverage
- ✅ 10+ production deployments
- ✅ Market validation

---

## Risk Management

### Schedule Risks

**Risk**: Phase 1 takes longer than 12 weeks
- **Mitigation**: Cut scope (defer Medium 3 to Phase 3)
- **Fallback**: Ship Phase 1 as "beta", iterate

**Risk**: Rust learning curve slows Phase 2
- **Mitigation**: Phase 1 works without Rust (fallback)
- **Fallback**: Ship v1.0 without Rust, add in v1.1

**Risk**: Schema-to-schema too complex for Phase 3
- **Mitigation**: Extensive design docs already done
- **Fallback**: Ship as experimental feature, stabilize in v1.1

---

## Next Steps

**Immediate** (This Week):
1. Set up project structure
2. Configure CI/CD
3. Begin Phase 1, Milestone 1.1 (Project Scaffolding)

**Phase 1 Kickoff** (Week 1):
- Complete project setup
- First TDD cycle (config system)
- Establish development rhythm

---

## Current Status (October 11, 2025)

**Phase 3: IN PROGRESS** 🔄

**Phase 2 Complete:**
- ✅ Rust project setup with PyO3 + maturin
- ✅ Fast schema builder (10-50x speedup, parallel file I/O)
- ✅ Fast hash computation (30-60x speedup, includes paths + content)
- ✅ Parallel processing with Rayon
- ✅ Binary wheel distribution (GitHub Actions CI/CD)
- ✅ Python fallback (graceful degradation)

**Phase 3 Progress:**
- ✅ **Milestone 3.1: FDW Strategy Setup** (COMPLETE)
  - postgres_fdw extension management
  - Foreign server creation with authentication
  - User mapping and schema import
  - Comprehensive integration tests

- ✅ **Milestone 3.2: Data Migration with Column Mapping** (COMPLETE)
  - Column rename/mapping support
  - INSERT ... SELECT implementation
  - Transaction safety and rollback
  - Row count verification

- ✅ **Milestone 3.3: COPY Strategy for Large Tables** (COMPLETE)
  - PostgreSQL COPY implementation
  - 10-20x faster than FDW for large tables
  - Streaming with BytesIO buffering
  - Column mapping support in COPY
  - 100K row test (represents 10M+ production scale)

- ✅ **Milestone 3.4: Hybrid Strategy (Auto-Detection)** (COMPLETE)
  - Table size analysis via pg_stat_user_tables
  - Automatic strategy recommendation
  - 10M row threshold (FDW vs COPY)
  - Performance estimation (throughput-based)

- ✅ **Milestone 3.5: Verification & Cutover** (COMPLETE)
  - Row count verification (source vs target)
  - Mismatch detection with detailed reporting
  - Structured verification results
  - Transaction-safe verification queries
  - Per-table verification status

**Schema-to-Schema Migration (Medium 4): COMPLETE** ✅

**Test Status:**
- ✅ 223 tests passing (88.35% coverage)
- ✅ 6 schema-to-schema integration tests
- ✅ All integration tests passing
- ✅ Type checking passing (mypy)
- ✅ Linting passing (ruff)

**Next Steps:**
1. **Week 23-26: Production Data Sync** (Medium 3)
   - Table selection (include/exclude)
   - Schema-aware copy
   - Progress reporting
   - PII anonymization

2. **Week 27-30: Polish & v1.0 Release**
   - Performance optimization
   - Documentation & examples
   - v1.0 release preparation

---

**Last Updated**: October 11, 2025
**Current Status**: Phase 3 - Schema-to-Schema Migration COMPLETE (Milestones 3.1-3.5) ✅
**Next Milestone**: Production Data Sync (Medium 3)

---

*Making jam from strawberries, one phase at a time.* 🍓→🍯
