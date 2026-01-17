# Confiture

**PostgreSQL migrations, sweetly done** 🍓

> **⚠️ Beta Software**: Confiture has comprehensive tests and documentation but has not yet been used in production. Use with caution in production environments.

Confiture is a PostgreSQL migration tool with **4 migration strategies** to handle scenarios from local development to zero-downtime production deployments.

---

## Why Confiture?

Traditional migration tools replay migration history to build databases. This is slow and brittle.

Confiture treats **DDL source files as the single source of truth**:

- **Direct DDL execution** instead of migration replay
- **4 migration strategies** (simple ALTER to zero-downtime FDW)
- **Production data sync** with PII anonymization
- **Optional Rust extension** for performance

---

## The Four Strategies

### 1. Build from DDL

```bash
confiture build --env local
```

Build fresh database from `db/schema/` DDL files.

**Use for**: Local development, CI/CD, fresh environments

[Learn more →](guides/01-build-from-ddl.md)

---

### 2. Incremental Migrations

```bash
confiture migrate up
```

Apply migrations to existing database (simple schema changes).

**Use for**: Small schema changes, backwards-compatible evolution

[Learn more →](guides/02-incremental-migrations.md)

---

### 3. Production Data Sync

```bash
confiture sync --from production --to staging --anonymize
```

Copy production data to local/staging with PII anonymization.

**Use for**: Debugging with real data, testing, QA

[Learn more →](guides/03-production-sync.md)

---

### 4. Schema-to-Schema Migration

```bash
confiture migrate schema-to-schema --source old --target new
```

Zero-downtime migrations via FDW for major refactoring.

**Use for**: Column renames, type changes, large tables

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

### User Guides
- [Migration Decision Tree](guides/migration-decision-tree.md) - Choose the right strategy
- [Build from DDL](guides/01-build-from-ddl.md) - Fresh databases in <1 second
- [Incremental Migrations](guides/02-incremental-migrations.md) - ALTER-based changes
- [Production Data Sync](guides/03-production-sync.md) - Copy and anonymize data
- [Schema-to-Schema](guides/04-schema-to-schema.md) - Zero-downtime via FDW

### Advanced Topics
- [Hooks](guides/hooks.md) - Before/after migration hooks
- [Anonymization](guides/anonymization.md) - Custom data masking
- [Compliance](guides/compliance.md) - HIPAA, SOX, GDPR, PCI-DSS
- [Integrations](guides/integrations.md) - CI/CD, Slack, monitoring
- [Dry-Run Mode](guides/dry-run.md) - Test migrations safely

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
| Zero-downtime | No | Yes | **Yes (FDW)** |
| Production sync | No | No | **Built-in** |
| PII Anonymization | No | No | **12+ strategies** |
| Production-tested | Yes | Yes | **No (Beta)** |

[Full comparison →](comparison-with-alembic.md)

---

## Examples

- [Basic Migration](../examples/01-basic-migration/) - Beginner tutorial
- [Zero-Downtime Migration](../examples/03-zero-downtime-migration/) - Production scenario
- [Production Sync](../examples/04-production-sync-anonymization/) - PII handling

---

**Part of the FraiseQL ecosystem** 🍓
