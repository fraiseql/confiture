# Production Syncer API

The `ProductionSyncer` class implements Medium 3: Production Data Sync with PII anonymization.

## Overview

The ProductionSyncer copies data from production to staging/local environments with built-in PII anonymization. It uses PostgreSQL's COPY protocol for high-performance streaming.

## Quick Example

```python
from confiture.core.syncer import (
    ProductionSyncer,
    SyncConfig,
    TableSelection,
    AnonymizationRule
)

# Define anonymization rules
anonymization = {
    "users": [
        AnonymizationRule(column="email", strategy="email", seed=12345),
        AnonymizationRule(column="phone", strategy="phone", seed=12345),
        AnonymizationRule(column="ssn", strategy="redact"),
    ]
}

# Configure sync
config = SyncConfig(
    tables=TableSelection(
        include=["users", "posts", "comments"],
        exclude=["logs", "analytics"]
    ),
    anonymization=anonymization,
    batch_size=5000,
    show_progress=True
)

# Execute sync
with ProductionSyncer(source="production", target="local") as syncer:
    results = syncer.sync(config)
    print(f"Synced {sum(results.values())} total rows")

    # Get metrics
    metrics = syncer.get_metrics()
    for table, stats in metrics.items():
        print(f"{table}: {stats['rows_per_second']:.0f} rows/sec")
```

## API Reference

::: confiture.core.syncer.ProductionSyncer
    options:
      show_source: true
      members:
        - __init__
        - sync
        - sync_table
        - get_all_tables
        - select_tables
        - get_metrics
        - save_checkpoint
        - load_checkpoint

## Anonymization Strategies

| Strategy | Example Input | Example Output | Use Case |
|----------|--------------|----------------|----------|
| `email` | `alice@example.com` | `user_a1b2c3d4@example.com` | Email addresses |
| `phone` | `+1-555-1234` | `+1-555-4567` | Phone numbers |
| `name` | `Alice Johnson` | `User A1B2` | Names |
| `redact` | `123-45-6789` | `[REDACTED]` | SSN, credit cards |
| `hash` | `secret123` | `a1b2c3d4e5f6789a` | API keys, tokens |

## Performance Benchmarks

Based on comprehensive testing:

| Mode | Throughput | Use Case |
|------|------------|----------|
| COPY (no anonymization) | 70,396 rows/sec | Non-PII tables |
| With anonymization (3 columns) | 6,515 rows/sec | User data |

**Optimal batch size**: 5,000 rows (determined via benchmarking)

## See Also

- [Medium 3: Production Sync Guide](../guides/medium-3-production-sync.md)
- [Performance Guide](../performance.md)
- [CLI Reference: sync command](../reference/cli.md#sync)
