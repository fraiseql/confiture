# Phase 4.2.2: Schema Linting Implementation Plan

**Status**: Ready to Start (Phase 4.2.1 Complete ✅)
**Date**: 2025-12-26
**Total Effort**: 16-18 hours (estimated)
**Approach**: TDD (RED → GREEN → REFACTOR → QA)
**Duration**: 3-4 working days

---

## Executive Summary

Phase 4.2.2 implements **Schema Linting**, a critical quality gate for database migrations. This feature enables teams to:

- **Enforce Naming Conventions** (snake_case for tables/columns)
- **Require Primary Keys** (data integrity)
- **Mandate Documentation** (operational knowledge)
- **Enforce Multi-Tenant Patterns** (data isolation)
- **Detect Missing Indexes** (performance)
- **Validate Security Practices** (password handling, etc.)

Linting is a **self-contained feature** that doesn't depend on Phase 4.2.3 (Interactive Wizard), so it can be developed in parallel.

---

## Phase 4.2.2 Scope

### What We're Building

```
confiture lint [--config confiture.yaml] [--schema db/schema/]
┌─────────────────────────────────────────────────────────────┐
│ NamingConventionRule      → "users" vs "user_table"          │
│ PrimaryKeyRule            → All tables need PRIMARY KEY       │
│ DocumentationRule         → All tables need COMMENT           │
│ MultiTenantRule           → tenant_id in multi-tenant tables  │
│ MissingIndexRule          → FK columns should be indexed      │
│ SecurityRule              → No plain passwords, use secrets   │
│                                                               │
│ OUTPUT: LintReport with violations grouped by severity       │
└─────────────────────────────────────────────────────────────┘
```

### Three Configuration Levels

**1. Built-in (No Config Needed)**:
```bash
confiture lint  # Uses sensible defaults
```

**2. Project Config (confiture.yaml)**:
```yaml
linting:
  rules:
    naming_convention:
      enabled: true
      style: snake_case
    primary_key:
      enabled: true
    multi_tenant:
      enabled: true
      identifier: tenant_id
```

**3. Programmatic**:
```python
linter = SchemaLinter(env="local", config=LintConfig(...))
report = linter.lint()
```

---

## Architecture Overview

### Data Flow

```
┌──────────────────────────────────────────────────────────────┐
│ SchemaBuilder.build_schema()                                 │
│ ↓                                                            │
│ Parse DDL → Tables, Columns, Indexes, Constraints          │
│ ↓                                                            │
│ SchemaLinter.lint()                                          │
│ ├── Execute each LintRule                                    │
│ ├── Collect Violations                                       │
│ └── Return LintReport                                        │
│ ↓                                                            │
│ LintReport (violations grouped by rule & severity)          │
│ ├── ERRORS (must fix before migration)                      │
│ ├── WARNINGS (should fix, optional)                         │
│ └── INFO (informational only)                               │
└──────────────────────────────────────────────────────────────┘
```

### Module Organization

```
python/confiture/
├── core/
│   └── linting.py          # SchemaLinter, LintRule, 6 built-in rules
│
├── models/
│   └── lint.py             # LintConfig, Violation, LintReport
│
└── cli/
    └── main.py             # Add 'lint' command

tests/
├── unit/
│   └── test_linting.py     # 40+ unit tests
│
└── integration/
    └── test_linting_rules.py  # 15+ database-dependent tests
```

---

## Step 1: Create Linting Models (Data Structures)

### File: `python/confiture/models/lint.py`

This file defines the data structures for linting configuration and results.

#### Models to Implement

**1. LintSeverity** (Enum):
```python
class LintSeverity(str, Enum):
    ERROR = "error"      # Must fix before migration
    WARNING = "warning"  # Should fix, but optional
    INFO = "info"        # Informational
```

**2. Violation** (Dataclass):
```python
@dataclass
class Violation:
    rule_name: str        # e.g., "NamingConventionRule"
    severity: LintSeverity
    message: str          # Human-readable message
    location: str         # Table name, column, etc.
    suggested_fix: str | None = None  # How to fix

    def __str__(self) -> str:
        return f"[{self.severity.upper()}] {self.location}: {self.message}"
```

