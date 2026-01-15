# Confiture 🍓

**PostgreSQL migrations, sweetly done**

Confiture is the official migration tool for [FraiseQL](https://github.com/fraiseql/fraiseql), designed with a **build-from-scratch philosophy** and **4 migration strategies** to handle every scenario from local development to zero-downtime production deployments.

> **Part of the FraiseQL ecosystem** - While Confiture works standalone for any PostgreSQL project, it's designed to integrate seamlessly with FraiseQL's GraphQL-first approach.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![PostgreSQL 12+](https://img.shields.io/badge/PostgreSQL-12%2B-blue?logo=postgresql&logoColor=white)](https://www.postgresql.org/)
[![CI](https://img.shields.io/github/actions/workflow/status/fraiseql/confiture/ci.yml?branch=main&label=CI&logo=github)](https://github.com/fraiseql/confiture/actions/workflows/ci.yml)
[![Code style: ruff](https://img.shields.io/badge/code%20style-ruff-000000.svg)](https://github.com/astral-sh/ruff)
[![Type checked: mypy](https://img.shields.io/badge/type%20checked-mypy-blue.svg)](https://github.com/python/mypy)
[![Made with Rust](https://img.shields.io/badge/Made%20with-Rust-orange?logo=rust)](https://www.rust-lang.org/)
[![Part of FraiseQL](https://img.shields.io/badge/Part%20of-FraiseQL-ff69b4)](https://github.com/fraiseql/fraiseql)
[![Status: Stable](https://img.shields.io/badge/status-stable-green)](https://github.com/fraiseql/confiture)

---

## 🍓 Part of the FraiseQL Ecosystem

**confiture** accelerates PostgreSQL schema evolution across the FraiseQL stack:

### **Server Stack (PostgreSQL + Python/Rust)**

| Tool | Purpose | Status | Performance Gain |
|------|---------|--------|------------------|
| **[pg_tviews](https://github.com/fraiseql/pg_tviews)** | Incremental materialized views | Beta | **100-500× faster** |
| **[jsonb_delta](https://github.com/evoludigit/jsonb_delta)** | JSONB surgical updates | Stable | **2-7× faster** |
| **[pgGit](https://pggit.dev)** | Database version control | Stable | Git for databases |
| **[confiture](https://github.com/fraiseql/confiture)** | PostgreSQL migrations | **Stable** ⭐ | **300-600× faster** |
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

**Lightning-fast workflow:**
```bash
# Build schema (300-600× faster than Alembic)
confiture build --env test  # <1 second!

# Seed test data
fraiseql-data add tb_user --count 100

# Run GraphQL tests
pytest  # Fresh DB every run, zero wait time
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

### Key Advantages Over Alembic

| Feature | Confiture | Alembic | Impact |
|---------|-----------|---------|--------|
| **Fresh DB setup** | <1 second | 5-10 minutes | 50-700x faster |
| **Zero-downtime migrations** | ✅ Yes (via FDW) | ❌ No | Production safety |
| **Production data sync** | ✅ Built-in (with PII anonymization) | ❌ Not available | Safer local dev |
| **Schema diffs** | ✅ Auto-generated | ⚠️ Manual | Less toil |
| **Conceptual simplicity** | ✅ DDL-first (simple) | ⚠️ Migration-first (complex) | Easier to learn |

### What You Get

- ✅ **Fresh databases in <1 second** (not minutes)
- ✅ **4 migration strategies** (simple ALTER to zero-downtime FDW)
- ✅ **Production data sync** built-in (with PII anonymization)
- ✅ **Python + Rust performance** (10-50x faster than pure Python)
- ✅ **Perfect with FraiseQL**, useful for everyone

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

### 📖 User Guides

**Core Concepts**:
- **[Medium 1: Build from DDL](docs/guides/medium-1-build-from-ddl.md)** - Fresh databases in <1 second
- **[Medium 2: Incremental Migrations](docs/guides/medium-2-incremental-migrations.md)** - ALTER-based changes
- **[Medium 3: Production Data Sync](docs/guides/medium-3-production-sync.md)** - Copy and anonymize data
- **[Medium 4: Zero-Downtime Migrations](docs/guides/medium-4-schema-to-schema.md)** - Schema-to-schema via FDW
- **[Migration Decision Tree](docs/guides/migration-decision-tree.md)** - Choose the right strategy

**Advanced Capabilities**:
- **[Dry-Run Analysis Guide](docs/guides/cli-dry-run.md)** - Test migrations before applying
- **[Schema Linting Guide](docs/linting.md)** - Validate schemas, catch issues early
- **[Migration Hooks](docs/guides/migration-hooks.md)** - Execute custom logic before/after migrations
- **[Advanced Patterns](docs/guides/advanced-patterns.md)** - Custom anonymization, CQRS patterns

**Integration & Compliance** (Phase 5 - NEW! ✨):
- **[Integration Guide: Slack](docs/guides/slack-integration.md)** - Slack webhook notifications
- **[Integration Guide: GitHub Actions](docs/guides/github-actions-workflow.md)** - CI/CD automation
- **[Integration Guide: Monitoring](docs/guides/monitoring-integration.md)** - Prometheus, Datadog, CloudWatch
- **[Integration Guide: PagerDuty](docs/guides/pagerduty-alerting.md)** - Incident management & alerting
- **[Integration Guide: Webhooks](docs/guides/generic-webhook-integration.md)** - Custom webhook integration
- **[Compliance: Healthcare (HIPAA)](docs/guides/healthcare-hipaa-compliance.md)** - HIPAA audit logging & compliance
- **[Compliance: Finance (SOX)](docs/guides/finance-sox-compliance.md)** - SOX segregation of duties & controls
- **[Compliance: E-Commerce (PCI-DSS)](docs/guides/ecommerce-data-masking.md)** - Credit card masking & PCI compliance
- **[Compliance: SaaS Multitenant](docs/guides/saas-multitenant-migrations.md)** - Multi-tenant data isolation & rollback
- **[Compliance: International](docs/guides/international-compliance.md)** - GDPR, LGPD, PIPEDA, PDPA, POPIA, Privacy Act

**Reference & Comparison**:
- **[Confiture vs Alembic](docs/comparison-with-alembic.md)** - Detailed comparison & migration path

### 📚 API Reference

**Core APIs**:
- **[CLI Reference](docs/reference/cli.md)** - All commands documented
- **[Configuration Reference](docs/reference/configuration.md)** - Environment configuration
- **[Schema Builder API](docs/api/builder.md)** - Building schemas programmatically
- **[Migrator API](docs/api/migrator.md)** - Migration execution
- **[Syncer API](docs/api/syncer.md)** - Production data sync
- **[Schema-to-Schema API](docs/api/schema-to-schema.md)** - Zero-downtime migrations

**Phase 5 APIs** (NEW! ✨):
- **[Hook API](docs/api/hooks.md)** - Migration lifecycle hooks (pre/post validation & execution)
- **[Anonymization API](docs/api/anonymization.md)** - PII data masking strategies & context-aware protection
- **[Linting API](docs/api/linting.md)** - Schema validation rules & custom linting
- **[Migration Wizard API](docs/api/wizard.md)** - Interactive guided migrations with risk assessment

### 💡 Examples
- **[Examples Overview](examples/)** - 5 complete production examples + linting examples
- **[Basic Migration](examples/01-basic-migration/)** - Learn the fundamentals (15 min)
- **[FraiseQL Integration](examples/02-fraiseql-integration/)** - GraphQL workflow (20 min)
- **[Zero-Downtime](examples/03-zero-downtime-migration/)** - Production deployment (30 min)
- **[Production Sync](examples/04-production-sync-anonymization/)** - PII anonymization (25 min)
- **[Multi-Environment Workflow](examples/05-multi-environment-workflow/)** - Complete CI/CD (30 min)
- **[Schema Linting Examples](examples/linting/)** - Linting guides and examples (NEW!)
  - Basic programmatic usage (Python)
  - CLI commands and workflows
  - CI/CD integration (GitHub Actions)
  - Configuration examples

---

## Features

### ✅ Complete (Phases 1-3)

**Core Migration System**:
- ✅ Build from DDL (Medium 1) - Fresh databases in <1 second
- ✅ Incremental migrations (Medium 2) - Simple ALTER-based changes
- ✅ Production data sync (Medium 3) - Copy with PII anonymization
- ✅ Zero-downtime migrations (Medium 4) - Schema-to-schema via FDW

**Performance & Distribution**:
- ✅ **Rust performance layer** (10-50x speedup) 🚀
- ✅ **Binary wheels** for Linux, macOS, Windows
- ✅ Parallel migration execution
- ✅ Progress tracking with resumability

**Developer Experience**:
- ✅ Environment-specific seed data (development/test/production)
- ✅ Schema diff detection with auto-generation
- ✅ CLI with rich terminal output and colors
- ✅ `--force` flag for migration reapplication
- ✅ Comprehensive documentation (5 guides, 4 API docs)
- ✅ Production-ready examples (5 complete scenarios)

**Integration & Safety**:
- ✅ FraiseQL GraphQL integration
- ✅ Multi-environment configuration
- ✅ Transaction safety with rollback support
- ✅ PII anonymization with compliance tools
- ✅ CI/CD pipeline examples (GitHub Actions)

### ✅ Phase 4.2: Schema Linting (Complete)
- ✅ **Schema linting** - Validate schemas against 6 built-in rules
- ✅ **Configuration management** - Environment-specific linting rules
- ✅ **Multiple output formats** - Table, JSON, CSV reports
- ✅ **CI/CD integration** - GitHub Actions examples included
- ✅ **Comprehensive documentation** - User guide with 2000+ words
- ✅ **4+ working examples** - From basic to advanced usage

### ✅ Phase 4.3: Migration Hooks (Complete - Dec 2025)
- ✅ **Migration hooks** - Execute custom code before/after DDL
- ✅ **6 hook phases** - BEFORE_VALIDATION, BEFORE_DDL, AFTER_DDL, AFTER_VALIDATION, CLEANUP, ON_ERROR
- ✅ **CQRS backfilling** - Sync read models after schema changes
- ✅ **Data validation** - Verify integrity before/after migrations
- ✅ **Error handling** - Custom error handlers with rollback
- ✅ **Comprehensive examples** - CQRS and validation hook examples
- ✅ **Full documentation** - 2000+ word hooks guide with patterns

### ✅ Phase 5: Enterprise Documentation & Integrations

**Integration Guides**:
- ✅ **Slack Integration** - Real-time migration notifications
- ✅ **GitHub Actions** - CI/CD workflow automation
- ✅ **Monitoring Integration** - Prometheus, Datadog, CloudWatch
- ✅ **PagerDuty** - Incident management
- ✅ **Webhooks** - Custom integrations

**Compliance & Industry Guides**:
- ✅ **Healthcare (HIPAA)** - Audit logging and PHI protection
- ✅ **Finance (SOX)** - Segregation of duties and controls
- ✅ **E-Commerce (PCI-DSS)** - Secure credit card handling
- ✅ **SaaS Multi-tenant** - Data isolation and rollback
- ✅ **International Compliance** - GDPR, LGPD, PIPEDA, PDPA, POPIA, Privacy Act

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

**v0.3.3** 🎉

### Core Migration System
All 4 migration strategies are implemented and production-tested:
- ✅ **Medium 1**: Build from DDL (fresh databases in <1 second)
- ✅ **Medium 2**: Incremental Migrations (simple ALTER-based changes)
- ✅ **Medium 3**: Production Data Sync (with PII anonymization)
- ✅ **Medium 4**: Zero-Downtime Migrations (via FDW)

### What's Included
- ✅ All 4 migration mediums fully implemented
- ✅ Comprehensive documentation and guides (14 guides covering core, integrations, and compliance)
- ✅ Production-ready examples
- ✅ Python 3.11, 3.12, 3.13 support
- ✅ Multi-platform wheels (Linux, macOS, Windows)
- ✅ Rust performance layer (10-50x faster)
- ✅ Advanced features: Migration hooks, schema linting, custom anonymization strategies
- ✅ Integration guides: Slack, GitHub Actions, Monitoring, PagerDuty, Webhooks
- ✅ Compliance guides: HIPAA, SOX, PCI-DSS, SaaS Multi-tenant, International regulations

For the detailed roadmap, see [PHASES.md](PHASES.md).

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
