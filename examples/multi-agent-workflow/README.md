# Multi-Agent Workflow Examples

This directory contains practical examples of multi-agent schema coordination workflows using Confiture.

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

# Ensure Confiture is installed
uv pip install -e .
```

## Running Examples

Each example is a standalone shell script:

```bash
cd examples/multi-agent-workflow

# Run example 1
bash 01-parallel-features.sh

# Run example 2
bash 02-conflicting-tables.sh

# Run example 3
bash 03-diamond-dependencies.sh
```

## What You'll Learn

- How to register agent intentions
- How conflict detection works
- Strategies for resolving conflicts
- Multi-agent coordination patterns
- Best practices for parallel development

## Clean Up

After running examples:

```bash
# Clean up test intentions
psql $DATABASE_URL -c "TRUNCATE TABLE tb_pggit_intent CASCADE;"
```

## Next Steps

- Read the [Multi-Agent Coordination Guide](../../docs/guides/multi-agent-coordination.md)
- Review [API documentation](../../docs/api/)
- Try the [pgGit integration](../../docs/guides/integrations.md)