**3. LintRuleConfig** (TypedDict):
```python
LintRuleConfig = dict[str, Any]

# Example usage:
# config = {
#     "naming_convention": {"style": "snake_case"},
#     "multi_tenant": {"identifier": "tenant_id"},
# }
```

**4. LintConfig** (Dataclass):
```python
@dataclass
class LintConfig:
    """Configuration for schema linting."""

    enabled: bool = True
    rules: dict[str, LintRuleConfig] = field(default_factory=dict)
    fail_on_error: bool = True   # Exit with error if violations found
    fail_on_warning: bool = False  # Stricter mode
    exclude_tables: list[str] = field(default_factory=list)

    @classmethod
    def from_yaml(cls, path: Path) -> "LintConfig":
        """Load from confiture.yaml linting section."""
        ...

    @classmethod
    def default(cls) -> "LintConfig":
        """Sensible defaults for all rules."""
        return cls(
            rules={
                "naming_convention": {"style": "snake_case"},
                "primary_key": {"enabled": True},
                "documentation": {"enabled": True},
                "multi_tenant": {"identifier": "tenant_id"},
                "missing_index": {"enabled": True},
                "security": {"enabled": True},
            }
        )
```

**5. LintReport** (Dataclass):
```python
@dataclass
class LintReport:
    """Results of a linting pass."""

    violations: list[Violation]
    schema_name: str
    tables_checked: int
    columns_checked: int
    errors_count: int
    warnings_count: int
    info_count: int
    execution_time_ms: int

    @property
    def has_errors(self) -> bool:
        return self.errors_count > 0

    @property
    def has_warnings(self) -> bool:
        return self.warnings_count > 0

    def violations_by_severity(self) -> dict[LintSeverity, list[Violation]]:
        """Group violations by severity."""
        grouped = {}
        for severity in LintSeverity:
            grouped[severity] = [
                v for v in self.violations
                if v.severity == severity
            ]
        return grouped

    def __str__(self) -> str:
        """Format report for CLI output."""
        # Return formatted report with tables, colors, etc.
        ...
```

#### Tests for Models

**File: `tests/unit/test_linting_models.py`**

```python
def test_violation_creation():
    """Violation should store all information."""
    violation = Violation(
        rule_name="NamingConventionRule",
        severity=LintSeverity.ERROR,
        message="Table 'UserTable' should be 'user_table'",
        location="UserTable",
        suggested_fix="Rename to 'user_table'"
    )
    assert violation.rule_name == "NamingConventionRule"
    assert violation.severity == LintSeverity.ERROR

def test_lint_config_default():
    """LintConfig.default() should have all rules."""
    config = LintConfig.default()
    assert "naming_convention" in config.rules
    assert "primary_key" in config.rules
    # ... etc for all 6 rules

def test_lint_report_grouping():
    """LintReport should group violations by severity."""
    violations = [
        Violation(..., severity=LintSeverity.ERROR, ...),
        Violation(..., severity=LintSeverity.WARNING, ...),
    ]
    report = LintReport(violations=violations, ...)
    grouped = report.violations_by_severity()
    assert len(grouped[LintSeverity.ERROR]) == 1
    assert len(grouped[LintSeverity.WARNING]) == 1
```

---

## Step 2: Implement SchemaLinter and LintRule Base Class

### File: `python/confiture/core/linting.py`

This is the core orchestrator and abstract base for linting rules.

#### Base Classes

**1. LintRule** (Abstract Base):
```python
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from confiture.models.lint import Violation, LintRuleConfig

class LintRule(ABC):
    """Abstract base for all lint rules."""

    name: str  # e.g., "NamingConventionRule"
    description: str  # "Enforces snake_case naming"
    enabled_by_default: bool = True

    @abstractmethod
    def lint(
        self,
        tables: list[Table],
        config: LintRuleConfig
    ) -> list[Violation]:
        """
        Analyze tables and return violations found.

        Args:
            tables: List of parsed Table objects (from SchemaDiffer)
            config: Rule-specific configuration

        Returns:
            List of violations found
        """
        ...
```

