# Phase 4.2.3: Schema Linting - Documentation & Examples

**Phase**: 4.2.3
**Status**: READY TO START ✅
**Duration**: 2-3 days
**Dependencies**: Phase 4.2.2 (COMPLETE ✅)

---

## Executive Summary

Phase 4.2.3 transforms the completed schema linting feature into a production-ready tool by documenting it comprehensively and providing practical examples. Users will have everything needed to integrate linting into their workflows.

### Deliverables
1. **User Guide** - `docs/linting.md` (2000+ words)
2. **4+ Examples** - Working code in `examples/linting/`
3. **API Reference** - Inline documentation (already done) + optional guide
4. **README Updates** - Highlight linting feature
5. **All Examples Tested** - Executable and verified

### Success Metrics
- User can read guide and use linting immediately
- All examples execute without error
- Zero broken links in documentation
- Clear path from beginner to advanced usage

---

## Day 1: User Documentation

### Task 1.1: Main Linting Guide (docs/linting.md)

**Target**: 2000+ word comprehensive guide

**Structure**:
```markdown
# Schema Linting Guide

## Overview
- What is schema linting?
- Why validate schemas?
- When to use linting

## Quick Start
- Installation
- First lint command
- Understanding output

## Six Linting Rules
- NamingConventionRule (snake_case enforcement)
- PrimaryKeyRule (require PRIMARY KEY)
- DocumentationRule (require COMMENT)
- MultiTenantRule (enforce tenant_id)
- MissingIndexRule (detect unindexed FKs)
- SecurityRule (detect passwords/secrets)

## Configuration
- Default configuration
- Custom rule settings
- Excluding tables
- Fail modes (error vs warning)

## Output Formats
- Table output (terminal)
- JSON output (automation)
- CSV output (spreadsheets)
- Exit codes

## CLI Usage
- All command options
- Common workflows
- Advanced usage

## Integration
- Adding to development workflow
- CI/CD integration
- Pre-commit hooks
- IDE integration

## Troubleshooting
- Common issues
- FAQ
- Getting help

## Best Practices
- Schema design patterns
- Fixing violations
- Gradual adoption
```

**Implementation**:
```markdown
# Schema Linting Guide

[2000+ word comprehensive guide covering all aspects]

## Quick Example

### Basic Usage
```bash
confiture lint
```

### With Custom Environment
```bash
confiture lint --env production
```

### Save Report
```bash
confiture lint --format json --output report.json
```

[More examples...]
```

**Verification**:
- [ ] >2000 words
- [ ] All sections present
- [ ] Examples are correct
- [ ] Links work
- [ ] Grammar/spelling correct

---

### Task 1.2: Configuration Reference

**Target**: Complete configuration guide

**Content**:
```yaml
# docs/linting-config-reference.yaml (in docs/linting.md)

# Complete configuration example with comments
enabled: true                    # Enable/disable linting
fail_on_error: true             # Exit with code 1 if errors found
fail_on_warning: false          # Exit with code 1 if warnings found (stricter)

exclude_tables:                 # Tables to exclude from linting
  - pg_*                        # Postgres system tables
  - information_schema.*        # Information schema

rules:
  naming_convention:
    enabled: true
    style: snake_case           # Enforce snake_case naming

  primary_key:
    enabled: true               # Require PRIMARY KEY on all tables

  documentation:
    enabled: true               # Require COMMENT on tables

  multi_tenant:
    enabled: true
    identifier: tenant_id       # Column to enforce in multi-tenant tables

  missing_index:
    enabled: true               # Warn about unindexed foreign keys

  security:
    enabled: true               # Flag password/secret/token columns
```

---

## Day 2: Examples & Integration

### Task 2.1: Basic Usage Example

**File**: `examples/linting/basic_usage.py`

```python
"""Basic schema linting example.

This example shows how to use the linting system programmatically.
"""

from pathlib import Path
from confiture.core.linting import SchemaLinter
from confiture.models.lint import LintConfig

# Create linter with default config
linter = SchemaLinter(env="local")
report = linter.lint()

# Display results
print(f"Schema: {report.schema_name}")
print(f"Tables: {report.tables_checked}")
print(f"Columns: {report.columns_checked}")
print(f"Violations: {len(report.violations)}")

# Show errors
for violation in report.violations:
    if violation.severity.value == "error":
        print(f"ERROR: {violation.location} - {violation.message}")
        if violation.suggested_fix:
            print(f"  → {violation.suggested_fix}")

# Show warnings
for violation in report.violations:
    if violation.severity.value == "warning":
        print(f"WARNING: {violation.location} - {violation.message}")

# Exit with appropriate code
exit(1 if report.has_errors else 0)
```

