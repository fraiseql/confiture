# Interactive Migration Wizard

**Step-by-step guided migrations with validation and confirmation prompts**

---

## What is the Interactive Wizard?

The Interactive Migration Wizard guides users through complex migrations with prompts, validation, and confirmations at each step. It's useful for team migrations where you want human oversight and detailed decision-making.

### Key Concept

> **"Migrations shouldn't be fire-and-forget - guide users through each decision"**

The wizard asks questions, validates answers, and ensures migrations are only applied when you're confident.

---

## When to Use the Wizard

### ✅ Perfect For

- **Team coordination** - Ensure team is aware of migration before applying
- **Complex migrations** - Break down into steps for clarity
- **First-time migrations** - Guide new developers through process
- **Production deployments** - Add human checkpoints before production
- **Risk mitigation** - Require explicit confirmation for dangerous operations
- **Audit trails** - Record who approved each migration step
- **Learning** - Understand what each migration does before applying

### ❌ Not For

- **CI/CD automation** - Use `--non-interactive` flag instead
- **Routine migrations** - Use automatic `migrate up` for simple cases
- **Batch operations** - Use scripts for multiple environments
- **Development environment** - Too slow for quick iteration

---

## How the Wizard Works

### The Interactive Lifecycle

```
confiture migrate wizard
         │
         ├─→ Load pending migrations
         │
         ├─→ For each migration:
         │   ├─ Display description
         │   ├─ Ask for confirmation
         │   ├─ Run migration
         │   ├─ Show results
         │   └─ Ask to continue
         │
         ├─→ Review summary
         │
         └─→ Ask for final confirmation
```

### Wizard Modes

| Mode | Interaction | Use Case |
|------|-------------|----------|
| `--wizard` | Full prompts | Team migrations |
| `--wizard --review` | Show changes first | Caution before executing |
| `--wizard --auto` | Skip confirmations | Supervised but quick |
| `--non-interactive` | No prompts | CI/CD pipelines |

---

## Basic Usage

### Running the Wizard

```bash
# Start interactive wizard for pending migrations
confiture migrate wizard

# Wizard with detailed review
confiture migrate wizard --review

# Skip confirmations (still interactive, just faster)
confiture migrate wizard --auto
```

**Output**:
```
🧙 Confiture Migration Wizard
═════════════════════════════════════════════════════════════

📋 Found 2 pending migrations:

  1. 001_create_users_table
     Added 2 days ago by john@acme.com

     Summary: Create users table with email and timestamps

  2. 002_add_user_bio
     Added 1 day ago by jane@acme.com

     Summary: Add optional biography field to users

═════════════════════════════════════════════════════════════

🚀 Ready to apply 2 migrations to 'production'?

Options:
  1. Review first migration
  2. Apply all (with confirmation at each step)
  3. Cancel

Choose: _
```

---

## Example: Step-by-Step Confirmation

**Situation**: Team applies migrations with full review before production.

```bash
# Start wizard
$ confiture migrate wizard --env production

🧙 Confiture Migration Wizard
═════════════════════════════════════════════════════════════

📋 Found 1 pending migration:
  001_add_payment_table
  Summary: Add payment processing table

🔍 Review migration SQL? [y/N]: y

SQL Preview:
┌─────────────────────────────────────────┐
│ CREATE TABLE payments (                 │
│   id UUID PRIMARY KEY,                  │
│   user_id UUID NOT NULL REFERENCES users,
│   amount DECIMAL(10, 2),                │
│   status TEXT DEFAULT 'pending',        │
│   created_at TIMESTAMPTZ DEFAULT NOW()  │
│ );                                      │
└─────────────────────────────────────────┘

👤 Apply as (default: current_user): payments_team

⏰ When to apply? [now/scheduled/cancel]: now

📝 Note for audit (optional): Production payment processing

✅ Ready to apply migration 001_add_payment_table?

  Environment: production
  Applied by: payments_team
  Note: Production payment processing

Confirm? [y/N]: y

⏳ Applying migration...
✅ Migration applied in 234ms

Continue to next migration? [Y/n]: n

═════════════════════════════════════════════════════════════
✅ Completed: 1/1 migrations applied
```

**Explanation**: The wizard walks through each migration with detailed review before applying to production.

---

## Example: Scheduled Migrations

**Situation**: Schedule migrations to run at maintenance window.

```bash
# Start wizard with scheduling
$ confiture migrate wizard --env production

🧙 Confiture Migration Wizard
═════════════════════════════════════════════════════════════

📋 Found 1 pending migration:
  002_add_indexes
  Summary: Add database indices for performance

⏰ When to apply?

Options:
  1. Now
  2. Scheduled (specify time)
  3. Skip

Choose: 2

📅 Schedule for when?

  Format: YYYY-MM-DD HH:MM (UTC)
  Examples:
    - Tomorrow 2am: 2025-12-28 02:00
    - Next Sunday: 2025-01-05 00:00

Enter time: 2025-12-28 02:00

🔔 Set reminder?

  Email: [alerts@acme.com]
  Slack: [#database-alerts]

Send reminder? [y/N]: y

📝 Note for scheduling: Scheduled during maintenance window

✅ Migration scheduled for 2025-12-28 02:00 UTC

  Email reminder: alerts@acme.com
  Applied by: john@acme.com
  Note: Scheduled during maintenance window

═════════════════════════════════════════════════════════════
✅ Scheduled: 1 migration set for future execution
```

---

## Example: Conditional Review

**Situation**: Only review risky migrations, auto-apply simple ones.

