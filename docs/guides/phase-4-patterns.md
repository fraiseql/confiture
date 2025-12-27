# Phase 4 Patterns: Advanced Migration Workflows

**Combine hooks, anonymization, linting, and wizard to build sophisticated migration systems**

---

## Overview

Phase 4 features work together to enable complex migration workflows. This guide shows real-world patterns combining multiple features.

---

## Pattern 1: Complete Audit System

**Use Case**: Track every migration with full audit trail, approval history, and impact analysis.

**Features Used**:
- Migration Hooks (logging and validation)
- Interactive Wizard (approvals)
- Schema Linting (pre-flight checks)
- Custom Anonymization (audit data masking)

```python
# confiture_hooks.py

from confiture.hooks import register_hook, HookContext
from datetime import datetime
import psycopg
import json
import os

@register_hook('pre_validate')
def pre_flight_check(context: HookContext) -> None:
    """Run linting before any migration."""
    import subprocess
    result = subprocess.run(
        ['confiture', 'lint', '--strict'],
        capture_output=True
    )
    if result.returncode != 0:
        raise RuntimeError("Schema lint failed - fix issues before migrating")

@register_hook('pre_execute')
def log_migration_start(context: HookContext) -> None:
    """Log migration start to audit table."""
    with psycopg.connect() as conn:
        conn.execute(
            """
            INSERT INTO audit_log (
                migration_version,
                migration_name,
                status,
                applied_by,
                started_at,
                approvers
            )
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                context.migration.version,
                context.migration.name,
                'running',
                os.getenv('USER'),
                datetime.now(),
                json.dumps(context.metadata.get('approvers', []))
            )
        )
        conn.commit()

@register_hook('post_execute')
def log_migration_complete(context: HookContext) -> None:
    """Log migration completion and verify results."""
    with psycopg.connect() as conn:
        # Update audit log
        conn.execute(
            """
            UPDATE audit_log
            SET status = %s, completed_at = %s, duration_ms = %s
            WHERE migration_version = %s
            """,
            (
                'completed',
                datetime.now(),
                context.duration_ms,
                context.migration.version
            )
        )

        # Verify schema integrity
        result = conn.execute("SELECT COUNT(*) FROM pg_tables WHERE schemaname = 'public'")
        table_count = result.scalar()

        # Log metrics
        conn.execute(
            """
            INSERT INTO audit_metrics (
                migration_version,
                table_count,
                index_count,
                procedure_count
            )
            VALUES (%s, %s, (SELECT COUNT(*) FROM pg_indexes), (SELECT COUNT(*) FROM pg_proc))
            """,
            (context.migration.version, table_count)
        )

        conn.commit()

@register_hook('post_rollback')
def log_rollback(context: HookContext) -> None:
    """Log rollback event."""
    with psycopg.connect() as conn:
        conn.execute(
            """
            INSERT INTO audit_log (
                migration_version,
                status,
                applied_by,
                started_at
            )
            VALUES (%s, %s, %s, %s)
            """,
            (
                context.migration.version,
                'rolled_back',
                os.getenv('USER'),
                datetime.now()
            )
        )
        conn.commit()
```

**Required Schema**:
```sql
-- db/schema/20_audit/audit_log.sql

CREATE TABLE IF NOT EXISTS audit_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    migration_version TEXT NOT NULL,
    migration_name TEXT NOT NULL,
    status TEXT NOT NULL,
    applied_by TEXT NOT NULL,
    started_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ,
    duration_ms FLOAT,
    approvers JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_audit_log_version ON audit_log(migration_version);
CREATE INDEX idx_audit_log_status ON audit_log(status);
```

**Usage**:
```bash
# Interactive wizard with linting pre-check
confiture migrate wizard --env production --review

# Step 1: Lint checks (pre_validate hook)
# Step 2: Review migrations
# Step 3: Approve (stores in approvers metadata)
# Step 4: Apply with hooks logging everything
# Step 5: Verify and complete

# Query audit log
psql -c "SELECT migration_version, status, applied_by FROM audit_log ORDER BY created_at DESC"
```

---

## Pattern 2: GDPR-Compliant Production Sync

**Use Case**: Sync production data to staging while ensuring GDPR compliance (encryption, anonymization, audit).

**Features Used**:
- Custom Anonymization (PII protection)
- Schema Linting (compliance rules)
- Migration Hooks (before/after sync logging)

