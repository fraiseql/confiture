# Confiture

**PostgreSQL schema evolution with built-in multi-agent coordination** 🍓

> **⚠️ Beta Software**: Confiture has comprehensive tests and documentation but has not yet been used in production. Use with caution in production environments.

Confiture enables teams and AI agents to collaborate on database schema changes safely, with **built-in multi-agent coordination** and **4 flexible migration strategies** for every scenario.

---

## Why Confiture?

### 🤝 Safe Multi-Agent Collaboration

Working with multiple agents or team members on database schemas? Confiture provides **automatic conflict detection**:

- **Declare intentions** before making changes
- **Detect conflicts** automatically (table, column, timing overlaps)
- **Track status** of all active schema work
- **Audit trail** with complete history
- **CI/CD integration** via JSON output

[Learn more about Multi-Agent Coordination →](guides/multi-agent-coordination.md)

### Build-from-DDL Philosophy

Traditional migration tools replay migration history to build databases. This is slow and brittle.

Confiture treats **DDL source files as the single source of truth**:

- **Direct DDL execution** instead of migration replay (<1 second)
- **4 migration strategies** (simple ALTER to zero-downtime FDW)
- **Production data sync** with PII anonymization
- **Optional Rust extension** for performance

---

## Core Features

### 🤝 Multi-Agent Coordination

Enable safe parallel schema development:

```bash
# Register intention
confiture coordinate register \
    --agent-id alice \
    --feature-name user_profiles \
    --tables-affected users

# Check for conflicts (by another agent)
confiture coordinate check \
    --agent-id bob \
    --tables-affected users
# ⚠️ Conflict detected: alice is working on 'users'

# View status (JSON for CI/CD)
confiture coordinate status --format json
```

**Key Benefits**:
- Automatic conflict detection before code is written
- Real-time visibility into active schema work
- JSON output for CI/CD integration
- Complete audit trail

[Multi-Agent Coordination Guide →](guides/multi-agent-coordination.md)

---

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
confiture migrate schema-to-schema --source old --target new
```
[Learn more →](guides/04-schema-to-schema.md)

---

## Quick Start

```bash
# Install
pip install confiture

# Initialize project
confiture init

# Build local database
confiture build --env local

# Create and apply migration
confiture migrate generate --name "add_user_bio"
confiture migrate up
```

---

## Documentation

### Getting Started
- [Getting Started](getting-started.md) - Installation and first steps
- [Getting Started by Role](getting-started-by-role.md) - Personalized learning paths
- [Glossary](glossary.md) - Key terms and concepts

### Multi-Agent Coordination (NEW!)
- [Multi-Agent Coordination Guide](guides/multi-agent-coordination.md) - Complete coordination guide
- [Architecture & Design](architecture/multi-agent-coordination.md) - Technical architecture
- [Performance Benchmarks](performance/coordination-performance.md) - Performance analysis
- [When to Use Coordination?](guides/multi-agent-coordination.md#when-to-use-coordination) - Decision guide

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
- [Dry-Run Mode](guides/dry-run.md) - Test migrations safely
- [Hooks](guides/hooks.md) - Before/after migration hooks
- [Anonymization](guides/anonymization.md) - Custom data masking
- [Compliance](guides/compliance.md) - HIPAA, SOX, GDPR, PCI-DSS
- [Integrations](guides/integrations.md) - CI/CD, Slack, monitoring

### Reference
- [CLI Reference](reference/cli.md) - All commands including coordination
- [Configuration](reference/configuration.md) - Environment setup
- [API Reference](api/index.md) - Python API documentation
- [Troubleshooting](troubleshooting.md) - Common issues

---

## Comparison

| Feature | Alembic | pgroll | **Confiture** |
|---------|---------|--------|---------------|
| Philosophy | Migration replay | Multi-version | **DDL-first + Coordination** |
| Multi-agent coordination | No | No | **✅ Built-in** |
| Conflict detection | No | No | **✅ Automatic** |
| Zero-downtime | No | Yes | **✅ Yes (FDW)** |
| Production sync | No | No | **✅ Built-in** |
| PII Anonymization | No | No | **✅ 12+ strategies** |
| CI/CD integration | Basic | Basic | **✅ JSON output** |
| Production-tested | Yes | Yes | **⚠️ No (Beta)** |

[Full comparison →](comparison-with-alembic.md)

---

## Examples

- [Multi-Agent Workflow](../examples/multi-agent-workflow/) - Coordination examples (NEW!)
- [Basic Migration](../examples/01-basic-migration/) - Beginner tutorial
- [Zero-Downtime Migration](../examples/03-zero-downtime-migration/) - Production scenario
- [Production Sync](../examples/04-production-sync-anonymization/) - PII handling

---

**Part of the FraiseQL ecosystem** 🍓
