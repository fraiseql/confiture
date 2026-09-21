# Multi-Agent Workflow Examples

This directory contains practical examples of multi-agent schema coordination workflows using the `confiture coordinate` commands this plugin adds.

## Examples

### 1. Simple Parallel Development (`01-parallel-features.sh`)
Two agents working on independent tables with no conflicts.

### 2. Conflicting Changes (`02-conflicting-tables.sh`)
Two agents working on the same table, detecting and resolving conflicts.

### 3. Diamond Dependencies (`03-diamond-dependencies.sh`)
Three agents with transitive dependencies requiring careful coordination.

## Prerequisites

```bash
# Set database URL
export DATABASE_URL=postgresql://localhost/confiture_dev

# Install confiture and this plugin (from confiture's repository root)
uv pip install -e . -e plugins/fraiseql-confiture-pggit
```

## Running Examples

Each example is a standalone shell script:

```bash
cd plugins/fraiseql-confiture-pggit/examples/multi-agent-workflow

# Run example 1
bash 01-parallel-features.sh

# Run example 2
bash 02-conflicting-tables.sh

# Run example 3
bash 03-diamond-dependencies.sh
```

## Key Commands

```bash
# Register an intention (the coordination tables are created on first use;
# there is no separate init step)
confiture coordinate register \
    --agent-id alice \
    --feature-name user_profiles \
    --schema-changes "ALTER TABLE users ADD COLUMN bio TEXT" \
    --tables-affected users

# Check a proposed change for conflicts before registering it
confiture coordinate check \
    --agent-id bob \
    --feature-name user_status \
    --schema-changes "ALTER TABLE users ADD COLUMN status TEXT" \
    --tables-affected users

# List every intention, or show one
confiture coordinate list-intents --format json
confiture coordinate status --intent-id int_abc123

# Resolve a conflict once the two agents have agreed (the ID is the integer
# `status` and `conflicts` print)
confiture coordinate resolve --conflict-id 1 --notes "alice goes first"

# Drop an intent that was never carried out
confiture coordinate abandon --intent-id int_abc123 --reason "superseded"
```

## What You'll Learn

- How to register agent intentions
- How conflict detection works
- Strategies for resolving conflicts
- Multi-agent coordination patterns
- Best practices for parallel development

These patterns suit teams with several developers on one schema, AI-assisted schema
development with several agents, CI/CD pipelines that check for conflicts
automatically, and projects that need an audit trail of who changed what, and when.

## Clean Up

After running examples:

```bash
# Clean up test intentions
psql $DATABASE_URL -c "TRUNCATE TABLE tb_pggit_intent CASCADE;"
```

## Next Steps

- Read the [Multi-Agent Coordination Guide](../../docs/multi-agent-coordination.md)
- Review the [Python API](../../docs/multi-agent-coordination.md#api-usage)
- Wire coordination into [CI/CD](../../docs/ci-integration.md)
- Try the [`confiture branch` commands](../../docs/cli.md#confiture-branch)
