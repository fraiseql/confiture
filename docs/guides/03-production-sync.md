# Production Data Sync

[← Back to Guides](../index.md) · [Incremental Migrations](02-incremental-migrations.md) · [Schema-to-Schema →](04-schema-to-schema.md)

**Copy production data to local/staging with PII anonymization**

---

## Overview

Production Data Sync copies data from production to development environments with built-in PII anonymization. Get realistic test data without privacy risks.

> **"Test with real data, protect real users"**

### When to Use

| Use Case | Production Sync |
|----------|----------------|
| Local debugging | Perfect |
| Staging environments | Perfect |
| Performance testing | Perfect |
| Schema changes | Use Medium 2 or 4 |
| Fresh database setup | Use Medium 1 |

---

## Quick Start

```bash
# Basic sync
confiture sync --from production --to local

# With anonymization
confiture sync --from production --to local --anonymize

# Specific tables
confiture sync --from production --to staging --tables users,posts

# Exclude tables
confiture sync --from production --to local --exclude logs,analytics
```

---

## Anonymization Strategies

| Strategy | Input | Output |
|----------|-------|--------|
| `email` | alice@example.com | user_a1b2c3@example.com |
| `phone` | +1-555-1234 | +1-555-4567 |
| `name` | Alice Johnson | User A1B2 |
| `redact` | 123-45-6789 | [REDACTED] |
| `hash` | secret_value | a1b2c3d4e5f6 |

### Configuration

```yaml
# db/sync/anonymization.yaml
users:
  - column: email
    strategy: email
    seed: 12345

  - column: phone
    strategy: phone
    seed: 12345

  - column: ssn
    strategy: redact

orders:
  - column: credit_card_last4
    strategy: redact
```

---

## Performance

| Mode | Speed |
|------|-------|
| COPY (no anonymization) | 70,000 rows/sec |
| With anonymization | 6,500 rows/sec |

**Optimal batch size**: 5,000 rows (~1MB memory)

---

## Resume Support

```bash
# Save checkpoint for long syncs
confiture sync --from production --to staging --checkpoint sync.json

# Resume if interrupted
confiture sync --from production --to staging --resume --checkpoint sync.json
```

---

## Best Practices

1. **Use read-only credentials** - Prevent accidental writes to production
2. **Always anonymize PII** - Never sync real user data unmasked
3. **Test anonymization first** - Sync small sample, verify masking
4. **Exclude large tables** - Skip logs, analytics, metrics
5. **Use checkpoints** - For multi-hour syncs
6. **Verify results** - Check that emails/phones are masked

### Verify Anonymization

```sql
-- Check for real emails (should return 0)
SELECT COUNT(*) FROM users WHERE email NOT LIKE '%@example.com';

-- Check redacted values
SELECT COUNT(*) FROM users WHERE ssn = '[REDACTED]';
```

---

## Security

```yaml
# Use environment variables for credentials
database:
  password: ${PROD_DB_PASSWORD}
```

```bash
# Use SSH tunnel for production access
ssh -L 5433:prod-db.internal:5432 bastion.example.com
confiture sync --from production --to local --source-port 5433
```

---

## Common Issues

### "Connection refused"
Verify database is running: `psql -h localhost -U postgres -d myapp_local -c "SELECT 1"`

### "Row count mismatch"
Data changed during sync. Re-run the sync.

### Sync slow (<1000 rows/sec)
Check network latency. Use same region/VPC for source and target.

---

## See Also

- [Anonymization Guide](./anonymization.md) - Custom strategies
- [Compliance Guide](./compliance.md) - GDPR, HIPAA requirements
- [CLI Reference](../reference/cli.md) - All sync commands
