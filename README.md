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

---

## Documentation

### 📖 User Guides
- **[Medium 1: Build from DDL](docs/guides/medium-1-build-from-ddl.md)** - Fresh databases in <1 second
- **[Medium 2: Incremental Migrations](docs/guides/medium-2-incremental-migrations.md)** - ALTER-based changes
- **[Medium 3: Production Data Sync](docs/guides/medium-3-production-sync.md)** - Copy and anonymize data
- **[Medium 4: Zero-Downtime Migrations](docs/guides/medium-4-schema-to-schema.md)** - Schema-to-schema via FDW
- **[Migration Decision Tree](docs/guides/migration-decision-tree.md)** - Choose the right strategy
- **[Schema Linting Guide](docs/linting.md)** - Validate schemas, catch issues early (NEW!)

### 📚 API Reference
- **[CLI Reference](docs/reference/cli.md)** - All commands documented
- **[Configuration Reference](docs/reference/configuration.md)** - Environment configuration
- **[Schema Builder API](docs/api/builder.md)** - Building schemas programmatically
- **[Migrator API](docs/api/migrator.md)** - Migration execution
- **[Syncer API](docs/api/syncer.md)** - Production data sync
- **[Schema-to-Schema API](docs/api/schema-to-schema.md)** - Zero-downtime migrations

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

### 🚧 Coming Soon (Phase 4.4+)
- Custom anonymization strategies
- Interactive migration wizard
- Migration dry-run mode
- Additional linting rules and extensibility

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

**Current Version**: 0.3.2 (Production Release) 🎉

**Recent Updates (v0.3.2)**:
- ✅ `--force` flag for migration reapplication
- ✅ Comprehensive troubleshooting guide with 400+ lines
- ✅ `database_url` connection format support
- ✅ Enhanced CLI warnings and safety messages

**Previous Release (v0.3.0)**:
- ✅ Hexadecimal file sorting for better schema organization
- ✅ Enhanced dynamic SQL file discovery
- ✅ Recursive directory support with improved performance

**Milestone Progress**:
- ✅ Phase 1: Python MVP (Complete - Oct 2025)
- ✅ Phase 2: Rust Performance Layer (Complete - Oct 2025)
- ✅ Phase 3: Production Features (Complete - Oct 2025)
  - ✅ Zero-downtime migrations (FDW)
  - ✅ Production data sync with PII anonymization
  - ✅ Comprehensive documentation (5 guides, 4 API references)
  - ✅ Production examples (5 complete scenarios)
- ✅ **CI/CD & Release Pipeline** (Complete - Nov 2025)
  - ✅ Multi-platform wheel building (Linux, macOS, Windows)
  - ✅ PyPI Trusted Publishing
  - ✅ Quality gate with comprehensive checks
  - ✅ Python 3.11, 3.12, 3.13 support verified
- ✅ **v0.3.0: Enhanced Schema Building** (Complete - Nov 2025)
  - ✅ Hexadecimal file sorting (0x01_, 0x0A_, etc.)
  - ✅ Dynamic discovery with patterns and filtering
  - ✅ Recursive directory support
  - ✅ Advanced configuration options
  - ✅ Comprehensive feature documentation
- ✅ **Phase 4.1-4.2: Advanced Features Foundation** (Complete - Dec 2025)
  - ✅ Entry points and structured logging
  - ✅ Schema linting with 6 rules
  - ✅ Type checker migration (mypy → Astral's ty)
- ✅ **Phase 4.3: Migration Hooks System** (Complete - Dec 2025)
  - ✅ 6-phase hook execution (BEFORE_VALIDATION → CLEANUP → ON_ERROR)
  - ✅ CQRS backfilling and validation hooks
  - ✅ Hook context for inter-hook communication
  - ✅ Error handling with ON_ERROR hooks
- ⏳ Phase 4.4+: Advanced Features (Q1 2026)
  - Custom anonymization strategies
  - Interactive migration wizard
  - Migration dry-run mode
  - Additional linting rules

**Statistics**:
- 📦 4 migration strategies implemented
- 📖 5 comprehensive user guides + 3 feature guides
- 📚 4 API reference pages
- 💡 5 production-ready examples
- 🧪 89% test coverage (258 tests) - 3 new test files added
- ⚡ 10-50x performance with Rust
- 🚀 Production-ready CI/CD pipeline
- 🔧 Advanced file discovery with hex sorting support

See [PHASES.md](PHASES.md) for detailed roadmap.

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