```python
# db/anonymization/gdpr_strategies.py

from confiture.anonymization import register_strategy
import hashlib

@register_strategy('email')
def anonymize_email_gdpr(value: str, field_name: str, row_context: dict = None) -> str:
    """GDPR-compliant email anonymization."""
    if value is None:
        return None

    # Hash the email for irreversibility
    hash_digest = hashlib.sha256(value.encode()).hexdigest()

    # Only keep domain if from internal system
    if '@company.com' in value:
        return f"user_{hash_digest[:8]}@company.com"

    # Remove external email domains entirely
    return f"user_{hash_digest[:8]}@anonymized.local"

@register_strategy('password')
def anonymize_password_gdpr(value: str, field_name: str, row_context: dict = None) -> str:
    """Password is already hashed, but replace with generic for extra safety."""
    return hashlib.sha256(b"anonymized").hexdigest()

@register_strategy('phone')
def anonymize_phone_gdpr(value: str, field_name: str, row_context: dict = None) -> str:
    """Mask phone numbers for GDPR."""
    if value is None:
        return None

    import re
    digits = re.sub(r'\D', '', value)

    if len(digits) < 4:
        return "***-***-****"

    # Keep last 4 digits only
    return f"***-***-{digits[-4:]}"

@register_strategy('ssn')
def anonymize_ssn_gdpr(value: str, field_name: str, row_context: dict = None) -> str:
    """Never sync SSN at all."""
    return None  # Remove entirely
```

```yaml
# db/linting/gdpr_rules.yaml

linting:
  compliance:
    gdpr_required_fields:
      - created_at: "Audit when created"
      - updated_at: "Audit when changed"
      - deleted_at: "Support data deletion"

    gdpr_forbidden_plain_text:
      - password
      - ssn
      - credit_card
      - api_key
      - secret_token

    gdpr_required_encryption:
      - email
      - phone
      - home_address
```

```python
# confiture_hooks.py (for sync operations)

from confiture.hooks import register_hook, HookContext

@register_hook('pre_execute')
def log_sync_start(context: HookContext) -> None:
    """Log data sync for GDPR audit."""
    print(f"📋 GDPR Data Sync")
    print(f"   From: {context.environment['source']}")
    print(f"   To:   {context.environment['target']}")
    print(f"   Anonymization: ENABLED")
    print(f"   Audit logging: ENABLED")

@register_hook('post_execute')
def log_sync_complete(context: HookContext) -> None:
    """Log sync completion."""
    with psycopg.connect() as conn:
        conn.execute(
            """
            INSERT INTO gdpr_sync_log (
                sync_time,
                rows_synced,
                anonymization_rules_applied,
                logged_by
            )
            VALUES (%s, %s, %s, %s)
            """,
            (
                datetime.now(),
                context.metadata.get('rows_synced'),
                'email,phone,ssn',
                os.getenv('USER')
            )
        )
        conn.commit()
```

**Usage**:
```bash
# Sync with GDPR compliance
confiture sync \
  --from production \
  --to staging \
  --anonymize \
  --strategy email=db.anonymization.gdpr_strategies.anonymize_email_gdpr \
  --strategy phone=db.anonymization.gdpr_strategies.anonymize_phone_gdpr \
  --strategy ssn=db.anonymization.gdpr_strategies.anonymize_ssn_gdpr \
  --strict-compliance

# Verifies:
# 1. Linting passes GDPR rules
# 2. All PII fields anonymized
# 3. Hooks log the sync
# 4. No sensitive data in staging
```

---

## Pattern 3: Risk-Based Migration Workflow

**Use Case**: Team applies migrations with automatic risk assessment and tiered approvals.

**Features Used**:
- Interactive Wizard (risk classification)
- Schema Linting (automatic risk detection)
- Migration Hooks (blocking on risk level)

```python
# confiture_hooks.py

from confiture.hooks import register_hook, HookContext

def assess_migration_risk(migration) -> str:
    """Assess migration risk: low, medium, high, critical."""

    sql = migration.sql.lower()

    # Critical risks
    if 'drop table' in sql or 'drop column' in sql:
        return 'critical'

    # High risks
    if 'alter table' in sql and ('rename' in sql or 'type' in sql):
        return 'high'
    if 'truncate' in sql:
        return 'high'

    # Medium risks
    if 'create index' in sql or 'drop index' in sql:
        return 'medium'
    if 'alter column' in sql:
        return 'medium'

    # Low risk
    if 'create table' in sql or 'add column' in sql:
        return 'low'

    return 'low'

@register_hook('pre_validate')
def check_migration_risk(context: HookContext) -> None:
    """Assess and report migration risk."""

    # Get all pending migrations
    from confiture.core.migrator import get_pending_migrations

    pending = get_pending_migrations()

    for migration in pending:
        risk = assess_migration_risk(migration)
        migration.metadata['risk_level'] = risk

        print(f"⚠️  Risk Assessment: {migration.name}")
        print(f"   Risk Level: {risk.upper()}")

        # Block critical in production without explicit approval
        if risk == 'critical' and context.environment == 'production':
            env_var = os.getenv('CRITICAL_MIGRATION_APPROVED')
            if not env_var or env_var != 'true':
                raise RuntimeError(
                    f"Critical migration '{migration.name}' requires approval. "
                    f"Set CRITICAL_MIGRATION_APPROVED=true to proceed."
                )
```