**Verification**:
- [ ] Script runs without error
- [ ] Output is clear
- [ ] Can be copied and modified
- [ ] Documented with comments

---

### Task 2.2: CLI Commands Reference

**File**: `examples/linting/cli_commands.sh`

```bash
#!/bin/bash
# Common confiture lint commands

# Basic linting
confiture lint

# Lint specific environment
confiture lint --env production

# Output as JSON
confiture lint --format json

# Save to file
confiture lint --format json --output report.json
confiture lint --format csv --output report.csv

# Strict mode (fail on warnings)
confiture lint --fail-on-warning

# Disable error checking
confiture lint --no-fail-on-error

# Help
confiture lint --help
```

**Verification**:
- [ ] All commands are valid
- [ ] Output is clear
- [ ] Documented
- [ ] Copy-paste ready

---

### Task 2.3: CI/CD Integration Example

**File**: `examples/linting/ci_github_actions.yaml`

```yaml
# .github/workflows/schema-lint.yaml
# Schema linting in GitHub Actions

name: Schema Linting

on:
  push:
    branches: [ main, develop ]
    paths:
      - 'db/schema/**'
      - '.github/workflows/schema-lint.yaml'
  pull_request:
    branches: [ main, develop ]
    paths:
      - 'db/schema/**'

jobs:
  lint:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ['3.11', '3.12']

    steps:
    - uses: actions/checkout@v4

    - name: Set up Python
      uses: actions/setup-python@v4
      with:
        python-version: ${{ matrix.python-version }}

    - name: Install uv
      run: curl -LsSf https://astral.sh/uv/install.sh | sh

    - name: Install dependencies
      run: uv sync

    - name: Lint schema
      run: uv run confiture lint --env ${{ github.base_ref || github.ref_name }} --fail-on-error

    - name: Generate report
      if: failure()
      run: uv run confiture lint --format json --output lint-report.json

    - name: Upload report
      if: failure()
      uses: actions/upload-artifact@v3
      with:
        name: lint-report
        path: lint-report.json
```

**Verification**:
- [ ] Syntax is correct
- [ ] Can be used directly
- [ ] Clear documentation
- [ ] Shows best practices

---

### Task 2.4: Configuration File Example

**File**: `examples/linting/linting.yaml`

```yaml
# Example linting configuration for different environments

# Development environment (relaxed)
dev:
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
      enabled: false          # Not required in dev
    multi_tenant:
      enabled: true
      identifier: tenant_id
    missing_index:
      enabled: true
    security:
      enabled: true

# Production environment (strict)
production:
  enabled: true
  fail_on_error: true
  fail_on_warning: true      # Strict: fail on all warnings
  exclude_tables:
    - pg_*
  rules:
    naming_convention:
      enabled: true
      style: snake_case
    primary_key:
      enabled: true
    documentation:
      enabled: true          # Required in production
    multi_tenant:
      enabled: true
      identifier: tenant_id
    missing_index:
      enabled: true
    security:
      enabled: true
```

---

### Task 2.5: Test Examples

**Verification for all examples**:
```bash
# Test basic_usage.py
python examples/linting/basic_usage.py

# Test CLI commands
bash examples/linting/cli_commands.sh

# Verify CI/CD syntax
# (Can't run, but validate YAML)
python -c "import yaml; yaml.safe_load(open('examples/linting/ci_github_actions.yaml'))"

# Verify config YAML
python -c "import yaml; yaml.safe_load(open('examples/linting/linting.yaml'))"
```

---

## Day 3: Integration & Polish

### Task 3.1: Update README.md

**Add to Feature List**:
```markdown
### Schema Linting
- Validate schema against 6 built-in rules
- Customize rules per environment
- Multiple output formats (table, JSON, CSV)
- CI/CD integration ready
- See [linting guide](docs/linting.md) for details
```

