# Confiture 🍓

**PostgreSQL migrations with multi-agent coordination and 4 flexible strategies**

Build fresh databases in <1 second. Zero-downtime migrations. Multi-agent conflict detection. Production data sync with PII anonymization.

[![PyPI](https://img.shields.io/pypi/v/fraiseql-confiture.svg?logo=python&logoColor=white)](https://pypi.org/project/fraiseql-confiture/)
[![Tests](https://img.shields.io/badge/tests-3800%2B-brightgreen)](https://github.com/fraiseql/confiture)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-blue)](https://www.python.org/)
[![PostgreSQL 12+](https://img.shields.io/badge/PostgreSQL-12%2B-blue)](https://www.postgresql.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## Why Confiture?

**Problem**: Traditional migration tools replay every migration on every build (slow, brittle, maintains technical debt).

**Solution**: DDL files are the single source of truth. Just execute your schema once. Fresh databases in <1 second.

**Multi-Agent Safe**: Automatic conflict detection prevents teams and agents from stepping on each other.

---

## Quick Start

### Installation
```bash
pip install fraiseql-confiture
```

### Basic Usage
```bash
# Initialize project
confiture init

# Write schema DDL files
vim db/schema/10_tables/users.sql

# Build database (<1 second)
confiture build --env local

# Generate and apply migrations
confiture migrate generate --name "add_bio"
confiture migrate up
```

### Team Workflow (Multi-Agent)
```bash
# Register intention before making changes
confiture coordinate register --agent-id alice --tables-affected users

# Check for conflicts (by other agent)
confiture coordinate check --agent-id bob --tables-affected users
# ⚠️ Conflict: alice is working on 'users'

# Complete when done
confiture coordinate complete --intent-id int_abc123
```

---

## Core Features

### 🛠️ Four Migration Strategies

| Strategy | Use Case | Command |
|----------|----------|---------|
| **Build from DDL** | Fresh DBs, testing | `confiture build --env local` |
| **Incremental** | Existing databases | `confiture migrate up` |
| **Production Sync** | Copy prod data (with anonymization) | `confiture sync --from production --anonymize users.email` |
| **Zero-Downtime** | Complex migrations via FDW | `confiture migrate schema-to-schema` |

### 🤝 Multi-Agent Coordination
- ✅ Automatic conflict detection
- ✅ Intent registration and tracking
- ✅ JSON output for CI/CD
- ✅ <10ms per operation

### 🌱 Seed Data Management
- ✅ Sequential execution (solves PostgreSQL parser limits on 650+ row files)
- ✅ Per-file savepoint isolation for error recovery
- ✅ Continue-on-error mode (skip failed files)
- ✅ Prep-seed validation (5-level orchestrator)
- ✅ 5-level validation (static → full execution)
- ✅ Catch NULL FKs before production
- ✅ Pre-commit safe (Levels 1-3)
- ✅ Database validation with SAVEPOINT safety

### 🔍 Git-Aware Validation
- ✅ Detect schema drift vs. main branch
- ✅ Enforce migrations for DDL changes
- ✅ Pre-commit hook support

### 🔧 Developer Experience
- ✅ Dry-run mode (analyze before applying)
- ✅ Migration hooks (pre/post)
- ✅ Schema linting
- ✅ PII anonymization
- ✅ Optional Rust extension
- ✅ Python 3.11, 3.12, 3.13

---

## Documentation

**Getting Started**: [docs/getting-started.md](docs/getting-started.md)

**Guides**:
- [Build from DDL](docs/guides/01-build-from-ddl.md)
- [Incremental Migrations](docs/guides/02-incremental-migrations.md)
- [Production Data Sync](docs/guides/03-production-sync.md)
- [Zero-Downtime Migrations](docs/guides/04-schema-to-schema.md)
- [Sequential Seed Execution](docs/guides/sequential-seed-execution.md) ⭐ NEW
- [Multi-Agent Coordination](docs/guides/multi-agent-coordination.md)
- [Prep-Seed Validation](docs/guides/prep-seed-validation.md)
- [Migration Decision Tree](docs/guides/migration-decision-tree.md)
- [Dry-Run Mode](docs/guides/dry-run.md)

**API Reference**: [docs/reference/](docs/reference/)

**Examples**: [examples/](examples/)

---

## Project Status

✅ **v0.4.0-dev** (In Development - February 4, 2026)

**Recent Addition (Phase 9)**:
- ✅ Sequential seed execution (solves PostgreSQL parser limits on large files)
- ✅ Per-file savepoint isolation for error recovery
- ✅ Continue-on-error mode for partial seeding
- ✅ 29 new tests for seed workflow

**What's Implemented**:
- ✅ All 4 migration strategies
- ✅ Sequential seed execution (NEW)
- ✅ Multi-agent coordination (production-ready, 123+ tests)
- ✅ Prep-seed validation (5 levels, 86+ tests)
- ✅ Git-aware schema validation
- ✅ Schema diff detection
- ✅ CLI with rich output
- ✅ Comprehensive tests (4,100+)
- ✅ Complete documentation

**⚠️ Beta Software**: All features implemented and tested, but not yet used in production. Use in staging/development first.

---

## Contributing

```bash
git clone https://github.com/fraiseql/confiture.git
cd confiture
uv sync --all-extras
uv run pytest
```

See [CONTRIBUTING.md](CONTRIBUTING.md) and [CLAUDE.md](CLAUDE.md).

---

## Author & License

**Vibe-engineered by [Lionel Hamayon](https://github.com/LionelHamayon)** 🍓

MIT License - Copyright (c) 2025 Lionel Hamayon

---

*Making jam from strawberries, one migration at a time.* 🍓→🍯
