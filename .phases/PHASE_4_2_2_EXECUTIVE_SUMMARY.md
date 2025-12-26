# Phase 4.2.2: Schema Linting - Executive Summary

**Status**: 🎯 Ready to Implement
**Date**: 2025-12-26
**Duration**: 3-4 working days (16-18 hours)
**Complexity**: Medium (40 unit tests, 6 rules, CLI integration)

---

## What We're Building

**Schema Linting** - A comprehensive quality gate that automatically validates database schemas against best practices:

```
confiture lint
├─ ✅ Naming Convention (snake_case)
├─ ✅ Primary Key Requirement
├─ ✅ Documentation (COMMENT)
├─ ✅ Multi-Tenant Pattern (tenant_id)
├─ ✅ Index on Foreign Keys
└─ ✅ Security Practices (passwords, secrets)
```

---

## Why Phase 4.2.2 Matters

### The Problem
- **No Schema Quality Gate**: Teams can't enforce consistency across migrations
- **Silent Failures**: Best practices aren't checked before production
- **Security Gaps**: Passwords and secrets might be stored in plain text
- **Performance Issues**: Foreign keys without indexes go undetected

### The Solution
**Automated Linting** catches issues before they reach production:

```
❌ BEFORE: No checks
│ Migration created
│ ├─ [userTable] ← CamelCase name (bad)
│ ├─ Missing PRIMARY KEY (risky)
│ ├─ No documentation (operational debt)
│ └─ password column - no hashing (security risk)
│ ↓
│ Migration runs to production
│ ↓
│ [CRITICAL ISSUES DISCOVERED]

✅ AFTER: Automatic linting
│ User writes migration
│ ↓
│ confiture lint
│ ├─ ❌ ERROR: 'userTable' should be 'user_table'
│ ├─ ❌ ERROR: Table missing PRIMARY KEY
│ ├─ ⚠️  WARNING: Table missing documentation
│ └─ ⚠️  WARNING: 'password' column should be hashed
│ ↓
│ Migration stopped - issues fixed
│ ↓
│ confiture lint ✅
│ Migration runs to production safely
```

---

## Architecture Overview

### Three Components

```
┌─────────────────────────────────────────────────────────┐
│ 1. DATA MODELS (models/lint.py)                         │
│ ├─ Violation     ← Individual issue                     │
│ ├─ LintConfig    ← Configuration + rules to apply       │
│ └─ LintReport    ← Aggregated results                   │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│ 2. SCHEMA LINTING (core/linting.py)                     │
│ ├─ LintRule (abstract)     ← Base for all rules         │
│ ├─ SchemaLinter            ← Orchestrator               │
│ └─ 6 Built-in Rules:                                    │
│    ├─ NamingConventionRule                              │
│    ├─ PrimaryKeyRule                                    │
│    ├─ DocumentationRule                                 │
│    ├─ MultiTenantRule                                   │
│    ├─ MissingIndexRule                                  │
│    └─ SecurityRule                                      │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│ 3. CLI INTEGRATION (cli/main.py)                        │
│ └─ confiture lint [options]                             │
│    ├─ --config confiture.yaml (load rules)              │
│    ├─ --env production (which environment)              │
│    ├─ --format json|table|csv (output format)           │
│    └─ --fail-on-warning (exit code handling)            │
└─────────────────────────────────────────────────────────┘
```

### Data Flow

```
User writes DDL
    ↓
confiture lint --config confiture.yaml
    ↓
SchemaBuilder.build()  → DDL string
    ↓
SchemaDiffer.parse_sql()  → Tables, Columns, Indexes
    ↓
SchemaLinter.lint()
  ├─ Execute NamingConventionRule  → 3 violations
  ├─ Execute PrimaryKeyRule        → 1 violation
  ├─ Execute DocumentationRule     → 0 violations
  ├─ Execute MultiTenantRule       → 0 violations
  ├─ Execute MissingIndexRule      → 2 violations
  └─ Execute SecurityRule          → 1 violation
    ↓
LintReport (7 violations)
  ├─ ERRORS: 4
  ├─ WARNINGS: 3
  └─ INFO: 0
    ↓
CLI formats output (table, JSON, CSV)
    ↓
Exit code 1 (failures) / 0 (success)
```

---

## The 6 Linting Rules

### 1. NamingConventionRule

**Purpose**: Enforce consistent naming (snake_case)

