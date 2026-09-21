# Confiture Examples

Practical examples demonstrating all four migration strategies in Confiture.

---

## 🎓 Learning Path

Follow these examples in order to master Confiture's migration workflows:

| # | Example | Strategy | Level | Time |
|---|---------|----------|-------|------|
| 1 | [Basic Migration](#1-basic-migration) | Build from DDL + Incremental | Beginner | 15 min |
| 2 | [FraiseQL Integration](#2-fraiseql-integration) | GraphQL → PostgreSQL | Intermediate | 20 min |
| 3 | [Zero-Downtime Migration](#3-zero-downtime-migration) | Schema-to-Schema (FDW) | Advanced | 30 min |
| 4 | [Production Sync](#4-production-sync--anonymization) | Production Data Sync | Advanced | 25 min |
| 5 | [Multi-Environment Workflow](#5-multi-environment-workflow) | Complete CI/CD | Advanced | 30 min |

The multi-agent coordination example moved with pgGit support into a plugin in 1.16:
[`plugins/fraiseql-confiture-pggit/examples/multi-agent-workflow/`](../plugins/fraiseql-confiture-pggit/examples/multi-agent-workflow/).

---

## Available Examples

### 1. Basic Migration

**Location**: [`01-basic-migration/`](./01-basic-migration/)

**Perfect for**: Learning Confiture fundamentals

**Strategies**: Medium 1 (Build from DDL) + Medium 2 (Incremental Migrations)

A simple blog application with users, posts, and comments. Learn the core workflow of building schemas and applying migrations.

**What you'll learn**:
- ✅ Project initialization with `confiture init`
- ✅ Schema organization (numbered directories)
- ✅ Building complete schema from DDL files (<1 second)
- ✅ Detecting schema changes with `confiture migrate diff`
- ✅ Generating and applying migrations
- ✅ Rolling back migrations safely
- ✅ Testing migrations locally

**Database**: 3 tables (users, posts, comments)

**Key commands**:
```bash
confiture init
confiture build --env local
confiture migrate diff old.sql new.sql --generate --name add_bio
confiture migrate up
confiture migrate down
```

[→ Go to Basic Example](./01-basic-migration/README.md)

---

### 2. FraiseQL Integration

**Location**: [`02-fraiseql-integration/`](./02-fraiseql-integration/)

**Perfect for**: GraphQL-first development teams

**Strategies**: GraphQL schema → PostgreSQL migrations

Integrate Confiture with FraiseQL to automatically generate database migrations from GraphQL schema changes. Build a task management API with type-safe queries.

**What you'll learn**:
- ✅ GraphQL type → PostgreSQL table mapping
- ✅ Automatic migration generation from schema changes
- ✅ Type-safe database queries via FraiseQL
- ✅ Full-stack GraphQL application setup
- ✅ Keeping GraphQL and database schemas in sync

**Database**: 4 tables (users, projects, tasks, task_assignments)

**Key concepts**:
- GraphQL types automatically generate migrations
- Single source of truth (GraphQL schema)
- Type safety from frontend to database

[→ Go to FraiseQL Example](./02-fraiseql-integration/README.md)

---

### 3. Zero-Downtime Migration

**Location**: [`03-zero-downtime-migration/`](./03-zero-downtime-migration/)

**Perfect for**: Production database migrations with zero downtime

**Strategies**: Medium 4 (Schema-to-Schema via Foreign Data Wrappers)

Migrate a production e-commerce database from old to new schema with zero downtime using PostgreSQL Foreign Data Wrappers (FDW). Includes complete migration scripts and rollback procedures.

**What you'll learn**:
- ✅ Setting up Foreign Data Wrappers (FDW)
- ✅ Dual-write pattern for zero-downtime
- ✅ Incremental data migration with progress tracking
- ✅ Blue-green deployment strategy
- ✅ Safe rollback procedures
- ✅ Production-ready migration orchestration

**Database**:
- Old schema: 5 tables (legacy structure)
- New schema: 6 tables (normalized, performant)

**Key scripts**:
- `01_setup_fdw.sql` - Configure Foreign Data Wrappers
- `02_dual_write.sql` - Enable writes to both schemas
- `03_migrate_data.sql` - Incremental data migration
- `04_cutover.sql` - Final cutover to new schema
- `05_cleanup.sql` - Remove old schema

[→ Go to Zero-Downtime Example](./03-zero-downtime-migration/README.md)

---

### 4. Production Sync & Anonymization

**Location**: [`04-production-sync-anonymization/`](./04-production-sync-anonymization/)

**Perfect for**: Syncing production data to staging/local with PII protection

**Strategies**: Medium 3 (Production Data Sync)

Copy production database to staging or local environments with automatic PII anonymization. Compliant with GDPR, CCPA, and other privacy regulations.

**What you'll learn**:
- ✅ Secure production database dumps with `pg_dump`
- ✅ Automatic PII detection and anonymization
- ✅ Custom anonymization rules per column
- ✅ Preserving referential integrity
- ✅ Anonymization strategies (masking, hashing, replacement)
- ✅ Compliance with data protection regulations

**PII Handling**:
- Email addresses → `user_N@example.com`
- Names → `User N`, `Anonymous N`
- Phone numbers → `+1-555-6633` (the reserved fictional range)
- Names → `User 40A9`
- SSN, card digits → `[REDACTED]` (one constant; no shape is preserved)
- IP addresses, processor ids → a 16-hex one-way hash that keeps values distinct

**Key commands**:
```bash
confiture sync --from production --to staging \
    --anonymize --anonymization-config db/sync/anonymization.yaml

# Then prove it worked — a sync exiting 0 means rows moved, not that they
# were masked.
psql "$STAGING_URL" -v ON_ERROR_STOP=1 -f verify_anonymization.sql
```

[→ Go to Production Sync Example](./04-production-sync-anonymization/README.md)

---

### 5. Multi-Environment Workflow

**Location**: [`05-multi-environment-workflow/`](./05-multi-environment-workflow/)

**Perfect for**: Teams with CI/CD pipelines and multiple environments

**Strategies**: All four mediums orchestrated across environments

Complete CI/CD workflow with automated testing, staging deployment, and production migration. Includes GitHub Actions, Docker, and rollback procedures.

**What you'll learn**:
- ✅ Multi-environment configuration (local, test, staging, production)
- ✅ CI/CD pipeline with GitHub Actions
- ✅ Automated testing of migrations
- ✅ Staging deployment with anonymized data
- ✅ Production deployment with safety checks
- ✅ Rollback and disaster recovery
- ✅ Docker and Docker Compose setup

**Environments**:
- **Local**: Developer machines (fast iteration)
- **Test**: CI/CD automated tests
- **Staging**: Pre-production testing with production-like data
- **Production**: Live customer database

**CI/CD Pipeline**:
1. Developer pushes to branch → Tests run automatically
2. Merge to `main` → Deploy to staging
3. Manual approval → Deploy to production
4. Automatic rollback on failure

**Key files**:
- `.github/workflows/test.yml` - Automated testing
- `.github/workflows/deploy-staging.yml` - Staging deployment
- `.github/workflows/deploy-production.yml` - Production deployment
- `docker-compose.yml` - Local multi-environment setup

[→ Go to Multi-Environment Example](./05-multi-environment-workflow/README.md)

---

## Quick Start

Each example includes:

1. **README.md** - Complete tutorial
2. **Schema files** - DDL in `db/schema/`
3. **Migrations** - Pre-written migrations in `db/migrations/`
4. **Configuration** - Environment configs in `db/environments/`
5. **Sample data** - SQL scripts to populate database

### Running an Example

```bash
# 1. Navigate to example
cd examples/basic

# 2. Create database
createdb blog_app_local

# 3. Apply migrations
confiture migrate up --config db/environments/local.yaml

# 4. Verify
psql blog_app_local -c "\dt"
```

## Example Structure

All examples follow this structure:

```
example-name/
├── README.md                       # Tutorial and documentation
├── db/
│   ├── schema/                     # DDL source files
│   │   ├── 00_common/              # Extensions, types
│   │   └── 10_tables/              # Table definitions
│   ├── migrations/                 # Python migrations
│   │   ├── 001_initial.py
│   │   └── 002_add_feature.py
│   └── environments/               # Configuration
│       ├── local.yaml
│       └── production.yaml
├── sample_data/                    # SQL scripts
│   └── seed.sql
└── .gitignore
```

## 📚 Learning Path by Experience Level

### 🌱 Beginner (0-3 months with Confiture)

**Start here if**: You're new to Confiture or database migrations

1. **[Example 1: Basic Migration](./01-basic-migration/)** - Core concepts (15 min)
2. Read [Getting Started Guide](../docs/getting-started.md)
3. Read [CLI Reference](../docs/reference/cli.md)
4. Practice: Create your own project with `confiture init`

**Goal**: Confidently build schemas and apply basic migrations

---

### 🌿 Intermediate (3+ months with Confiture)

**Start here if**: You understand basics and want to integrate with frameworks

1. **[Example 2: FraiseQL Integration](./02-fraiseql-integration/)** - GraphQL integration (20 min)
2. Read [Migration Decision Tree](../docs/guides/migration-decision-tree.md)
3. Review [Configuration Reference](../docs/reference/configuration.md)
4. Practice: Apply to your team's project

**Goal**: Choose the right strategy and configure multiple environments

---

### 🌳 Advanced (6+ months with Confiture)

**Start here if**: You need production-grade migrations and zero-downtime

1. **[Example 3: Zero-Downtime](./03-zero-downtime-migration/)** - Production safety (30 min)
2. **[Example 4: Production Sync](./04-production-sync-anonymization/)** - PII anonymization (25 min)
3. **[Example 5: Multi-Environment Workflow](./05-multi-environment-workflow/)** - Complete CI/CD (30 min)
4. Read [Zero-Downtime Migrations](../docs/guides/04-schema-to-schema.md)
5. Practice: Deploy to production with rollback procedures

**Goal**: Master production deployments, CI/CD, and data compliance

## Tips for Learning

### 1. Follow the README

Each example has a detailed README with:
- Step-by-step instructions
- Expected output
- Troubleshooting tips
- Common operations

### 2. Experiment Freely

```bash
# Try things out
confiture migrate up
confiture migrate down
confiture migrate status

# Break things!
# Then fix them:
confiture migrate down
confiture migrate up
```

### 3. Read the Migrations

Open the migration files and understand:
- How `up()` applies changes
- How `down()` rolls back
- SQL best practices
- Transaction handling

### 4. Check the Database

```bash
# Connect to database
psql blog_app_local

# Explore schema
\dt                    # List tables
\d users              # Describe table
\di                   # List indexes

# Check migrations
SELECT * FROM confiture_migrations;
```

## 🎯 Which Example Should I Start With?

Choose based on your specific needs:

| If you want to... | Start with | Time |
|-------------------|------------|------|
| Learn the basics | [Example 1](./01-basic-migration/) | 15 min |
| Use GraphQL with PostgreSQL | [Example 2](./02-fraiseql-integration/) | 20 min |
| Deploy to production safely | [Example 3](./03-zero-downtime-migration/) | 30 min |
| Sync production data locally | [Example 4](./04-production-sync-anonymization/) | 25 min |
| Set up CI/CD pipelines | [Example 5](./05-multi-environment-workflow/) | 30 min |

**Recommended order**: 1 → 2 → 5 → 3 → 4

---

## 🤝 Contributing Examples

Have a great example to share? We'd love to include it!

**Requirements**:
- ✅ Complete README with step-by-step tutorial
- ✅ Working schema and migrations
- ✅ Sample data (optional but encouraged)
- ✅ Tested on PostgreSQL 12+
- ✅ Follows Confiture best practices

**How to contribute**:
1. Fork the repository
2. Create your example in `examples/XX-your-example/`
3. Follow the example structure (see above)
4. Add your example to this README
5. Submit a PR

Submit a PR to: https://github.com/evoludigit/confiture

## Resources

- **[Documentation](../docs/)** - Complete guides
- **[GitHub](https://github.com/fraiseql/confiture)** - Source code
- **[FraiseQL](https://github.com/fraiseql/fraiseql)** - GraphQL framework

---

**Part of the FraiseQL family** 🍓

*Vibe-engineered with ❤️ by [evoludigit](https://github.com/evoludigit)*