```yaml
# db/confiture.yaml

migrations:
  risk_levels:
    low:
      auto_apply: true
      require_review: false
      require_approval: false
      backup_required: false

    medium:
      auto_apply: false
      require_review: true
      require_approval: false
      backup_required: false

    high:
      auto_apply: false
      require_review: true
      require_approval: true
      backup_required: false
      approval_required: ["dba", "platform-lead"]

    critical:
      auto_apply: false
      require_review: true
      require_approval: true
      require_backup: true
      approval_required: ["dba", "cto"]
```

**Usage**:
```bash
# Wizard automatically classifies risk
confiture migrate wizard --env production

# Low-risk migrations: Auto-approved, just shows info
# Medium-risk migrations: Requires review
# High-risk migrations: Requires DBA + lead approval
# Critical migrations: Requires DBA + CTO approval + backup confirmation
```

---

## Pattern 4: Multi-Environment Promotion Pipeline

**Use Case**: Promote migrations from dev → staging → production with validation at each step.

**Features Used**:
- Schema Linting (pre-promotion validation)
- Migration Hooks (environment-specific checks)
- Custom Anonymization (data masking per environment)

```bash
#!/bin/bash
# scripts/promote_migrations.sh

# Promote migrations through environments

ENV_FROM=$1  # dev
ENV_TO=$2    # staging or production
MIGRATION=$3 # migration name

echo "🚀 Promoting migration from $ENV_FROM to $ENV_TO"

# Step 1: Lint schema in source environment
echo "Step 1: Linting schema..."
confiture lint db/schema/ --fail-level critical
if [ $? -ne 0 ]; then
    echo "❌ Schema linting failed"
    exit 1
fi

# Step 2: Test in source environment
echo "Step 2: Testing migration..."
confiture migrate up --env $ENV_FROM --dry-run-execute --target $MIGRATION
if [ $? -ne 0 ]; then
    echo "❌ Migration failed in test"
    exit 1
fi

# Step 3: Sync data from source (if applicable)
if [ "$ENV_TO" == "staging" ]; then
    echo "Step 3: Syncing data from $ENV_FROM..."
    confiture sync \
        --from $ENV_FROM \
        --to $ENV_TO \
        --anonymize
    if [ $? -ne 0 ]; then
        echo "❌ Data sync failed"
        exit 1
    fi
fi

# Step 4: Apply to target environment
echo "Step 4: Applying to $ENV_TO..."
confiture migrate up --env $ENV_TO

# Step 5: Verify in target environment
echo "Step 5: Verifying..."
confiture lint db/schema/ --fail-level critical
if [ $? -ne 0 ]; then
    echo "❌ Verification failed"
    exit 1
fi

echo "✅ Promotion successful: $ENV_FROM → $ENV_TO"
```

---

## Pattern 5: Self-Service Team Migrations

**Use Case**: Enable teams to safely apply their own migrations without DBA involvement.

**Features Used**:
- Interactive Wizard (guided workflow)
- Schema Linting (guardrails)
- Migration Hooks (validation and notification)

```python
# confiture_hooks.py

@register_hook('pre_validate')
def check_team_permissions(context: HookContext) -> None:
    """Ensure team can apply migrations."""

    # Get team from git
    import subprocess
    try:
        team = subprocess.check_output(
            ['git', 'config', 'user.name'],
            text=True
        ).strip()
    except:
        team = os.getenv('USER', 'unknown')

    # Check permissions
    allowed_teams = ['platform-team', 'data-team', 'api-team']
    if team not in allowed_teams and context.environment == 'production':
        raise PermissionError(f"Team '{team}' cannot apply migrations to production")

@register_hook('post_execute')
def notify_team(context: HookContext) -> None:
    """Notify team of successful migration."""

    import requests

    webhook = os.getenv('SLACK_WEBHOOK')
    if not webhook:
        return

    message = {
        "text": f"✅ Migration applied: {context.migration.name}",
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"""
*Migration Applied Successfully*
Environment: `{context.environment}`
Migration: `{context.migration.name}`
Duration: {context.duration_ms}ms
Applied by: {os.getenv('USER')}
"""
                }
            }
        ]
    }

    requests.post(webhook, json=message)
```

---

## See Also

- [Migration Hooks](./migration-hooks.md) - Hook details
- [Custom Anonymization](./custom-anonymization-strategies.md) - Strategy details
- [Interactive Wizard](./interactive-migration-wizard.md) - Wizard details
- [Schema Linting](./schema-linting.md) - Linting details

---

*Part of Confiture documentation* 🍓

*Making migrations sweet and simple*
