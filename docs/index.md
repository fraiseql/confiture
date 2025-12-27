# Confiture

**PostgreSQL migrations, sweetly done** 🍓

Confiture is a modern PostgreSQL migration tool with **4 migration strategies** ("mediums") to handle every scenario from local development to zero-downtime production deployments.

## Why Confiture?

Traditional migration tools (Alembic, Django migrations) replay migration history to build databases. This is slow and brittle.

Confiture treats **DDL source files as the single source of truth**:

- ✅ **Fresh databases in <1 second** (not minutes)
- ✅ **4 migration strategies** (simple ALTER to zero-downtime FDW)
- ✅ **Production data sync** built-in (with PII anonymization)
- ✅ **Python + Rust performance** (10-50x faster than pure Python)
- ✅ **Perfect with FraiseQL**, useful for everyone

## The Four Mediums

### 1️⃣ Build from DDL

```bash
confiture build --env production
```

Build fresh database from `db/schema/` DDL files in <1 second.

**Use for**: Local development, CI/CD, fresh environments

[Learn more →](guides/medium-1-build-from-ddl.md)

---

### 2️⃣ Incremental Migrations (ALTER)

```bash
confiture migrate up
```

Apply migrations to existing database (simple schema changes).

**Use for**: Small schema changes, backwards-compatible evolution

[Learn more →](guides/medium-2-incremental-migrations.md)

---

### 3️⃣ Production Data Sync

```bash
confiture sync --from production --to staging --anonymize
```

Copy production data to local/staging with PII anonymization.

**Use for**: Debugging with real data, testing, QA

**Performance**: 70K rows/sec (COPY), 6.5K rows/sec (with anonymization)

[Learn more →](guides/medium-3-production-sync.md)

---

### 4️⃣ Schema-to-Schema Migration (Zero-Downtime)

```bash
confiture schema-to-schema --source old --target new --strategy auto
```

Complex migrations via FDW with 0-5 second downtime.

**Use for**: Major refactoring, breaking changes, large tables

**Performance**: Auto-detects optimal strategy (FDW or COPY) per table

[Learn more →](guides/medium-4-schema-to-schema.md)

---

## Quick Start

### Installation

```bash
pip install confiture
```

### Initialize Project

```bash
confiture init
```

Creates:
```
db/
├── schema/           # DDL files (CREATE TABLE, views, functions)
├── migrations/       # Generated migration files
└── environments/     # Environment configurations
```

### Build Schema

```bash
confiture build --env local
```

### Create Migration

```bash
# Edit schema
vim db/schema/10_tables/users.sql

# Generate migration
confiture migrate generate --name "add_user_bio"

# Apply migration
confiture migrate up
```

## Not Sure Which Medium to Use?

Check out our [Migration Decision Tree](guides/migration-decision-tree.md) to find the right strategy for your situation.

## Examples

Explore complete, production-ready examples:

- **[Basic Migration](examples/01-basic-migration/)** - 15-minute beginner tutorial
- **[FraiseQL Integration](examples/02-fraiseql-integration/)** - GraphQL schema integration
- **[Zero-Downtime Migration](examples/03-zero-downtime-migration/)** - Production scenario
- **[Production Sync](examples/04-production-sync-anonymization/)** - PII handling
- **[Multi-Environment](examples/05-multi-environment-workflow/)** - CI/CD pipeline

## Features

### ✅ Available Now

**Core Mediums**:
- Build from DDL (Medium 1)
- Incremental migrations (Medium 2)
- Production data sync with anonymization (Medium 3)
- Schema-to-schema FDW migration (Medium 4)

**Performance & Integration**:
- Rust performance layer (10-50x speedup)
- Binary wheels for Linux, macOS, Windows
- FraiseQL integration
- Environment-specific configurations
- Schema diff detection

**Phase 4 Features** (NEW!):
- **Migration Hooks** - Before/after execution hooks
- **Custom Anonymization** - Build your own data masking strategies
- **Interactive Wizard** - Guided step-by-step migrations
- **Schema Linting** - Validate schema against best practices
- **Dry-run Mode** - Analyze migrations before applying (v0.4.0)

**v0.3.0+ Features**:
- Hexadecimal file sorting
- Dynamic SQL discovery with patterns
- Recursive directory support
- CLI with rich terminal output

## Comparison

| Feature | Alembic | pgroll | **Confiture** |
|---------|---------|--------|---------------|
| **Philosophy** | Migration replay | Multi-version schema | **Build-from-DDL** |
| **Fresh DB setup** | Minutes | Minutes | **<1 second** |
| **Zero-downtime** | ❌ No | ✅ Yes | **✅ Yes (FDW)** |
| **Production sync** | ❌ No | ❌ No | **✅ Built-in** |
| **Language** | Python | Go | **Python + Rust** |
| **PII Anonymization** | ❌ No | ❌ No | **✅ 5 strategies** |

## Documentation

### 🚀 Getting Started
- **[Getting Started](getting-started.md)** - Installation and first steps
- **[Glossary](glossary.md)** - Key terms and concepts (NEW!)

### 📖 User Guides
- **[Migration Decision Tree](guides/migration-decision-tree.md)** - Choose the right strategy
- **[Medium 1: Build from DDL](guides/medium-1-build-from-ddl.md)** - Fresh databases in <1 second
- **[Medium 2: Incremental Migrations](guides/medium-2-incremental-migrations.md)** - ALTER-based changes
- **[Medium 3: Production Data Sync](guides/medium-3-production-sync.md)** - Copy and anonymize data
- **[Medium 4: Zero-Downtime](guides/medium-4-schema-to-schema.md)** - Schema-to-schema via FDW

### 📚 Reference
- **[CLI Reference](reference/cli.md)** - All commands documented
- **[Configuration Reference](reference/configuration.md)** - Environment setup
- **[API Reference](api/builder.md)** - Python API documentation

### 💡 Advanced Topics (Phase 4 - NEW!)
- **[Migration Hooks](guides/migration-hooks.md)** - Extend migrations with before/after hooks
- **[Custom Anonymization Strategies](guides/custom-anonymization-strategies.md)** - Build your own data masking
- **[Interactive Migration Wizard](guides/interactive-migration-wizard.md)** - Guided step-by-step migrations
- **[Schema Linting](guides/schema-linting.md)** - Validate schema against best practices
- **[Hooks vs Pre-commit](guides/hooks-vs-pre-commit.md)** - Choose the right validation tool
- **[Advanced Patterns](guides/advanced-patterns.md)** - Custom workflows, CQRS patterns
- **[Comparison with Alembic](comparison-with-alembic.md)** - Detailed comparison
- **[Performance Guide](performance.md)** - Benchmarks and optimization

### 🆘 Help & Support
- **[Troubleshooting](guides/troubleshooting.md)** - Common issues and solutions
- **[Examples](../examples/)** - Production-ready examples

## Contributing

Contributions welcome! See [../CONTRIBUTING.md](../CONTRIBUTING.md) for development guide.

## License

MIT License - see [../LICENSE](../LICENSE) for details.

Copyright (c) 2025 Lionel Hamayon

---

**Part of the FraiseQL ecosystem** 🍓

*Vibe-engineered with ❤️ by Lionel Hamayon*