**2. SchemaLinter** (Orchestrator):
```python
class SchemaLinter:
    """Main schema linter orchestrator."""

    def __init__(
        self,
        env: str,
        config: LintConfig | None = None,
        conn: psycopg.Connection | None = None
    ):
        self.env = env
        self.config = config or LintConfig.default()
        self.conn = conn
        self.builder = SchemaBuilder(env)
        self.differ = SchemaDiffer()
        self._register_rules()

    def _register_rules(self) -> None:
        """Register all built-in rules."""
        self.rules: dict[str, LintRule] = {
            "naming_convention": NamingConventionRule(),
            "primary_key": PrimaryKeyRule(),
            "documentation": DocumentationRule(),
            "multi_tenant": MultiTenantRule(),
            "missing_index": MissingIndexRule(),
            "security": SecurityRule(),
        }

    def lint(self) -> LintReport:
        """Run all enabled rules and return report."""
        start_time = time.time()

        # Build schema
        schema_content = self.builder.build()
        tables = self.differ.parse_sql(schema_content)

        # Filter excluded tables
        tables = [
            t for t in tables
            if t.name not in self.config.exclude_tables
        ]

        # Execute each rule
        all_violations = []
        for rule_name, rule in self.rules.items():
            if rule_name not in self.config.rules:
                continue  # Skip if not in config

            rule_config = self.config.rules[rule_name]
            violations = rule.lint(tables, rule_config)
            all_violations.extend(violations)

        # Build report
        errors = [v for v in all_violations if v.severity == LintSeverity.ERROR]
        warnings = [v for v in all_violations if v.severity == LintSeverity.WARNING]
        infos = [v for v in all_violations if v.severity == LintSeverity.INFO]

        execution_time_ms = int((time.time() - start_time) * 1000)

        return LintReport(
            violations=all_violations,
            schema_name=self.env,
            tables_checked=len(tables),
            columns_checked=sum(len(t.columns) for t in tables),
            errors_count=len(errors),
            warnings_count=len(warnings),
            info_count=len(infos),
            execution_time_ms=execution_time_ms,
        )
```

#### Tests

**File: `tests/unit/test_linting_core.py`**

```python
def test_schema_linter_initialization():
    """SchemaLinter should initialize with default config."""
    linter = SchemaLinter(env="test")
    assert linter.config is not None
    assert len(linter.rules) == 6  # All 6 rules registered

def test_schema_linter_lint():
    """SchemaLinter.lint() should return LintReport."""
    linter = SchemaLinter(env="test")
    report = linter.lint()

    assert isinstance(report, LintReport)
    assert report.tables_checked > 0
    assert report.execution_time_ms > 0

def test_schema_linter_excluded_tables():
    """SchemaLinter should skip excluded tables."""
    config = LintConfig.default()
    config.exclude_tables = ["pg_*", "information_schema.*"]

    linter = SchemaLinter(env="test", config=config)
    report = linter.lint()

    # Should not check excluded tables
    assert all(t not in [v.location for v in report.violations]
               for t in config.exclude_tables)
```

---

## Step 3: Implement 6 Built-in Linting Rules

All rules in `python/confiture/core/linting.py` (same file as SchemaLinter).

### Rule 1: NamingConventionRule

