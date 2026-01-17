# Glossary

**Key terms and concepts used throughout Confiture documentation.**

---

## A

### Anonymization
Replacing sensitive data with fictional or redacted values to protect privacy.

**In Confiture**: Used during [Production Data Sync](guides/03-production-sync.md) to safely copy production data to local development environments while masking PII (personally identifiable information).

**Example**: Email "alice@example.com" → "alice@hashed.local" before sync

**Related**: [Anonymization Guide](guides/anonymization.md)

---

## B

### Backfill
Populating data in a newly added column based on existing data.

**In Confiture**: After adding a new column to a table, backfill operations populate it with calculated or copied values.

**Example**:
```sql
-- Add new column
ALTER TABLE users ADD COLUMN account_status VARCHAR;

-- Backfill based on existing data
UPDATE users SET account_status = 'active' WHERE created_at < now() - interval '30 days';
```

**Related**: [Medium 2: Incremental Migrations](guides/02-incremental-migrations.md)

---

## C

### Checkpoint
Saved progress point during long-running migrations that allows resumption if interrupted.

**In Confiture**: When syncing large datasets, checkpoints save progress so you can resume without starting over.

**Related**: [Production Data Sync](guides/03-production-sync.md), `--checkpoint-file` flag

---

### CQRS
Command Query Responsibility Segregation - architectural pattern separating write operations (commands) from read operations (queries).

**In Confiture**: After schema changes, CQRS systems need to update read models (caches, denormalized tables) to stay in sync.

**Example**: When users table schema changes, rebuild Elasticsearch index and Redis cache

**Related**: [Advanced Patterns - CQRS Backfilling](guides/advanced-patterns.md)

---

## D

### DDL
Data Definition Language - SQL commands that define database structure.

**Includes**: CREATE TABLE, ALTER TABLE, CREATE INDEX, CREATE VIEW, DROP TABLE, etc.

