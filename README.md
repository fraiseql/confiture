# Confiture 🍓

**PostgreSQL migrations, sweetly done**

Confiture is the official migration tool for [FraiseQL](https://github.com/fraiseql/fraiseql), designed with a **build-from-scratch philosophy** and **4 migration strategies** to handle every scenario from local development to zero-downtime production deployments.

> **Part of the FraiseQL ecosystem** - While Confiture works standalone for any PostgreSQL project, it's designed to integrate seamlessly with FraiseQL's GraphQL-first approach.

<div align="center">

### 📦 Package Status

[![PyPI version](https://img.shields.io/pypi/v/confiture?color=blue&logo=pypi&logoColor=white)](https://pypi.org/project/confiture/)
[![PyPI - Python Version](https://img.shields.io/pypi/pyversions/confiture?logo=python&logoColor=white)](https://www.python.org/downloads/)
[![PyPI - Downloads](https://img.shields.io/pypi/dm/confiture?color=blue&logo=pypi&logoColor=white)](https://pypi.org/project/confiture/)
[![PyPI - Wheel](https://img.shields.io/pypi/wheel/confiture?logo=pypi&logoColor=white)](https://pypi.org/project/confiture/)

### 🔨 Build & Quality

[![CI](https://img.shields.io/github/actions/workflow/status/evoludigit/confiture/ci.yml?branch=main&logo=github&label=CI)](https://github.com/evoludigit/confiture/actions/workflows/ci.yml)
[![Build Wheels](https://img.shields.io/github/actions/workflow/status/evoludigit/confiture/wheels.yml?branch=main&logo=github&label=Wheels)](https://github.com/evoludigit/confiture/actions/workflows/wheels.yml)
[![codecov](https://img.shields.io/codecov/c/github/evoludigit/confiture?logo=codecov&logoColor=white)](https://codecov.io/gh/evoludigit/confiture)
[![Code style: ruff](https://img.shields.io/badge/code%20style-ruff-000000.svg)](https://github.com/astral-sh/ruff)
[![Type checked: mypy](https://img.shields.io/badge/type%20checked-mypy-blue.svg)](https://github.com/python/mypy)
[![pre-commit](https://img.shields.io/badge/pre--commit-enabled-brightgreen?logo=pre-commit&logoColor=white)](https://github.com/pre-commit/pre-commit)

### 🖥️ Platform Support

[![Platform: Linux](https://img.shields.io/badge/platform-Linux-blue?logo=linux&logoColor=white)](https://pypi.org/project/confiture/)
[![Platform: macOS](https://img.shields.io/badge/platform-macOS-blue?logo=apple&logoColor=white)](https://pypi.org/project/confiture/)
[![Platform: Windows](https://img.shields.io/badge/platform-Windows-blue?logo=windows&logoColor=white)](https://pypi.org/project/confiture/)
[![PostgreSQL: 12+](https://img.shields.io/badge/PostgreSQL-12%2B-blue?logo=postgresql&logoColor=white)](https://www.postgresql.org/)

### 📖 Project Info

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![GitHub stars](https://img.shields.io/github/stars/evoludigit/confiture?style=social)](https://github.com/evoludigit/confiture/stargazers)
[![GitHub last commit](https://img.shields.io/github/last-commit/evoludigit/confiture?logo=github)](https://github.com/evoludigit/confiture/commits/main)
[![GitHub issues](https://img.shields.io/github/issues/evoludigit/confiture?logo=github)](https://github.com/evoludigit/confiture/issues)
[![Maintenance](https://img.shields.io/badge/Maintained%3F-yes-green.svg)](https://github.com/evoludigit/confiture/graphs/commit-activity)
[![Development Status](https://img.shields.io/badge/status-beta-orange)](https://github.com/evoludigit/confiture)

</div>

---

## Why Confiture?

Traditional migration tools (Alembic, Django migrations) **replay migration history** to build databases. This is slow and brittle.

Confiture treats **DDL source files as the single source of truth**:

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
pip install confiture

# Or with FraiseQL integration
pip install confiture[fraiseql]
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

---

## Documentation

### 📖 User Guides
- **[Getting Started](docs/guides/getting-started.md)** - Installation and first steps
- **[Migration Strategies](docs/guides/migration-strategies.md)** - When to use each medium
- **[Zero-Downtime Migrations](docs/guides/zero-downtime.md)** - Production deployments with FDW
- **[Production Data Sync](docs/guides/production-sync.md)** - Copy and anonymize production data
- **[FraiseQL Integration](docs/guides/fraiseql-integration.md)** - GraphQL schema sync

### 📚 Reference
- **[CLI Reference](docs/reference/cli.md)** - All commands documented
- **[Configuration Reference](docs/reference/configuration.md)** - Environment configuration
- **[API Reference](docs/reference/api.md)** - Python API documentation
- **[Schema Differ](docs/reference/differ.md)** - Schema comparison engine

### 💡 Examples
- **[Examples Overview](examples/)** - 5 complete production examples
- **[Basic Migration](examples/01-basic-migration/)** - Learn the fundamentals (15 min)
- **[FraiseQL Integration](examples/02-fraiseql-integration/)** - GraphQL workflow (20 min)
- **[Zero-Downtime](examples/03-zero-downtime-migration/)** - Production deployment (30 min)
- **[Production Sync](examples/04-production-sync-anonymization/)** - PII anonymization (25 min)
- **[Multi-Environment Workflow](examples/05-multi-environment-workflow/)** - Complete CI/CD (30 min)

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
- ✅ Comprehensive documentation (5 guides, 4 API docs)
- ✅ Production-ready examples (5 complete scenarios)

**Integration & Safety**:
- ✅ FraiseQL GraphQL integration
- ✅ Multi-environment configuration
- ✅ Transaction safety with rollback support
- ✅ PII anonymization with compliance tools
- ✅ CI/CD pipeline examples (GitHub Actions)

### 🚧 Coming Soon (Phase 4)
- Advanced migration hooks (before/after)
- Custom anonymization strategies
- Interactive migration wizard
- Migration dry-run mode
- Database schema linting

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

## Development Status

**Current Version**: 0.3.0-beta (Phase 3 Complete) 🎉

**Milestone Progress**:
- ✅ Phase 1: Python MVP (Complete - Oct 2025)
- ✅ Phase 2: Rust Performance Layer (Complete - Oct 2025)
- ✅ Phase 3: Production Features (Complete - Oct 2025)
  - ✅ Zero-downtime migrations (FDW)
  - ✅ Production data sync with PII anonymization
  - ✅ Comprehensive documentation (5 guides, 4 API references)
  - ✅ Production examples (5 complete scenarios)
- ⏳ Phase 4: Advanced Features (Q1 2026)
  - Migration hooks, wizards, dry-run mode

**Statistics**:
- 📦 4 migration strategies implemented
- 📖 5 comprehensive user guides
- 📚 4 API reference pages
- 💡 5 production-ready examples
- 🧪 95% test coverage
- ⚡ 10-50x performance with Rust

See [PHASES.md](PHASES.md) for detailed roadmap.

---

## Contributing

Contributions welcome! We'd love your help making Confiture even better.

**Quick Start**:
```bash
# Clone repository
git clone https://github.com/evoludigit/confiture.git
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

**[Documentation](https://github.com/fraiseql/confiture)** • **[GitHub](https://github.com/fraiseql/confiture)** • **[PyPI](https://pypi.org/project/confiture/)**