```python
class NamingConventionRule(LintRule):
    """Enforce snake_case for tables and columns."""

    name = "NamingConventionRule"
    description = "Enforces snake_case naming for tables and columns"

    def lint(self, tables: list[Table], config: dict) -> list[Violation]:
        violations = []
        style = config.get("style", "snake_case")

        for table in tables:
            # Check table name
            if not self._is_valid_name(table.name, style):
                violations.append(Violation(
                    rule_name=self.name,
                    severity=LintSeverity.ERROR,
                    message=f"Table '{table.name}' should use {style}",
                    location=f"Table: {table.name}",
                    suggested_fix=self._suggest_name(table.name, style)
                ))

            # Check column names
            for column in table.columns:
                if not self._is_valid_name(column.name, style):
                    violations.append(Violation(
                        rule_name=self.name,
                        severity=LintSeverity.ERROR,
                        message=f"Column '{column.name}' should use {style}",
                        location=f"{table.name}.{column.name}",
                        suggested_fix=self._suggest_name(column.name, style)
                    ))

        return violations

    def _is_valid_name(self, name: str, style: str) -> bool:
        """Check if name matches style."""
        if style == "snake_case":
            # Allow [a-z0-9_]
            return bool(re.match(r'^[a-z][a-z0-9_]*$', name))
        return True

    def _suggest_name(self, name: str, style: str) -> str:
        """Suggest fixed name."""
        if style == "snake_case":
            # Convert camelCase/PascalCase to snake_case
            # UserTable → user_table
            import re
            s1 = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', name)
            return re.sub('([a-z0-9])([A-Z])', r'\1_\2', s1).lower()
        return name
```

### Rule 2: PrimaryKeyRule

```python
class PrimaryKeyRule(LintRule):
    """Ensure all tables have a primary key."""

    name = "PrimaryKeyRule"
    description = "Ensures all tables have a PRIMARY KEY"

    def lint(self, tables: list[Table], config: dict) -> list[Violation]:
        violations = []

        for table in tables:
            # Skip system tables
            if table.name.startswith("pg_"):
                continue

            # Check if table has primary key
            has_pk = any(c.is_primary_key for c in table.columns)

            if not has_pk:
                violations.append(Violation(
                    rule_name=self.name,
                    severity=LintSeverity.ERROR,
                    message=f"Table '{table.name}' missing PRIMARY KEY",
                    location=f"Table: {table.name}",
                    suggested_fix="Add PRIMARY KEY constraint"
                ))

        return violations
```

### Rule 3: DocumentationRule

```python
class DocumentationRule(LintRule):
    """Require COMMENT on all tables."""

    name = "DocumentationRule"
    description = "Requires COMMENT on all tables"

    def lint(self, tables: list[Table], config: dict) -> list[Violation]:
        violations = []

        for table in tables:
            # Skip system tables
            if table.name.startswith("pg_"):
                continue

            if not table.comment or not table.comment.strip():
                violations.append(Violation(
                    rule_name=self.name,
                    severity=LintSeverity.WARNING,
                    message=f"Table '{table.name}' missing documentation",
                    location=f"Table: {table.name}",
                    suggested_fix=(
                        f"Add: COMMENT ON TABLE {table.name} IS 'Description...'"
                    )
                ))

        return violations
```

### Rule 4: MultiTenantRule

```python
class MultiTenantRule(LintRule):
    """Enforce tenant_id in multi-tenant tables."""

    name = "MultiTenantRule"
    description = "Enforces tenant_id in multi-tenant tables"

    def lint(self, tables: list[Table], config: dict) -> list[Violation]:
        violations = []
        identifier = config.get("identifier", "tenant_id")

        # Multi-tenant tables (heuristic)
        multi_tenant_patterns = ["customers", "tenants", "organizations", "accounts"]

        for table in tables:
            # Check if table looks like it should be multi-tenant
            table_name_lower = table.name.lower()
            is_multi_tenant = any(
                pattern in table_name_lower
                for pattern in multi_tenant_patterns
            )

            if is_multi_tenant:
                # Check if tenant_id column exists
                has_tenant_id = any(
                    c.name == identifier for c in table.columns
                )

                if not has_tenant_id:
                    violations.append(Violation(
                        rule_name=self.name,
                        severity=LintSeverity.ERROR,
                        message=f"Multi-tenant table '{table.name}' missing '{identifier}'",
                        location=f"Table: {table.name}",
                        suggested_fix=f"Add column: {identifier} UUID REFERENCES tenants(id)"
                    ))

        return violations
```

### Rule 5: MissingIndexRule

