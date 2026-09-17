# Confiture - Product Requirements Document

**Version**: 1.0
**Date**: October 11, 2025
**Status**: Draft
**Owner**: Lionel Hamayon (@evoludigit)

---

## Executive Summary

**Confiture** is a modern PostgreSQL migration tool for Python that introduces a **build-from-scratch philosophy** with **4 migration strategies** to handle every scenario from local development to zero-downtime production deployments.

Unlike traditional migration tools (Alembic, Django migrations) that replay migration history, Confiture treats DDL source files as the single source of truth, enabling instant fresh database creation while still supporting incremental production migrations.

**Tagline**: *"PostgreSQL migrations, sweetly done 🍓"*

---

## Problem Statement

### Current Pain Points

1. **Slow Fresh Database Setup**
   - Alembic/Django replay 100+ migrations → minutes to hours
   - New developers waste time on migration replay
   - CI/CD builds are slow

2. **No Zero-Downtime Migration Strategy**
   - Traditional ALTER migrations lock tables
   - Production deployments require downtime
   - No tooling for schema-to-schema migrations (manual process)

3. **No Production Data Sync**
   - Developers manually dump/restore production data
   - No built-in PII anonymization
   - Separate tools needed (pg_dump, custom scripts)

4. **One-Size-Fits-All Approach**
   - Forced to use ALTER migrations for everything
   - No choice between speed (downtime) vs complexity (zero-downtime)
   - Tools don't adapt to problem complexity

### Market Gap

| Tool | Build from DDL | Zero-Downtime | Production Sync | Python |
|------|----------------|---------------|-----------------|--------|
| Alembic | ❌ | ❌ | ❌ | ✅ |
| pgroll | ❌ | ✅ | ❌ | ❌ (Go) |
| Atlas | Partial | Partial | ❌ | ❌ (Go) |
| Django | ❌ | ❌ | ❌ | ✅ |
| **Confiture** | ✅ | ✅ | ✅ | ✅ |

---

## Product Vision

### North Star

**"Every PostgreSQL + Python developer should be able to migrate their database schema as easily as making jam from strawberries."**

### Goals

1. **Speed**: Fresh database setup in <1 second (not minutes)
2. **Safety**: Zero-downtime production migrations
3. **Simplicity**: One tool for all migration scenarios
4. **Integration**: Seamless FraiseQL integration, useful for everyone

---

## Target Users

### Primary Personas

#### **1. Python Web Developer**
- **Profile**: Building FastAPI/Django/Flask apps with PostgreSQL
- **Pain**: Alembic is slow for fresh DB setup, no zero-downtime option
- **Gain**: `confiture build` creates DB instantly, `confiture migrate schema-to-schema` for production

#### **2. FraiseQL User**
- **Profile**: GraphQL API developer using FraiseQL
- **Pain**: No migration tool built for FraiseQL workflow
- **Gain**: Native integration, GraphQL schema → SQL DDL helpers

#### **3. Data Engineer**
- **Profile**: Managing data pipelines (Airflow, dbt) with PostgreSQL
- **Pain**: Schema evolution breaks pipelines, manual migration scripts
- **Gain**: Deterministic schema builds, production data sync for testing

#### **4. DevOps Engineer**
- **Profile**: Managing production PostgreSQL deployments
- **Pain**: Downtime during schema changes, manual Blue/Green setups
- **Gain**: Built-in zero-downtime migrations via FDW

---

## Core Concepts

### The Four Mediums

Confiture provides **4 distinct strategies** for different migration scenarios:

#### **Medium 1: Build from Source DDL**
```bash
confiture build --env production
```
- **Input**: `db/schema/` directory (DDL files)
- **Output**: Fresh database with current schema
- **Use case**: New environments, CI/CD, developer onboarding
- **Speed**: <1 second for 1000+ files

#### **Medium 2: Incremental Migrations (ALTER)**
```bash
confiture migrate up
```
- **Input**: `db/migrations/` directory (Python migration files)
- **Output**: Modified existing database
- **Use case**: Simple production changes (add column, index)
- **Downtime**: 5-30 seconds (table lock)

#### **Medium 3: Production Data Sync**
```bash
confiture sync --from production --to local
```
- **Input**: Production database
- **Output**: Local database with production data
- **Use case**: Developer needs real data, staging refresh
- **Features**: PII anonymization, table filtering

#### **Medium 4: Schema-to-Schema Migration (FDW)**
```bash
confiture migrate schema-to-schema migrate --source old --target new --strategy fdw
```
- **Input**: Old production DB + new schema DDL
- **Output**: New pristine database with migrated data
- **Use case**: Complex changes, zero-downtime production
- **Downtime**: 0-5 seconds (atomic cutover)

---

