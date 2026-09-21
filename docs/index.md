# Confiture

**PostgreSQL migrations, sweetly done** 🍓

Confiture treats your DDL files as the source of truth and offers **4 migration strategies**: build from DDL, incremental migrations, production data sync with anonymization, and schema-to-schema migration via FDW. Schema linting, drift detection and preflight checks guard each change before it reaches production.

---

## Why Confiture?

### Build-from-DDL Philosophy

Traditional migration tools replay migration history to build databases. This is slow and brittle.

Confiture treats **DDL source files as the single source of truth**:

- **Direct DDL execution** instead of migration replay (<1 second)
- **4 migration strategies** (simple ALTER to zero-downtime FDW)
- **Production data sync** with PII anonymization
- **Optional Rust extension** for performance

---

## Core Features

### 🛠️ Four Migration Strategies

Choose the right strategy for your use case:

**1. Build from DDL** - Fresh databases in <1 second
```bash
confiture build --env local
```
[Learn more →](guides/01-build-from-ddl.md)

**2. Incremental Migrations** - ALTER-based changes
```bash
confiture migrate up
```
[Learn more →](guides/02-incremental-migrations.md)

**3. Production Data Sync** - Copy with PII anonymization
```bash
confiture sync --from production --to staging --anonymize
```
[Learn more →](guides/03-production-sync.md)

**4. Schema-to-Schema** - Zero-downtime via FDW
```bash
confiture migrate schema-to-schema setup --source old --target new
```
[Learn more →](guides/04-schema-to-schema.md)

---

## Quick Start

```bash
# Install
pip install fraiseql-confiture

# Initialize project
confiture init

# Build local database
confiture build --env local

# Create and apply migration
confiture migrate generate add_user_bio
confiture migrate up
```

---

## Documentation

### Getting Started
- [Getting Started](getting-started.md) - Installation and first steps
- [Getting Started by Role](getting-started-by-role.md) - Personalized learning paths
- [Glossary](glossary.md) - Key terms and concepts

### Migration Strategies
- [Migration Decision Tree](guides/migration-decision-tree.md) - Choose the right strategy
- [Build from DDL](guides/01-build-from-ddl.md) - Fresh databases in <1 second
- [Incremental Migrations](guides/02-incremental-migrations.md) - ALTER-based changes
- [Production Data Sync](guides/03-production-sync.md) - Copy and anonymize data
- [Schema-to-Schema](guides/04-schema-to-schema.md) - Zero-downtime via FDW

### Migration Versioning (v0.6.0+)
- [Migration Versioning Strategies](guides/migration-versioning-strategies.md) - **NEW!** Timestamp-based versioning (v0.6.0)
  - Comparison: Confiture vs Flyway vs Django vs Rails vs Alembic
  - Why we switched to timestamps, no more merge conflicts
  - Backwards compatible with legacy `001_` format

### Migration File Management
- [Migration Naming Best Practices](guides/migration-naming-best-practices.md) - Naming conventions and validation

### Advanced Topics
- [Git-Aware Schema Validation](guides/git-aware-validation.md) - Pre-commit hooks and CI/CD validation (NEW!)
- [View Helpers](guides/view-helpers.md) - Manage dependent views during column changes
- [Dry-Run Mode](guides/dry-run.md) - Test migrations safely
- [Hooks](guides/hooks.md) - Before/after migration hooks
- [Anonymization](guides/anonymization.md) - Custom data masking
- [Compliance](guides/compliance.md) - HIPAA, SOX, GDPR, PCI-DSS
- [Integrations](guides/integrations.md) - CI/CD, Slack, monitoring

### pgGit Branching and Multi-Agent Coordination
- A plugin since 1.16, not part of confiture's core: [`plugins/fraiseql-confiture-pggit/`](https://github.com/fraiseql/confiture/tree/main/plugins/fraiseql-confiture-pggit) (see its README)

### Reference
- [CLI Reference](reference/cli.md) - All commands
- [Configuration](reference/configuration.md) - Environment setup
- [API Reference](api/index.md) - Python API documentation
- [Troubleshooting](troubleshooting.md) - Common issues

---

## Comparison

| Feature | Alembic | pgroll | **Confiture** |
|---------|---------|--------|---------------|
| Philosophy | Migration replay | Multi-version | **DDL-first** |
| Zero-downtime | No | Yes | **✅ Yes (FDW)** |
| Production sync | No | No | **✅ Built-in** |
| PII Anonymization | No | No | **✅ 12+ strategies** |
| CI/CD integration | Basic | Basic | **✅ JSON output** |
| Production-tested | Yes | Yes | **✅ Yes** |

[Full comparison →](comparison-with-alembic.md)

---

## Examples

- [Basic Migration](https://github.com/fraiseql/confiture/tree/main/examples/01-basic-migration) - Beginner tutorial
- [Zero-Downtime Migration](https://github.com/fraiseql/confiture/tree/main/examples/03-zero-downtime-migration) - Production scenario
- [Production Sync](https://github.com/fraiseql/confiture/tree/main/examples/04-production-sync-anonymization) - PII handling

---

**Part of the FraiseQL ecosystem** 🍓