```python
class MissingIndexRule(LintRule):
    """Warn about unindexed foreign key columns."""

    name = "MissingIndexRule"
    description = "Detects unindexed foreign keys"

    def lint(self, tables: list[Table], config: dict) -> list[Violation]:
        violations = []

        for table in tables:
            for column in table.columns:
                # Check if column is a foreign key
                if not column.is_foreign_key:
                    continue

                # Check if column is indexed
                is_indexed = any(
                    column.name in idx.columns
                    for idx in table.indexes
                )

                if not is_indexed:
                    violations.append(Violation(
                        rule_name=self.name,
                        severity=LintSeverity.WARNING,
                        message=f"Foreign key '{column.name}' should be indexed",
                        location=f"{table.name}.{column.name}",
                        suggested_fix=(
                            f"Add: CREATE INDEX ON {table.name}({column.name})"
                        )
                    ))

        return violations
```

### Rule 6: SecurityRule

```python
class SecurityRule(LintRule):
    """Validate security best practices."""

    name = "SecurityRule"
    description = "Checks for security best practices"

    def lint(self, tables: list[Table], config: dict) -> list[Violation]:
        violations = []

        for table in tables:
            for column in table.columns:
                # Check for "password" columns
                if "password" in column.name.lower():
                    # Should be hashed, not plain text
                    if column.column_type.upper() in ("VARCHAR", "TEXT"):
                        violations.append(Violation(
                            rule_name=self.name,
                            severity=LintSeverity.WARNING,
                            message=(
                                f"Column '{column.name}' may contain passwords - "
                                "should be hashed"
                            ),
                            location=f"{table.name}.{column.name}",
                            suggested_fix=(
                                "Use bcrypt/argon2 hashing, never store plain passwords"
                            )
                        ))

                # Check for "token" or "secret" columns
                if any(s in column.name.lower() for s in ["token", "secret", "key"]):
                    violations.append(Violation(
                        rule_name=self.name,
                        severity=LintSeverity.WARNING,
                        message=(
                            f"Column '{column.name}' contains sensitive data - "
                            "should be encrypted"
                        ),
                        location=f"{table.name}.{column.name}",
                        suggested_fix="Use encrypted column or external secrets manager"
                    ))

        return violations
```

#### Tests for Rules

**File: `tests/unit/test_linting_rules.py`**

```python
def test_naming_convention_rule():
    """NamingConventionRule should detect non-snake_case names."""
    rule = NamingConventionRule()

    # Create test tables
    tables = [
        Table(name="UserTable", columns=[
            Column(name="UserId", ...),
            Column(name="FullName", ...),
        ]),
    ]

    violations = rule.lint(tables, {"style": "snake_case"})

    # Should have violations for UserTable, UserId, FullName
    assert len(violations) == 3
    assert all(v.severity == LintSeverity.ERROR for v in violations)

def test_primary_key_rule():
    """PrimaryKeyRule should require PRIMARY KEY on all tables."""
    rule = PrimaryKeyRule()

    # Table without PK
    table_no_pk = Table(name="users", columns=[
        Column(name="name", ...),
    ])

    violations = rule.lint([table_no_pk], {})
    assert len(violations) == 1
    assert "PRIMARY KEY" in violations[0].message

def test_security_rule_password():
    """SecurityRule should warn about password columns."""
    rule = SecurityRule()

    table = Table(name="users", columns=[
        Column(name="password_hash", column_type="VARCHAR", ...),
    ])

    violations = rule.lint([table], {})
    assert len(violations) >= 1
    assert any("password" in v.message.lower() for v in violations)
```

---

## Step 4: Add CLI Command (`confiture lint`)

### File: Update `python/confiture/cli/main.py`

Add new command:

```python
@app.command()
def lint(
    config: Path = typer.Option(
        Path("confiture.yaml"),
        "--config",
        help="Path to lint configuration (default: confiture.yaml)"
    ),
    schema_dir: Path = typer.Option(
        Path("db/schema"),
        "--schema",
        help="Path to schema directory (default: db/schema)"
    ),
    env: str = typer.Option(
        "local",
        "--env",
        help="Environment name (local, staging, production)"
    ),
    format: str = typer.Option(
        "table",
        "--format",
        help="Output format: table, json, csv"
    ),
    fail_on_error: bool = typer.Option(
        True,
        "--fail-on-error",
        help="Exit with error if violations found"
    ),
    fail_on_warning: bool = typer.Option(
        False,
        "--fail-on-warning",
        help="Exit with error if warnings found"
    ),
):
    """Lint schema for best practices and consistency.

    Examples:
        confiture lint                    # Check using defaults
        confiture lint --env production   # Check production schema
        confiture lint --format json      # Output as JSON
    """
    try:
        # Load config if exists
        lint_config = LintConfig.default()
        if config.exists():
            lint_config = LintConfig.from_yaml(config)

        # Override from CLI flags
        lint_config.fail_on_error = fail_on_error
        lint_config.fail_on_warning = fail_on_warning

        # Create linter
        linter = SchemaLinter(env=env, config=lint_config)

        # Run linting
        console.print("Linting schema...", style="cyan")
        report = linter.lint()

        # Format output
        if format == "json":
            output = format_report_json(report)
        elif format == "csv":
            output = format_report_csv(report)
        else:  # table (default)
            output = format_report_table(report)

        console.print(output)

        # Summary
        console.print()
        console.print(f"Schema: {report.schema_name}")
        console.print(f"Tables checked: {report.tables_checked}")
        console.print(f"Errors: {report.errors_count} | Warnings: {report.warnings_count}")
        console.print(f"Time: {report.execution_time_ms}ms")

        # Exit code
        if report.has_errors and fail_on_error:
            console.print("[red]❌ Linting failed with errors[/red]")
            raise typer.Exit(1)
        elif report.has_warnings and fail_on_warning:
            console.print("[yellow]⚠️  Linting failed with warnings[/yellow]")
            raise typer.Exit(1)
        else:
            console.print("[green]✅ Linting passed[/green]")
            raise typer.Exit(0)

    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)
```

Helper functions for formatting:

```python
def format_report_table(report: LintReport) -> str:
    """Format report as rich table."""
    from rich.table import Table

    table = Table(title=f"Lint Report - {report.schema_name}")
    table.add_column("Rule", style="cyan")
    table.add_column("Location", style="magenta")
    table.add_column("Severity", style="yellow")
    table.add_column("Message")

    for violation in report.violations:
        severity_style = {
            "error": "red",
            "warning": "yellow",
            "info": "blue",
        }[violation.severity]

        table.add_row(
            violation.rule_name,
            violation.location,
            f"[{severity_style}]{violation.severity}[/{severity_style}]",
            violation.message
        )

    return table

def format_report_json(report: LintReport) -> str:
    """Format report as JSON."""
    import json

    data = {
        "schema": report.schema_name,
        "tables_checked": report.tables_checked,
        "errors": report.errors_count,
        "warnings": report.warnings_count,
        "violations": [
            {
                "rule": v.rule_name,
                "location": v.location,
                "severity": v.severity,
                "message": v.message,
                "suggested_fix": v.suggested_fix,
            }
            for v in report.violations
        ]
    }

    return json.dumps(data, indent=2)
```

---

## Step 5: Write Tests

### Unit Tests: `tests/unit/test_linting.py`

```python
# Test suite structure (40+ tests):
- test_linting_models.py (10 tests)
  - Violation creation and formatting
  - LintConfig defaults and from_yaml
  - LintReport grouping and properties

- test_linting_core.py (10 tests)
  - SchemaLinter initialization
  - SchemaLinter.lint() execution
  - SchemaLinter with custom config
  - Rule registration and enablement

- test_linting_rules.py (20+ tests)
  - NamingConventionRule (5 tests)
  - PrimaryKeyRule (3 tests)
  - DocumentationRule (3 tests)
  - MultiTenantRule (3 tests)
  - MissingIndexRule (3 tests)
  - SecurityRule (4 tests)
```

### Integration Tests: `tests/integration/test_linting_rules.py`

