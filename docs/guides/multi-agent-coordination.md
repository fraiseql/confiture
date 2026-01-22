# Multi-Agent Coordination Guide

**Confiture Multi-Agent Coordination** enables multiple agents (AI or human developers) to work in parallel on database schema changes with automatic conflict detection and resolution workflows.

This guide covers the `confiture coordinate` CLI commands and multi-agent development patterns.

---

## Table of Contents

- [Overview](#overview)
- [Quick Start](#quick-start)
- [CLI Reference](#cli-reference)
- [Workflows](#workflows)
- [Conflict Resolution](#conflict-resolution)
- [Best Practices](#best-practices)
- [Examples](#examples)
- [Troubleshooting](#troubleshooting)

---

## Overview

### Why Multi-Agent Coordination?

In modern development workflows, multiple teams or AI agents often need to make database schema changes simultaneously. Without coordination:

❌ **Problems:**
- Conflicting schema changes discovered late (during merge)
- Unclear who's working on which tables
- Wasted effort from incompatible changes
- Database migration conflicts

✅ **With Confiture Coordination:**
- Declare intentions **before** making changes
- Automatic conflict detection
- Clear visibility into all active schema work
- Suggestions for resolving conflicts
- Audit trail of all coordination decisions

### Key Concepts

**Intent**: A declared plan to make schema changes
- Agent ID (who's making the change)
- Feature name (what's being built)
- Schema changes (DDL statements)
- Tables affected
- Risk level

**Conflict**: Detected overlap between intents
- Type (table, column, function, constraint, index, timing)
- Severity (warning, error)
- Suggestions for resolution

**Status Lifecycle**:
```
REGISTERED → IN_PROGRESS → COMPLETED → MERGED
                ↓
           ABANDONED / CONFLICTED
```

---

## Quick Start

### 1. Register Your Intention

Before starting work, declare what you plan to change:

```bash
confiture coordinate register \
    --agent-id claude-payments \
    --feature-name stripe_integration \
    --schema-changes "ALTER TABLE users ADD COLUMN stripe_customer_id TEXT" \
    --tables-affected users \
    --risk-level medium \
    --estimated-hours 3
```

**Output:**
```
┌─────────────────────────────────────────┐
│ Intention Registered                     │
├─────────────────────────────────────────┤
│ Intent ID:     int_abc123def456          │
│ Agent:         claude-payments           │
│ Feature:       stripe_integration        │
│ Branch:        feature/stripe_int_001    │
│ Status:        REGISTERED                │
│ Risk Level:    medium                    │
│ Tables Affected: users                   │
└─────────────────────────────────────────┘

⚠️  Warning: Found 1 conflict(s) with existing intentions:
  - table: users [warning]
```

### 2. Check for Conflicts

Pre-flight check before registering:

```bash
confiture coordinate check \
    --agent-id claude-auth \
    --feature-name oauth2 \
    --schema-changes "ALTER TABLE users ADD COLUMN oauth_provider TEXT" \
    --tables-affected users
```

### 3. List All Intentions

See what everyone's working on:

```bash
confiture coordinate list-intents
```

**Output:**
```
┌──────────────────────────────────────────────────────────┐
│ Intentions (3 total)                                     │
├──────────┬──────────┬──────────────┬──────────┬────────┤
│ ID       │ Agent    │ Feature      │ Status   │ Risk   │
├──────────┼──────────┼──────────────┼──────────┼────────┤
│ int_abc1 │ claude-p │ stripe       │ in_prog  │ medium │
│ int_def2 │ claude-a │ oauth2       │ register │ low    │
│ int_ghi3 │ claude-n │ notifications│ complete │ low    │
└──────────┴──────────┴──────────────┴──────────┴────────┘
```

### 4. Get Intent Status

Check detailed status of specific intent:

```bash
confiture coordinate status --intent-id int_abc123def456
```

### 5. Resolve Conflicts

Mark conflict as reviewed:

```bash
confiture coordinate resolve \
    --conflict-id 42 \
    --notes "Coordinated with claude-auth: using oauth_provider_id instead"
```

### 6. Abandon Intent

Changed your mind? Abandon the intent:

```bash
confiture coordinate abandon \
    --intent-id int_abc123def456 \
    --reason "Feature cancelled by product team"
```

---

## CLI Reference

### `confiture coordinate register`

Register a new agent intention for schema changes.

**Required Options:**
- `--agent-id TEXT` - Agent identifier (e.g., `claude-payments`, `developer-alice`)
- `--feature-name TEXT` - Human-readable feature name
- `--schema-changes TEXT` - DDL statements (semicolon-separated) or path to SQL file

**Optional Options:**
- `--tables-affected TEXT` - Comma-separated table names
- `--risk-level TEXT` - Risk assessment: `low`, `medium`, `high` (default: `low`)
- `--estimated-hours FLOAT` - Estimated hours to complete
- `--metadata TEXT` - JSON metadata string
- `--database-url TEXT` - Database URL (or use `DATABASE_URL` env var)

**Examples:**
```bash
# Simple registration
confiture coordinate register \
    --agent-id claude-test \
    --feature-name user_profiles \
    --schema-changes "ALTER TABLE users ADD COLUMN bio TEXT"

# With all options
confiture coordinate register \
    --agent-id claude-payments \
    --feature-name stripe_integration \
    --schema-changes "ALTER TABLE users ADD COLUMN stripe_id TEXT; CREATE INDEX idx_users_stripe ON users(stripe_id)" \
    --tables-affected users \
    --risk-level high \
    --estimated-hours 8 \
    --metadata '{"jira_ticket": "PROJ-123", "priority": "high"}'

# From SQL file
confiture coordinate register \
    --agent-id claude-data \
    --feature-name analytics \
    --schema-changes ./migrations/add_analytics_tables.sql \
    --risk-level medium
```

---

### `confiture coordinate list-intents`

List all registered intentions with optional filtering.

**Optional Options:**
- `--status-filter TEXT` - Filter by status: `registered`, `in_progress`, `completed`, `merged`, `abandoned`, `conflicted`
- `--agent-filter TEXT` - Filter by agent ID
- `--database-url TEXT` - Database URL

**Examples:**
```bash
# List all intentions
confiture coordinate list-intents

# Show only in-progress work
confiture coordinate list-intents --status-filter in_progress

# Show work by specific agent
confiture coordinate list-intents --agent-filter claude-payments

# Combine filters (show claude-payments' in-progress work)
confiture coordinate list-intents \
    --status-filter in_progress \
    --agent-filter claude-payments
```

---

### `confiture coordinate check`

Pre-flight check for conflicts with proposed changes.

**Required Options:**
- `--agent-id TEXT` - Agent identifier
- `--feature-name TEXT` - Feature name
- `--schema-changes TEXT` - DDL statements or SQL file path

**Optional Options:**
- `--tables-affected TEXT` - Comma-separated table names
- `--database-url TEXT` - Database URL

**Examples:**
```bash
# Check before registering
confiture coordinate check \
    --agent-id claude-auth \
    --feature-name oauth2 \
    --schema-changes "ALTER TABLE users ADD COLUMN oauth_provider TEXT" \
    --tables-affected users

# Check from file
confiture coordinate check \
    --agent-id claude-test \
    --feature-name test_feature \
    --schema-changes ./proposed_changes.sql
```

---

### `confiture coordinate status`

Show detailed status of a specific intention.

**Required Options:**
- `--intent-id TEXT` - Intention ID (returned from `register` or found in `list-intents`)

**Optional Options:**
- `--database-url TEXT` - Database URL

**Examples:**
```bash
confiture coordinate status --intent-id 550e8400-e29b-41d4-a716-446655440000
```

---

### `confiture coordinate conflicts`

List all detected conflicts between intentions.

**Optional Options:**
- `--database-url TEXT` - Database URL

**Examples:**
```bash
# Show all conflicts
confiture coordinate conflicts
```

---

### `confiture coordinate resolve`

Mark a conflict as reviewed and provide resolution notes.

**Required Options:**
- `--conflict-id INTEGER` - Conflict ID (from `status` or `conflicts` output)
- `--notes TEXT` - Resolution notes explaining how conflict was resolved

**Optional Options:**
- `--database-url TEXT` - Database URL

**Examples:**
```bash
confiture coordinate resolve \
    --conflict-id 42 \
    --notes "Agents coordinated: applying changes sequentially. Auth first, then payments."

confiture coordinate resolve \
    --conflict-id 15 \
    --notes "No actual conflict - different columns. Risk accepted."
```

---

### `confiture coordinate abandon`

Abandon an intention before completion.

**Required Options:**
- `--intent-id TEXT` - Intention ID
- `--reason TEXT` - Reason for abandonment

**Optional Options:**
- `--database-url TEXT` - Database URL

**Examples:**
```bash
confiture coordinate abandon \
    --intent-id int_abc123 \
    --reason "Feature cancelled by product team"

confiture coordinate abandon \
    --intent-id int_def456 \
    --reason "Replaced by different approach (see int_xyz789)"
```

---

## Workflows

### Workflow 1: Solo Agent (No Conflicts)

```bash
# 1. Check for conflicts first
confiture coordinate check \
    --agent-id claude-solo \
    --feature-name new_feature \
    --schema-changes "CREATE TABLE widgets (id UUID PRIMARY KEY)"
# ✓ No conflicts detected!

# 2. Register intention
confiture coordinate register \
    --agent-id claude-solo \
    --feature-name new_feature \
    --schema-changes "CREATE TABLE widgets (id UUID PRIMARY KEY)"
# Intent ID: int_solo123

# 3. Perform migration work
# ... develop schema changes ...

# 4. Mark as completed (done via registry API or manually)
# registry.mark_completed('int_solo123')
```

### Workflow 2: Two Agents, Same Table (Conflict)

**Agent A (Payments):**
```bash
# Register first
confiture coordinate register \
    --agent-id claude-payments \
    --feature-name stripe_integration \
    --schema-changes "ALTER TABLE users ADD COLUMN stripe_customer_id TEXT" \
    --tables-affected users \
    --risk-level medium
# Intent ID: int_payments123
# ✓ No conflicts
```

**Agent B (Auth):**
```bash
# Register second
confiture coordinate register \
    --agent-id claude-auth \
    --feature-name oauth2_provider \
    --schema-changes "ALTER TABLE users ADD COLUMN oauth_provider_id TEXT" \
    --tables-affected users \
    --risk-level medium
# Intent ID: int_auth456
# ⚠️  Warning: Found 1 conflict(s):
#   - table: users [warning]
```

**Coordination:**
```bash
# Agent B checks conflict details
confiture coordinate status --intent-id int_auth456
# Conflict (1):
#   1. table [warning] (users)
#      Suggestions:
#      - Coordinate column naming with other agent
#      - Consider sequential application
#      - Review column names for conflicts

# Agents discuss and decide: proceed sequentially
confiture coordinate resolve \
    --conflict-id 1 \
    --notes "Coordinated: Payments applies first, then Auth. No column name conflicts."

# Both agents proceed with awareness
```

### Workflow 3: Diamond Dependencies

Three agents with transitive dependencies:

```bash
# Agent A: Modify users table
confiture coordinate register \
    --agent-id claude-users \
    --feature-name user_enhancements \
    --schema-changes "ALTER TABLE users ADD COLUMN preferences JSONB" \
    --tables-affected users

# Agent B: Modify orders table (FK to users)
confiture coordinate register \
    --agent-id claude-orders \
    --feature-name order_tracking \
    --schema-changes "ALTER TABLE orders ADD CONSTRAINT fk_users FOREIGN KEY (user_id) REFERENCES users(id)" \
    --tables-affected orders,users

# Agent C: Create new table referencing both
confiture coordinate register \
    --agent-id claude-analytics \
    --feature-name user_order_analytics \
    --schema-changes "CREATE TABLE user_order_stats AS SELECT u.id, COUNT(o.id) FROM users u JOIN orders o ON u.id = o.user_id" \
    --tables-affected users,orders

# System detects all 3-way conflict
# Agents coordinate execution order: A → B → C
```

---

## Conflict Resolution

### Conflict Types

1. **TABLE** - Both agents modifying same table
   - **Severity**: WARNING
   - **Action**: Coordinate column names, review for actual conflicts

2. **COLUMN** - Both agents modifying same column
   - **Severity**: ERROR
   - **Action**: Must coordinate - likely incompatible

3. **FUNCTION** - Both agents redefining same function
   - **Severity**: ERROR
   - **Action**: Must coordinate - cannot both change same function

4. **INDEX** - Both creating/modifying same index
   - **Severity**: WARNING
   - **Action**: Review for duplication

5. **CONSTRAINT** - Both modifying constraints
   - **Severity**: WARNING
   - **Action**: Check for conflicts

6. **TIMING** - Timing-based conflicts (e.g., same feature name)
   - **Severity**: WARNING
   - **Action**: Review if intentional

### Resolution Strategies

**Strategy 1: Sequential Application**
- Agents agree on order: A → B → C
- Mark conflicts as resolved with notes
- Apply migrations in sequence

**Strategy 2: Scope Adjustment**
- One agent adjusts scope (different column name)
- Abandon and re-register with new scope
- Proceed independently

**Strategy 3: Risk Acceptance**
- Review conflict, determine low risk
- Mark as resolved with justification
- Proceed with caution

**Strategy 4: Merge Efforts**
- Agents combine work into single intent
- Abandon duplicate intents
- One agent proceeds with combined changes

---

## Best Practices

### 1. Always Check First
```bash
# Good: Check before registering
confiture coordinate check ... && confiture coordinate register ...

# Bad: Register without checking
confiture coordinate register ...  # Might conflict!
```

### 2. Descriptive Intent Information
```bash
# Good: Clear, specific
confiture coordinate register \
    --agent-id claude-payments \
    --feature-name stripe_payment_methods \
    --schema-changes "..." \
    --tables-affected users,payments,payment_methods \
    --metadata '{"jira": "PAY-123", "pr": "https://github.com/..."}'

# Bad: Vague
confiture coordinate register \
    --agent-id claude \
    --feature-name update \
    --schema-changes "..."
```

### 3. Update Status Regularly
- Mark `IN_PROGRESS` when starting work
- Mark `COMPLETED` when done
- Mark `ABANDONED` if cancelled
- Don't leave stale intentions

### 4. Resolve Conflicts Explicitly
```bash
# Document resolution
confiture coordinate resolve \
    --conflict-id 42 \
    --notes "Detailed explanation of how conflict was resolved"

# Bad: Ignore conflicts
# (System will track unresolved conflicts)
```

### 5. Use Risk Levels Appropriately
- `low`: Single table, additive changes (ADD COLUMN)
- `medium`: Multiple tables, FK changes, indexes
- `high`: DROP operations, major refactoring, data migrations

### 6. Coordinate Large Changes
For large schema changes affecting many tables:
1. Break into smaller intents
2. Register sequentially
3. Coordinate with team
4. Document dependencies

---

## Examples

### Example 1: Adding User Preferences

```bash
# Check for conflicts
confiture coordinate check \
    --agent-id claude-ux \
    --feature-name user_preferences \
    --schema-changes "ALTER TABLE users ADD COLUMN preferences JSONB DEFAULT '{}'" \
    --tables-affected users

# Register (assuming no conflicts)
confiture coordinate register \
    --agent-id claude-ux \
    --feature-name user_preferences \
    --schema-changes "ALTER TABLE users ADD COLUMN preferences JSONB DEFAULT '{}'; CREATE INDEX idx_users_preferences ON users USING GIN(preferences)" \
    --tables-affected users \
    --risk-level low \
    --estimated-hours 2

# Perform migration work
# ...

# Check status
confiture coordinate status --intent-id <returned_id>
```

### Example 2: Two-Phase Feature

**Phase 1: Add Columns**
```bash
confiture coordinate register \
    --agent-id claude-analytics \
    --feature-name analytics_phase1 \
    --schema-changes "ALTER TABLE events ADD COLUMN session_id UUID; ALTER TABLE events ADD COLUMN user_agent TEXT" \
    --tables-affected events \
    --risk-level low
```

**Phase 2: Add Indexes (after Phase 1)**
```bash
confiture coordinate register \
    --agent-id claude-analytics \
    --feature-name analytics_phase2 \
    --schema-changes "CREATE INDEX idx_events_session ON events(session_id); CREATE INDEX idx_events_user_agent ON events USING GIN(user_agent gin_trgm_ops)" \
    --tables-affected events \
    --risk-level low \
    --metadata '{"depends_on": "analytics_phase1"}'
```

### Example 3: Handling Conflict

```bash
# Agent A registers
confiture coordinate register \
    --agent-id claude-a \
    --feature-name feature_a \
    --schema-changes "ALTER TABLE products ADD COLUMN featured BOOLEAN DEFAULT FALSE" \
    --tables-affected products

# Agent B registers (conflict!)
confiture coordinate register \
    --agent-id claude-b \
    --feature-name feature_b \
    --schema-changes "ALTER TABLE products ADD COLUMN is_featured BOOLEAN DEFAULT FALSE" \
    --tables-affected products
# ⚠️  Warning: Found 1 conflict(s): table: products [warning]

# Review conflict
confiture coordinate status --intent-id <agent_b_id>

# Agents discuss: Agent B renames to avoid overlap
confiture coordinate abandon \
    --intent-id <agent_b_id> \
    --reason "Column name conflict with feature_a, adjusting scope"

confiture coordinate register \
    --agent-id claude-b \
    --feature-name feature_b \
    --schema-changes "ALTER TABLE products ADD COLUMN promoted BOOLEAN DEFAULT FALSE" \
    --tables-affected products
# ✓ No conflicts
```

---

## Troubleshooting

### Problem: "No database URL provided"

**Error:**
```
Error: No database URL provided. Use --db-url or set DATABASE_URL environment variable
```

**Solution:**
```bash
# Option 1: Pass URL directly
confiture coordinate register --database-url postgresql://localhost/mydb ...

# Option 2: Set environment variable
export DATABASE_URL=postgresql://localhost/mydb
confiture coordinate register ...
```

### Problem: "Intention not found"

**Error:**
```
Error: Intention not found: int_abc123
```

**Solution:**
- Check intent ID spelling
- Verify intent wasn't abandoned
- List all intents: `confiture coordinate list-intents`

### Problem: Conflicts Not Detected

**Issue:** Expected conflict not showing up

**Check:**
1. Are both intents in `REGISTERED` or `IN_PROGRESS` status?
2. Did you specify `--tables-affected` accurately?
3. Are DDL statements parseable (valid SQL)?

**Debug:**
```bash
# List all intents to verify states
confiture coordinate list-intents

# Check specific intent
confiture coordinate status --intent-id <id>

# View all conflicts
confiture coordinate conflicts
```

### Problem: Cannot Mark as Resolved

**Issue:** Conflict resolution not working

**Check:**
- Use correct `--conflict-id` (integer, not intent ID)
- Get conflict ID from `status` or `conflicts` output

**Example:**
```bash
# Get conflict ID from status
confiture coordinate status --intent-id int_abc123
# Output shows: "1. table [warning] ..."
#               ↑ This is conflict ID (database row ID)

# Use that ID
confiture coordinate resolve --conflict-id 1 --notes "..."
```

---

## Integration with pgGit

Multi-agent coordination is designed to work seamlessly with Confiture's pgGit integration:

1. **Intent → Branch**: Each registered intent gets a unique branch name
2. **Conflicts → Review**: Conflicts detected before git merge
3. **Coordination → Merge Order**: Agents coordinate merge sequence
4. **History → Audit**: Full audit trail preserved

See [pgGit Integration Guide](integrations.md) for details.

---

## API Usage

For programmatic usage (not CLI), see the Python API:

```python
from confiture.integrations.pggit.coordination import IntentRegistry
import psycopg

# Connect
conn = psycopg.connect("postgresql://localhost/mydb")
registry = IntentRegistry(conn)

# Register
intent = registry.register(
    agent_id="claude-test",
    feature_name="test_feature",
    schema_changes=["ALTER TABLE users ADD COLUMN test TEXT"],
    tables_affected=["users"],
)

# Check conflicts
conflicts = registry.get_conflicts(intent.id)

# Update status
registry.mark_in_progress(intent.id)
registry.mark_completed(intent.id)
```

---

## Summary

Multi-agent coordination enables:
- ✅ Parallel development without conflicts
- ✅ Early detection of incompatible changes
- ✅ Clear communication between agents
- ✅ Audit trail of all schema work
- ✅ Reduced merge conflicts
- ✅ Better collaboration

Start with `confiture coordinate check`, register intentions, resolve conflicts, and enjoy smooth multi-agent development!

---

**Related Guides:**
- [pgGit Integration](integrations.md)
- [Migration Hooks](hooks.md)
- [Schema Linting](schema-linting.md)

**Version:** 0.3.7
**Last Updated:** January 2026