**Examples**:
```python
# ❌ FAIL
CREATE TABLE UserTable (...)  # ← Should be user_table
  UserId INT,                  # ← Should be user_id
  FullName VARCHAR(255)       # ← Should be full_name

# ✅ PASS
CREATE TABLE users (
  user_id INT,
  full_name VARCHAR(255)
)
```

**Config**:
```yaml
rules:
  naming_convention:
    style: snake_case  # or: PascalCase, camelCase
```

---

### 2. PrimaryKeyRule

**Purpose**: Ensure data integrity with PRIMARY KEY

**Examples**:
```python
# ❌ FAIL
CREATE TABLE users (
  id INT,
  name VARCHAR(255)
)  # ← No PRIMARY KEY!

# ✅ PASS
CREATE TABLE users (
  id INT PRIMARY KEY,
  name VARCHAR(255)
)
```

**Rationale**: Every table needs a unique identifier for joins and updates.

---

### 3. DocumentationRule

**Purpose**: Require COMMENT on tables (operational knowledge)

**Examples**:
```python
# ❌ FAIL
CREATE TABLE users (
  id INT PRIMARY KEY,
  name VARCHAR(255)
);  # ← No documentation

# ✅ PASS
CREATE TABLE users (
  id INT PRIMARY KEY,
  name VARCHAR(255)
);
COMMENT ON TABLE users IS 'Registered users and their profiles';
```

**Rationale**: New developers/operators need to understand table purpose.

---

### 4. MultiTenantRule

**Purpose**: Enforce tenant isolation in multi-tenant tables

**Examples**:
```python
# ❌ FAIL
CREATE TABLE customers (
  id UUID PRIMARY KEY,
  name VARCHAR(255)
);  # ← Missing tenant_id! Data leak risk!

# ✅ PASS
CREATE TABLE customers (
  id UUID PRIMARY KEY,
  tenant_id UUID NOT NULL REFERENCES tenants(id),
  name VARCHAR(255)
);
```

**Rationale**: One of the most critical mistakes - accidental data leaks between tenants.

**Configuration**:
```yaml
rules:
  multi_tenant:
    identifier: tenant_id  # Which column name to check
```

---

### 5. MissingIndexRule

**Purpose**: Warn about unindexed foreign keys (performance)

**Examples**:
```python
# ⚠️  WARNING
CREATE TABLE orders (
  id INT PRIMARY KEY,
  customer_id INT REFERENCES customers(id)  # ← Should be indexed
);

# ✅ PASS
CREATE TABLE orders (
  id INT PRIMARY KEY,
  customer_id INT REFERENCES customers(id)
);
CREATE INDEX ON orders(customer_id);
```

**Rationale**: Foreign key lookups are slow without indexes.

---

### 6. SecurityRule

**Purpose**: Flag security anti-patterns

**Examples**:
```python
# ❌ FAIL
CREATE TABLE users (
  id INT PRIMARY KEY,
  email VARCHAR(255),
  password VARCHAR(255)  # ← Plain text password!
);

# ✅ PASS
CREATE TABLE users (
  id INT PRIMARY KEY,
  email VARCHAR(255),
  password_hash VARCHAR(255)  # ← Use bcrypt/argon2 to hash
);
```

**Also Detects**:
- API tokens in columns (should be encrypted)
- Secrets in columns (should use external secrets manager)

---

## Configuration Modes

### Mode 1: Default (No Config)

```bash
$ confiture lint
✅ Linting passed
```

Uses sensible defaults for all 6 rules.

### Mode 2: confiture.yaml

```yaml
linting:
  enabled: true
  fail_on_error: true
  fail_on_warning: false

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

### Mode 3: CLI Flags

```bash
# Fail on any warning
confiture lint --fail-on-warning

# JSON output for CI/CD parsing
confiture lint --format json > report.json

# Specific environment
confiture lint --env production
```

---

## Output Formats

### Table Format (Default)

```
┏━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━┓
┃ Rule               ┃ Location    ┃ Severity┃ Message            ┃
┡━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━┩
│ NamingConvention   │ Table: user │ ERROR   │ Should be 'users'  │
│ NamingConvention   │ users.uuid  │ ERROR   │ Should be 'id'     │
│ PrimaryKey         │ Table: user │ ERROR   │ Missing PRIMARY KEY│
│ Documentation      │ users       │ WARNING │ Missing COMMENT    │
│ MultiTenant        │ customers   │ ERROR   │ Missing tenant_id  │
│ MissingIndex       │ orders.fk   │ WARNING │ Foreign key not... │
└────────────────────┴─────────────┴─────────┴────────────────────┘