## Key Features

### Phase 1: MVP (Pure Python)

#### **1.1 Schema Builder**
- Concatenate DDL files from `db/schema/` in deterministic order
- Environment-specific builds (local, test, production)
- Hash-based change detection
- Version tracking (`.confiture_version.json`)

#### **1.2 Migration System**
- Python-based migration files (like Alembic)
- `up()` and `down()` methods
- Transaction wrapping
- Rollback support
- Migration state tracking in database

#### **1.3 Schema Diff Detection**
- Compare old schema → new schema
- Auto-generate migration files
- Detect: table/column/index/constraint changes
- Suggest migration strategy (ALTER vs schema-to-schema)

#### **1.4 CLI**
- `confiture init` - Initialize project structure
- `confiture build` - Build schema from DDL
- `confiture migrate` - Migration commands
- `confiture sync` - Production data sync
- `confiture migrate status` - Show current state

#### **1.5 Configuration**
- YAML-based environment configs
- `db/environments/{env}.yaml`
- Database connection settings
- Include/exclude directories
- Migration behavior (auto-backup, confirmations)

### Phase 2: Rust Performance Layer

#### **2.1 Fast Schema Builder**
- Rust-based file concatenation (10-50x faster)
- Parallel file reading
- Efficient string handling

#### **2.2 Fast Schema Diff**
- Rust-based SQL parser (sqlparser-rs)
- AST comparison algorithm
- 10-50x faster than Python

#### **2.3 Parallel Operations**
- Concurrent hash computation
- Parallel file processing
- Async database operations

### Phase 3: Advanced Features

#### **3.1 Schema-to-Schema Migration**
- FDW-based zero-downtime migrations
- Automatic column mapping detection
- Data transformation support
- Verification and rollback

#### **3.2 Production Data Sync**
- Table-by-table sync
- PII anonymization
- Incremental sync (only changed data)
- Schema-aware data copying

#### **3.3 FraiseQL Integration**
- GraphQL schema → SQL DDL generation
- Type mapping (GraphQL → PostgreSQL)
- `@model` decorator support
- Automatic migration from schema changes

---

## User Stories

### Must-Have (Phase 1)

**US-1**: As a **new developer**, I want to setup a local database in one command, so I can start coding immediately.
```bash
confiture build --env local
# Result: Fresh database in <1 second
```

**US-2**: As a **backend developer**, I want to add a column to production without downtime risk, so I can deploy safely.
```bash
# Edit db/schema/10_tables/users.sql (add column)
confiture migrate generate add_user_bio
confiture migrate up --config db/environments/production.yaml
```

**US-3**: As a **DevOps engineer**, I want to see what migrations will run before applying them, so I can verify safety.
```bash
confiture migrate status
confiture migrate up --dry-run
```

**US-4**: As a **developer**, I want to rollback a migration if something goes wrong, so I can recover quickly.
```bash
confiture migrate down
```

**US-5**: As a **team lead**, I want new developers to use production-like data, so testing is realistic.
```bash
confiture sync --from production --anonymize users.email,users.phone
```

### Should-Have (Phase 2)

**US-6**: As a **backend developer**, I want schema builds to be instant even with 1000+ files, so CI/CD is fast.
```bash
confiture build --env test
# Result: <100ms with Rust core
```

**US-7**: As a **developer**, I want automatic migration generation from schema changes, so I don't write migrations manually.
```bash
# Edit db/schema/10_tables/users.sql
confiture migrate diff old_schema.sql new_schema.sql --generate --name add_user_bio
# Result: Migration file created with detected changes
```

### Nice-to-Have (Phase 3)

**US-8**: As a **DevOps engineer**, I want zero-downtime production migrations, so users experience no interruption.
```bash
confiture migrate schema-to-schema \
    --from production \
    --to production_new \
    --strategy fdw \
    --execute
```

**US-9**: As a **FraiseQL developer**, I want my GraphQL schema to generate SQL migrations, so schema and DB stay in sync.
```bash
fraiseql schema sync
# Calls: confiture migrate generate --from-graphql
```

---

## Technical Architecture

### Technology Stack

**Phase 1 (Pure Python)**:
- **Language**: Python 3.11+
- **CLI**: Typer (rich terminal output)
- **Database**: psycopg3 (PostgreSQL driver)
- **Config**: PyYAML + Pydantic
- **Testing**: pytest + pytest-asyncio
- **Packaging**: pyproject.toml + uv

**Phase 2 (Rust Performance)**:
- **Core**: Rust 1.75+ (stable)
- **Bindings**: PyO3 + maturin
- **Parser**: sqlparser-rs (PostgreSQL dialect)
- **Async**: tokio + tokio-postgres
- **Distribution**: Binary wheels via GitHub Actions

