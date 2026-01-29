# Confiture 🍓

**PostgreSQL schema evolution with built-in multi-agent coordination**

Confiture enables teams and AI agents to collaborate on database schema changes safely, with **built-in multi-agent coordination** and **4 flexible migration strategies** for every scenario from local development to zero-downtime production deployments.

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

### Safe Multi-Agent Collaboration 🤝

Working on database schemas with multiple agents or team members? Confiture provides **automatic conflict detection**:

```bash
# Agent 1: Declare intention to modify users table
confiture coordinate register --agent-id alice --tables-affected users

# Agent 2: Before modifying users table, check for conflicts
confiture coordinate check --agent-id bob --tables-affected users
# ⚠️ Conflict detected: alice is already working on 'users' table
```

**Benefits:**
- 🛡️ **Prevent conflicts** before code is written
- 👁️ **Visibility** into all active schema work
- 📋 **Audit trail** of coordination decisions
- 🤖 **JSON output** for CI/CD integration

Perfect for solo developers (optional safety), small teams (avoid surprises), and AI-assisted development (parallel agents).

**[→ Learn more about Multi-Agent Coordination](docs/guides/multi-agent-coordination.md)**

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

## Core Features

### 🤝 Multi-Agent Coordination (NEW!)

Enable safe parallel schema development with automatic conflict detection:

```bash
# Register intention before making changes
confiture coordinate register \
    --agent-id alice \
    --feature-name user_profiles \
    --tables-affected users,profiles

# Check status and conflicts
confiture coordinate status --format json

# Complete when done
confiture coordinate complete --intent-id int_abc123
```

**Key capabilities:**
- ✅ Declare intentions before coding
- ✅ Automatic conflict detection (table, column, timing overlaps)
- ✅ Audit trail with rich terminal output
- ✅ JSON output for automation/CI-CD
- ✅ Performance: <10ms operations, 10K+ intents supported

**[→ Multi-Agent Coordination Guide](docs/guides/multi-agent-coordination.md)** | **[→ Architecture Details](docs/architecture/multi-agent-coordination.md)**

---

### 🛠️ Four Migration Strategies

Choose the right strategy for your use case:

**1️⃣ Build from DDL** - Execute DDL files directly (<1 second)
```bash
confiture build --env production
```

**2️⃣ Incremental Migrations** - ALTER-based changes for existing databases
```bash
confiture migrate up
```

**3️⃣ Production Data Sync** - Copy data with PII anonymization
```bash
confiture sync --from production --anonymize users.email
```

**4️⃣ Schema-to-Schema (Zero-Downtime)** - Complex migrations via FDW
```bash
confiture migrate schema-to-schema --strategy fdw
```

**[→ Migration Decision Tree](docs/guides/migration-decision-tree.md)**

---

## Quick Start

### Installation

```bash
pip install fraiseql-confiture

# Or with FraiseQL integration
pip install fraiseql-confiture[fraiseql]
```

### For Solo Developers (Traditional Workflow)

```bash
# 1. Initialize project
confiture init

# 2. Write schema DDL files
vim db/schema/10_tables/users.sql

# 3. Build database
confiture build --env local

# 4. Generate and apply migrations
confiture migrate generate --name "add_user_bio"
confiture migrate up
```

**[→ Getting Started Guide](docs/getting-started.md)**

### For Teams & Multi-Agent Work (Coordination Workflow)

```bash
# 1. Initialize project with coordination database
confiture init
confiture coordinate init --db-url postgresql://localhost/confiture_coord

# 2. Register intention before making changes
confiture coordinate register \
    --agent-id alice \
    --feature-name user_profiles \
    --tables-affected users,profiles \
    --schema-changes "ALTER TABLE users ADD COLUMN bio TEXT"

# 3. Check for conflicts (by other agent)
confiture coordinate check \
    --agent-id bob \
    --tables-affected users
# ⚠️ Warning: alice is working on 'users' table

# 4. View active work
confiture coordinate status --format json

# 5. Complete when done
confiture coordinate complete --intent-id int_abc123
```

**[→ Multi-Agent Coordination Guide](docs/guides/multi-agent-coordination.md)**

### Project Structure

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

For more details, see **[Dry-Run Guide](docs/guides/dry-run.md)**.

---

## Documentation

### Getting Started