```python
# Database-dependent tests (15 tests):
- test_linting_real_schema (5 tests)
  - Run linting on actual test database
  - Verify violations match actual schema

- test_linting_with_config (5 tests)
  - Test config file loading
  - Test config overrides

- test_cli_lint_command (5 tests)
  - Test CLI command execution
  - Test CLI output formatting
```

---

## Step 6: Integration with CLI

The `confiture lint` command will:

1. Load configuration from `confiture.yaml` (if exists)
2. Override with CLI flags
3. Run SchemaLinter
4. Format output (table, JSON, CSV)
5. Exit with appropriate code

Example workflow:

```bash
# Check schema with defaults
$ confiture lint
✅ Linting passed

# Check with warnings as errors
$ confiture lint --fail-on-warning
❌ Linting failed with warnings

# Get JSON output for CI/CD
$ confiture lint --format json
{
  "schema": "local",
  "tables_checked": 42,
  "errors": 0,
  "warnings": 5,
  "violations": [...]
}

# Strict mode (fails on any issue)
$ confiture lint --fail-on-warning
```

---

## Step 7: Documentation

Create `docs/linting.md`:

1. **Quick Start** - Basic usage examples
2. **Configuration** - confiture.yaml format
3. **Rules Reference** - All 6 rules explained
4. **Custom Rules** - How to extend with own rules
5. **Integration** - CI/CD integration examples
6. **Troubleshooting** - Common issues and fixes

Example sections:

```markdown
## Configuration

confiture.yaml:
```yaml
linting:
  enabled: true
  fail_on_error: true
  fail_on_warning: false
  exclude_tables:
    - pg_*
    - information_schema.*

  rules:
    naming_convention:
      enabled: true
      style: snake_case

    primary_key:
      enabled: true

    documentation:
      enabled: true

    multi_tenant:
      enabled: true
      identifier: tenant_id

    missing_index:
      enabled: true

    security:
      enabled: true
```

## CI/CD Integration

GitHub Actions example:
```yaml
- name: Lint Database Schema
  run: confiture lint --format json > lint-report.json

- name: Check Linting Results
  if: failure()
  run: cat lint-report.json
```
```

---

## Implementation Sequence

### Phase 4.2.2 Timeline

| Day | Task | Hours | Files |
|-----|------|-------|-------|
| 1 | Models (Violation, LintConfig, LintReport) | 3 | models/lint.py |
| 1-2 | SchemaLinter + LintRule base | 3 | core/linting.py |
| 2-3 | Implement 6 rules | 5 | core/linting.py |
| 3 | CLI command + formatting | 2 | cli/main.py |
| 3-4 | Unit + integration tests | 4 | tests/unit/test_linting*.py, tests/integration/ |
| 4 | Documentation + examples | 2 | docs/linting.md |
| 4 | QA + cleanup | 1 | |
| **TOTAL** | | **16-18** | |

---

## TDD Workflow (RED → GREEN → REFACTOR → QA)

### Phase 4.2.2 Day 1: Models (RED → GREEN)

```bash
# RED: Write failing tests
$ uv run pytest tests/unit/test_linting_models.py -v
# FAILED: 10 tests

# GREEN: Implement models
# models/lint.py: Create Violation, LintConfig, LintReport

$ uv run pytest tests/unit/test_linting_models.py -v
# PASSED: 10 tests

# REFACTOR: Improve model code
# - Add __str__, __repr__
# - Add type hints
# - Add docstrings

$ uv run pytest tests/unit/test_linting_models.py -v
# PASSED: 10 tests (still passing)

# COMMIT
$ git add models/lint.py tests/unit/test_linting_models.py
$ git commit -m "feat: linting models (Violation, Config, Report) [GREEN]"
```

### Phase 4.2.2 Day 2: SchemaLinter + Rules

```bash
# RED: Write failing tests for SchemaLinter and rules
$ uv run pytest tests/unit/test_linting_core.py tests/unit/test_linting_rules.py -v
# FAILED: 30 tests

# GREEN: Implement SchemaLinter, LintRule, and 6 rules
# core/linting.py: Full implementation

$ uv run pytest tests/unit/test_linting_*.py -v
# PASSED: 30+ tests

# REFACTOR: Extract methods, improve code quality
$ uv run ruff check . --fix
$ uv run mypy confiture/core/linting.py

# COMMIT
$ git add confiture/core/linting.py tests/unit/test_linting*.py
$ git commit -m "feat: schema linting with 6 rules [GREEN]"
```

