# Confiture 🍓

**PostgreSQL migrations, sweetly done.**

Build fresh databases in <1 second. Apply incremental migrations. Sync production data with PII anonymization. Zero-downtime schema swaps via FDW. All from the same tool.

[![PyPI](https://img.shields.io/pypi/v/fraiseql-confiture.svg?logo=python&logoColor=white)](https://pypi.org/project/fraiseql-confiture/)
[![Quality Gate](https://github.com/fraiseql/confiture/actions/workflows/quality-gate.yml/badge.svg)](https://github.com/fraiseql/confiture/actions/workflows/quality-gate.yml)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-blue)](https://www.python.org/)
[![PostgreSQL 12+](https://img.shields.io/badge/PostgreSQL-12%2B-blue)](https://www.postgresql.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## Why Confiture?

- **DDL is the source of truth** — your `db/schema/` directory defines the database, not a chain of migrations. Fresh databases build in <1 second by executing DDL directly.
- **Timestamp-based versioning** — migration filenames use `YYYYMMDDHHMMSS`, so parallel branches never collide. No more `003_add_users` merge conflicts.
- **4 strategies, one tool** — build from DDL, incremental migrations, production sync with anonymization, and zero-downtime schema-to-schema via FDW. Pick the right one for each situation.
- **Multi-agent coordination** — built-in intent registration and conflict detection so teams and AI agents don't step on each other's schema changes.
- **CI/CD-native** — semantic exit codes, structured output (JSON/CSV/YAML), distributed locking, and dry-run with SAVEPOINT testing.

---

## Quick Start

### Installation

```bash
pip install fraiseql-confiture

# Recommended: include pglast for large-schema support
# (uses PostgreSQL's own C parser — no token limits)
pip install "fraiseql-confiture[ast]"
```

### CLI

```bash
# Initialize project structure
confiture init

# Write your schema DDL files
vim db/schema/10_tables/users.sql

# Build database from DDL (<1 second)
confiture build --env local

# Generate and apply migrations
confiture migrate generate --name "add_bio"
confiture migrate up
```

### Library API

```python
from confiture import Migrator

with Migrator.from_config("db/environments/prod.yaml") as m:
    status = m.status()
    if status.has_pending:
        result = m.up()
```

---

## The Four Strategies

| Strategy | Use Case | Command |
|----------|----------|---------|
| **Build from DDL** | Fresh databases, testing, CI | `confiture build --env local` |
| **Incremental Migrations** | Existing databases, production | `confiture migrate up` |
| **Production Sync** | Copy data with PII anonymization | `confiture sync --from prod --anonymize users.email` |
| **Zero-Downtime** | Complex migrations via FDW | `confiture migrate schema-to-schema` |

---

## Features

### Migration Management
- **`migrate preflight`** — pre-deploy safety gate: checks reversibility, non-transactional statements, duplicate versions, and checksum tampering. JSON output for CI/CD.
- **Semantic exit codes** — `0` success, `2` validation error, `3` SQL failure, `6` lock contention. Script with confidence.
- **`migrate rebuild`** — drop and recreate from DDL + replay migrations in one command. Fast environment reset.
- **`migrate validate`** — naming convention checks, schema drift detection, function signature and body drift.
- **`migrate fix-signatures`** — detect and atomically fix stale function overloads and body drift.
- **Dry-run with SAVEPOINT testing** — `--dry-run-execute` runs migrations inside a savepoint, then rolls back.
- **Checksum verification** — detect tampered migration files before applying.
- **Distributed locking** — safe concurrent deployments via PostgreSQL advisory locks.
- **Migration hooks** — run custom logic before/after each migration.

### Schema Intelligence
- **Schema diff detection** — two-tier parser: pglast (PostgreSQL's C parser) primary, sqlparse fallback.
- **Schema linting** — configurable rules to catch common DDL mistakes.
- **Function introspection** — `FunctionIntrospector`, `TypeMapper`, and `DependencyGraph` for deep schema analysis.
- **Grant accompaniment checker** — detect permission changes without corresponding migrations.

### Seed Data
- **Sequential execution** — handles PostgreSQL parser limits on large seed files.
- **Per-file savepoint isolation** — one bad seed file doesn't ruin the batch.
- **5-level prep-seed validation** — static analysis through full execution, pre-commit safe at levels 1-3.

### Multi-Agent Coordination
- **Intent registration** — declare which tables you're changing before you start.
- **Conflict detection** — automatic alerts when agents touch overlapping tables.
- **JSON output** — machine-readable for CI/CD pipelines.

### Developer Experience
- **Structured output** — JSON, CSV, and YAML for all commands.
- **Exception hierarchy** — typed errors with error codes and resolution hints.
- **Git-aware validation** — detect schema drift vs. main branch, enforce migrations for DDL changes.
- **PII anonymization** — built-in strategies for production sync.
- **Optional Rust extension** — drop-in performance boost for SQL parsing and hashing.
- **Python 3.11, 3.12, 3.13** — tested across all supported versions.
- **4,480+ tests** passing.

---

## Documentation

**Getting Started**: [docs/getting-started.md](docs/getting-started.md)

**Guides**:
- [Build from DDL](docs/guides/01-build-from-ddl.md)
- [Incremental Migrations](docs/guides/02-incremental-migrations.md)
- [Production Data Sync](docs/guides/03-production-sync.md)
- [Zero-Downtime Migrations](docs/guides/04-schema-to-schema.md)
- [Sequential Seed Execution](docs/guides/sequential-seed-execution.md)
- [Multi-Agent Coordination](docs/guides/multi-agent-coordination.md)
- [Prep-Seed Validation](docs/guides/prep-seed-validation.md)
- [Migration Decision Tree](docs/guides/migration-decision-tree.md)
- [Dry-Run Mode](docs/guides/dry-run.md)

**CLI Reference**: [docs/reference/cli.md](docs/reference/cli.md)

**API Reference**: [docs/reference/](docs/reference/)

**Examples**: [examples/](examples/)

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