- **[Getting Started Guide](docs/getting-started.md)** - First steps with Confiture
- **[When to Use Coordination?](docs/guides/multi-agent-coordination.md#when-to-use-coordination)** - Solo vs. team vs. multi-agent

### Multi-Agent Coordination

- **[Multi-Agent Coordination Guide](docs/guides/multi-agent-coordination.md)** - Complete guide to coordination features
- **[Architecture & Design](docs/architecture/multi-agent-coordination.md)** - Technical architecture details
- **[Performance Benchmarks](docs/performance/coordination-performance.md)** - Performance analysis & results
- **[CI/CD Integration](docs/guides/multi-agent-coordination.md#json-output-format)** - JSON output for automation

### Migration Strategies

**Core Strategies**:
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
- **[Multi-Agent Workflow](examples/multi-agent-workflow/)** - Coordination examples (NEW!)
- **[Basic Migration](examples/01-basic-migration/)** - Learn the fundamentals
- **[FraiseQL Integration](examples/02-fraiseql-integration/)** - GraphQL workflow
- **[Zero-Downtime](examples/03-zero-downtime-migration/)** - FDW-based migration
- **[Production Sync](examples/04-production-sync-anonymization/)** - PII anonymization

---

## Features

### 🤝 Multi-Agent Coordination (Production-Ready)

- ✅ **Intent registration** - Declare changes before implementation
- ✅ **Conflict detection** - Automatic overlap detection (table, column, timing)
- ✅ **Status tracking** - Real-time visibility into active schema work
- ✅ **Audit trail** - Complete history of coordination decisions
- ✅ **JSON output** - CI/CD and automation integration
- ✅ **High performance** - <10ms operations, 10K+ intents supported
- ✅ **123 comprehensive tests** - All passing, production-ready

### 🛠️ Migration System (Implemented)

- ✅ **Build from DDL** (Strategy 1) - Execute DDL files directly (<1s)
- ✅ **Incremental migrations** (Strategy 2) - ALTER-based changes
- ✅ **Production data sync** (Strategy 3) - Copy with PII anonymization
- ✅ **Zero-downtime migrations** (Strategy 4) - Schema-to-schema via FDW

### 🔧 Developer Experience

- ✅ Optional Rust extension for performance
- ✅ Schema diff detection with auto-generation
- ✅ CLI with rich terminal output
- ✅ Multi-environment configuration
- ✅ Migration hooks (pre/post execution)
- ✅ Schema linting with multiple rules
- ✅ PII anonymization strategies
- ✅ Dry-run mode for testing migrations

### 📖 Documentation (Comprehensive)

- ✅ **Coordination guides** - Multi-agent workflows, architecture, performance
- ✅ **Migration guides** - All 4 strategies documented
- ✅ **API reference** - Complete CLI and Python API docs
- ✅ **Integration guides** - CI/CD, Slack, GitHub Actions, monitoring
- ✅ **Compliance guides** - HIPAA, SOX, PCI-DSS, GDPR
- ✅ **Examples** - 5+ complete examples including multi-agent workflows

---

## Comparison

| Feature | Alembic | pgroll | **Confiture** |
|---------|---------|--------|---------------|
| **Philosophy** | Migration replay | Multi-version schema | **Build-from-DDL + Coordination** |
| **Multi-agent coordination** | ❌ No | ❌ No | **✅ Built-in** |
| **Fresh DB setup** | Minutes | Minutes | **<1 second** |
| **Zero-downtime** | ❌ No | ✅ Yes | **✅ Yes (FDW)** |
| **Production sync** | ❌ No | ❌ No | **✅ Built-in** |
| **Conflict detection** | ❌ No | ❌ No | **✅ Automatic** |
| **CI/CD integration** | Basic | Basic | **✅ JSON output** |
| **Language** | Python | Go | **Python + Rust** |

---

## Current Version

**v0.3.9** (Latest) - January 27, 2026

### ✨ What's New in v0.3.9

**Migration File Validation & Auto-Fix**:
- ✅ New `confiture migrate validate` command with auto-fix
- ✅ Orphaned migration file detection (missing `.up.sql` suffix)
- ✅ Safe auto-fix with `--fix-naming` flag
- ✅ Dry-run preview mode with `--dry-run`
- ✅ JSON output for CI/CD integration
- ✅ Comprehensive "Migration Naming Best Practices" guide (500+ lines)
- ✅ 8 new tests covering all scenarios

**Previous Release - v0.3.8**: Multi-Agent Coordination (Production-Ready)
- ✅ 7 CLI commands (`confiture coordinate register/check/status/complete/abandon/list/conflicts`)
- ✅ Automatic conflict detection (table, column, function, constraint, index, timing)
- ✅ JSON output for CI/CD integration
- ✅ 123 comprehensive tests (all passing)
- ✅ Performance: <10ms operations, 10K+ intents supported
- ✅ Complete documentation (3,500+ lines)

> **⚠️ Beta Software**: While the multi-agent coordination system is production-ready and thoroughly tested, Confiture has not yet been used in production environments. Real-world usage may reveal edge cases. Use with appropriate caution.

### What's Implemented
- ✅ **Multi-agent coordination** with conflict detection
- ✅ All 4 migration strategies (Build from DDL, ALTER, Production Sync, FDW)
- ✅ Comprehensive test suite (3,200+ migration tests, 123 coordination tests)
- ✅ Complete documentation and guides
- ✅ Python 3.11, 3.12, 3.13 support
- ✅ Optional Rust extension
- ✅ Migration hooks, schema linting, anonymization strategies

### What's NOT Validated
- ❌ Production usage (never deployed to production)
- ❌ Performance claims (benchmarks only, not real-world workloads)
- ❌ Edge cases under load (not battle-tested at scale)
- ❌ Large-scale data migrations (theoretical performance)

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