### Phase 4.2.2 Day 3: CLI + Tests

```bash
# Add CLI command
$ uv run pytest tests/integration/test_linting_rules.py -v
# PASSED: 15 tests

# Add documentation
$ uv run pytest --cov=confiture.core.linting --cov-report=html

# QA Phase: Full validation
$ uv run ruff check .
$ uv run mypy confiture/
$ uv run pytest --cov=confiture --cov-report=term-missing

# COMMIT
$ git add confiture/cli/main.py docs/linting.md tests/integration/
$ git commit -m "feat: confiture lint CLI command and documentation [QA]"
```

---

## Success Criteria

### Functionality ✅
- [x] All 6 linting rules implemented and working
- [x] SchemaLinter orchestrator handles all rules
- [x] LintConfig supports YAML loading and CLI overrides
- [x] `confiture lint` CLI command works
- [x] Output formats: table, JSON, CSV
- [x] Exit codes reflect severity (errors vs warnings)

### Code Quality ✅
- [x] 40+ unit tests passing
- [x] 15+ integration tests passing
- [x] Type hints on all code
- [x] Docstrings on public methods
- [x] ruff linting passes
- [x] mypy type checking passes
- [x] >85% coverage for new code

### Documentation ✅
- [x] User guide: docs/linting.md
- [x] Configuration examples in guide
- [x] All 6 rules explained with examples
- [x] CI/CD integration examples
- [x] Troubleshooting section

### Integration ✅
- [x] Works with existing SchemaBuilder
- [x] Works with existing SchemaDiffer
- [x] No breaking changes to Phase 4.1 code
- [x] Zero regressions in existing tests

---

## Risk Assessment

### Low Risk
- Linting rules are self-contained and isolated
- Each rule can be tested independently
- No changes to core migration logic
- Backward compatible (entirely new feature)

### Medium Risk
- SQL parsing accuracy depends on SchemaDiffer
- Multi-tenant detection is heuristic-based (may have false positives)
- Index detection requires accurate schema introspection

### Mitigation
- Extensive unit tests for each rule
- Integration tests with real database schemas
- Clear documentation on rule behavior and limitations
- Allow users to exclude specific tables/rules
- Provide fallback and override options

---

## Dependencies

**Phase 4.2.2 Requires**:
- ✅ Phase 4.1 complete (hooks, dry-run)
- ✅ SchemaBuilder for DDL parsing
- ✅ SchemaDiffer for schema analysis
- ✅ psycopg3 for database connection

**Phase 4.2.2 Does NOT Require**:
- ❌ Phase 4.2.3 (Interactive Wizard)
- ❌ Any new external dependencies
- ❌ Rust extensions

---

## Deliverables Summary

### New Files
1. **models/lint.py** - Data models (Violation, LintConfig, LintReport)
2. **core/linting.py** - SchemaLinter, LintRule, 6 rules
3. **tests/unit/test_linting.py** - 40+ unit tests
4. **tests/integration/test_linting_rules.py** - 15+ integration tests
5. **docs/linting.md** - User guide and reference

### Modified Files
1. **cli/main.py** - Add `lint` command
2. **README.md** - Add linting feature to feature list

### Total Lines of Code
- ~800 lines (models + rules + CLI)
- ~500 lines (tests)
- ~200 lines (documentation)

---

## Next Phase (Phase 4.2.3)

After Phase 4.2.2 is complete:
- Interactive Wizard implementation
- Risk assessment engine
- Migration preview features

These can be developed in parallel with minimal dependencies on Phase 4.2.2.

---

**Ready to start Phase 4.2.2. Linting foundation is well-architected. Let's build it.** 🍓

---

*Phase 4.2.2 Implementation Plan*
*Created: 2025-12-26*
*Status: Ready for Development*