Schema: local
Tables checked: 42 | Columns: 256
Errors: 3 | Warnings: 2
Time: 123ms
```

### JSON Format (CI/CD)

```json
{
  "schema": "local",
  "tables_checked": 42,
  "errors": 3,
  "warnings": 2,
  "violations": [
    {
      "rule": "NamingConventionRule",
      "location": "Table: user",
      "severity": "error",
      "message": "Table 'user' should be 'users'",
      "suggested_fix": "Rename to 'users'"
    },
    ...
  ]
}
```

### CSV Format (Spreadsheet)

```
rule,location,severity,message,suggested_fix
NamingConventionRule,"Table: user",error,"Should be 'users'","Rename to 'users'"
NamingConventionRule,"users.uuid",error,"Should be 'id'","Rename to 'id'"
...
```

---

## CI/CD Integration Example

### GitHub Actions

```yaml
name: Schema Quality Gates

on: [push, pull_request]

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'

      - name: Install dependencies
        run: uv sync

      - name: Lint database schema
        run: |
          confiture lint \
            --env production \
            --format json \
            --fail-on-error \
            > lint-report.json

      - name: Upload results
        if: always()
        uses: actions/upload-artifact@v3
        with:
          name: lint-report
          path: lint-report.json

      - name: Comment PR with results
        if: failure()
        uses: actions/github-script@v6
        with:
          script: |
            const fs = require('fs');
            const report = JSON.parse(fs.readFileSync('lint-report.json', 'utf8'));
            github.rest.issues.createComment({
              issue_number: context.issue.number,
              owner: context.repo.owner,
              repo: context.repo.repo,
              body: `Schema Linting Results:\n- Errors: ${report.errors}\n- Warnings: ${report.warnings}`
            });
```

---

## Testing Strategy

### Unit Tests (40+)

- **10 tests**: Models (Violation, LintConfig, LintReport)
- **10 tests**: SchemaLinter core logic
- **20 tests**: Individual rules (3-4 tests per rule)

### Integration Tests (15+)

- **5 tests**: Real database schema linting
- **5 tests**: Configuration loading
- **5 tests**: CLI command execution

### Test Examples

```python
def test_naming_convention_detects_camel_case():
    """Should detect table names not in snake_case."""
    rule = NamingConventionRule()
    violations = rule.lint([
        Table(name="UserTable", columns=[...])
    ], {"style": "snake_case"})

    assert len(violations) == 1
    assert "user_table" in violations[0].suggested_fix

def test_multi_tenant_rule_finds_missing_tenant_id():
    """Should warn if customers table lacks tenant_id."""
    rule = MultiTenantRule()
    violations = rule.lint([
        Table(name="customers", columns=[
            Column(name="id", ...),
            # tenant_id missing
        ])
    ], {})

    assert len(violations) == 1
    assert "tenant_id" in violations[0].message

def test_cli_lint_command_fails_on_errors():
    """CLI should exit with code 1 on errors."""
    runner = CliRunner()
    result = runner.invoke(app, ["lint", "--fail-on-error"])

    assert result.exit_code == 1
    assert "failed" in result.output.lower()
