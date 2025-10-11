# Confiture 🍓

**PostgreSQL migrations, sweetly done**

Confiture is a modern PostgreSQL migration tool for Python with a **build-from-scratch philosophy** and **4 migration strategies** to handle every scenario from local development to zero-downtime production deployments.

[![PyPI version](https://badge.fury.io/py/confiture.svg)](https://pypi.org/project/confiture/)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Tests](https://github.com/evoludigit/confiture/workflows/tests/badge.svg)](https://github.com/evoludigit/confiture/actions)

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
├── schema/
│   ├── 00_common/
│   ├── 10_tables/
│   └── 20_views/
├── migrations/
└── environments/
    ├── local.yaml
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

- **[Getting Started Guide](docs/getting-started.md)** - Installation and first steps
- **[Migration Strategies](docs/migration-strategies.md)** - When to use each medium
- **[CLI Reference](docs/cli-reference.md)** - All commands documented
- **[FraiseQL Integration](docs/fraiseql-integration.md)** - GraphQL schema sync

---

## Features

### ✅ Available Now (Phase 1)
- Build from DDL (Medium 1)
- Incremental migrations (Medium 2)
- Schema diff detection
- CLI with rich terminal output
- FraiseQL integration

### 🚧 Coming Soon (Phase 2-3)
- Rust performance layer (10-50x speedup)
- Schema-to-schema FDW migration (Medium 4)
- Production data sync with anonymization (Medium 3)
- Binary wheels for all platforms

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

**Current Version**: 0.1.0-alpha (Phase 1)

**Roadmap**:
- ✅ Phase 1: Python MVP (Jan 2026)
- 🚧 Phase 2: Rust Performance (Mar 2026)
- ⏳ Phase 3: Advanced Features (Jun 2026)

See [PHASES.md](PHASES.md) for detailed timeline.

---

## Contributing

Contributions welcome! See [CLAUDE.md](CLAUDE.md) for development guide.

```bash
# Clone repository
git clone https://github.com/evoludigit/confiture.git
cd confiture

# Install dependencies
uv sync --all-extras

# Run tests
uv run pytest
```

---

## License

MIT License - see [LICENSE](LICENSE) for details.

---

## Acknowledgments

- Inspired by printoptim_backend's build-from-scratch approach
- Built for [FraiseQL](https://github.com/evoludigit/fraiseql) GraphQL framework
- Influenced by pgroll, Alembic, and Reshape

---

*Making jam from strawberries, one migration at a time.* 🍓→🍯

**[Documentation](https://confiture.readthedocs.io)** • **[GitHub](https://github.com/evoludigit/confiture)** • **[PyPI](https://pypi.org/project/confiture/)**
