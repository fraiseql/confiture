# Confiture Phase 4: Long-Term Strategy

**Status**: Strategic Planning (Pre-Implementation)
**Target Timeline**: Q1 2026
**Audience**: Specialists, Architects, Technical Leads
**Last Updated**: 2025-12-26

---

## Executive Summary

Phase 4 transforms Confiture from a **migration execution tool** into a **comprehensive schema governance platform** by adding:

1. **Migration Hooks** (before/after DDL execution)
2. **Custom Anonymization Strategies** (flexible PII redaction)
3. **Interactive Migration Wizard** (guided safe migrations)
4. **Migration Dry-Run Mode** (transactional testing)
5. **Database Schema Linting** (validation & best practices)

These features enable seamless integration with:
- **pggit** (PostgreSQL version control system)
- **PrintOptim** (1,256+ SQL files, multi-tenant CQRS architecture)
- Complex production environments requiring schema governance

**Key Vision**: "Build from DDL, Version with pggit, Govern with Confiture"

---

## Table of Contents

1. [Context & Motivation](#context--motivation)
2. [Phase 4 Features Deep Dive](#phase-4-features-deep-dive)
3. [Integration Architecture](#integration-architecture)
4. [Implementation Roadmap](#implementation-roadmap)
5. [Technical Dependencies](#technical-dependencies)
6. [PrintOptim Integration Guide](#printoptim-integration-guide)
7. [pggit Integration Guide](#pggit-integration-guide)
8. [Risk Analysis & Mitigation](#risk-analysis--mitigation)
9. [Success Metrics](#success-metrics)
10. [Appendix: Code Examples](#appendix-code-examples)

---

## Context & Motivation

### Current State (v0.3.2)

**Completed Phases 1-3**:
- ✅ Phase 1: Python MVP with 4 mediums
  - Medium 1: Build from DDL (`confiture build`)
  - Medium 2: Incremental migrations (`confiture migrate up/down`)
  - Medium 3: Production data sync (`confiture sync`)
  - Medium 4: Zero-downtime FDW migration (`confiture migrate schema-to-schema`)

- ✅ Phase 2: Rust performance layer
  - 10-50x speedup via Rust extensions
  - Binary wheels for multi-platform distribution
  - Fast schema diffing and hashing

- ✅ Phase 3: Production features
  - PII anonymization in Medium 3
  - FDW strategy implementation in Medium 4
  - 332 passing tests, 81.68% coverage
  - Production-ready documentation

**Current Limitations**:
1. **No schema change validation** before execution (risky in production)
2. **Limited customization** of data transformations
3. **No audit trail integration** with version control systems
4. **Manual risk assessment** by operators
5. **No linting/standardization** enforcement across schemas

### Why Phase 4?

**Pain Points from Real-World Usage**:

1. **PrintOptim Problem**: 1,256+ SQL files organized hierarchically
   - No validation that all multi-tenant tables have `tenant_id`
   - Manual review of schema changes is error-prone
   - Naming conventions not enforced (write-side vs read-side)
   - Risk assessment for CQRS migrations is manual/subjective

2. **pggit Integration**: Version control exists but disconnected
   - pggit tracks DDL changes as audit trail
   - Confiture executes migrations independently
   - No way to link migration execution back to pggit commits
   - No way to query schema at historical pggit refs

3. **Production Safety**:
   - Complex migrations need testing before execution
   - Data anonymization rules vary per environment
   - Hooks for backfilling read models don't exist
   - No dry-run capability for production migrations

---

## Phase 4 Features Deep Dive

### Feature 1: Migration Hooks (Before/After)

#### Purpose

Execute custom code during migration execution to:
- Run data transformations before/after structural changes
- Maintain application invariants during schema evolution
- Handle backwards compatibility logic
- Implement CQRS backfill strategies (write→read data sync)

#### Architecture

```
Migration Execution Flow (with Hooks):

┌──────────────────────────────────────────────────────────┐
│ Migration: 003_add_user_analytics                        │
├──────────────────────────────────────────────────────────┤
│                                                           │
│  1. BEFORE_VALIDATION Hooks                              │
│     └─ Check preconditions (backup exists, etc.)         │
│                                                           │
│  2. BEFORE_DDL Hooks                                      │
│     ├─ Create shadow table for data migration             │
│     ├─ Capture current row counts for validation          │
│     └─ Prepare rollback triggers                          │
│                                                           │
│  3. [EXECUTE DDL] ← Structural changes                    │
│     ├─ ALTER TABLE, CREATE INDEX, etc.                   │
│     └─ Transaction checkpoint A                          │
│                                                           │
│  4. AFTER_DDL Hooks                                       │
│     ├─ Backfill new columns from existing data           │
│     ├─ Rebuild materialized views                         │
│     └─ Reindex search tables                              │
│                                                           │
│  5. AFTER_VALIDATION Hooks                                │
│     ├─ Verify data consistency (row counts, checksums)   │
│     ├─ Check constraint violations                        │
│     └─ Validate application queries work                  │
│                                                           │
│  6. CLEANUP Hooks                                         │
│     └─ Drop temporary tables, reset sequences             │
│                                                           │
│  [COMMIT] or [ROLLBACK on error]                          │
│                                                           │
└──────────────────────────────────────────────────────────┘
```

#### Types of Hooks

```python
class HookPhase(Enum):
    BEFORE_VALIDATION = 1   # Pre-flight checks
    BEFORE_DDL = 2          # Data prep before schema change
    AFTER_DDL = 3           # Data backfill after schema change
    AFTER_VALIDATION = 4    # Verification after data ops
    CLEANUP = 5             # Final cleanup
    ON_ERROR = 6            # Error handlers for rollback

class Hook(ABC):
    """Base class for all hooks."""

    @abstractmethod
    async def execute(
        self,
        conn: AsyncConnection,
        context: HookContext
    ) -> HookResult:
        """Execute hook with database connection and migration context."""
        pass
```

#### Use Cases

**1. CQRS Backfill (PrintOptim specific)**
```python
class BackfillReadModelHook(Hook):
    """Populate read-side table from write-side data."""

    phase = HookPhase.AFTER_DDL

    async def execute(self, conn, context):
        # After creating r_customer_lifetime_value table,
        # populate from orders (write side)
        await conn.execute("""
            INSERT INTO r_customer_lifetime_value (
                id, tenant_id, customer_id, total_spent, order_count
            )
            SELECT
                gen_random_uuid(),
                tenant_id,
                customer_id,
                SUM(amount),
                COUNT(*)
            FROM orders
            GROUP BY tenant_id, customer_id
        """)
        return HookResult(rows_affected=context.get_stats())
```

**2. Data Consistency Validation**
```python
class ConstraintValidationHook(Hook):
    """Verify no existing data violates new constraint."""

    phase = HookPhase.AFTER_VALIDATION

    async def execute(self, conn, context):
        violations = await conn.execute("""
            SELECT COUNT(*) FROM users
            WHERE email IS NULL OR email = ''
        """).scalar()

        if violations > 0:
            raise MigrationValidationError(
                f"Found {violations} NULL emails - "
                f"cannot add NOT NULL constraint"
            )
        return HookResult(validation_passed=True)
```

**3. Rollback Triggers**
```python
class CreateRollbackTriggerHook(Hook):
    """Create triggers to support rollback."""

    phase = HookPhase.BEFORE_DDL

    async def execute(self, conn, context):
        await conn.execute("""
            CREATE TRIGGER undo_column_drop
            BEFORE DELETE ON pg_class
            FOR EACH ROW
            WHEN (OLD.relname = 'users' AND NEW.relname IS NULL)
            EXECUTE FUNCTION restore_dropped_column()
        """)
```

#### Configuration Format

```yaml
# confiture-migrations/003_add_user_analytics.yaml
migration:
  name: 003_add_user_analytics
  description: Add analytics read model from user events

  hooks:
    before_validation:
      - type: backup_database
        config:
          backup_dir: /backups
          compression: gzip

    before_ddl:
      - type: capture_statistics
        config:
          capture_row_counts: true
          capture_table_sizes: true

    after_ddl:
      - type: backfill_read_model
        config:
          source_table: events
          target_table: r_user_analytics
          batch_size: 10000
          parallel_workers: 4

      - type: rebuild_index
        config:
          indexes:
            - idx_r_user_analytics_user_id
            - idx_r_user_analytics_date

    after_validation:
      - type: verify_consistency
        config:
          source_target_joins:
            - source: events
              target: r_user_analytics
              join_key: user_id
              expected_ratio: 1.0

      - type: test_application_queries
        config:
          query_file: tests/queries/analytics_queries.sql

    cleanup:
      - type: drop_temporary_tables

      - type: analyze_statistics
```

#### Implementation Details

**Hook Registry & Discovery**:
```python
class HookRegistry:
    """Central registry for all available hooks."""

    _builtin_hooks = {
        'backup_database': BackupDatabaseHook,
        'capture_statistics': CaptureStatisticsHook,
        'backfill_read_model': BackfillReadModelHook,
        'rebuild_index': RebuildIndexHook,
        'verify_consistency': VerifyConsistencyHook,
        'test_application_queries': TestApplicationQueriesHook,
    }

    def register_custom_hook(self, name: str, hook_class: type[Hook]):
        """Allow projects to register custom hooks."""
        self._builtin_hooks[name] = hook_class

    def get_hook(self, name: str, config: dict) -> Hook:
        """Instantiate hook by name with configuration."""
        hook_class = self._builtin_hooks[name]
        return hook_class(**config)
```

**Hook Execution with Error Handling**:
```python
class HookExecutor:
    """Execute hooks with proper transaction management."""

    async def execute_phase(
        self,
        conn: AsyncConnection,
        phase: HookPhase,
        hooks: list[Hook],
        context: HookContext
    ) -> list[HookResult]:
        """Execute all hooks in a phase."""
        results = []

        # Use savepoint for each hook (allows partial rollback)
        async with conn.transaction():
            for hook in hooks:
                try:
                    savepoint = await conn.savepoint()
                    result = await hook.execute(conn, context)
                    results.append(result)
                except Exception as e:
                    await savepoint.rollback()

                    # Execute error handlers
                    for error_hook in context.error_handlers:
                        await error_hook.execute(conn, context, error=e)

                    raise MigrationHookError(
                        phase=phase,
                        hook=hook,
                        error=e
                    ) from e

        return results
```

---

### Feature 2: Custom Anonymization Strategies

#### Purpose

Enhance Phase 3's basic anonymization with:
- Pattern-based rules (email masking, phone formatting)
- Deterministic hashing (UUID consistency across tables)
- Conditional strategies (role-based, table-based)
- Environment-specific profiles (local, test, qa, staging, production)
- Custom user-defined transformations

#### Current State (Phase 3)

```python
# Phase 3: Basic anonymization (limited)
anonymizer = SyncAnonymizer(
    rules={
        "users.email": mask_email,
        "users.phone": mask_phone,
    }
)
```

#### Phase 4 Enhancement

```python
# Phase 4: Advanced anonymization strategies
class AnonymizationStrategy(ABC):
    """Base class for anonymization strategies."""

    @abstractmethod
    def transform(self, value: Any, row_context: dict) -> Any:
        """Transform value according to strategy rules."""
        pass

    @abstractmethod
    def is_reversible(self) -> bool:
        """Can this transformation be reversed?"""
        pass

# Built-in strategies
class EmailMaskingStrategy(AnonymizationStrategy):
    """Keep domain, mask local part: user@example.com → user+anon@example.com"""

    def __init__(self, keep_domain: bool = True, prefix: str = "user+"):
        self.keep_domain = keep_domain
        self.prefix = prefix

    def transform(self, value: str, row_context: dict) -> str:
        if not value or '@' not in value:
            return value

        local, domain = value.split('@', 1)
        if self.keep_domain:
            return f"{self.prefix}{uuid.uuid4().hex[:8]}@{domain}"
        else:
            return f"{self.prefix}{uuid.uuid4().hex}@anon.local"

    def is_reversible(self) -> bool:
        return False  # Cannot recover original email

class DeterministicHashStrategy(AnonymizationStrategy):
    """Hash value deterministically (same input → same output)."""

    def __init__(self, salt: str, algorithm: str = 'sha256'):
        self.salt = salt
        self.algorithm = algorithm
        self.hasher = hashlib.new(algorithm)

    def transform(self, value: Any, row_context: dict) -> str:
        input_str = f"{value}:{self.salt}"
        return hashlib.sha256(input_str.encode()).hexdigest()

    def is_reversible(self) -> bool:
        return False  # Hash is one-way

class ConditionalStrategy(AnonymizationStrategy):
    """Apply strategy conditionally based on row data."""

    def __init__(
        self,
        condition: Callable[[dict], bool],
        if_true: AnonymizationStrategy,
        if_false: AnonymizationStrategy | None = None
    ):
        self.condition = condition
        self.if_true = if_true
        self.if_false = if_false

    def transform(self, value: Any, row_context: dict) -> Any:
        if self.condition(row_context):
            return self.if_true.transform(value, row_context)
        elif self.if_false:
            return self.if_false.transform(value, row_context)
        else:
            return value  # Don't anonymize

    def is_reversible(self) -> bool:
        return False

class PatternMaskingStrategy(AnonymizationStrategy):
    """Mask value according to pattern (e.g., SSN: ***-**-9999)."""

    def __init__(self, pattern: str):
        self.pattern = pattern  # Pattern with * for masked chars

    def transform(self, value: str, row_context: dict) -> str:
        value_str = str(value)
        if len(value_str) != len(self.pattern):
            return value_str  # Can't apply pattern

        result = []
        for i, (char, mask) in enumerate(zip(value_str, self.pattern)):
            if mask == '*':
                result.append('*')
            else:
                result.append(char)
        return ''.join(result)

    def is_reversible(self) -> bool:
        return False

class NoAnonymizationStrategy(AnonymizationStrategy):
    """Keep value unchanged (useful for conditional rules)."""

    def transform(self, value: Any, row_context: dict) -> Any:
        return value

    def is_reversible(self) -> bool:
        return True  # No change = reversible
```

#### Configuration Format

```yaml
# confiture-environments/qa-anonymization.yaml
anonymization_profile: qa
description: |
  Safe for QA team (real-looking but anonymous data)
  - Names: kept intact for readability
  - Emails: masked domain
  - Sensitive: fully anonymized

strategies:
  email_mask:
    type: email_masking
    keep_domain: true
    prefix: "qa+"

  phone_mask:
    type: pattern_masking
    pattern: "***-***-9999"

  ssn_mask:
    type: pattern_masking
    pattern: "***-**-####"  # Keep last 4 digits

  uuid_hash:
    type: deterministic_hash
    salt: "${QA_ANON_SALT}"  # From environment variable
    algorithm: sha256

rules:
  - table: users
    columns:
      first_name:
        strategy: none  # Keep names readable for QA
      last_name:
        strategy: none
      email:
        strategy: email_mask
      phone:
        strategy: phone_mask
      ssn:
        strategy: ssn_mask
      password_hash:
        strategy: uuid_hash  # Hash for consistency

  - table: customers
    columns:
      contact_email:
        strategy: email_mask
      contact_phone:
        strategy: phone_mask
      tax_id:
        strategy: ssn_mask

  - table: orders
    columns:
      customer_id:
        # Conditional: keep internal customer IDs, anonymize external
        type: conditional
        condition: |
          row['is_internal_customer'] == true
        if_true:
          strategy: none
        if_false:
          strategy: uuid_hash

  - table: admin_logs
    # Special handling: don't sync to QA at all
    strategy: skip_table
```

#### PrintOptim-Specific Example

```yaml
# confiture-environments/test-anonymization-printoptim.yaml
anonymization_profile: test
description: Test environment - strong anonymization

strategies:
  email_mask:
    type: email_masking
    keep_domain: false
    prefix: "test+"

  phone_mask:
    type: pattern_masking
    pattern: "555-5555"

  tenant_hash:
    type: deterministic_hash
    salt: "${TEST_TENANT_SALT}"

rules:
  # Common schema
  - table: audit_log
    strategy: skip_table  # Never sync audit logs

  - table: entity_change_log
    strategy: skip_table  # Never sync change history

  # Write side
  - table: w_customers
    columns:
      email:
        strategy: email_mask
      phone:
        strategy: phone_mask
      tenant_id:
        # CRITICAL: Must keep tenant_id for data integrity!
        strategy: none

  - table: w_orders
    columns:
      tenant_id:
        strategy: none  # Keep for relational integrity
      payment_method:
        strategy: uuid_hash  # Mask payment data
      billing_address:
        strategy: none  # Address OK for testing

  # Read side
  - table: r_customer_lifetime_value
    columns:
      tenant_id:
        strategy: none
      customer_id:
        # Mask but keep deterministic (consistent with w_customers)
        strategy: uuid_hash
      total_spent:
        # Randomize amounts to protect real data
        type: custom
        strategy: random_in_range
        min: 100
        max: 50000
```

#### Verification & Compliance

```python
class AnonymizationVerifier:
    """Verify anonymization rules and compliance."""

    async def verify_profile(
        self,
        profile: AnonymizationProfile,
        source_db: str,
        sample_size: int = 100
    ) -> AnonymizationVerificationReport:
        """Verify anonymization profile is safe to use."""

        report = AnonymizationVerificationReport()

        for rule in profile.rules:
            table_name = rule.table

            # Sample rows from source
            rows = await self.sample_table(source_db, table_name, sample_size)

            for row in rows:
                for column, strategy in rule.columns.items():
                    original = row[column]
                    anonymized = strategy.transform(original, row)

                    # Check: anonymization occurred
                    if original == anonymized and not strategy.is_reversible():
                        report.add_warning(
                            f"{table_name}.{column}: "
                            f"Strategy didn't modify value"
                        )

                    # Check: deterministic hashes are consistent
                    if isinstance(strategy, DeterministicHashStrategy):
                        anonymized_2 = strategy.transform(original, row)
                        if anonymized != anonymized_2:
                            report.add_error(
                                f"{table_name}.{column}: "
                                f"Hash not deterministic!"
                            )

        return report
```

---

### Feature 3: Interactive Migration Wizard

#### Purpose

Guide operators through complex migrations safely:
- Analyze schema changes and identify risks
- Suggest best practices and optimizations
- Preview SQL before execution
- Provide estimated execution time
- Create rollback strategy
- Support interactive decision-making

#### User Experience Flow

```
$ confiture migrate --interactive --env production

╔════════════════════════════════════════════════════════════╗
║         Confiture Interactive Migration Wizard             ║
╚════════════════════════════════════════════════════════════╝

 📊 Analyzing pending migrations...
    ├─ 001_add_order_timestamp
    ├─ 002_add_customer_segment
    └─ 003_backfill_analytics

 ✓ Analysis complete. Found 3 migrations.

────────────────────────────────────────────────────────────

 🔍 Migration: 001_add_order_timestamp
    └─ ALTER TABLE orders ADD COLUMN created_at TIMESTAMP

    ⚠️  Risk Assessment:
        ├─ Backward compatibility: LOW
        │  └─ Adding nullable column, safe for existing code
        ├─ Data loss risk: NONE
        ├─ Performance risk: MEDIUM
        │  └─ Adding column to 5.2M row table (est. 3-5s)
        └─ Locking risk: LOW
           └─ No primary key changes, quick operation

    💡 Recommendations:
        ├─ Set default value to reduce lock time
        ├─ Consider CONCURRENTLY if on PostgreSQL 11+
        └─ Run during off-peak hours (current: peak)

    🔄 Rollback Strategy: ALTER TABLE ONLY
       └─ Can be undone quickly with DROP COLUMN

    Proceed with this migration? [y/n/preview/skip] > preview

    SQL to execute:
    ┌─────────────────────────────────────────────────┐
    │ ALTER TABLE orders                              │
    │   ADD COLUMN created_at TIMESTAMP DEFAULT NOW()│
    │ ;                                               │
    │                                                 │
    │ CREATE INDEX idx_orders_created_at              │
    │   ON orders(created_at);                        │
    └─────────────────────────────────────────────────┘

    Estimated execution time: 4.2 seconds
    Estimated downtime: < 100ms

    Continue? [y/n] > y

 ✓ 001_add_order_timestamp: COMPLETED (3.9s)

────────────────────────────────────────────────────────────

 🔍 Migration: 002_add_customer_segment
    └─ ALTER TABLE customers ADD COLUMN segment VARCHAR(50)
    └─ Hooks: backfill_segment_from_orders (after DDL)

    ⚠️  Risk Assessment:
        ├─ Backward compatibility: MEDIUM
        │  └─ Code must handle new column, may affect queries
        ├─ Data loss risk: NONE
        ├─ Performance risk: HIGH
        │  └─ Backfill hook will process 2.1M rows (est. 15-20s)
        └─ Locking risk: MEDIUM
           └─ Hook uses temporary table, holds lock during backfill

    💡 Recommendations:
        ├─ ⭐ Deploy application code BEFORE this migration
        ├─ ⭐ Run during maintenance window
        ├─ Consider batch backfill: 10k rows at a time
        └─ Monitor lock times during execution

    🔄 Rollback Strategy: Trigger-based
       └─ Before/after hooks log row counts for verification

    Hooks that will execute:
    ├─ BEFORE_DDL:
    │  └─ capture_statistics
    ├─ AFTER_DDL:
    │  └─ backfill_segment_from_orders (est. 18s)
    ├─ AFTER_VALIDATION:
    │  └─ verify_consistency (check row counts)
    └─ CLEANUP:
       └─ analyze_statistics

    Execute all hooks with this migration? [y/n/details] > details

    Hook: backfill_segment_from_orders
    ├─ Type: Custom Python callable
    ├─ Estimated rows: 2,100,000
    ├─ Batch size: 50,000
    ├─ Parallel workers: 4
    └─ Estimated time: 18 seconds

    Timeout: 300s (5 minutes)
    Retry on failure: 3 attempts

    Continue? [y/n] > y

 ⏳ 002_add_customer_segment: IN PROGRESS...
    ├─ DDL: COMPLETED (0.3s)
    ├─ Hook [1/4] capture_statistics: COMPLETED (0.1s)
    ├─ Hook [2/4] backfill_segment_from_orders: IN PROGRESS...
    │  └─ Batch 1/42: 50,000 rows (0.2s elapsed)
    │  └─ Batch 2/42: 50,000 rows (0.4s elapsed)
    │  └─ [████████░░░░░░░░░░░] 25% complete

    (Showing live progress)

 ✓ 002_add_customer_segment: COMPLETED (18.7s)

────────────────────────────────────────────────────────────

 🔍 Migration: 003_backfill_analytics
    └─ CREATE TABLE r_analytics AS SELECT ...
    └─ Hooks: rebuild_indexes (after DDL)

    (Continuing with similar detailed analysis...)

────────────────────────────────────────────────────────────

 📋 Summary:
    ├─ Migrations: 3 completed
    ├─ Total time: 26.6 seconds
    ├─ Hooks executed: 9 successful
    └─ Issues: 0 errors, 2 warnings

 ⚠️  Warnings:
    ├─ 002_add_customer_segment: Lock time exceeded 1s
    │  └─ Monitor application response times
    └─ 003_backfill_analytics: Index creation slow
       └─ Consider running ANALYZE after migration

 ✅ All migrations completed successfully!

    Review what was changed?
    [y/n] > y

 📝 Change Summary:
    Migrations: 3
    ├─ Added columns: 2
    ├─ Created indexes: 3
    ├─ Created tables: 1
    └─ Rows modified: 2,100,000

 🔄 To rollback, run:
    $ confiture migrate down --migration 003
    $ confiture migrate down --migration 002
    $ confiture migrate down --migration 001

────────────────────────────────────────────────────────────
```

#### Implementation Architecture

```python
class InteractiveMigrationWizard:
    """Guide user through migrations with analysis and recommendations."""

    async def run(
        self,
        env: str,
        migrations: list[Migration],
        dry_run: bool = False
    ) -> WizardResult:
        """Run interactive wizard for migration execution."""

        result = WizardResult()

        for migration in migrations:
            # 1. Analyze migration
            analysis = await self.analyzer.analyze(migration, env)

            # 2. Present risk assessment
            await self._present_analysis(analysis)

            # 3. Get user decision
            decision = await self._prompt_user(
                f"Proceed with {migration.name}?",
                options=['yes', 'no', 'preview', 'skip', 'details']
            )

            if decision == 'preview':
                await self._show_sql(migration)
                decision = await self._prompt_user("Execute?")

            if decision in ['yes', 'execute']:
                # 4. Execute migration
                exec_result = await self.executor.execute(
                    migration,
                    env=env,
                    dry_run=dry_run,
                    progress_callback=self._show_progress
                )
                result.add_execution(exec_result)

            elif decision == 'skip':
                result.add_skipped(migration)

        # 5. Show summary
        await self._show_summary(result)

        return result
```

#### Risk Assessment Engine

```python
class RiskAssessmentEngine:
    """Analyze migrations for risks and provide recommendations."""

    async def analyze(self, migration: Migration, env: str) -> RiskAssessment:
        """Analyze migration for risks."""

        assessment = RiskAssessment(migration=migration)

        # Parse DDL to understand changes
        changes = await self.parser.parse_ddl(migration.sql)

        for change in changes:
            if isinstance(change, ColumnDrop):
                assessment.add_risk(
                    category="data_loss",
                    severity="critical",
                    message=f"Dropping column {change.column} is irreversible"
                )

            elif isinstance(change, ColumnAdd):
                # Check if column is nullable or has default
                if not change.nullable and not change.default:
                    assessment.add_warning(
                        f"Adding NOT NULL column {change.column} without default"
                    )

                # Estimate lock time
                table_size = await self._get_table_size(env, change.table)
                lock_time = self._estimate_lock_time(table_size, change)
                assessment.add_performance_metric(
                    metric="lock_time",
                    value=lock_time,
                    severity=self._assess_lock_severity(lock_time)
                )

            elif isinstance(change, IndexCreate):
                # Estimate index creation time
                table_size = await self._get_table_size(env, change.table)
                creation_time = self._estimate_index_time(table_size, change)
                assessment.add_performance_metric(
                    metric="index_creation_time",
                    value=creation_time
                )

            elif isinstance(change, ConstraintAdd):
                # Check if existing data violates constraint
                violations = await self._check_constraint_violations(
                    env, change.table, change.constraint
                )
                if violations > 0:
                    assessment.add_risk(
                        category="constraint_violation",
                        severity="critical",
                        message=f"Found {violations} rows violating new constraint"
                    )

        # Generate recommendations
        assessment.recommendations = self._generate_recommendations(assessment)

        return assessment
```

---

### Feature 4: Migration Dry-Run Mode

#### Purpose

Test migrations in a transaction that automatically rolls back:
- Execute full migration process
- Capture performance metrics
- Verify no constraint violations
- Test hooks and data transformations
- No permanent changes to database

#### Implementation

```python
class DryRunMigrator(Migrator):
    """Execute migrations in transaction with automatic rollback."""

    async def migrate_up(self, target: str | None = None, dry_run: bool = False):
        """Execute migration with optional dry-run."""

        async with self.pool.connection() as conn:
            if dry_run:
                async with conn.transaction() as txn:
                    try:
                        # Execute entire migration
                        await self._execute_migration(conn, target)

                        # Capture metrics before rollback
                        metrics = await self._capture_metrics(conn)

                        # Automatic rollback on exit
                    except Exception as e:
                        # Still rolls back, but logs error
                        raise DryRunError(error=e, metrics=metrics)
            else:
                # Normal execution with commit
                await self._execute_migration(conn, target)
```

#### Metrics Captured During Dry-Run

```python
@dataclass
class DryRunMetrics:
    """Metrics captured during dry-run execution."""

    # Timing
    total_execution_time: float
    ddl_execution_time: float
    hook_execution_times: dict[str, float]

    # Data changes
    rows_inserted: int
    rows_updated: int
    rows_deleted: int

    # Lock times
    table_lock_duration: dict[str, float]
    max_lock_duration: float

    # Index changes
    indexes_created: list[str]
    indexes_dropped: list[str]
    index_creation_times: dict[str, float]

    # Constraint changes
    constraints_added: list[str]
    constraints_removed: list[str]

    # Violations found
    constraint_violations: list[str]
    data_inconsistencies: list[str]

    # Estimates for production
    estimated_production_time: float
    estimated_downtime: float
    confidence_level: float  # 0-100%, based on data variance
```

#### Usage Examples

```bash
# Dry-run single migration
$ confiture migrate up --target 003 --dry-run --env production

 ⏳ Running migration 003 in dry-run mode...
    (in transaction, will rollback)

 ✓ DDL execution: 2.3s
 ✓ Hooks executed: 4 (total 5.1s)
 ✓ Data consistency check: passed
 ✓ Constraints verified: 12/12 OK

 📊 Metrics:
    ├─ Rows affected: 152,340
    ├─ Max lock time: 850ms
    ├─ Index creation: 3.2s
    └─ Total time: 10.6s

 📈 Estimated production impact:
    ├─ Execution time: 11-13s (±15%)
    ├─ Expected downtime: < 500ms
    └─ Confidence: 92%

 ✅ Dry-run successful! Safe to deploy.

# Dry-run with detailed analysis
$ confiture migrate up --target 003 --dry-run --show-sample-rows --env production

 ✓ Data sample before/after:

    Table: orders (152k rows affected)
    ┌────────┬────────────┬──────────┐
    │ id     │ amount     │ status   │
    ├────────┼────────────┼──────────┤
    │ 1000   │ 150.00     │ pending  │  → status: 'draft'
    │ 1001   │ 275.50     │ pending  │  → status: 'draft'
    │ 1002   │ 99.99      │ pending  │  → status: 'draft'
    └────────┴────────────┴──────────┘

# Preview SQL without executing
$ confiture migrate up --target 003 --preview --env production

 SQL to be executed:
 ┌────────────────────────────────────┐
 │ BEGIN;                              │
 │ ALTER TABLE orders ADD COLUMN ...   │
 │ CREATE INDEX idx_orders_status ...  │
 │ ... (10 more DDL statements)        │
 │ COMMIT;                             │
 └────────────────────────────────────┘
```

---

### Feature 5: Database Schema Linting

#### Purpose

Validate schemas against best practices and standards:
- Naming conventions (snake_case, PascalCase)
- Performance rules (missing indexes, N+1 patterns)
- Security checks (implicit casts, unlogged tables in production)
- Documentation requirements (comments, descriptions)
- Multi-tenant rules (tenant_id required in certain tables)

#### Architecture

```python
class SchemaLinter:
    """Lint database schema against defined rules."""

    def __init__(self, config: LintConfig):
        self.config = config
        self.rules = self._load_rules(config)

    async def check(
        self,
        env: str,
        schema: str = "public",
        fail_on_severity: str = "error"
    ) -> LintReport:
        """Check schema for lint violations."""

        report = LintReport()

        async with self.pool.connection() as conn:
            # Load schema metadata
            schema_info = await self._load_schema_info(conn, schema)

            # Apply all rules
            for rule in self.rules:
                violations = await rule.check(conn, schema_info)
                report.add_violations(violations)

        # Apply fail threshold
        if report.max_severity >= fail_on_severity:
            raise LintError(report=report)

        return report
```

#### Built-in Rules

```python
class NamingConventionRule(LintRule):
    """Enforce naming conventions."""

    async def check(self, conn, schema_info) -> list[Violation]:
        violations = []

        for table in schema_info.tables:
            # Tables: snake_case
            if not self._is_snake_case(table.name):
                violations.append(Violation(
                    severity="warning",
                    category="naming",
                    message=f"Table '{table.name}' is not snake_case",
                    location=f"{schema_info.name}.{table.name}",
                    suggestion=self._to_snake_case(table.name)
                ))

            # Columns: snake_case
            for column in table.columns:
                if not self._is_snake_case(column.name):
                    violations.append(Violation(
                        severity="warning",
                        category="naming",
                        message=f"Column '{column.name}' is not snake_case",
                        location=f"{schema_info.name}.{table.name}.{column.name}",
                        suggestion=self._to_snake_case(column.name)
                    ))

        # Types: PascalCase
        for type_obj in schema_info.types:
            if not self._is_pascal_case(type_obj.name):
                violations.append(Violation(
                    severity="warning",
                    category="naming",
                    message=f"Type '{type_obj.name}' is not PascalCase",
                    location=f"{schema_info.name}.{type_obj.name}",
                    suggestion=self._to_pascal_case(type_obj.name)
                ))

        return violations

class PrimaryKeyRule(LintRule):
    """Require primary key on all tables."""

    async def check(self, conn, schema_info) -> list[Violation]:
        violations = []

        for table in schema_info.tables:
            if table.primary_key is None:
                violations.append(Violation(
                    severity="error",
                    category="performance",
                    message=f"Table '{table.name}' has no primary key",
                    location=f"{schema_info.name}.{table.name}",
                    suggestion="Add PRIMARY KEY constraint"
                ))

        return violations

class DocumentationRule(LintRule):
    """Require documentation on tables and important columns."""

    async def check(self, conn, schema_info) -> list[Violation]:
        violations = []

        for table in schema_info.tables:
            # All public tables need comments
            if table.visibility == "public" and not table.comment:
                violations.append(Violation(
                    severity="warning",
                    category="documentation",
                    message=f"Table '{table.name}' has no COMMENT",
                    location=f"{schema_info.name}.{table.name}",
                    suggestion=f"COMMENT ON TABLE {table.name} IS 'Description of {table.name}';"
                ))

        return violations

class MultiTenantRule(LintRule):
    """Enforce tenant_id in multi-tenant tables."""

    def __init__(self, config: dict):
        super().__init__()
        self.exempt_tables = config.get('exempt_tables', [])
        self.required_column = config.get('required_column', 'tenant_id')

    async def check(self, conn, schema_info) -> list[Violation]:
        violations = []

        for table in schema_info.tables:
            # Skip system/exempt tables
            if table.name.startswith('_') or table.name in self.exempt_tables:
                continue

            # Check for tenant_id column
            has_tenant = any(
                col.name == self.required_column
                for col in table.columns
            )

            if not has_tenant:
                violations.append(Violation(
                    severity="error",
                    category="multi_tenant",
                    message=f"Table '{table.name}' is missing '{self.required_column}'",
                    location=f"{schema_info.name}.{table.name}",
                    suggestion=f"ADD COLUMN {self.required_column} UUID NOT NULL REFERENCES tenants(id);"
                ))

        return violations

class MissingIndexRule(LintRule):
    """Detect foreign keys without indexes (N+1 risk)."""

    async def check(self, conn, schema_info) -> list[Violation]:
        violations = []

        for table in schema_info.tables:
            for constraint in table.foreign_keys:
                # Check if FK column is indexed
                is_indexed = any(
                    constraint.column in index.columns
                    for index in table.indexes
                )

                if not is_indexed:
                    violations.append(Violation(
                        severity="warning",
                        category="performance",
                        message=f"Foreign key '{constraint.name}' on "
                                f"'{table.name}' is not indexed (N+1 risk)",
                        location=f"{schema_info.name}.{table.name}",
                        suggestion=f"CREATE INDEX ON {table.name}({constraint.column});"
                    ))

        return violations

class SecurityRule(LintRule):
    """Check for security issues (implicit casts, etc)."""

    async def check(self, conn, schema_info) -> list[Violation]:
        violations = []

        for table in schema_info.tables:
            for column in table.columns:
                # Warn about storing passwords without hashing
                if 'password' in column.name and column.type not in ['bytea', 'text']:
                    violations.append(Violation(
                        severity="error",
                        category="security",
                        message=f"Password column '{column.name}' has wrong type",
                        location=f"{schema_info.name}.{table.name}.{column.name}",
                        suggestion=f"Use bytea or ensure hashing in application code"
                    ))

                # Warn about unlogged tables in production
                if table.unlogged and env == "production":
                    violations.append(Violation(
                        severity="error",
                        category="security",
                        message=f"Table '{table.name}' is UNLOGGED (unsafe for production)",
                        location=f"{schema_info.name}.{table.name}",
                        suggestion="Remove UNLOGGED or move to non-production environment"
                    ))

        return violations
```

#### Configuration Format

```yaml
# confiture.yaml - linting configuration
linting:
  enabled: true
  fail_on_severity: error

  rules:
    naming_convention:
      enabled: true
      tables: snake_case
      columns: snake_case
      functions: snake_case_pl
      types: PascalCase
      indexes: idx_{table}_{columns}
      constraints: "{type}_{table}_{columns}"

    documentation:
      enabled: true
      require_table_comments: true
      require_column_comments:
        - public_tables_only: true
        - exemptions:
            - created_at
            - updated_at
            - id

    performance:
      enabled: true
      rules:
        - primary_key_required: error
        - foreign_key_indexed: warning
        - large_table_has_indexes: warning
        - sequential_scan_potential: warning

    multi_tenant:
      enabled: true
      required_column: tenant_id
      exempt_tables:
        - pg_*
        - information_schema.*
        - system_config
        - audit_*

    security:
      enabled: true
      rules:
        - no_unlogged_tables_in_production: error
        - no_implicit_casts: warning
        - password_fields_must_be_hashed: error
        - sensitive_columns_must_be_masked: error

  custom_rules:
    - name: write_side_naming
      description: Write-side tables must start with w_
      pattern: "^w_.*"
      affected_schema: 01_write_side
      severity: error

    - name: read_side_naming
      description: Read-side tables must start with r_
      pattern: "^r_.*"
      affected_schema: 02_query_side
      severity: error
```

#### CLI Usage

```bash
# Check schema linting
$ confiture lint --env production

 🔍 Linting schema in production database...
    ├─ Checking 145 tables
    ├─ Checking 1,256 columns
    ├─ Checking 890 indexes
    └─ Checking 345 constraints

 ❌ Found 12 lint violations:

 ERRORS (3):
 ├─ 001: Table 'UserAccount' is not snake_case
 │       └─ Suggestion: Rename to 'user_account'
 ├─ 002: Table 'customers' is missing 'tenant_id'
 │       └─ Suggestion: ADD COLUMN tenant_id UUID NOT NULL REFERENCES tenants(id);
 └─ 003: Foreign key on orders(customer_id) is not indexed
          └─ Suggestion: CREATE INDEX ON orders(customer_id);

 WARNINGS (9):
 ├─ 004: Column 'user_id' in table 'audit_log' could be indexed
 ├─ 005: Table 'legacy_events' has no COMMENT
 └─ ... (6 more)

 Exit code: 1 (failed due to errors)

# Generate linting report
$ confiture lint --env production --report html > report.html

# Fix linting issues automatically
$ confiture lint --fix --env production

 🔧 Auto-fixing lint violations...
    ├─ ✓ Renamed 2 tables to snake_case
    ├─ ✓ Added 3 missing documentation comments
    └─ ⚠️  5 violations require manual review

# Lint specific schema
$ confiture lint --env production --schema 02_query_side

 🔍 Linting 02_query_side schema...
    ├─ Checking 67 tables
    └─ ✓ All tables follow naming convention (r_*)
```

---

## Integration Architecture

### System Overview

```
┌────────────────────────────────────────────────────────────────┐
│                    Development Workflow                        │
└────────────────────────────────────────────────────────────────┘
                                │
                ┌───────────────┴───────────────┐
                ▼                               ▼
        ┌──────────────────┐          ┌──────────────────┐
        │   Developer      │          │   Database       │
        │   Writes SQL     │          │   Evolution      │
        │  Files (DDL)     │          │   Tracking       │
        └─────────┬────────┘          └────────┬─────────┘
                  │                           │
                  ▼                           ▼
        ┌──────────────────────────┐
        │      pggit               │
        │   (Git-like VCS)         │
        ├──────────────────────────┤
        │ • Captures DDL changes   │
        │ • Version history        │
        │ • Branching/Merging      │
        │ • Audit trail            │
        └────────────┬─────────────┘
                     │
                     ▼
        ┌──────────────────────────┐
        │    Confiture Phase 4     │
        │ (Schema Governance)      │
        ├──────────────────────────┤
        │ • Detect changes         │
        │ • Linting & validation   │
        │ • Risk assessment        │
        │ • Interactive wizard     │
        │ • Dry-run testing        │
        │ • Hook execution         │
        │ • Anonymization          │
        └────────────┬─────────────┘
                     │
        ┌────────────┴────────────┐
        ▼                         ▼
    ┌──────────────┐      ┌──────────────┐
    │  Staging DB  │      │   Prod DB    │
    │ (FDW sync)   │      │ (Zero-DT)    │
    └──────────────┘      └──────────────┘
```

### Integration Points

#### 1. pggit → Confiture: Schema Discovery

**Current State**:
- pggit captures DDL changes as audit trail
- Confiture discovers schemas from filesystem

**Phase 4 Integration**:
```python
# confiture/core/builder.py
class SchemaBuilder:
    async def build_from_git_history(self, env: str, ref: str = "main"):
        """Build schema from pggit reference instead of files."""
        pggit_client = PggitClient(database=env)

        # Get schema state at specific git ref
        ddl_statements = await pggit_client.get_schema_at_ref(ref)

        # Use Confiture's normal build process
        return self._concatenate_ddl(ddl_statements)

    async def diff_against_git_ref(self, env: str, ref: str = "main"):
        """Compare current schema against historical pggit ref."""
        current = await self.build_schema(env)
        historical = await self.build_from_git_history(env, ref)

        return self.differ.diff(historical, current)
```

**Benefits**:
- Query any historical version of schema
- Compare branches before merging
- Understand schema evolution
- Audit trail automatically maintained

#### 2. Confiture → pggit: Change Registration

**Current State**:
- Confiture applies migrations independently
- pggit captures changes via DDL triggers

**Phase 4 Enhancement**:
```python
# confiture/core/migrator.py
class Migrator:
    async def migrate_up(self, target: str | None = None):
        """Apply migration and register with pggit."""

        # Execute migration
        result = await self._execute_migration(target)

        # Notify pggit of successful migration
        pggit = PggitClient(database=self.env)
        await pggit.register_event(
            type="MIGRATION_APPLIED",
            name=target,
            timestamp=datetime.now(),
            applied_by=os.getenv("USER"),
            duration=result.execution_time,
            status="SUCCESS"
        )

        return result

    async def rollback(self, migration_name: str):
        """Rollback migration and register with pggit."""

        result = await self._execute_rollback(migration_name)

        pggit = PggitClient(database=self.env)
        await pggit.register_event(
            type="MIGRATION_ROLLED_BACK",
            name=migration_name,
            timestamp=datetime.now(),
            applied_by=os.getenv("USER"),
            status="SUCCESS"
        )

        return result
```

**Benefits**:
- Full audit trail of all migrations
- Who applied what, when
- Correlation with git commits
- Ability to replay history

#### 3. PrintOptim Structure → Confiture Configuration

**Current PrintOptim Structure**:
```
db/0_schema/
├── 00_common/          # Shared: security, functions, types
├── 01_write_side/      # CQRS write model (commands)
├── 02_query_side/      # CQRS read model (queries)
├── 03_functions/       # Stored procedures
└── 019_prep_seed/      # Seed data (applied last)
```

**Phase 4 Configuration**:
```yaml
# confiture.yaml for PrintOptim
environment:
  name: production

  # Load order critical for dependencies
  load_order:
    - db/0_schema/00_common/000_security      # Roles first
    - db/0_schema/00_common/001_extensions    # PL/pgSQL, etc
    - db/0_schema/00_common/001_functions     # Helper functions
    - db/0_schema/00_common/002_versioning    # Version tracking
    - db/0_schema/00_common/**/*              # Rest of common
    - db/0_schema/01_write_side/**/*          # Write side
    - db/0_schema/02_query_side/**/*          # Read side
    - db/0_schema/03_functions/**/*           # Stored procedures
    - db/0_schema/019_prep_seed/**/*          # Seed data last

  hooks:
    # After write-side changes, rebuild read models
    after_migration:
      - type: rebuild_read_models
        condition: "migration_name contains '01_write_side'"
        action: |
          SELECT * INTO r_customer_lifetime_value
          FROM compute_clv();

  linting:
    # PrintOptim-specific rules
    multi_tenant:
      enabled: true
      required_column: tenant_id
      exempt_tables:
        - audit_*
        - entity_change_log
        - system_*

    naming_conventions:
      write_side: "^w_"         # All write tables: w_*
      read_side: "^r_"          # All read tables: r_*
      functions: "^fn_"         # Functions: fn_*

    cqrs_validation:
      # Ensure read models are derived from write models
      read_model_sources:
        r_customer_lifetime_value:
          - w_customers
          - w_orders
        r_inventory_summary:
          - w_inventory
```

**Benefits**:
- Confiture understands PrintOptim structure
- Automatic validation of CQRS relationships
- Enforcement of multi-tenant constraints
- Systematic approach to schema governance

---

## Implementation Roadmap

### Timeline & Milestones

**Phase 4: Advanced Features (Q1 2026)**

#### Milestone 4.1: Migration Hooks & Dry-Run (Weeks 1-2)

**Objective**: Implement hook system and dry-run capability

**RED Phase**:
```python
# tests/unit/test_hooks.py
def test_before_ddl_hook_executes():
    migration = Migration(name="test", forward_hooks=[BeforeDDL(...)])
    assert migration.forward_hooks is not None

def test_dry_run_rolls_back():
    result = migrator.migrate_up(target="001", dry_run=True)
    assert result.rolled_back == True
```

**GREEN Phase**:
- Implement Hook base class and registry
- Implement DryRunMigrator
- Add hook execution in migration pipeline

**REFACTOR Phase**:
- Extract hook execution into separate module
- Add hook error handling with savepoints
- Document hook APIs

**QA Phase**:
```bash
uv run pytest tests/unit/test_hooks.py -v
uv run pytest tests/integration/test_dry_run.py -v
uv run ruff check .
uv run ty check confiture/
```

**Deliverables**:
- [ ] Hook system with 5 phases (BEFORE_VALIDATION, BEFORE_DDL, AFTER_DDL, AFTER_VALIDATION, CLEANUP)
- [ ] Dry-run transaction support with automatic rollback
- [ ] Metrics capture (rows, execution time, lock duration)
- [ ] 20+ tests for hook execution paths
- [ ] Hook error handling with savepoints per hook

#### Milestone 4.2: Interactive Wizard & Linting (Weeks 3-4)

**Objective**: Implement interactive CLI and schema linting

**RED Phase**:
```python
# tests/unit/test_wizard.py
def test_wizard_presents_risk_assessment():
    wizard = InteractiveMigrationWizard()
    analysis = wizard.analyze(migration)
    assert analysis.risk_level in ["low", "medium", "high"]

# tests/unit/test_linting.py
def test_lint_detects_missing_primary_key():
    linter = SchemaLinter(rules=default_rules)
    violations = linter.check(schema)
    assert any(v.category == "primary_key" for v in violations)
```

**GREEN Phase**:
- Implement RiskAssessmentEngine
- Implement SchemaLinter with 5 built-in rules
- Implement InteractiveMigrationWizard (basic prompts)

**REFACTOR Phase**:
- Extract risk calculation into separate module
- Create rule plugin system for custom linting
- Enhance wizard UX with rich formatting

**QA Phase**:
```bash
uv run pytest tests/unit/test_wizard.py -v
uv run pytest tests/unit/test_linting.py -v
uv run pytest tests/e2e/test_interactive_workflow.py -v
```

**Deliverables**:
- [ ] RiskAssessmentEngine with lock time estimation
- [ ] SchemaLinter with 5+ built-in rules
- [ ] Interactive migration wizard with rich formatting
- [ ] 30+ tests for risk assessment and linting
- [ ] Wizard UX improvements (progress bars, live metrics)

#### Milestone 4.3: Custom Anonymization (Weeks 5-6)

**Objective**: Extend Phase 3 anonymization with custom strategies

**RED Phase**:
```python
# tests/unit/test_anonymization_strategies.py
def test_email_masking_preserves_domain():
    strategy = EmailMaskingStrategy(keep_domain=True)
    result = strategy.transform("user@example.com", {})
    assert result.endswith("@example.com")

def test_deterministic_hash_is_consistent():
    strategy = DeterministicHashStrategy(salt="test-salt")
    h1 = strategy.transform("sensitive-data", {})
    h2 = strategy.transform("sensitive-data", {})
    assert h1 == h2
```

**GREEN Phase**:
- Implement AnonymizationStrategy base class
- Implement 4+ built-in strategies (Email, Hash, Pattern, Conditional)
- Integrate with Phase 3 syncer

**REFACTOR Phase**:
- Create strategy composition system
- Add YAML configuration support
- Implement AnonymizationVerifier

**QA Phase**:
```bash
uv run pytest tests/unit/test_anonymization_strategies.py -v
uv run pytest tests/integration/test_sync_with_anonymization.py -v
```

**Deliverables**:
- [ ] AnonymizationStrategy interface with 4+ implementations
- [ ] YAML configuration for anonymization profiles
- [ ] AnonymizationVerifier for compliance checking
- [ ] 25+ tests for anonymization strategies
- [ ] PrintOptim-specific anonymization profiles

#### Milestone 4.4: pggit Integration (Weeks 7-8)

**Objective**: Connect Confiture with pggit for full audit trail

**RED Phase**:
```python
# tests/integration/test_pggit_integration.py
def test_build_schema_from_pggit_ref():
    builder = SchemaBuilder()
    schema = builder.build_from_git_history("main")
    assert len(schema) > 0

def test_migration_registers_with_pggit():
    migrator = Migrator()
    result = migrator.migrate_up(target="001")
    # Verify pggit has recorded this migration
    assert pggit_client.get_event(type="MIGRATION_APPLIED") is not None
```

**GREEN Phase**:
- Implement PggitAwareBuilder
- Implement PggitAwareMigrator with event registration
- Create PggitClient for API communication

**REFACTOR Phase**:
- Enhance error handling for pggit connection failures
- Add retry logic for unreliable networks
- Create migration history dashboard

**QA Phase**:
```bash
uv run pytest tests/integration/test_pggit_integration.py -v
uv run pytest tests/e2e/test_full_workflow_with_pggit.py -v
```

**Deliverables**:
- [ ] PggitAwareBuilder for querying historical schemas
- [ ] PggitAwareMigrator with event registration
- [ ] PggitClient library for API communication
- [ ] 20+ integration tests with pggit
- [ ] Migration history dashboard (HTML report)

### Detailed TDD Cycles

#### Example: Migration Hooks TDD Cycle

**RED Phase - Write Failing Test**:
```python
# tests/unit/test_hooks.py::test_before_ddl_hook_executes
@pytest.mark.asyncio
async def test_before_ddl_hook_executes():
    """FAILING: Hook system doesn't exist yet."""

    # Define hook
    class CaptureStatsHook(Hook):
        async def execute(self, conn, context):
            result = await conn.execute(
                "SELECT COUNT(*) FROM orders"
            )
            context.stats['initial_rows'] = result.scalar()
            return HookResult(stats=context.stats)

    # Create migration with hook
    migration = Migration(
        name="001_test",
        sql="ALTER TABLE orders ADD COLUMN status VARCHAR(50);",
        forward_hooks={
            HookPhase.BEFORE_DDL: [CaptureStatsHook()]
        }
    )

    # Execute and verify hook ran
    executor = HookExecutor()
    results = await executor.execute_phase(
        conn, HookPhase.BEFORE_DDL, migration.forward_hooks[HookPhase.BEFORE_DDL]
    )

    assert len(results) == 1
    assert results[0].stats['initial_rows'] > 0
```

**Expected Failure**:
```
FAILED - HookExecutor not implemented
```

**GREEN Phase - Minimal Implementation**:
```python
# confiture/core/hooks.py
class Hook(ABC):
    @abstractmethod
    async def execute(self, conn, context):
        pass

class HookPhase(Enum):
    BEFORE_DDL = 2

class HookResult:
    def __init__(self, stats=None):
        self.stats = stats or {}

class HookExecutor:
    async def execute_phase(self, conn, phase, hooks, context):
        results = []
        for hook in hooks:
            result = await hook.execute(conn, context)
            results.append(result)
        return results

# confiture/core/migrator.py
class Migration:
    def __init__(self, name, sql, forward_hooks=None):
        self.name = name
        self.sql = sql
        self.forward_hooks = forward_hooks or {}
```

**Test Now Passes** ✓

**REFACTOR Phase - Clean Up**:
```python
# Extract hook context
class HookContext:
    """Context passed to hooks."""
    def __init__(self, migration, migration_name):
        self.migration = migration
        self.stats = {}

    def get_stats(self):
        return self.stats

# Add error handling with savepoints
class HookExecutor:
    async def execute_phase(self, conn, phase, hooks, context):
        results = []

        async with conn.transaction():
            for hook in hooks:
                # Savepoint per hook allows partial rollback
                async with conn.savepoint() as savepoint:
                    try:
                        result = await hook.execute(conn, context)
                        results.append(result)
                    except Exception as e:
                        await savepoint.rollback()
                        raise HookError(hook=hook, phase=phase, error=e)

        return results

# Add hook registry for discovery
class HookRegistry:
    _builtin_hooks = {}

    @classmethod
    def register(cls, name, hook_class):
        cls._builtin_hooks[name] = hook_class

    @classmethod
    def get(cls, name):
        return cls._builtin_hooks.get(name)
```

**QA Phase - Quality Checks**:
```bash
# All tests pass
$ uv run pytest tests/unit/test_hooks.py -v
# tests/unit/test_hooks.py::test_before_ddl_hook_executes PASSED

# Check code style
$ uv run ruff check confiture/core/hooks.py
# ✓ No style issues

# Type checking
$ uv run ty check confiture/core/hooks.py
# ✓ No type errors

# Test coverage
$ uv run pytest tests/unit/test_hooks.py --cov=confiture/core/hooks
# ✓ 95% coverage

# Add to PHASES.md
$ git commit -m "feat(hooks): implement hook system with savepoint support [GREEN]"
```

---

## Technical Dependencies

### Phase 4 Prerequisites

**From Phase 2 (Rust)**: ✅ Already available
- Rust schema parser (`sqlparser` crate)
- Fast file I/O with parallel processing
- Binary wheels for Python 3.11+

**New Dependencies for Phase 4**:

```toml
# pyproject.toml additions
[project.optional-dependencies]
dev = [
    # ... existing
    "rich>=13.7.0",            # Already installed (for pretty printing)
    "prompt_toolkit>=3.0.0",   # Interactive CLI support
    "sqlglot>=16.0.0",         # SQL parsing/normalization
    "networkx>=3.0",           # Dependency graph analysis
]

hooks = [
    # Optional: for hook extensions
    "pluggy>=1.5.0",           # Plugin system
]

pggit = [
    # Optional: for pggit integration
    # (pggit will provide Python client library)
]
```

**External Systems**:

1. **pggit** (new integration):
   - Requires Python client library (to be developed in pggit Phase 2)
   - HTTP/gRPC API for querying audit trail
   - Event registration API for migrations

2. **PostgreSQL 13+** (already required):
   - Savepoint support ✓
   - JSON functions for complex data ✓
   - EXPLAIN ANALYZE for cost estimation ✓

### Compatibility

**PostgreSQL Versions**:
- 13+: Full support (all Phase 4 features)
- 12: Partial (no JSON validation functions)
- <12: Not supported

**Python Versions**:
- 3.11: Full support
- 3.12: Full support
- 3.13: Full support

**Operating Systems**:
- Linux: Full support
- macOS: Full support
- Windows: WSL recommended (WSL2)

---

## PrintOptim Integration Guide

### Applying Phase 4 to PrintOptim

#### Step 1: Enable Linting for CQRS Validation

```yaml
# printoptim/confiture.yaml
linting:
  enabled: true
  fail_on_severity: error

  custom_rules:
    - name: write_side_tables
      description: "Write-side tables in 01_write_side must start with w_"
      pattern: "^w_"
      affected_dirs:
        - db/0_schema/01_write_side
      severity: error
      example:
        good: "w_customers"
        bad: "customers"

    - name: read_side_tables
      description: "Read-side tables in 02_query_side must start with r_"
      pattern: "^r_"
      affected_dirs:
        - db/0_schema/02_query_side
      severity: error
      example:
        good: "r_customer_lifetime_value"
        bad: "customer_lifetime_value"

    - name: multi_tenant_write_tables
      description: "All write-side tables must have tenant_id"
      affected_dirs:
        - db/0_schema/01_write_side
      severity: error
      exemptions:
        - w_tenant_*  # Tenant tables don't need tenant_id
        - system_*    # System tables

    - name: read_model_derivation
      description: "Read models must be derived from write models"
      examples:
        - source: "w_orders, w_customers"
          target: "r_customer_lifetime_value"
          rule: "r_customer_lifetime_value is VIEW or materialized table from w_orders + w_customers"
```

**Usage**:
```bash
$ confiture lint --env production

✓ Linting PrintOptim schema...
  ├─ Checking 145 tables
  ├─ Write-side naming: 67 tables checked ✓
  ├─ Read-side naming: 34 tables checked ✓
  └─ Tenant_id presence: 23 tables checked ✓

✓ All lint checks passed!
```

#### Step 2: Implement Hooks for Read Model Backfill

```yaml
# printoptim/confiture-migrations/003_add_clv_model.yaml
migration:
  name: 003_add_clv_model
  description: Add customer lifetime value read model

  hooks:
    after_ddl:
      - type: backfill_read_model
        description: "Populate r_customer_lifetime_value from w_orders"
        config:
          source_query: |
            SELECT
              gen_random_uuid() as id,
              tenant_id,
              customer_id,
              SUM(total) as total_spent,
              COUNT(*) as order_count,
              MAX(created_at) as last_order_date
            FROM w_orders
            GROUP BY tenant_id, customer_id
          target_table: r_customer_lifetime_value
          batch_size: 50000
          parallel_workers: 4

    after_validation:
      - type: verify_consistency
        description: "Verify read model matches write side"
        config:
          validation_queries:
            - name: "Row count check"
              query: |
                SELECT
                  COUNT(DISTINCT (tenant_id, customer_id)) as write_side_count,
                  COUNT(*) as read_side_count
                FROM w_orders
                UNION ALL
                SELECT NULL, COUNT(*) FROM r_customer_lifetime_value
              expected_ratio: 1.0

            - name: "Total spent verification"
              query: |
                SELECT
                  SUM(total) as write_side_total,
                  SUM(total_spent) as read_side_total
                FROM w_orders, r_customer_lifetime_value
                WHERE w_orders.tenant_id = r_customer_lifetime_value.tenant_id
                  AND w_orders.customer_id = r_customer_lifetime_value.customer_id
              expected_ratio: 0.99  # Allow 1% variance for floating point
```

#### Step 3: Define Anonymization Profiles for Environments

```yaml
# printoptim/confiture-environments/qa-anonymization.yaml
anonymization_profile: qa
description: "Safe for QA team - keeps structure, anonymizes PII"

strategies:
  email_mask:
    type: email_masking
    keep_domain: true
    prefix: "qa+"

  name_keep:
    type: no_anonymization

  ssn_mask:
    type: pattern_masking
    pattern: "***-**-####"

  uuid_hash:
    type: deterministic_hash
    salt: "${QA_ANON_SALT}"
    algorithm: sha256

rules:
  # Common tables
  - table: w_tenants
    strategy: skip_table  # Never anonymize tenant list

  - table: audit_log
    strategy: skip_table

  # Write side - customers
  - table: w_customers
    columns:
      tenant_id:
        strategy: none  # CRITICAL: Required for joins
      first_name:
        strategy: name_keep  # OK for QA
      last_name:
        strategy: name_keep
      email:
        strategy: email_mask
      phone:
        strategy: ssn_mask  # Use same format
      ssn:
        strategy: ssn_mask

  # Write side - orders
  - table: w_orders
    columns:
      tenant_id:
        strategy: none  # CRITICAL: Required for multi-tenancy
      customer_id:
        strategy: uuid_hash  # Mask but keep deterministic
      shipping_address:
        strategy: none  # OK for QA testing
      payment_token:
        strategy: uuid_hash
      total:
        strategy: none  # Keep amounts for budget testing

  # Read side - CLV
  - table: r_customer_lifetime_value
    columns:
      tenant_id:
        strategy: none  # CRITICAL
      customer_id:
        strategy: uuid_hash  # Match w_orders anonymization
      total_spent:
        # Randomize to protect real financial data
        type: custom_function
        function: random_decimal(100, 50000)
```

**Usage**:
```bash
# Sync production → QA with anonymization
$ confiture sync \
    --source production \
    --target qa_env \
    --anonymization-profile qa-anonymization \
    --verify-consistency

✓ Syncing production → qa_env with anonymization...
  ├─ Tables: 145
  ├─ Rows: 12.5M
  ├─ Anonymization: qa-anonymization profile
  ├─ Verification: strict (row counts, checksums)
  └─ Estimated time: 45 minutes

Proceed? [y/n] > y

⏳ Syncing... [████████████░░░░░░░░░░░░░] 35% complete (15 min)
```

#### Step 4: Interactive Migrations for CQRS Changes

```bash
# Complex read model migration
$ confiture migrate up --target 005_add_inventory_query_model --interactive --env production

╔════════════════════════════════════════════════════════════╗
║    Adding Inventory Query Model (Read Side CQRS)         ║
╚════════════════════════════════════════════════════════════╝

 📊 Analyzing migration...

 🔍 Migration: 005_add_inventory_query_model
    ├─ Type: CREATE TABLE (read-side model)
    ├─ Source tables: w_inventory (2.3M rows)
    ├─ Target table: r_inventory_summary
    └─ Hooks: backfill_inventory (EST. 8 seconds)

 ⚠️  Risk Assessment:
    ├─ Data loss: NONE
    ├─ Lock time: < 1s (just CREATE TABLE)
    ├─ Backfill time: 8-10s (moderate)
    ├─ Multi-tenant: ✓ tenant_id present in source and target
    └─ CQRS consistency: ✓ Write→Read derivation valid

 💡 Recommendations:
    ├─ ✓ Safe to run during business hours
    ├─ ⭐ Deploy application code that uses r_inventory_summary first
    └─ Monitor backfill performance (should complete < 15s)

 🔄 Rollback: Simple (DROP TABLE r_inventory_summary)

 Proceed? [y/n/preview] > preview

 SQL to execute:
 ┌──────────────────────────────────────────────────────┐
 │ CREATE TABLE r_inventory_summary (                    │
 │   id UUID PRIMARY KEY,                               │
 │   tenant_id UUID NOT NULL REFERENCES w_tenants(id),  │
 │   product_id UUID NOT NULL,                          │
 │   quantity_on_hand INT,                              │
 │   quantity_reserved INT,                             │
 │   reorder_point INT,                                 │
 │   created_at TIMESTAMP DEFAULT NOW(),                │
 │   updated_at TIMESTAMP DEFAULT NOW()                 │
 │ );                                                   │
 │ CREATE INDEX idx_r_inv_tenant_product                │
 │   ON r_inventory_summary(tenant_id, product_id);     │
 │                                                      │
 │ -- Backfill hook will run after DDL                  │
 │ INSERT INTO r_inventory_summary                      │
 │   SELECT ... FROM w_inventory ...                    │
 └──────────────────────────────────────────────────────┘

 Continue? [y/n] > y

 ✓ Migration 005: COMPLETED (8.2s)
   ├─ DDL: 0.3s
   ├─ Backfill: 7.1s
   ├─ Verification: 0.8s
   └─ Total: 8.2s

 ✅ r_inventory_summary now available for application queries!
```

---

## pggit Integration Guide

### Connecting Confiture with pggit

#### Step 1: pggit Phase 2 - Python Client Library

pggit needs to develop a Python client library before Phase 4 can integrate:

```python
# pggit/src/pggit_client.py (to be developed in pggit Phase 2)
from pggit_client import PggitClient

client = PggitClient(
    database="production",
    host="localhost",
    port=5432
)

# Query historical schema
schema_at_commit = await client.get_schema_at_ref(
    ref="feature/add-analytics",
    include_views=True
)

# Register migration event
await client.register_event(
    type="MIGRATION_APPLIED",
    migration_name="003_add_user_analytics",
    applied_by="alice@example.com",
    duration_seconds=5.1,
    status="SUCCESS"
)

# Get migration history
history = await client.get_events(
    type="MIGRATION_*",
    limit=50,
    order_by="timestamp DESC"
)
```

#### Step 2: Confiture Integration with pggit

```python
# confiture/core/pggit_aware_builder.py
from pggit_client import PggitClient

class PggitAwareSchemaBuilder(SchemaBuilder):
    """Builder that can query schemas from pggit history."""

    def __init__(self, env: str, pggit_client: PggitClient | None = None):
        super().__init__(env)
        self.pggit = pggit_client or PggitClient(database=env)

    async def build_from_git_ref(self, ref: str) -> str:
        """Build schema from specific git reference."""
        schema = await self.pggit.get_schema_at_ref(ref)
        return schema

    async def build_from_git_tag(self, tag: str) -> str:
        """Build schema from git tag (e.g., v1.0.0)."""
        schema = await self.pggit.get_schema_at_ref(tag)
        return schema

    async def diff_against_main(self) -> SchemaDiff:
        """Compare current schema against main branch."""
        current = await self.build_schema(self.env)
        main = await self.build_from_git_ref("main")
        return self.differ.diff(main, current)

# confiture/core/pggit_aware_migrator.py
class PggitAwareMigrator(Migrator):
    """Migrator that auto-registers events with pggit."""

    def __init__(self, env: str, pggit_client: PggitClient | None = None):
        super().__init__(env)
        self.pggit = pggit_client or PggitClient(database=env)

    async def migrate_up(self, target: str | None = None):
        """Apply migration and register with pggit."""

        import time
        start = time.time()

        try:
            result = await super().migrate_up(target)
            duration = time.time() - start

            # Register success with pggit
            await self.pggit.register_event(
                type="MIGRATION_APPLIED",
                migration_name=target,
                applied_by=os.getenv("USER", "unknown"),
                duration_seconds=duration,
                status="SUCCESS",
                metadata={
                    "rows_affected": result.rows_affected,
                    "execution_time": result.execution_time,
                    "hooks_executed": len(result.hooks_executed),
                }
            )

            return result

        except Exception as e:
            duration = time.time() - start

            # Register failure with pggit
            await self.pggit.register_event(
                type="MIGRATION_FAILED",
                migration_name=target,
                applied_by=os.getenv("USER", "unknown"),
                duration_seconds=duration,
                status="FAILED",
                error_message=str(e)
            )

            raise
```

#### Step 3: Migration History Dashboard

```python
# confiture/cli/history.py
@app.command()
def history(env: str = "production", format: str = "table"):
    """Show migration history from pggit."""

    pggit = PggitClient(database=env)
    events = asyncio.run(pggit.get_events(
        type="MIGRATION_*",
        limit=100,
        order_by="timestamp DESC"
    ))

    if format == "table":
        table = Table(title=f"Migration History ({env})")
        table.add_column("Timestamp", style="cyan")
        table.add_column("Migration", style="green")
        table.add_column("Status", style="magenta")
        table.add_column("Duration", style="yellow")
        table.add_column("Applied By", style="blue")

        for event in events:
            status_icon = "✓" if event.status == "SUCCESS" else "✗"
            table.add_row(
                event.timestamp.isoformat(),
                event.migration_name,
                f"{status_icon} {event.status}",
                f"{event.duration_seconds:.1f}s",
                event.applied_by
            )

        console.print(table)

    elif format == "json":
        print(json.dumps([e.dict() for e in events], indent=2))

    elif format == "html":
        # Generate HTML dashboard
        html = generate_migration_dashboard_html(events)
        with open("migration_history.html", "w") as f:
            f.write(html)
        print("✓ Generated migration_history.html")
```

---

## Risk Analysis & Mitigation

### Identified Risks

#### Risk 1: Hook Failures in Production

**Risk**: Hook execution fails mid-way, leaving database in inconsistent state

**Mitigation**:
- Savepoints per hook allow partial rollback
- ON_ERROR hooks for cleanup
- Dry-run mode to test hooks before production
- Timeout protection to prevent hanging hooks

**Implementation**:
```python
class HookExecutor:
    async def execute_phase(self, conn, phase, hooks, context):
        for hook in hooks:
            async with conn.savepoint() as sp:
                try:
                    result = await asyncio.wait_for(
                        hook.execute(conn, context),
                        timeout=context.hook_timeout  # Default: 300s
                    )
                except asyncio.TimeoutError:
                    await sp.rollback()
                    raise HookTimeoutError(hook=hook)
                except Exception as e:
                    await sp.rollback()

                    # Execute error handlers
                    for error_handler in context.error_handlers:
                        await error_handler.execute(conn, context, error=e)

                    raise
```

#### Risk 2: Linting False Positives

**Risk**: Linting rules are too strict, preventing valid schema changes

**Mitigation**:
- Make severity configurable (error vs warning vs info)
- Allow rule exemptions per table/schema
- Dry-run linting before enforcing
- Community feedback on rule accuracy

**Implementation**:
```yaml
linting:
  rules:
    primary_key_required:
      severity: error
      exemptions:
        - audit_log
        - unlogged_staging_*

    documentation:
      severity: warning
      exemptions:
        - system_*
        - temporary_*
```

#### Risk 3: Anonymization Data Loss

**Risk**: Anonymization strategy is too aggressive, losing valuable data

**Mitigation**:
- Anonymization verification mode
- Sample rows comparison before/after
- Dry-run anonymization with report
- Reversibility checks (flag irreversible strategies)

**Implementation**:
```python
# Verify anonymization doesn't lose too much information
verifier = AnonymizationVerifier()
report = await verifier.verify_profile(
    profile=qa_profile,
    source_db="production",
    sample_size=1000
)

# Check for issues
if report.has_errors():
    print("❌ Anonymization profile issues found:")
    for error in report.errors:
        print(f"  - {error}")
    sys.exit(1)
```

#### Risk 4: pggit Integration Failure

**Risk**: pggit server is down, preventing migration registration

**Mitigation**:
- Optional integration (migrations work without pggit)
- Retry logic with exponential backoff
- Local queue for pending events
- Offline mode with batch replay

**Implementation**:
```python
class PggitAwareMigrator(Migrator):
    async def migrate_up(self, target: str):
        # Apply migration (required)
        result = await super().migrate_up(target)

        # Register with pggit (optional, with fallback)
        try:
            await self.pggit.register_event(...)
        except PggitConnectionError:
            # Log locally if pggit unavailable
            self._queue_pggit_event(...)
            logger.warning("pggit unavailable, event queued for later")

        return result

    async def replay_pggit_queue(self):
        """Replay queued pggit events when service recovers."""
        queued_events = self._load_queued_events()
        for event in queued_events:
            try:
                await self.pggit.register_event(**event)
                self._remove_queued_event(event)
            except PggitConnectionError:
                break  # Retry later
```

### Testing Strategy

**Unit Tests**:
- Hook execution paths (success, error, timeout)
- Linting rules accuracy
- Anonymization strategies
- Risk assessment calculations

**Integration Tests**:
- End-to-end hook execution with real database
- Linting against PrintOptim schema (1,256 files)
- Anonymization verification with production data
- pggit event registration

**E2E Tests**:
- Complete migration workflow with all Phase 4 features
- Interactive wizard with simulated user input
- Dry-run vs real migration comparison
- Failure scenarios and rollback

---

## Success Metrics

### Feature Adoption

- [ ] **Hook System**: 90% of production migrations use hooks
- [ ] **Linting**: 100% of schema PRs pass linting
- [ ] **Anonymization**: 100% of data syncs use appropriate profiles
- [ ] **Wizard**: 100% of production migrations use interactive mode
- [ ] **Dry-Run**: 100% of risky migrations tested with dry-run first

### Quality Metrics

- [ ] **Hook Reliability**: 99.9% of hooks execute successfully
- [ ] **Linting Accuracy**: <2% false positive rate
- [ ] **Risk Estimation**: ±15% accuracy on execution time
- [ ] **Anonymization Compliance**: 100% PII masked per profile
- [ ] **Test Coverage**: ≥90% of Phase 4 code covered

### Performance Metrics

- [ ] **Dry-Run Overhead**: <10% slower than normal migration
- [ ] **Linting Performance**: <5s for 1,000+ tables
- [ ] **Anonymization Throughput**: ≥100k rows/min
- [ ] **Hook Execution**: <2s per hook phase

### PrintOptim-Specific Metrics

- [ ] **CQRS Validation**: 100% of read models validated
- [ ] **Multi-Tenant Checks**: 100% of tables have tenant_id
- [ ] **Schema Consistency**: Zero data mismatches after sync
- [ ] **Migration Safety**: Zero unplanned rollbacks

### User Experience Metrics

- [ ] **Interactive Wizard Completion**: >95% migrations complete wizard
- [ ] **User Satisfaction**: >8/10 on feedback surveys
- [ ] **Documentation Clarity**: <5% support questions on Phase 4 features
- [ ] **Error Messages**: <2% user confusion on error messages

---

## Appendix: Code Examples

### Example 1: Complete Migration with Hooks

```python
# confiture-migrations/003_add_customer_analytics.yaml
migration:
  name: 003_add_customer_analytics
  version: "1.0"
  description: Add customer analytics read model with backfill
  applies_to:
    - environment: production
    - environment: staging

  ddl: |
    -- Create read-side table
    CREATE TABLE r_customer_analytics (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      tenant_id UUID NOT NULL REFERENCES w_tenants(id),
      customer_id UUID NOT NULL REFERENCES w_customers(id),
      total_orders INT DEFAULT 0,
      total_spent DECIMAL(19,2) DEFAULT 0,
      avg_order_value DECIMAL(19,2),
      last_order_date TIMESTAMP,
      created_at TIMESTAMP DEFAULT NOW(),
      updated_at TIMESTAMP DEFAULT NOW(),
      UNIQUE(tenant_id, customer_id),
      CONSTRAINT tenant_customer_fk FOREIGN KEY (tenant_id, customer_id)
        REFERENCES (w_tenants, w_customers)(id, id)
    );

    CREATE INDEX idx_r_customer_analytics_tenant
      ON r_customer_analytics(tenant_id);

    CREATE INDEX idx_r_customer_analytics_customer
      ON r_customer_analytics(customer_id);

    CREATE INDEX idx_r_customer_analytics_spend
      ON r_customer_analytics(total_spent DESC);

  hooks:
    before_validation:
      - type: backup_database
        config:
          backup_dir: /backups
          compression: gzip
          keep_backup_days: 7

    before_ddl:
      - type: capture_statistics
        config:
          tables:
            - w_customers
            - w_orders
          capture_row_counts: true
          capture_table_sizes: true

    after_ddl:
      - type: backfill_read_model
        description: "Populate analytics from orders"
        config:
          source_tables:
            - w_orders
            - w_customers
          target_table: r_customer_analytics
          batch_size: 50000
          parallel_workers: 4
          backfill_query: |
            WITH customer_orders AS (
              SELECT
                t.id as tenant_id,
                c.id as customer_id,
                COUNT(*) as total_orders,
                SUM(o.total) as total_spent,
                AVG(o.total) as avg_order_value,
                MAX(o.created_at) as last_order_date
              FROM w_tenants t
              JOIN w_customers c ON c.tenant_id = t.id
              LEFT JOIN w_orders o ON o.customer_id = c.id
              GROUP BY t.id, c.id
            )
            INSERT INTO r_customer_analytics (
              tenant_id,
              customer_id,
              total_orders,
              total_spent,
              avg_order_value,
              last_order_date
            )
            SELECT * FROM customer_orders
            ON CONFLICT (tenant_id, customer_id) DO UPDATE SET
              total_orders = EXCLUDED.total_orders,
              total_spent = EXCLUDED.total_spent,
              avg_order_value = EXCLUDED.avg_order_value,
              last_order_date = EXCLUDED.last_order_date

      - type: rebuild_index
        config:
          indexes:
            - idx_r_customer_analytics_tenant
            - idx_r_customer_analytics_spend
          concurrent: true

    after_validation:
      - type: verify_consistency
        config:
          checks:
            - name: row_count
              query: |
                SELECT COUNT(DISTINCT (tenant_id, customer_id)) as expected
                FROM w_orders
                UNION ALL
                SELECT COUNT(*) as actual
                FROM r_customer_analytics
              tolerance_percent: 0.0

            - name: total_spent
              query: |
                WITH calculated AS (
                  SELECT
                    tenant_id,
                    customer_id,
                    SUM(total) as expected_total
                  FROM w_orders
                  GROUP BY tenant_id, customer_id
                )
                SELECT
                  SUM(ABS(c.expected_total - r.total_spent)) as total_variance,
                  MAX(ABS(c.expected_total - r.total_spent)) as max_variance
                FROM calculated c
                JOIN r_customer_analytics r
                  ON r.tenant_id = c.tenant_id
                  AND r.customer_id = c.customer_id
              tolerance_percent: 0.01  # 1% variance OK

      - type: test_application_queries
        config:
          test_queries:
            - name: get_top_customers
              query: SELECT * FROM r_customer_analytics ORDER BY total_spent DESC LIMIT 10
              expected_columns:
                - id
                - tenant_id
                - customer_id
                - total_spent

            - name: customer_lifetime_value
              query: SELECT SUM(total_spent) FROM r_customer_analytics WHERE tenant_id = $1
              test_params:
                - "550e8400-e29b-41d4-a716-446655440000"
              expected_return_type: numeric

    cleanup:
      - type: drop_temporary_tables
        config:
          keep_logs: true  # Keep execution logs

      - type: analyze_statistics
        config:
          tables:
            - r_customer_analytics
          update_table_stats: true

  rollback:
    ddl: |
      DROP TABLE IF EXISTS r_customer_analytics CASCADE;

    hooks:
      - type: restore_from_backup
        config:
          backup_dir: /backups
          backup_name: pre_003_analytics
```

### Example 2: PrintOptim Linting Configuration

```yaml
# printoptim/confiture-lint.yaml
linting:
  enabled: true
  fail_on_severity: error
  report_format: html

  rules:
    # Standard rules
    primary_key:
      type: primary_key_required
      severity: error

    naming_tables:
      type: naming_convention
      severity: warning
      pattern: "^[a-z_]+$"

    naming_columns:
      type: naming_convention
      severity: warning
      pattern: "^[a-z_]+$"
      exemptions:
        - "^_.*"  # Internal columns

    # PrintOptim-specific rules
    write_side_prefix:
      type: table_prefix
      severity: error
      pattern: "^w_"
      applicable_to:
        schema_path: db/0_schema/01_write_side
      message: "Write-side tables must start with w_"

    read_side_prefix:
      type: table_prefix
      severity: error
      pattern: "^r_"
      applicable_to:
        schema_path: db/0_schema/02_query_side
      message: "Read-side tables must start with r_"

    multi_tenant_required:
      type: column_required
      severity: error
      column: tenant_id
      applicable_to:
        exclude_patterns:
          - "^pg_.*"
          - "^system_.*"
          - "^audit_.*"
          - "^migration_.*"
          - "^w_tenant"  # Tenant tables themselves
      message: "All data tables must have tenant_id column"

    documentation:
      type: documentation_required
      severity: warning
      require_table_comments: true
      require_column_comments: false

    cqrs_validation:
      type: custom
      severity: error
      implementation: |
        # Custom rule to verify read models are properly derived
        for read_model in (
          SELECT tablename FROM pg_tables
          WHERE tablename LIKE 'r_%' AND schemaname = '02_query_side'
        ):
          # Verify there's a source write model or view definition
          validate_read_model_source(read_model)

    foreign_key_indexed:
      type: index_required_for_fk
      severity: warning
      message: "Foreign keys should be indexed for performance"
```

### Example 3: Interactive Wizard Session

```bash
$ confiture migrate up --interactive --env production --target 005

╔════════════════════════════════════════════════════════════╗
║      Confiture Interactive Migration Wizard                ║
║           Production Environment (main cluster)            ║
╚════════════════════════════════════════════════════════════╝

 📊 Scanning pending migrations...
    ├─ 004_add_order_history (pending)
    └─ 005_add_analytics (pending)

 ✓ Found 2 pending migrations
   └─ Target: 005_add_analytics

 Would you like to run these in sequence? [y/n] > y

────────────────────────────────────────────────────────────

 🔍 Migration 004: add_order_history
    └─ ALTER TABLE orders ADD COLUMN created_at TIMESTAMP

    ⚠️  Risk Assessment:
        • Backward compatibility: LOW
        • Data loss: NONE
        • Lock time: MEDIUM (5-7 seconds on 5.2M rows)
        • Performance impact: LOW

    Estimated time: 7 seconds
    Rollback: Simple (DROP COLUMN)

    Ready to proceed? [y/n/details/preview/skip] > y

 ⏳ Executing migration 004...
    ├─ Before validation: ✓ (0.2s)
    ├─ Before DDL: ✓ (0.1s)
    ├─ DDL: ✓ (6.8s)
    │  └─ ALTER TABLE: 6.3s, Lock time: 850ms
    ├─ After DDL: ✓ (0.2s)
    ├─ After validation: ✓ (0.3s)
    └─ Cleanup: ✓ (0.1s)

 ✅ Migration 004: SUCCESS (7.7s total)

────────────────────────────────────────────────────────────

 🔍 Migration 005: add_analytics
    └─ CREATE TABLE r_customer_analytics

    ⚠️  Risk Assessment:
        • Backward compatibility: MEDIUM
        • Data loss: NONE
        • Lock time: LOW (< 1s for CREATE TABLE)
        • Backfill time: HIGH (15-20s for 2.1M customers)
        • Multi-tenant: ✓ VALID
        • CQRS: ✓ Read model properly derived

    Hooks to execute:
    ├─ BEFORE_DDL: capture_statistics
    ├─ AFTER_DDL: backfill_analytics (est. 18s)
    ├─ AFTER_VALIDATION: verify_consistency (est. 2s)
    └─ CLEANUP: analyze_statistics (est. 1s)

    Total estimated time: 22 seconds
    Rollback: DROP TABLE (1 second)

    Ready to proceed? [y/n/details/preview/skip/dry-run] > dry-run

 ⏳ Running migration in dry-run mode (will rollback)...

    📊 Dry-run Results:
    ├─ DDL execution: 0.3s
    ├─ Backfill: 17.4s
    ├─ Verification: 1.8s
    ├─ Total: 19.5s
    ├─ Rows affected: 2,150,340
    ├─ Constraint violations: 0
    └─ All checks: ✓ PASSED

    📈 Estimated Production Time:
    ├─ Expected: 19-21 seconds
    ├─ Confidence: 95%
    └─ Ready to execute

    Proceed with real migration? [y/n] > y

 ⏳ Executing migration 005...
    ├─ Before validation: ✓ (0.1s)
    ├─ Before DDL: ✓ (0.2s)
    ├─ DDL: ✓ (0.3s)
    ├─ After DDL (backfill):
    │  ├─ Batch 1/43: 50k rows ✓ (0.4s)
    │  ├─ Batch 2/43: 50k rows ✓ (0.4s)
    │  ├─ Batch 3/43: 50k rows ✓ (0.4s)
    │  ├─ [████████████░░░░░░░░] 30% complete (6.2s)
    │  ├─ Batch 22/43: 50k rows ✓ (0.4s)
    │  └─ [████████████████████] 100% complete (17.3s)
    ├─ After validation: ✓ (1.9s)
    └─ Cleanup: ✓ (0.8s)

 ✅ Migration 005: SUCCESS (20.6s total)

────────────────────────────────────────────────────────────

 📋 Migration Summary:
    ├─ Total migrations: 2
    ├─ Successful: 2
    ├─ Failed: 0
    ├─ Total time: 28.3 seconds
    ├─ Hooks executed: 7
    └─ Rows affected: 2,150,340

 💡 Post-Migration Notes:
    ├─ r_customer_analytics is ready for queries
    ├─ Application code using new table can be deployed now
    ├─ Consider running VACUUM ANALYZE during maintenance window
    └─ Monitor query performance on r_customer_analytics

 ✅ All migrations completed successfully!
```

---

## Conclusion

Phase 4 represents the maturation of Confiture from a migration execution tool into a **comprehensive schema governance platform**. By integrating with pggit for version control and providing advanced features for validation, safety, and compliance, Phase 4 enables teams to manage complex database evolution with confidence.

**Key Achievements**:
- ✅ Safe migrations through hooks, dry-run, and risk assessment
- ✅ Enforced standards through linting and validation
- ✅ Flexible data handling through custom anonymization
- ✅ Full audit trail through pggit integration
- ✅ Complex use cases like PrintOptim's CQRS architecture

**Timeline**: Q1 2026 (8 weeks)
**Success Rate Target**: >95% migrations complete without issues
**Team**: 1-2 senior engineers with PostgreSQL expertise

This document serves as a long-term strategy guide for specialists to evaluate and refine before implementation begins.

---

**Document Version**: 1.0
**Last Updated**: 2025-12-26
**Status**: Ready for Review