```

---

## Implementation Roadmap

### Day 1: Foundation
- [ ] Create `models/lint.py` (data structures)
- [ ] Implement SchemaLinter + LintRule base
- [ ] Write model tests (10)
- **Deliverable**: Schema Linter core architecture

### Day 2: Rules Implementation
- [ ] Implement 6 linting rules
- [ ] Write rule tests (20)
- **Deliverable**: All linting rules complete

### Day 3: Integration
- [ ] Add CLI command
- [ ] Output formatting (table, JSON, CSV)
- [ ] Integration tests (15)
- **Deliverable**: `confiture lint` command working

### Day 4: Polish
- [ ] Documentation (user guide)
- [ ] Examples (CI/CD, config)
- [ ] Quality checks (coverage, linting)
- **Deliverable**: Phase 4.2.2 complete

---

## Success Metrics

| Metric | Target | Status |
|--------|--------|--------|
| Unit Tests | 40+ | Planned |
| Integration Tests | 15+ | Planned |
| Code Coverage | >85% | Planned |
| Rules Implemented | 6/6 | Planned |
| CLI Command | Working | Planned |
| Documentation | Complete | Planned |
| Zero Regressions | 330/330 tests pass | Planned |

---

## Key Design Decisions

### ✅ Why 6 Rules?

**Reasoning**:
1. **Naming** - Consistency (CamelCase vs snake_case)
2. **PrimaryKey** - Data integrity
3. **Documentation** - Operational knowledge
4. **MultiTenant** - Data isolation (critical!)
5. **MissingIndex** - Performance
6. **Security** - Password/secret handling

These cover the **80% of issues** that cause production problems.

### ✅ Why Separate Config from Code?

**Reasoning**:
- Teams have different standards
- Some may want stricter/looser rules
- Allows gradual adoption (enable rules one-by-one)
- Configuration in confiture.yaml (declarative)

### ✅ Why Multiple Output Formats?

**Reasoning**:
- **Table**: Human-readable for developers
- **JSON**: Machine-readable for CI/CD pipelines
- **CSV**: Spreadsheet/audit trail

### ✅ Why Automatic Detection of Multi-Tenant Tables?

**Reasoning**:
- Can't manually specify every table
- Pattern matching on table names (customers, organizations, etc.)
- Heuristic: if table name looks multi-tenant, require tenant_id

---

## Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|-----------|
| False positives in rule detection | Medium | Low | Comprehensive unit tests, allow exclusions |
| Performance on large schemas | Low | Medium | Rule execution is O(n), tested with 500+ tables |
| Users don't enable linting | Medium | Medium | Make it easy (defaults work well), documentation |
| Multi-tenant detection inaccurate | Medium | Low | Heuristic-based, users can override in config |

---

## Dependencies & Prerequisites

### ✅ Already Available
- SchemaBuilder (parse DDL)
- SchemaDiffer (analyze schema)
- psycopg3 (database access)
- Typer (CLI framework)
- Rich (terminal formatting)

### ❌ NOT Required
- Rust extensions (Phase 2)
- Interactive wizard (Phase 4.2.3)
- New external dependencies

---

## What's NOT Included in Phase 4.2.2

### Deferred to Phase 4.2.3+
- ✋ Custom rule development (extensibility framework)
- ✋ Automatic rule suggestion/fixes
- ✋ Integration with migration hooks (BEFORE_VALIDATION phase)
- ✋ Policy enforcement (require linting passes before migration)

These are nice-to-have features that can be added later.

---

## Success Definition

Phase 4.2.2 is **COMPLETE** when:

✅ **Functionality**
- All 6 linting rules working end-to-end
- `confiture lint` CLI command executes successfully
- Configuration via confiture.yaml and CLI flags
- Multiple output formats (table, JSON, CSV)

✅ **Quality**
- 40+ unit tests (100% passing)
- 15+ integration tests (100% passing)
- >85% code coverage
- Zero regressions in Phase 4.1 tests

✅ **Documentation**
- User guide (docs/linting.md)
- Configuration reference
- All 6 rules explained with examples
- CI/CD integration guide
- Troubleshooting section

✅ **Integration**
- Works seamlessly with existing tools
- Doesn't require changes to migrations
- Optional (can be disabled)
- Backward compatible

---

## Recommended Reading Order

1. **This document** (executive summary)
2. **PHASE_4_2_2_SCHEMA_LINTING_PLAN.md** (detailed implementation)
3. **PHASE_4_2_IMPLEMENTATION_PLAN.md** (Phase 4.2 context)
4. **PHASE_4_2_HANDOFF.md** (Phase 4.2 overview)

---

## Questions to Answer Before Starting

✅ **Architecture Clear?**
- [x] SchemaLinter orchestrates rules
- [x] Each rule is independent
- [x] Data flows from DDL → violations → report

✅ **Implementation Scope Clear?**
- [x] 6 rules (not more, not fewer)
- [x] Configuration via YAML + CLI
- [x] Three output formats

✅ **Testing Strategy Clear?**
- [x] 40+ unit tests
- [x] 15+ integration tests
- [x] Test coverage >85%

✅ **Success Criteria Clear?**
- [x] All tests passing
- [x] Zero regressions
- [x] Documentation complete

---

## Next Steps

1. **Review** this executive summary
2. **Confirm** architecture and scope with team
3. **Read** PHASE_4_2_2_SCHEMA_LINTING_PLAN.md for implementation details
4. **Start** Phase 4.2.2 implementation (Day 1: Models)
5. **Track** progress using TDD (RED → GREEN → REFACTOR → QA)

---

## Contact / Questions

For questions about Phase 4.2.2:
- Review PHASE_4_2_2_SCHEMA_LINTING_PLAN.md (detailed)
- Check PHASE_4_LONG_TERM_STRATEGY.md (context)
- Reference existing code (hooks.py, dry_run.py)

---

**Phase 4.2.2 is well-designed, low-risk, and ready to build.** 🍓

*Made from strawberries, linting best practices.* 🍓→🍯