```bash
# Wizard with smart review
$ confiture migrate wizard --review --smart

🧙 Confiture Migration Wizard (Smart Mode)
═════════════════════════════════════════════════════════════

📋 Found 3 pending migrations:

  1. 003_add_column (LOW RISK - auto-approved)
     Adding optional column to users

  2. 004_rename_table (HIGH RISK - requires review)
     Renaming table (schema change)

  3. 005_drop_column (CRITICAL - requires approval)
     Removing column with data

═════════════════════════════════════════════════════════════

🔍 Review HIGH RISK migration: 004_rename_table?

SQL:
  ALTER TABLE old_name RENAME TO new_name;

⚠️  This operation requires:
  - All references updated
  - Application code changes
  - Possible downtime

Approve? [y/N]: y

🔍 Review CRITICAL migration: 005_drop_column?

⚠️  CRITICAL: This will DELETE DATA!

Column: user_preferences (TEXT, 45,000 rows)
Cannot be recovered unless backed up externally.

Backup taken? [y/N]: y

Confirm delete? [y/N]: y

✅ All migrations reviewed and approved

Apply now? [Y/n]: y

Applying migrations: 003, 004, 005...
✅ All 3 migrations applied successfully
```

---

## Example: Collaborative Migration

**Situation**: Multiple team members review and approve migration chain.

```bash
# Start collaborative mode
$ confiture migrate wizard --collaborative --env production

🧙 Confiture Migration Wizard (Collaborative)
═════════════════════════════════════════════════════════════

📋 Found 2 pending migrations:

  1. 006_add_audit_table
  2. 007_add_audit_triggers

👥 Assigned to:
  Developer: john@acme.com
  Reviewer: jane@acme.com
  DBA: bob@acme.com

═════════════════════════════════════════════════════════════

Your role: Developer

✏️  Write migration description (for reviewers):

What's the business impact?
> Adding compliance audit table to track all data changes

Any risks or concerns?
> No known risks, similar to staging migrations

Should reviewers test first?
> Yes, test in staging first

═════════════════════════════════════════════════════════════

📨 Sending for review to:
  - jane@acme.com (Reviewer)
  - bob@acme.com (DBA)

Waiting for approvals:
  ⏳ jane@acme.com
  ⏳ bob@acme.com

[Interactive: You can cancel or wait for approvals]

---

[After reviewers approve via email/link]

✅ Approval from jane@acme.com
✅ Approval from bob@acme.com

Ready to proceed? [Y/n]: y

📝 Apply with notes:
  Developer: john@acme.com
  Reviewed by: jane@acme.com, bob@acme.com
  Applied: 2025-12-27 15:00 UTC

✅ Applying 2 migrations with full audit trail...
✅ Completed successfully

═════════════════════════════════════════════════════════════
✅ Audit log created with all approvals
```

---

## Best Practices

### 1. Always Review Production Migrations

**Good**:
```bash
# Use wizard for important environments
confiture migrate wizard --env production --review

# Or add confirmation manually
confiture migrate up --env production --require-confirmation
```

**Bad**:
```bash
# Auto-apply to production without review
confiture migrate up --env production
```

### 2. Use Risk Classification

**Good**:
```yaml
# db/confiture.yaml

migrations:
  001_add_column:
    risk_level: low
    auto_approve: true

  002_rename_table:
    risk_level: high
    require_approval: true

  003_drop_column:
    risk_level: critical
    require_backup: true
```

**Bad**:
```yaml
# No risk classification
migrations: {}
```

### 3. Include Rollback Plan

**Good**:
```bash
# Wizard shows rollback options
confiture migrate wizard --show-rollback

# Review rollback before executing migration
confiture migrate wizard --review-rollback --env production
```

**Bad**:
```bash
# Apply without understanding how to rollback
confiture migrate up --env production
```

---

## Troubleshooting

### ❌ Error: "User timeout in wizard"

**Cause**: Wizard waiting for input too long.

**Solution**: Use `--timeout` flag:

```bash
# Set 5-minute timeout
confiture migrate wizard --timeout 300

# Or use non-interactive for automation
confiture migrate up --non-interactive
```

**Explanation**: Interactive mode is human-driven; set timeouts for CI/CD.

---

### ❌ Error: "Insufficient permissions"

**Cause**: User doesn't have role to approve migration.

**Solution**: Check collaborative settings:

```python
# In confiture_hooks.py

@register_hook('pre_execute')
def check_permissions(context: HookContext) -> None:
    """Ensure user has permission."""
    import os
    user = os.getenv('USER')
    required_role = context.migration.metadata.get('required_role')

    if required_role and not has_role(user, required_role):
        raise PermissionError(f"User {user} cannot apply {required_role} migrations")
```

---

## See Also

- [Advanced Patterns](./advanced-patterns.md) - Collaborative workflows
- [Migration Decision Tree](./migration-decision-tree.md) - Choose strategy
- [Troubleshooting](../troubleshooting.md) - Common issues
- [CLI Reference](../reference/cli.md) - All wizard flags

---

## 🎯 Next Steps

**Ready to guide your migrations?**
- ✅ You now understand: Wizard modes, risk classification, collaboration

**What to do next:**

1. **[Advanced Patterns](./advanced-patterns.md)** - Collaborative workflows
2. **[CLI Reference](../reference/cli.md)** - Full wizard command documentation
3. **[Examples](../../examples/)** - Production-ready wizard examples

**Got questions?**
- **[FAQ](../glossary.md)** - Glossary and definitions
- **[Troubleshooting](../troubleshooting.md)** - Common issues

---

*Part of Confiture documentation* 🍓

*Making migrations sweet and simple*
