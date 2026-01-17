# Migration Wizard API Reference

[← Back to API Reference](index.md)

**Stability**: Stable ✅

---

## Overview

The Migration Wizard API provides an interactive, guided interface for executing migrations. The wizard helps teams safely plan, review, and execute migrations with built-in risk assessment and approval workflows.

**Tagline**: *Guide teams through migrations safely with interactive assistance*

---

## What is the Migration Wizard?

The Migration Wizard is an interactive CLI tool that:
- Guides you through migration steps
- Assesses migration risk
- Schedules migrations for specific times
- Manages approvals before execution
- Provides real-time execution monitoring
- Handles rollback scenarios

**Key Concept**: Wizard = Interactive + Risk-Aware + Collaborative migrations

---

## When to Use the Wizard

**✅ Best For**:
- Team migrations (multiple reviewers needed)
- Production migrations (high stakes)
- Complex schemas (many tables involved)
- First-time migrations (guidance helpful)
- Compliance-required approvals

**❌ Not Needed For**:
- Development migrations (direct execution OK)
- Routine maintenance (automated OK)
- Single-table changes (simple)
- Low-risk alterations

---

## Invoking the Wizard

### CLI Command

```bash
# Interactive wizard
confiture migrate --wizard

# Wizard with specific migration
confiture migrate --wizard --target 005_add_payment_table

# Non-interactive dry-run
confiture migrate --wizard --dry-run

# Schedule migration for later
confiture migrate --wizard --schedule "2026-01-15 10:00 AM"
```

### Python API

```python
from confiture.wizard import MigrationWizard

wizard = MigrationWizard(database_url="postgresql://localhost/mydb")
result = await wizard.run_interactive()
```

---

## Wizard Modes

### Interactive Mode (Default)

```
🧙 Migration Wizard
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Step 1/5: Selecting migrations
> Which migration to execute? (001, 002, 003)
  ⓵ 001_create_users_table
  ⓶ 002_add_email_to_users
  ⓷ 003_create_posts_table

Select [1-3]: 2

Step 2/5: Reviewing changes
  Table: users
  ├─ ADD COLUMN email VARCHAR(255) NOT NULL
  └─ ADD CONSTRAINT email_unique UNIQUE (email)

Continue? [y/n]: y

Step 3/5: Risk assessment
  Risk Level: MEDIUM
  ├─ ⚠️ Adding non-nullable column to 50K row table
  ├─ ⚠️ Creating unique constraint (may fail if duplicates)
  └─ ✅ No data loss

Approve risk? [y/n]: y

Step 4/5: Approval workflow
  Requires 1 approval from: Backend team
  Current approvals: 0/1

  Request approval? [y/n]: y

Step 5/5: Execution
  Ready to execute?
  ├─ Migration: 002_add_email_to_users
  ├─ Risk: MEDIUM
  ├─ Approvals: 1/1 ✅
  ├─ Execute now? [y/n]: y

✅ Migration completed in 1.23s
```

---

### Dry-Run Mode

```bash
confiture migrate --wizard --dry-run

# Output shows what would happen without executing
[DRY RUN] Migration 002_add_email_to_users
[DRY RUN] ├─ ADD COLUMN email VARCHAR
[DRY RUN] ├─ Table: users (50000 rows)
[DRY RUN] ├─ Risk: MEDIUM
[DRY RUN] ├─ Time estimate: 2-5 seconds
[DRY RUN] └─ Would you like to proceed? No changes made.
```

---

### Scheduled Mode

```bash
# Schedule for future execution
confiture migrate --wizard --schedule "2026-01-15 02:00 AM"

# Output
✅ Migration scheduled for 2026-01-15 02:00:00 AM
   Migration: 002_add_email_to_users
   ID: scheduled_20260115_0200_002

   Manage scheduled migrations:
   confiture migrate list-scheduled    # Show all
   confiture migrate run-scheduled 002  # Run now
   confiture migrate cancel 002         # Cancel
```

---

## Risk Assessment API

### Risk Levels

```python
class RiskLevel(Enum):
    LOW = "low"        # Safe changes
    MEDIUM = "medium"  # Requires attention
    HIGH = "high"      # Significant impact
    CRITICAL = "critical"  # Requires approval
```

### Risk Factors

```python
@dataclass
class RiskAssessment:
    level: RiskLevel
    factors: list[RiskFactor]
    estimated_time: timedelta
    estimated_impact: str
    mitigation_steps: list[str]

@dataclass
class RiskFactor:
    category: str       # 'data_loss', 'performance', 'blocking', etc.
    severity: str       # 'low', 'medium', 'high'
    description: str
    mitigation: str     # How to mitigate
```