**In Confiture**:
- **Primary source of truth** for Confiture (DDL-first philosophy)
- Stored in `db/schema/` directory
- Execute once to build database (vs Alembic's migration history)

**Example**: `db/schema/10_tables/users.sql` contains full CREATE TABLE statement

**Contrast with**: [DML](#dml)

**Related**: [Medium 1: Build from DDL](guides/01-build-from-ddl.md), [Why Confiture?](../README.md#why-confiture)

---

### Dry-run
Testing a migration without actually executing it on the database.

**In Confiture**: Two modes:
1. **Analysis**: `--dry-run` shows what would happen
2. **Test execution**: `--dry-run-execute` runs in a transaction that rolls back

**Usage**:
```bash
confiture migrate up --dry-run              # Analyze migration
confiture migrate up --dry-run-execute      # Test with rollback
```

**Related**: [Dry-Run Guide](guides/dry-run.md)

---

### DML
Data Manipulation Language - SQL commands that modify data.

**Includes**: SELECT, INSERT, UPDATE, DELETE, etc.

**In Confiture**: Used during [Production Data Sync](guides/03-production-sync.md) and data backfilling operations.

**Contrast with**: [DDL](#ddl)

---

## E

### Environment
Named database configuration (local, test, staging, production, etc.)

**In Confiture**: Defined in `db/environments/`:
- `local.yaml` - Local development database
- `test.yaml` - Test database
- `staging.yaml` - Staging environment
- `production.yaml` - Production database

**Usage**: `confiture build --env production`

**Related**: [Configuration Reference](reference/configuration.md)

---

## F

### FDW
Foreign Data Wrapper - PostgreSQL feature allowing one database to read from another.

**In Confiture**: Used in [Medium 4: Schema-to-Schema](guides/04-schema-to-schema.md) for zero-downtime migrations.

**How it works**:
1. Target database connects to source via FDW
2. Copies data from source
3. Meanwhile, source continues accepting writes
4. Incremental sync catches up before cutover

**Related**: [Zero-Downtime Migrations](guides/04-schema-to-schema.md)

---

## H

### Hook
Extension point in the migration lifecycle where custom code executes.

**In Confiture**: 6 hook phases:
1. **BEFORE_VALIDATION** - Pre-flight checks
2. **BEFORE_DDL** - Prepare for schema changes
3. **AFTER_DDL** - Post-schema operations (backfill, rebuild indexes)
4. **AFTER_VALIDATION** - Verify migration succeeded
5. **CLEANUP** - Clean up temporary artifacts
6. **ON_ERROR** - Handle failures

**Example**:
```python
class BackfillHook(MigrationHook):
    async def execute(self, context: HookContext) -> None:
        if context.phase == HookPhase.AFTER_DDL:
            # Backfill new column after schema change
            await context.connection.execute(...)
```

**Related**: [Migration Hooks](guides/hooks.md), [Advanced Patterns](guides/advanced-patterns.md)

---

## M

### Medium
One of Confiture's 4 migration strategies.

**The 4 Mediums**:
1. **Build from DDL** - Fresh database from schema files (<1 second)
2. **Incremental Migrations** - ALTER statements for simple changes
3. **Production Data Sync** - Copy data with anonymization
4. **Schema-to-Schema** - Zero-downtime via FDW

**Related**: [Migration Decision Tree](guides/migration-decision-tree.md)

---

## M

### Migration
Schema change from one state to another.

**In Confiture**: Implemented as:
- **Migrations** - Generated ALTER statements
- **Scripts** - Custom SQL or Python in hooks
- **Data sync** - Copying and transforming data

**Related**: [Incremental Migrations](guides/02-incremental-migrations.md)

---

## P

### PII
Personally Identifiable Information - data that identifies individuals.

**Examples**: Email, phone number, SSN, credit card, name, address

**In Confiture**: Masked during [Production Data Sync](guides/03-production-sync.md) using [anonymization strategies](guides/anonymization.md)

**Related**: [Anonymization](#anonymization)

---

## S

### Schema
Database structure definition - tables, columns, indexes, views, functions, etc.

**In Confiture**:
- **Source schema** - `db/schema/` directory with DDL files
- **Database schema** - Actual structure in PostgreSQL

**Building schema**: Execute `db/schema/` files to create database schema

**Related**: [DDL](#ddl), [Medium 1: Build from DDL](guides/01-build-from-ddl.md)

---

### Seed
Test data inserted into database for testing purposes.

**In Confiture**: Stored in `db/seeds/` directory:
- `db/seeds/common/` - Used in all environments
- `db/seeds/local/` - Local development only
- `db/seeds/test/` - Test database only

**Usage**: Automatically loaded after schema build

**Related**: [Getting Started](getting-started.md)

---

## T

### Transaction
Atomic database operation - all changes succeed or all rollback.

**In Confiture**: Migrations execute in transactions. If any statement fails, entire migration rolls back.

**Dry-run**: Uses transactions to test without persisting changes

**Related**: [Dry-Run Guide](guides/dry-run.md)

---

## V

### Validation
Checking that data and schema are consistent and correct after migrations.

**In Confiture**:
- **Schema validation** - Verify table structure matches expectations
- **Data validation** - Verify data integrity after migration
- **Hook phase**: [AFTER_VALIDATION](#hook)

**Related**: [Advanced Patterns](guides/advanced-patterns.md)

---

## Z

### Zero-Downtime Migration
Schema change that doesn't interrupt database access or application traffic.

**Traditional approach**: Lock database, apply changes (minutes of downtime)

**Confiture approach**: Use FDW to copy data while source remains live, then quickly switch

**In Confiture**: [Medium 4: Schema-to-Schema](guides/04-schema-to-schema.md)

**Downtime**: 0-5 seconds (cutover only)

**Related**: [Zero-Downtime Migrations](guides/04-schema-to-schema.md)

---

## 🔗 Related

- **[Getting Started](getting-started.md)** - Learn basic concepts
- **[Architecture](../ARCHITECTURE.md)** - How Confiture works
- **[FAQ](../README.md)** - Common questions

---

*Last updated: January 17, 2026*