### Directory Structure

```
confiture/
├── python/
│   └── confiture/
│       ├── __init__.py
│       ├── cli/
│       │   └── main.py          # Typer CLI
│       ├── core/
│       │   ├── builder.py       # Schema builder
│       │   ├── migrator.py      # Migration executor
│       │   ├── differ.py        # Schema diff
│       │   └── syncer.py        # Production sync
│       ├── config/
│       │   └── environment.py   # YAML config
│       └── _core.pyi            # Rust bindings (Phase 2)
│
├── crates/                       # Phase 2
│   └── confiture-core/
│       └── src/
│           ├── lib.rs
│           ├── builder.rs
│           └── differ.rs
│
├── tests/
│   ├── unit/
│   ├── integration/
│   └── e2e/
│
├── docs/
│   ├── getting-started.md
│   ├── migration-strategies.md
│   ├── zero-downtime.md
│   └── fraiseql-integration.md
│
├── examples/
│   ├── basic/
│   ├── fraiseql/
│   └── zero-downtime/
│
├── pyproject.toml
├── Cargo.toml                    # Phase 2
├── PRD.md                        # This file
├── CLAUDE.md                     # Development guide
├── PHASES.md                     # Implementation phases
└── README.md
```

---

## User Experience

### Installation

```bash
# PyPI (Phase 1)
pip install confiture

# With FraiseQL
pip install fraiseql[migrations]  # Includes confiture

# Verify
confiture --version
```

### Quick Start

```bash
# 1. Initialize project
confiture init

# Creates:
# db/
# ├── schema/
# │   ├── 00_common/
# │   ├── 10_tables/
# │   └── 20_views/
# ├── migrations/
# ├── environments/
# │   ├── local.yaml
# │   └── production.yaml
# └── .confiture_version.json

# 2. Build local database
confiture build --env local

# 3. Make schema change
vim db/schema/10_tables/users.sql

# 4. Generate migration
confiture migrate generate add_user_bio

# 5. Apply migration
confiture migrate up

# 6. Deploy to production
confiture migrate up --config db/environments/production.yaml
```

---

## Success Metrics

### Phase 1 (3 months)

**Technical**:
- ✅ Build 1000 SQL files in <2 seconds
- ✅ 200+ passing tests (unit + integration)
- ✅ 90%+ test coverage
- ✅ Works with PostgreSQL 13-16

**Adoption**:
- ✅ 100+ GitHub stars (first month)
- ✅ 10+ production deployments documented
- ✅ FraiseQL integration complete
- ✅ 5+ blog posts / tutorials

**Quality**:
- ✅ Zero critical bugs in production
- ✅ <5% migration failure rate
- ✅ Complete documentation (20+ guides)

### Phase 2 (6 months)

**Technical**:
- ✅ Build 1000 SQL files in <100ms (10-20x improvement)
- ✅ Schema diff in <500ms
- ✅ Binary wheels for Mac/Linux/Windows

**Adoption**:
- ✅ 500+ GitHub stars
- ✅ 50+ production deployments
- ✅ Used by 3+ Python frameworks/tools
- ✅ Conference talk (PyCon, PostgresConf)

### Phase 3 (12 months)

**Technical**:
- ✅ Zero-downtime migrations proven at scale (1M+ rows)
- ✅ Production data sync with anonymization
- ✅ 500+ passing tests

**Adoption**:
- ✅ 1,000+ GitHub stars
- ✅ 100+ production deployments
- ✅ "Top PostgreSQL migration tool" recognition
- ✅ Enterprise customers (1-5)

---

## Risks & Mitigation

### Technical Risks

**Risk 1: Schema Diff Complexity**
- **Likelihood**: High
- **Impact**: Medium
- **Mitigation**: Start with simple cases (tables, columns), add complexity iteratively

**Risk 2: PostgreSQL Version Compatibility**
- **Likelihood**: Medium
- **Impact**: High
- **Mitigation**: Test against PG 13-16, use version-specific features conditionally

**Risk 3: Rust Learning Curve**
- **Likelihood**: Medium
- **Impact**: Low
- **Mitigation**: Phase 1 is pure Python, Rust is optional performance layer

### Market Risks

**Risk 4: pgroll Dominance**
- **Likelihood**: Medium
- **Impact**: High
- **Mitigation**: Python ecosystem focus, 4 strategies vs pgroll's 1, FraiseQL integration

**Risk 5: Insufficient Adoption**
- **Likelihood**: Low
- **Impact**: Critical
- **Mitigation**: FraiseQL users as base, proven printoptim_backend approach, clear differentiation

### Execution Risks

**Risk 6: Scope Creep**
- **Likelihood**: High
- **Impact**: Medium
- **Mitigation**: Strict phasing, MVP-first approach, defer nice-to-haves

