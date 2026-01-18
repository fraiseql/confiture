# Confiture 🍓

**PostgreSQL migrations, sweetly done**

Confiture is the official migration tool for [FraiseQL](https://github.com/fraiseql/fraiseql), designed with a **build-from-scratch philosophy** and **4 migration strategies** to handle every scenario from local development to zero-downtime production deployments.

> **Part of the FraiseQL ecosystem** - While Confiture works standalone for any PostgreSQL project, it's designed to integrate seamlessly with FraiseQL's GraphQL-first approach.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![PostgreSQL 12+](https://img.shields.io/badge/PostgreSQL-12%2B-blue?logo=postgresql&logoColor=white)](https://www.postgresql.org/)
[![CI](https://img.shields.io/github/actions/workflow/status/fraiseql/confiture/ci.yml?branch=main&label=CI&logo=github)](https://github.com/fraiseql/confiture/actions/workflows/ci.yml)
[![Code style: ruff](https://img.shields.io/badge/code%20style-ruff-000000.svg)](https://github.com/astral-sh/ruff)
[![Made with Rust](https://img.shields.io/badge/Made%20with-Rust-orange?logo=rust)](https://www.rust-lang.org/)
[![Part of FraiseQL](https://img.shields.io/badge/Part%20of-FraiseQL-ff69b4)](https://github.com/fraiseql/fraiseql)
[![Status: Beta](https://img.shields.io/badge/status-beta-yellow)](https://github.com/fraiseql/confiture)

---

## 🍓 Part of the FraiseQL Ecosystem

**confiture** accelerates PostgreSQL schema evolution across the FraiseQL stack:

### **Server Stack (PostgreSQL + Python/Rust)**

| Tool | Purpose | Status | Performance Gain |
|------|---------|--------|------------------|
| **[pg_tviews](https://github.com/fraiseql/pg_tviews)** | Incremental materialized views | Beta | **100-500× faster** |
| **[jsonb_delta](https://github.com/evoludigit/jsonb_delta)** | JSONB surgical updates | Stable | **2-7× faster** |
| **[pgGit](https://pggit.dev)** | Database version control | Stable | Git for databases |
| **[confiture](https://github.com/fraiseql/confiture)** | PostgreSQL migrations | **Beta** | **300-600× faster** (theoretical) |
| **[fraiseql](https://fraiseql.dev)** | GraphQL framework | Stable | **7-10× faster** |
| **[fraiseql-data](https://github.com/fraiseql/fraiseql-seed)** | Seed data generation | Phase 6 | Auto-dependency resolution |

### **Client Libraries (TypeScript/JavaScript)**

| Library | Purpose | Framework Support |
|---------|---------|-------------------|
| **[graphql-cascade](https://github.com/graphql-cascade/graphql-cascade)** | Automatic cache invalidation | Apollo, React Query, Relay, URQL |

**How confiture fits:**
- **Build from DDL** → Fresh DB in <1s for **fraiseql** GraphQL testing
- **pgGit** automatically tracks confiture migrations
- Manage **pg_tviews** schema evolution with 4 migration strategies
- **fraiseql-data** seeds the schema confiture built

**Intended workflow:**
```bash
# Build schema from DDL files
confiture build --env test

# Seed test data
fraiseql-data add tb_user --count 100

# Run GraphQL tests
pytest
```

---

## Why Confiture?

### The Problem with Migration History

Traditional migration tools (Alembic, Django migrations, Flyway) use **migration history replay**: every time you build a database, the tool executes every migration file in order. This works, but it's **slow and brittle**:

- **Slow**: Fresh database builds take 5-10 minutes (replaying hundreds of operations)
- **Brittle**: One broken migration breaks everything - your database history is fragile
- **Complicated**: Developers maintain two things: current schema AND migration history
- **Messy**: Technical debt accumulates as migrations pile up over months/years

### The Confiture Approach

Confiture flips the model: **DDL source files are the single source of truth**. To build a database:

1. Read all `.sql` files in `db/schema/`
2. Execute them once (in order)
3. Done ✅

No migration history to replay. No accumulated technical debt. Just your actual, current schema. **Fresh databases in <1 second.**

### Intended Advantages Over Alembic

| Feature | Confiture | Alembic | Notes |
|---------|-----------|---------|-------|
| **Fresh DB setup** | Direct DDL execution | Migration replay | Theoretically faster |
| **Zero-downtime migrations** | Via FDW (planned) | Not built-in | Not yet production-tested |
| **Production data sync** | Built-in (with PII anonymization) | Not available | Not yet production-tested |
| **Schema diffs** | Auto-generated | Manual | Implemented |
| **Conceptual simplicity** | DDL-first | Migration-first | Different philosophy |

### What's Implemented

- ✅ **4 migration strategies** (Build from DDL, ALTER, Production Sync, FDW)
- ✅ **Python + optional Rust extension**
- ✅ **PII anonymization strategies**
- ✅ **Comprehensive test suite** (3,200+ tests)
- ⚠️ **Not yet used in production** - Beta software

---

## The Four Mediums

### 1️⃣ Build from DDL
```bash
confiture build --env production
```
Build fresh database from `db/schema/` DDL files in <1 second.

### 2️⃣ Incremental Migrations (ALTER)
```bash
confiture migrate up
```
Apply migrations to existing database (simple schema changes).

### 3️⃣ Production Data Sync
```bash
confiture sync --from production --anonymize users.email
```
Copy production data to local/staging with PII anonymization.

### 4️⃣ Schema-to-Schema Migration (Zero-Downtime)
```bash
confiture migrate schema-to-schema --strategy fdw
```
Complex migrations via FDW with 0-5 second downtime.

---

## Quick Start

### Installation

```bash
pip install fraiseql-confiture

# Or with FraiseQL integration
pip install fraiseql-confiture[fraiseql]
```

### Initialize Project

```bash
confiture init
```

Creates:
```
db/
├── schema/           # DDL: CREATE TABLE, views, functions
│   ├── 00_common/
│   ├── 10_tables/
│   └── 20_views/
├── seeds/            # INSERT: Environment-specific test data
│   ├── common/
│   ├── development/
│   └── test/
├── migrations/       # Generated migration files
└── environments/     # Environment configurations
    ├── local.yaml
    ├── test.yaml
    └── production.yaml
```

### Build Schema

```bash
# Build local database
confiture build --env local

# Build production schema
confiture build --env production
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

### Test Migrations Before Applying (Dry-Run)

Analyze migrations without executing them:

```bash
# Analyze pending migrations
confiture migrate up --dry-run

# Test in SAVEPOINT (guaranteed rollback)
confiture migrate up --dry-run-execute

# Save analysis to file
confiture migrate up --dry-run --format json --output report.json

# Analyze rollback impact
confiture migrate down --dry-run --steps 2
```

For more details, see **[Dry-Run Guide](docs/guides/cli-dry-run.md)**.

---

## Documentation

### User Guides

**Core Concepts**:
- **[Build from DDL](docs/guides/01-build-from-ddl.md)** - Execute DDL files directly
- **[Incremental Migrations](docs/guides/02-incremental-migrations.md)** - ALTER-based changes
- **[Production Data Sync](docs/guides/03-production-sync.md)** - Copy and anonymize data
- **[Zero-Downtime Migrations](docs/guides/04-schema-to-schema.md)** - Schema-to-schema via FDW
- **[Migration Decision Tree](docs/guides/migration-decision-tree.md)** - Choose the right strategy

**Advanced**:
- **[Dry-Run Mode](docs/guides/dry-run.md)** - Test migrations before applying
- **[Migration Hooks](docs/guides/hooks.md)** - Execute custom logic before/after migrations
- **[Anonymization](docs/guides/anonymization.md)** - PII data masking strategies
- **[Compliance](docs/guides/compliance.md)** - HIPAA, SOX, PCI-DSS, GDPR
- **[Integrations](docs/guides/integrations.md)** - Slack, GitHub Actions, monitoring

### API Reference

- **[CLI Reference](docs/reference/cli.md)** - All commands documented
- **[Configuration](docs/reference/configuration.md)** - Environment configuration
- **[Schema Builder API](docs/api/builder.md)** - Building schemas programmatically
- **[Migrator API](docs/api/migrator.md)** - Migration execution
- **[Syncer API](docs/api/syncer.md)** - Production data sync
- **[Hook API](docs/api/hooks.md)** - Migration lifecycle hooks
- **[Anonymization API](docs/api/anonymization.md)** - PII data masking
- **[Linting API](docs/api/linting.md)** - Schema validation rules

### Examples
- **[Examples Overview](examples/)** - Complete examples
- **[Basic Migration](examples/01-basic-migration/)** - Learn the fundamentals
- **[FraiseQL Integration](examples/02-fraiseql-integration/)** - GraphQL workflow
- **[Zero-Downtime](examples/03-zero-downtime-migration/)** - FDW-based migration
- **[Production Sync](examples/04-production-sync-anonymization/)** - PII anonymization

---

## Features

### Core Migration System (Implemented)

- ✅ **Build from DDL** (Medium 1) - Execute DDL files directly
- ✅ **Incremental migrations** (Medium 2) - ALTER-based changes
- ✅ **Production data sync** (Medium 3) - Copy with PII anonymization
- ✅ **Zero-downtime migrations** (Medium 4) - Schema-to-schema via FDW

### Additional Features (Implemented)

- ✅ Optional Rust extension for performance
- ✅ Schema diff detection with auto-generation
- ✅ CLI with rich terminal output
- ✅ Multi-environment configuration
- ✅ Migration hooks (pre/post execution)
- ✅ Schema linting with multiple rules
- ✅ PII anonymization strategies
- ✅ Dry-run mode for testing

### Documentation (Comprehensive)

- ✅ User guides for all 4 migration strategies
- ✅ API reference documentation
- ✅ Integration guides (Slack, GitHub Actions, monitoring)
- ✅ Compliance guides (HIPAA, SOX, PCI-DSS, GDPR)

---

## Comparison

| Feature | Alembic | pgroll | **Confiture** |
|---------|---------|--------|---------------|
| **Philosophy** | Migration replay | Multi-version schema | **Build-from-DDL** |
| **Fresh DB setup** | Minutes | Minutes | **<1 second** |
| **Zero-downtime** | ❌ No | ✅ Yes | **✅ Yes (FDW)** |
| **Production sync** | ❌ No | ❌ No | **✅ Built-in** |
| **Language** | Python | Go | **Python + Rust** |

---

## Current Version

**v0.3.5**

> **⚠️ Beta Software**: Confiture has not yet been used in production. While the codebase includes comprehensive tests and documentation, real-world usage may reveal issues. Use with caution in production environments.

### What's Implemented
- ✅ All 4 migration strategies (Build from DDL, ALTER, Production Sync, FDW)
- ✅ Comprehensive test suite (3,200+ tests passing)
- ✅ Documentation and guides
- ✅ Python 3.11, 3.12, 3.13 support
- ✅ Optional Rust extension
- ✅ Migration hooks, schema linting, anonymization strategies

### What's NOT Validated
- ❌ Production usage (never deployed to production)
- ❌ Performance claims (benchmarks only, not real-world)
- ❌ Edge cases and failure recovery (not battle-tested)
- ❌ Large-scale data migrations (theoretical only)

---

## Contributing

Contributions welcome! We'd love your help making Confiture even better.

**Quick Start**:
```bash
# Clone repository
git clone https://github.com/fraiseql/confiture.git
cd confiture

# Install dependencies (includes Rust build)
uv sync --all-extras

# Build Rust extension
uv run maturin develop

# Run tests
uv run pytest --cov=confiture

# Format code
uv run ruff format .

# Type checking
uv run mypy python/confiture/
```

**Resources**:
- **[CONTRIBUTING.md](CONTRIBUTING.md)** - Contributing guidelines
- **[CLAUDE.md](CLAUDE.md)** - AI-assisted development guide
- **[PHASES.md](PHASES.md)** - Detailed roadmap

**What to contribute**:
- 🐛 Bug fixes
- ✨ New features
- 📖 Documentation improvements
- 💡 New examples
- 🧪 Test coverage improvements

---

## Author

**Vibe-engineered by [Lionel Hamayon](https://github.com/LionelHamayon)** 🍓

Confiture was crafted with care as the migration tool for the FraiseQL ecosystem, combining the elegance of Python with the performance of Rust, and the sweetness of strawberry jam.

---

## License

MIT License - see [LICENSE](LICENSE) for details.

Copyright (c) 2025 Lionel Hamayon

---

## Acknowledgments

- Inspired by printoptim_backend's build-from-scratch approach
- Built for [FraiseQL](https://github.com/fraiseql/fraiseql) GraphQL framework
- Influenced by pgroll, Alembic, and Reshape
- Developed with AI-assisted vibe engineering ✨

---

## FraiseQL Ecosystem

Confiture is part of the FraiseQL family:

- **[FraiseQL](https://github.com/fraiseql/fraiseql)** - Modern GraphQL framework for Python
- **[Confiture](https://github.com/fraiseql/confiture)** - PostgreSQL migration tool (you are here)

---

*Making jam from strawberries, one migration at a time.* 🍓→🍯

*Vibe-engineered with ❤️ by Lionel Hamayon*

**[Documentation](https://github.com/fraiseql/confiture)** • **[GitHub](https://github.com/fraiseql/confiture)** • **[PyPI](https://pypi.org/project/fraiseql-confiture/)**