### Risk Examples

```
🟢 LOW RISK
  ├─ Adding indexed column to empty table
  └─ Estimated time: < 100ms

🟡 MEDIUM RISK
  ├─ Adding non-nullable column to 50K row table
  ├─ Creating unique constraint
  └─ Estimated time: 2-5 seconds

🔴 HIGH RISK
  ├─ Dropping column with data
  ├─ Changing column type (potential data loss)
  ├─ Requires backup verification
  └─ Estimated time: 10+ seconds

🔥 CRITICAL RISK
  ├─ Bulk deleting rows (> 10% of table)
  ├─ Dropping frequently-used column
  ├─ Requires explicit approval
  ├─ Backup strongly recommended
  └─ May cause application errors
```

---

## Approval Workflow API

### Approval Modes

```python
class ApprovalMode(Enum):
    NONE = "none"           # No approval needed
    SINGLE = "single"       # One person must approve
    MULTIPLE = "multiple"   # Multiple people must approve
    CONSENSUS = "consensus" # Everyone must agree
```

### Approval Configuration

```python
@dataclass
class ApprovalRequest:
    migration_id: str
    risk_level: RiskLevel
    required_approvers: int
    approver_groups: list[str]  # 'backend', 'dba', 'devops'
    deadline: datetime | None

    current_approvals: list[str]  # Who approved
    pending_approvals: list[str]  # Who needs to approve
```

### Requesting Approvals

```python
wizard = MigrationWizard(...)
approval_request = await wizard.request_approval(
    migration_id="002_add_email_to_users",
    risk_level=RiskLevel.MEDIUM,
    required_approvers=1,
    approver_groups=['backend_team']
)

# Output
Request ID: apr_20260115_001
Status: Pending
Required: 1 approval
Pending from: alice@company.com, bob@company.com
Deadline: 2026-01-15 10:00:00 AM

# Check status
status = await wizard.check_approval_status("apr_20260115_001")
print(f"Approvals: {status.current_approvals}/{status.required_approvers}")
```

---

## Wizard API Methods

### run_interactive()

```python
async def run_interactive(self) -> WizardResult:
    """
    Run wizard in interactive mode.

    Returns:
        WizardResult with execution details
    """
    pass

# Result
@dataclass
class WizardResult:
    migration_id: str
    status: str           # 'success', 'pending_approval', 'cancelled'
    risk_level: RiskLevel
    execution_time: timedelta | None
    error: Exception | None
```

### run_scheduled()

```python
async def run_scheduled(
    self,
    migration_id: str,
    scheduled_time: datetime
) -> ScheduledMigration:
    """
    Schedule migration for future execution.

    Args:
        migration_id: Migration to execute
        scheduled_time: When to execute

    Returns:
        ScheduledMigration object
    """
    pass

@dataclass
class ScheduledMigration:
    id: str
    migration_id: str
    scheduled_time: datetime
    status: str  # 'scheduled', 'running', 'completed', 'cancelled'
```

### assess_risk()

```python
async def assess_risk(
    self,
    migration_id: str
) -> RiskAssessment:
    """
    Assess migration risk without executing.

    Args:
        migration_id: Migration to assess

    Returns:
        RiskAssessment details
    """
    pass
```

### dry_run()

```python
async def dry_run(
    self,
    migration_id: str
) -> DryRunResult:
    """
    Execute migration in dry-run mode (no actual changes).

    Args:
        migration_id: Migration to dry-run

    Returns:
        DryRunResult showing what would happen
    """
    pass

@dataclass
class DryRunResult:
    migration_id: str
    would_succeed: bool
    estimated_time: timedelta
    affected_rows: int
    warnings: list[str]
    errors: list[str]
```

---

## Wizard Examples

### Example 1: Simple Interactive Migration

```python
from confiture.wizard import MigrationWizard

async def migrate_with_wizard():
    wizard = MigrationWizard(
        database_url="postgresql://localhost/mydb"
    )

    result = await wizard.run_interactive()

    if result.status == 'success':
        print(f"✅ Migration completed in {result.execution_time}")
    elif result.status == 'pending_approval':
        print("⏳ Migration pending approval")
    else:
        print(f"❌ Migration failed: {result.error}")
```

---

### Example 2: Risk Assessment Before Approval

```python
async def assess_before_approval():
    wizard = MigrationWizard(database_url="postgresql://localhost/mydb")

    # Assess risk
    risk = await wizard.assess_risk("003_drop_old_column")

    print(f"Risk Level: {risk.level}")
    for factor in risk.factors:
        print(f"  - {factor.description}")
        print(f"    Mitigation: {factor.mitigation}")

    if risk.level == RiskLevel.CRITICAL:
        print("⚠️ Critical risk - requires explicit approval")
        # Request approval workflow
```

