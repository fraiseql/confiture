# Confiture 🍓

**PostgreSQL migrations, sweetly done.**

Build from DDL. Adopt on day one against a database that already has migrations applied. Preflight every deploy against a parallel database with structural diff. Sync production data with PII anonymization.

[![PyPI](https://img.shields.io/pypi/v/fraiseql-confiture.svg?logo=python&logoColor=white)](https://pypi.org/project/fraiseql-confiture/)
[![Quality Gate](https://github.com/fraiseql/confiture/actions/workflows/quality-gate.yml/badge.svg)](https://github.com/fraiseql/confiture/actions/workflows/quality-gate.yml)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-blue)](https://www.python.org/)
[![PostgreSQL 12+](https://img.shields.io/badge/PostgreSQL-12%2B-blue)](https://www.postgresql.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## In 30 seconds

```bash
# 1. You already have a database at migration 004 (applied by hand or by another tool).
#    Tell Confiture about that history without re-running the SQL:
$ confiture migrate baseline --through 004 -c db/environments/production.yaml
  ✅ 001 create_users (marked as applied)
  ✅ 002 create_orders (marked as applied)
  ✅ 003 add_user_email (marked as applied)
  ✅ 004 add_user_preferences (marked as applied)
✅ Marked 4 migration(s) as applied, skipped 0 already applied

# 2. Machine-readable proof that the tracking is healthy:
$ confiture migrate status -c db/environments/production.yaml --format json | jq '.applied | length'
4

# 3. Preflight the next deploy end-to-end against a parallel database:
$ confiture migrate preflight --against "$PREFLIGHT_URL" -c db/environments/production.yaml
▸ Replaying pending migrations on preflight DB …
  ✓ 20260520143015_add_user_bio                 applied in 24 ms
▸ Comparing resulting schema vs. db/schema/ …
  ✓ No drift — preflight matches db/schema/
✓ Preflight passed. Safe to deploy.
exit 0
```

That's the loop. **Baseline once → status to confirm → preflight every deploy.**

---

## Already have migrations?

The single biggest reason migration tools fail adoption is the day-one cliff: existing tables already exist, so any tool that tries to apply migrations from scratch crashes on the first `CREATE TABLE`. Confiture's answer is `migrate baseline`:

```bash
confiture migrate baseline --through <last-applied-version>
```

The walkthrough — including failure modes, the integration test that backs the recipe, and what `tb_confiture` ends up looking like — is in [docs/guides/legacy-bootstrap.md](docs/guides/legacy-bootstrap.md).

---

## When to use Confiture?

| Capability | Confiture | Flyway | Alembic | dbmate | sqlx-cli | plain psql |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| Source of truth | DDL files | migration chain | model classes | migration chain | migration chain | DDL files |
| Tracking table | yes | yes | yes | yes | yes | no |
| Rollback (`down.sql`) | yes | paid | yes | yes | yes | no |
| Preflight against a copy DB | **yes (structural diff)** | no | no | no | no | no |
| Build from scratch in <1s | **yes** | no | no | no | no | yes (manual) |
| Production sync + anonymization | **yes** | no | no | no | no | no |
| Zero-downtime via FDW | **yes** | no | no | no | no | no |
| Multi-agent coordination | **yes** | no | no | no | no | no |
| Ecosystem maturity / stars | early | very mature | mature | mature | mature | n/a |

Confiture wins on **build-from-DDL**, **structural-diff preflight**, **production sync**, and **multi-agent coordination**. It loses on ecosystem age — Flyway and Alembic have a decade of community knowledge. Pick honestly.

### Adoption checklist

| Situation | Recommended tool |
|---|---|
| 1 environment + 1 contributor, schema rarely changes | plain `psql` |
| 2+ environments, schema changes weekly | Confiture, Flyway, Alembic, or dbmate |
| Multi-agent / AI-driven development on shared schemas | **Confiture** |
| You want `db/schema/` to be source of truth, not a migration chain | **Confiture** |
| You need zero-downtime schema swaps with `postgres_fdw` | **Confiture** (Medium 4) |
| You're committed to SQLAlchemy ORM | Alembic |
| You're committed to a JVM stack | Flyway |

---

## CI integration

A `migrate preflight` gate on every PR, a `migrate up` step on deploy. Exit codes are semantic, so the CI configuration stays simple:

```yaml
# .github/workflows/db.yml
name: DB

on:
  pull_request:
    paths:
      - 'db/**'
  push:
    branches: [main]

jobs:
  preflight:
    if: github.event_name == 'pull_request'
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:16
        env: { POSTGRES_PASSWORD: x }
        ports: ['5432:5432']
        options: >-
          --health-cmd pg_isready --health-interval 10s
          --health-timeout 5s --health-retries 5
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
      - run: uv pip install --system "fraiseql-confiture[ast]"
      - name: Restore production snapshot to preflight DB
        run: ./scripts/restore-snapshot.sh   # your own; pg_restore from S3/GCS
      - name: Confiture preflight
        env:
          PREFLIGHT_URL: postgresql://postgres:x@localhost:5432/preflight
        run: |
          confiture migrate preflight \
            --against "$PREFLIGHT_URL" \
            -c db/environments/preflight.yaml \
            --format json --output preflight.json
      - uses: actions/upload-artifact@v4
        with:
          name: preflight-report
          path: preflight.json

  deploy:
    if: github.ref == 'refs/heads/main'
    runs-on: ubuntu-latest
    environment: production
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
      - run: uv pip install --system "fraiseql-confiture[ast]"
      - run: confiture migrate up -c db/environments/production.yaml
        env:
          DATABASE_URL: ${{ secrets.PROD_DATABASE_URL }}
```

Exit codes: `0` success, `2` config error, `3` SQL failure, `6` lock contention, `7` structural drift. See [the dry-run guide](docs/guides/dry-run.md) for what each one means.

---

## Python project snippet

Add Confiture as a dev dependency. The `[ast]` extra pulls in `pglast` for full PostgreSQL parsing — recommended for schemas with bulk seed data.

```toml
# pyproject.toml
[dependency-groups]
dev = [
  "fraiseql-confiture[ast]>=0.9",
  "pytest>=8",
]
```

```just
# justfile
default:
    just --list

db-build:
    confiture build --env local

db-up:
    confiture migrate up

db-status:
    confiture migrate status

db-preflight:
    confiture migrate preflight --against "$PREFLIGHT_URL"
```

Or as a `Makefile`:

```makefile
db-build:
	confiture build --env local

db-up:
	confiture migrate up

db-status:
	confiture migrate status
```

---

## Library API

Confiture is a CLI first, but the migrator is fully usable from Python:

```python
from confiture import Migrator

with Migrator.from_config("db/environments/prod.yaml") as m:
    status = m.status()
    if status.has_pending:
        result = m.up()
        print(f"Applied {len(result.applied)} migrations")
```

---

## The Four Strategies

| Strategy | Use Case | Command |
|---|---|---|
| **Build from DDL** | Fresh databases, testing, CI | `confiture build --env local` |
| **Incremental Migrations** | Existing databases, production | `confiture migrate up` |
| **Production Sync** | Copy data with PII anonymization | `confiture sync --from prod --anonymize users.email` |
| **Zero-Downtime** | Complex migrations via FDW | `confiture migrate schema-to-schema` |

---

## Documentation

**Start here**
- [Getting started](docs/getting-started.md) — first 5 minutes.
- [Legacy bootstrap guide](docs/guides/legacy-bootstrap.md) — adopting on an existing database.
- [Prerequisites](docs/reference/prerequisites.md) — PostgreSQL version, roles, secret stores.

**Guides**
- [Build from DDL](docs/guides/01-build-from-ddl.md)
- [Incremental Migrations](docs/guides/02-incremental-migrations.md) — `up`, `down`, rollback.
- [Production Data Sync](docs/guides/03-production-sync.md)
- [Zero-Downtime Migrations](docs/guides/04-schema-to-schema.md)
- [Dry-Run + Preflight](docs/guides/dry-run.md)
- [Named Schemas](docs/guides/named-schemas.md)
- [Hooks](docs/guides/hooks.md)
- [Multi-Agent Coordination](docs/guides/multi-agent-coordination.md)

**Reference**
- [Tracking table (`tb_confiture`)](docs/reference/tracking-table.md)
- [CLI](docs/reference/cli.md)
- [Configuration YAML](docs/reference/configuration.md)
- [Complete feature list](docs/features/overview.md)

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

MIT License — Copyright (c) 2025 Lionel Hamayon

---

*Making jam from strawberries, one migration at a time.* 🍓→🍯