**Add Quick Start**:
```bash
# Lint your schema
confiture lint

# Save results as JSON
confiture lint --format json --output report.json
```

---

### Task 3.2: Create API Reference (Optional)

**File**: `docs/linting-api.md` (if needed)

**Content**:
- SchemaLinter class
- LintRule interface
- LintConfig options
- Report structure
- Configuration options

---

### Task 3.3: Cross-references

**Update documentation links**:
- README.md → docs/linting.md
- docs/linting.md → examples/
- examples/ → docs/linting.md for details

---

### Task 3.4: Final Review

**Checklist**:
- [ ] All documentation complete
- [ ] All examples tested
- [ ] All links valid
- [ ] Spelling/grammar correct
- [ ] Formatting consistent
- [ ] Examples copy-paste ready
- [ ] Can follow guide start-to-finish

---

## Testing & QA

### Test All Examples

```bash
# Test Python example
python examples/linting/basic_usage.py
# Expected: Output showing violations found

# Test CLI commands
bash examples/linting/cli_commands.sh
# Expected: All commands execute successfully

# Test configurations
python -c "import yaml; yaml.safe_load(open('examples/linting/linting.yaml'))"
# Expected: No errors

# Test JSON output
confiture lint --format json > /tmp/report.json
python -c "import json; json.load(open('/tmp/report.json'))"
# Expected: Valid JSON
```

### Verify Documentation

```bash
# Check for broken links (if using markdown checker)
npm install -g markdown-link-check
markdown-link-check docs/linting.md

# Check for spelling
npm install -g cspell
cspell docs/linting.md
```

---

## Files to Create

### Documentation
- [ ] `docs/linting.md` - Main guide (2000+ words)
- [ ] Update `README.md` with linting section

### Examples
- [ ] `examples/linting/basic_usage.py`
- [ ] `examples/linting/cli_commands.sh`
- [ ] `examples/linting/ci_github_actions.yaml`
- [ ] `examples/linting/linting.yaml`
- [ ] `examples/linting/schema_example.sql` (optional)

### Updates
- [ ] README.md - Add linting to features
- [ ] PHASES.md - Document Phase 4.2.3 (if needed)

---

## Success Criteria

**Documentation**:
- [ ] docs/linting.md > 2000 words
- [ ] Covers all 6 rules
- [ ] Configuration options documented
- [ ] Output formats explained
- [ ] Examples provided

**Examples**:
- [ ] Basic Python usage example works
- [ ] CLI commands documented
- [ ] CI/CD integration example provided
- [ ] Configuration examples provided
- [ ] All examples tested

**Integration**:
- [ ] README updated
- [ ] Links all valid
- [ ] User can follow guide start-to-finish
- [ ] Zero broken references

**Quality**:
- [ ] All examples execute without error
- [ ] Documentation is clear and complete
- [ ] No grammatical errors
- [ ] Formatting is consistent
- [ ] Examples are production-ready

---

## TDD Approach (Optional for Documentation)

Since this is documentation-focused, formal TDD may not apply, but we can follow a similar pattern:

**RED**: Define what documentation should exist (checklist above)
**GREEN**: Write documentation and examples
**REFACTOR**: Improve organization and clarity
**QA**: Test examples and verify completeness

---

## Commits

Expected commits:
```
docs: add comprehensive linting guide [GREEN]
examples: add linting usage examples [GREEN]
docs: update README with linting feature [GREEN]
docs: refactor for clarity and completeness [REFACTOR]
docs: verify all examples and links [QA]
```

---

## Related Resources

- Phase 4.2.2: [PHASE_4_2_2_INDEX.md](./PHASE_4_2_2_INDEX.md)
- Linting source code: `python/confiture/core/linting.py`
- Linting tests: `tests/unit/test_lint*.py`
- Linting CLI: `python/confiture/cli/main.py` (lint command)

---

## Next Phase (4.2.4)

After documentation is complete, Phase 4.2.4 will focus on:
- Performance optimization
- Additional linting rules
- Custom rule development guide
- Extension mechanisms

---

**Ready to start**: Phase 4.2.3 documentation implementation

See [PHASE_4_2_3_INDEX.md](./PHASE_4_2_3_INDEX.md) for navigation.