**Risk 7: FraiseQL Dependency**
- **Likelihood**: Low
- **Impact**: Medium
- **Mitigation**: Keep confiture framework-agnostic, FraiseQL is optional integration

---

## Non-Goals (Out of Scope)

### Version 1.0

❌ **Multi-database support** (MySQL, SQLite)
→ PostgreSQL-first, others later

❌ **GUI/Web Interface**
→ CLI-first, GUI is v2.0+

❌ **Database backup/restore tool**
→ Use pg_dump/pg_restore, confiture focuses on schema evolution

❌ **Query builder / ORM**
→ Not a replacement for SQLAlchemy, just migrations

❌ **Schema visualization**
→ Nice-to-have for v2.0, not critical for MVP

---

## Open Questions

1. **Migration file format**: Pure Python (like Alembic) or allow SQL?
   - **Recommendation**: Python for flexibility, add SQL support in v1.1

2. **Automatic vs Manual migration generation**: Default behavior?
   - **Recommendation**: Manual by default, `--auto-detect` flag for automatic

3. **Schema-to-schema cutover**: Require pg_bouncer or support connection pool switch?
   - **Recommendation**: Support multiple strategies (database rename, pg_bouncer, DNS)

4. **FraiseQL coupling**: How tight should integration be?
   - **Recommendation**: Loose coupling, confiture is standalone, FraiseQL optional

---

## Competitive Positioning

### Messaging

**Tagline**: *"PostgreSQL migrations, sweetly done 🍓"*

**Value Propositions**:
1. **"Build from DDL, not migration history"** → Fresh databases in <1 second
2. **"4 strategies for every scenario"** → Simple ALTER to zero-downtime FDW
3. **"Production data sync built-in"** → No manual pg_dump scripts
4. **"Python + Rust performance"** → Best of both worlds

### Comparison

| Feature | Alembic | pgroll | **Confiture** |
|---------|---------|--------|---------------|
| **Philosophy** | Migration replay | Multi-version schema | Build-from-DDL + 4 strategies |
| **Fresh DB setup** | Minutes (replay all) | Minutes (replay all) | **<1 second** |
| **Zero-downtime** | ❌ No | ✅ Yes | ✅ Yes (FDW) |
| **Production sync** | ❌ No | ❌ No | ✅ Yes |
| **Language** | Python | Go | **Python + Rust** |
| **FraiseQL integration** | Manual | Manual | **Native** |

---

## Timeline

| Phase | Duration | Deliverables | Target Date |
|-------|----------|--------------|-------------|
| **Phase 1: Python MVP** | 3 months | Build, migrate, diff, CLI | Jan 2026 |
| **Phase 2: Rust Performance** | 2 months | 10-50x speedup, binary wheels | Mar 2026 |
| **Phase 3: Advanced Features** | 3 months | Schema-to-schema, production sync | Jun 2026 |

**Total**: 8 months to feature-complete v1.0

**FraiseQL v1.0 Integration**: Feb 2026 (uses Phase 1 Confiture)

---

## Success Criteria

**Launch Ready** (Phase 1 complete):
- ✅ Core 4 mediums implemented
- ✅ CLI working end-to-end
- ✅ FraiseQL integration done
- ✅ 200+ tests passing
- ✅ Documentation complete

**Production Ready** (Phase 2 complete):
- ✅ Performance meets benchmarks (<100ms builds)
- ✅ 10+ production deployments
- ✅ Zero critical bugs
- ✅ Binary wheels available

**Market Leader** (Phase 3 complete):
- ✅ 1,000+ GitHub stars
- ✅ "Top PostgreSQL tool" recognition
- ✅ Conference presentations
- ✅ Enterprise adoption

---

## Appendix

### Related Documents
- [CLAUDE.md](./CLAUDE.md) - Development guide for AI assistance
- [PHASES.md](./PHASES.md) - Detailed implementation phases
- [MIGRATION_SYSTEM_DESIGN.md](/home/lionel/code/fraiseql/MIGRATION_SYSTEM_DESIGN.md) - Technical design
- [MIGRATION_COMPETITIVE_ANALYSIS.md](/home/lionel/code/fraiseql/MIGRATION_COMPETITIVE_ANALYSIS.md) - Market analysis

### References
- printoptim_backend: Proven build-from-scratch approach
- FraiseQL: GraphQL integration patterns
- pgroll: Zero-downtime inspiration
- Alembic: Migration file format reference

---

**Last Updated**: October 11, 2025
**Status**: ✅ Ready for Development
**Next Steps**: Create CLAUDE.md, PHASES.md, begin Phase 1

---

*Making jam from strawberries, one migration at a time.* 🍓→🍯