---

### Example 3: Dry-Run Before Production

```python
async def dry_run_then_execute():
    wizard = MigrationWizard(database_url="postgresql://prod.mydb")

    # Step 1: Dry-run to verify
    dry_run = await wizard.dry_run("004_add_payment_table")

    if dry_run.would_succeed:
        print(f"✅ Dry-run passed (estimated time: {dry_run.estimated_time})")
        print(f"   Would affect: {dry_run.affected_rows} rows")

        # Step 2: Request approval with dry-run results
        result = await wizard.run_interactive()
        if result.status == 'success':
            print("✅ Production migration completed successfully")
    else:
        print("❌ Dry-run failed - would not proceed")
        for error in dry_run.errors:
            print(f"   Error: {error}")
```

---

### Example 4: Scheduled Migration with Monitoring

```python
async def schedule_and_monitor():
    wizard = MigrationWizard(database_url="postgresql://localhost/mydb")

    from datetime import datetime, timedelta

    # Schedule for 2 AM (maintenance window)
    scheduled_time = datetime.now() + timedelta(days=1, hours=2)

    scheduled = await wizard.run_scheduled("005_index_users_email", scheduled_time)

    print(f"✅ Scheduled for {scheduled.scheduled_time}")
    print(f"   ID: {scheduled.id}")

    # Monitor execution
    while True:
        status = await wizard.check_migration_status(scheduled.id)

        if status.status == 'completed':
            print(f"✅ Migration completed!")
            break
        elif status.status == 'running':
            print(f"⏳ Running... {status.progress}%")
        elif status.status == 'failed':
            print(f"❌ Migration failed: {status.error}")
            break

        await asyncio.sleep(5)
```

---

## Best Practices

### ✅ Do's

1. **Always dry-run in production**
   ```python
   # Production: Always dry-run first
   dry_run = await wizard.dry_run(migration_id)
   if not dry_run.would_succeed:
       print("Dry-run failed - aborting")
       return
   ```

2. **Assess risk before approval**
   ```python
   risk = await wizard.assess_risk(migration_id)
   if risk.level >= RiskLevel.MEDIUM:
       await wizard.request_approval(...)
   ```

3. **Schedule during maintenance windows**
   ```python
   # 2 AM on Sunday (low traffic)
   scheduled_time = get_maintenance_window()
   await wizard.run_scheduled(migration_id, scheduled_time)
   ```

4. **Monitor scheduled migrations**
   ```python
   # Check status periodically
   while status.status == 'running':
       print(f"Progress: {status.progress}%")
       await asyncio.sleep(10)
   ```

### ❌ Don'ts

1. **Don't execute critical migrations without dry-run**
   ```python
   # Bad: Execute directly
   result = await wizard.run_interactive()

   # Good: Dry-run first
   dry_run = await wizard.dry_run(migration_id)
   result = await wizard.run_interactive()
   ```

2. **Don't ignore risk assessments**
   ```python
   # Bad: Skip risk check
   result = await wizard.run_interactive()

   # Good: Check risk first
   risk = await wizard.assess_risk(migration_id)
   # Handle based on risk level
   ```

3. **Don't schedule critical migrations during peak hours**
   ```python
   # Bad: Run during business hours
   await wizard.run_scheduled(migration_id, datetime(2026, 1, 15, 10, 0))

   # Good: Schedule for maintenance window
   await wizard.run_scheduled(migration_id, datetime(2026, 1, 15, 2, 0))
   ```

---

## Troubleshooting

### Problem: Migration Approval Stuck

**Solution**:
```python
# Check approval status
approval = await wizard.check_approval_status(request_id)
print(f"Pending from: {approval.pending_approvals}")

# Send reminder
await wizard.send_approval_reminder(request_id)

# Force after deadline if configured
if approval.deadline < datetime.now():
    await wizard.auto_approve(request_id)
```

### Problem: Scheduled Migration Didn't Run

**Solution**:
```python
# Check scheduled migration status
scheduled = await wizard.get_scheduled(migration_id)
print(f"Status: {scheduled.status}")
print(f"Error: {scheduled.error}")

# Re-schedule if needed
new_scheduled = await wizard.run_scheduled(migration_id, new_time)
```

---

## See Also

- [Interactive Migration Wizard Guide](../guides/interactive-migration-wizard.md) - User guide
- [Advanced Patterns](../guides/advanced-patterns.md) - Workflow patterns
- [Troubleshooting](../troubleshooting.md) - Common issues

---

**Last Updated**: January 17, 2026

