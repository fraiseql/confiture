# Medium 3: Production Data Sync

**Copy production data to local/staging environments with PII anonymization**

## What is Production Data Sync?

Production Data Sync copies data from your production database to local or staging environments, with built-in [PII](../glossary.md#pii) (Personally Identifiable Information) [anonymization](../glossary.md#anonymization). This gives you production-like data for development and testing without exposing sensitive user information.

### Key Concept

> **"Test with real data, protect real users"**

Confiture streams data using PostgreSQL's high-performance COPY protocol while anonymizing PII columns on-the-fly. Get realistic test data without privacy risks.

---

## When to Use Production Data Sync

### ✅ Perfect For

- **Local development** - Reproduce production bugs with real data
- **Staging environments** - Test features with production-like data
- **Bug investigation** - Debug issues that only occur with real data patterns
- **Performance testing** - Realistic dataset sizes and distributions
- **Migration testing** - Validate migrations on production-like data
- **QA testing** - Test edge cases present in production

### ❌ Not For

- **Schema changes** - Use [Medium 2](./medium-2-incremental-migrations.md) (Incremental) or [Medium 4](./medium-4-schema-to-schema.md) (Schema-to-Schema)
- **Fresh database setup** - Use [Medium 1](./medium-1-build-from-ddl.md) (Build from DDL)
- **Production backups** - Use pg_dump or proper backup tools
- **Sharing unmasked [PII](../glossary.md#pii)** - Always use [anonymization](../glossary.md#anonymization)!

### Compliance and Security

Production Data Sync with anonymization helps maintain compliance with:
- **GDPR** (General Data Protection Regulation)
- **CCPA** (California Consumer Privacy Act)
- **HIPAA** (Health Insurance Portability and Accountability Act)
- **SOC 2** (System and Organization Controls)

---

## How Production Data Sync Works

### The Sync Process

```
1. Table Selection
   ↓
   Select which tables to sync (include/exclude patterns)

2. Schema Verification
   ↓
   Verify target schema matches source

3. For each table:
   ├─ No anonymization needed?
   │  └─ Fast path: COPY streaming (70K rows/sec)
   │
   └─ Anonymization needed?
      └─ Slower path: Fetch, anonymize, insert (6.5K rows/sec)

4. Progress Tracking
   ↓
   Real-time progress with estimated time remaining

5. Verification
   ↓
   Verify row counts match

6. Checkpoint (optional)
   ↓
   Save progress for resume capability
```

### Performance Characteristics

Based on comprehensive benchmarking (see `docs/performance.md`):

| Mode | Speed | Use Case |
|------|-------|----------|
| **COPY (no anonymization)** | 70,396 rows/sec | Non-PII tables (logs, metrics) |
| **With anonymization (3 columns)** | 6,515 rows/sec | User data, orders, profiles |

**Memory usage**: ~1MB per batch (5,000 rows optimized)

---

## Commands

### Basic Sync

```bash
# Sync all tables from production to local
confiture sync --from production --to local

# Sync specific tables
confiture sync \
    --from production \
    --to staging \
    --tables users,posts,comments

# Exclude tables
confiture sync \
    --from production \
    --to local \
    --exclude logs,analytics,metrics
```

### With Anonymization

```bash
# Sync with default anonymization config
confiture sync \
    --from production \
    --to local \
    --anonymize

# Specify custom anonymization config
confiture sync \
    --from production \
    --to staging \
    --anonymize-config db/sync/anonymization.yaml
```

### Progress and Resume

```bash
# Show progress bar
confiture sync \
    --from production \
    --to local \
    --show-progress

# Save checkpoint for resume
confiture sync \
    --from production \
    --to staging \
    --checkpoint /tmp/sync_checkpoint.json

# Resume interrupted sync
confiture sync \
    --from production \
    --to staging \
    --resume \
    --checkpoint /tmp/sync_checkpoint.json
```

---

## Configuration

### Environment Configuration

**db/environments/production.yaml**:
```yaml
name: production
database:
  host: prod-db.example.com
  port: 5432
  database: myapp_production
  user: readonly_user
  password: ${PROD_DB_PASSWORD}  # From environment variable
```

**db/environments/local.yaml**:
```yaml
name: local
database:
  host: localhost
  port: 5432
  database: myapp_local
  user: postgres
  password: postgres
```

### Anonymization Configuration

**db/sync/anonymization.yaml**:
```yaml
# Table-level anonymization rules
users:
  - column: email
    strategy: email
    seed: 12345  # Reproducible anonymization

  - column: phone
    strategy: phone
    seed: 12345

  - column: full_name
    strategy: name
    seed: 12345

  - column: ssn
    strategy: redact  # Replace with [REDACTED]

  - column: password_hash
    strategy: hash  # One-way hash

orders:
  - column: billing_address
    strategy: redact

  - column: credit_card_last4
    strategy: redact

profiles:
  - column: bio
    strategy: redact  # May contain personal info

  - column: avatar_url
    strategy: redact
```

---

## Anonymization Strategies

### 1. Email Strategy

Replaces email addresses with fake but realistic emails.

**Input**: `alice@example.com`, `bob@company.com`

**Output**: `user_a1b2c3d4@example.com`, `user_e5f6g7h8@example.com`

**Properties**:
- Preserves uniqueness (same input → same output with seed)
- Valid email format
- Deterministic with seed
- Safe for email validation tests

**Example**:
```yaml
users:
  - column: email
    strategy: email
    seed: 12345
```

---

### 2. Phone Strategy

Generates fake phone numbers in consistent format.

**Input**: `+1-555-1234`, `(555) 555-5678`

**Output**: `+1-555-4567`, `+1-555-8901`

**Properties**:
- US format: +1-555-XXXX
- Deterministic with seed
- Safe for phone validation tests
- 555 area code (reserved for fiction)

**Example**:
```yaml
users:
  - column: phone
    strategy: phone
    seed: 12345
```

---

### 3. Name Strategy

Generates anonymous but realistic names.

**Input**: `Alice Johnson`, `Bob Smith`

**Output**: `User A1B2`, `User E5F6`

**Properties**:
- Short, anonymous format
- Deterministic with seed
- Preserves uniqueness
- Easy to identify as test data

**Example**:
```yaml
users:
  - column: full_name
    strategy: name
    seed: 12345
```

---

### 4. Redact Strategy

Simply replaces value with `[REDACTED]`.

**Input**: `123-45-6789`, `4111-1111-1111-1111`

**Output**: `[REDACTED]`, `[REDACTED]`

**Properties**:
- Maximum privacy
- No information leakage
- Not suitable for tests requiring real data
- Fast

**Example**:
```yaml
users:
  - column: ssn
    strategy: redact

  - column: credit_card
    strategy: redact
```

---

### 5. Hash Strategy

One-way hash that preserves uniqueness.

**Input**: `secret_value_1`, `secret_value_2`

**Output**: `a1b2c3d4e5f6789a`, `b2c3d4e5f6789abc`

**Properties**:
- Preserves uniqueness (1-to-1 mapping)
- Irreversible (one-way)
- Good for password hashes, API keys
- 16-character hex output

**Example**:
```yaml
users:
  - column: api_key
    strategy: hash

  - column: password_reset_token
    strategy: hash
```

---

## Table Selection

### Include Specific Tables

```bash
# Sync only user-related tables
confiture sync \
    --from production \
    --to local \
    --tables users,profiles,user_settings
```

### Exclude Tables

```bash
# Sync all except analytics
confiture sync \
    --from production \
    --to staging \
    --exclude analytics,logs,metrics,events
```

### Patterns (Future Feature)

```bash
# Future: Pattern matching
confiture sync \
    --from production \
    --to local \
    --include "user_*,order_*" \
    --exclude "*_archive,*_backup"
```

---

## Progress Reporting

### Real-Time Progress Bar

```bash
confiture sync \
    --from production \
    --to staging \
    --show-progress

# Output:
# Syncing users       ████████████████████ 100% • 1,234,567/1,234,567 rows • 00:19
# Syncing posts       ████████████░░░░░░░░  65% • 654,321/1,000,000 rows   • 00:05
```

### Progress Features

- **Per-table progress** - See progress for each table
- **Row counts** - Current/total rows synced
- **Time remaining** - Estimated completion time
- **Throughput** - Rows per second

---

## Resume Support

### Checkpoint System

Confiture can save progress and resume interrupted syncs.

**Create checkpoint**:
```bash
confiture sync \
    --from production \
    --to staging \
    --checkpoint /tmp/sync.json \
    --show-progress
```

**If sync interrupted** (network issue, crash, etc.):
```bash
# Resume from where it left off
confiture sync \
    --from production \
    --to staging \
    --resume \
    --checkpoint /tmp/sync.json
```

### Checkpoint File Format

**/tmp/sync.json**:
```json
{
  "version": "1.0",
  "timestamp": "2025-10-12T10:30:00",
  "source_database": "prod-db.example.com:5432/myapp_production",
  "target_database": "localhost:5432/myapp_staging",
  "completed_tables": {
    "users": {
      "rows_synced": 1234567,
      "synced_at": "2025-10-12T10:28:00"
    },
    "posts": {
      "rows_synced": 987654,
      "synced_at": "2025-10-12T10:29:30"
    }
  }
}
```

### Resume Behavior

- **Completed tables**: Skipped (already synced)
- **Partial tables**: Re-synced from beginning
- **Pending tables**: Synced normally

**Note**: Resume works at table-level granularity. Individual tables are not resumable.

---

## Best Practices

### 1. Use Read-Only Credentials

**Production database**:
```yaml
# db/environments/production.yaml
database:
  host: prod-db.example.com
  user: readonly_user  # ✅ Read-only
  password: ${PROD_DB_PASSWORD}
```

Create read-only user:
```sql
-- On production database
CREATE USER readonly_user WITH PASSWORD 'secure_password';
GRANT CONNECT ON DATABASE myapp_production TO readonly_user;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO readonly_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO readonly_user;
```

---

### 2. Always Anonymize PII

**Bad**: No anonymization
```bash
# ❌ Exposes real user emails, phones, names
confiture sync --from production --to local
```

**Good**: With anonymization
```bash
# ✅ PII is anonymized
confiture sync \
    --from production \
    --to local \
    --anonymize-config db/sync/anonymization.yaml
```

---

### 3. Test Anonymization Locally First

```bash
# 1. Sync small sample to verify anonymization
confiture sync \
    --from production \
    --to local \
    --tables users \
    --anonymize

# 2. Verify PII is anonymized
psql myapp_local -c "SELECT email, phone, full_name FROM users LIMIT 10"

# Expected output:
# email                    | phone          | full_name
# -------------------------+----------------+-----------
# user_a1b2c3d4@example.com| +1-555-4567   | User A1B2
# user_e5f6g7h8@example.com| +1-555-8901   | User E5F6

# 3. If good, sync all tables
confiture sync --from production --to staging --anonymize
```

---

### 4. Exclude Large, Non-Essential Tables

```bash
# Skip large analytics/metrics tables
confiture sync \
    --from production \
    --to local \
    --exclude logs,analytics,page_views,events

# Saves time and disk space
```

---

### 5. Schedule Regular Syncs

**Staging refresh (weekly)**:
```bash
#!/bin/bash
# scripts/refresh_staging.sh

echo "Refreshing staging database from production..."

confiture sync \
    --from production \
    --to staging \
    --anonymize-config db/sync/anonymization.yaml \
    --show-progress \
    --checkpoint /tmp/staging_sync.json

echo "Staging refresh complete!"
```

**Cron job**:
```cron
# Refresh staging every Sunday at 2 AM
0 2 * * 0 /path/to/scripts/refresh_staging.sh
```

---

### 6. Use Checkpoints for Large Syncs

```bash
# For multi-hour syncs, always use checkpoints
confiture sync \
    --from production \
    --to staging \
    --checkpoint /var/tmp/sync_$(date +%Y%m%d).json \
    --show-progress
```

---

## Common Use Cases

### Use Case 1: Bug Investigation

**Scenario**: Production bug that doesn't reproduce with test data

**Solution**:
```bash
# 1. Sync affected user's data
confiture sync \
    --from production \
    --to local \
    --tables users,orders,payments \
    --anonymize

# 2. Reproduce bug locally
# 3. Fix and verify
# 4. Deploy to production
```

---

### Use Case 2: Feature Testing

**Scenario**: New feature needs testing with realistic data

**Solution**:
```bash
# Sync relevant tables to staging
confiture sync \
    --from production \
    --to staging \
    --tables users,posts,comments \
    --anonymize \
    --show-progress

# Test new feature on staging
# Verify performance with production data volumes
```

---

### Use Case 3: Migration Testing

**Scenario**: Test complex migration before applying to production

**Solution**:
```bash
# 1. Sync production data to test environment
confiture sync \
    --from production \
    --to test \
    --anonymize

# 2. Apply migration to test database
confiture migrate up -c test.yaml

# 3. Verify migration succeeded
# 4. Check data integrity
# 5. Measure migration time

# 6. Apply to production with confidence
```

---

### Use Case 4: Performance Testing

**Scenario**: Load test needs production-scale data

**Solution**:
```bash
# Sync full dataset (may take hours)
confiture sync \
    --from production \
    --to performance_test \
    --exclude logs,metrics \
    --checkpoint /tmp/perf_sync.json \
    --show-progress

# Run load tests with realistic data volumes
```

---

## Performance Optimization

### Batch Size Tuning

Confiture uses optimized batch size of **5,000 rows** (determined via benchmarking).

**Default (optimized)**:
```bash
# Uses default batch_size=5000
confiture sync --from production --to local --anonymize
```

**Custom (advanced)**:
```bash
# Future: Custom batch size
confiture sync \
    --from production \
    --to local \
    --batch-size 10000  # Larger batches (more memory)
```

### Memory Considerations

| Batch Size | Memory Usage | Throughput |
|------------|--------------|------------|
| 1,000 | ~200KB | 4,200 rows/sec |
| 5,000 | ~1MB | 6,515 rows/sec ⭐ |
| 10,000 | ~2MB | 6,200 rows/sec |

**Recommendation**: Use default 5,000 (optimal speed/memory)

---

### Network Optimization

**Use same region/VPC**:
```yaml
# Faster: Same AWS region
production:
  host: prod-db.us-east-1.rds.amazonaws.com

staging:
  host: staging-db.us-east-1.rds.amazonaws.com  # ✅ Same region

# Slower: Cross-region
  host: staging-db.eu-west-1.rds.amazonaws.com  # ❌ High latency
```

---

### Parallel Sync (Future)

```bash
# Future feature: Parallel table sync
confiture sync \
    --from production \
    --to staging \
    --parallel 4  # Sync 4 tables concurrently
```

---

## Security Considerations

### 1. Network Security

**Use SSL/TLS**:
```yaml
# db/environments/production.yaml
database:
  host: prod-db.example.com
  sslmode: require  # Enforce SSL
  sslrootcert: /path/to/ca-cert.pem
```

**Use SSH tunnel**:
```bash
# Create SSH tunnel to production
ssh -L 5433:prod-db.internal:5432 bastion.example.com

# Sync through tunnel
confiture sync \
    --from production \
    --to local \
    --source-port 5433
```

---

### 2. Credential Management

**Use environment variables**:
```yaml
database:
  password: ${PROD_DB_PASSWORD}  # Not hardcoded
```

```bash
# Set in environment
export PROD_DB_PASSWORD="secure_password"

confiture sync --from production --to local
```

**Use secret managers**:
```bash
# AWS Secrets Manager
export PROD_DB_PASSWORD=$(aws secretsmanager get-secret-value \
    --secret-id prod-db-password \
    --query SecretString \
    --output text)
```

---

### 3. Audit Logging

**Log sync operations**:
```bash
# Log to file
confiture sync \
    --from production \
    --to staging \
    --anonymize \
    2>&1 | tee /var/log/confiture/sync_$(date +%Y%m%d_%H%M%S).log
```

---

### 4. Verify Anonymization

**Always verify anonymization worked**:
```sql
-- Check for real emails
SELECT email FROM users WHERE email NOT LIKE '%@example.com';
-- Should return 0 rows

-- Check for real phone numbers
SELECT phone FROM users WHERE phone NOT LIKE '+1-555-%';
-- Should return 0 rows

-- Check for [REDACTED] values
SELECT COUNT(*) FROM users WHERE ssn = '[REDACTED]';
-- Should equal total row count
```

---

## Troubleshooting

### Sync Fails: "Connection refused"

**Cause**: Target database not accessible

**Solution**:
```bash
# Verify database is running
psql -h localhost -U postgres -d myapp_local -c "SELECT 1"

# Check firewall rules
# Check network connectivity
```

---

### Sync Fails: "Row count mismatch"

**Cause**: Data changed during sync (e.g., deletions in production)

**Solution**: Re-run sync (production data is read at transaction start)

---

### Sync Slow (<1000 rows/sec)

**Cause**: Network latency or disk I/O

**Solutions**:
- Use same region/VPC
- Check disk space on target
- Verify network bandwidth
- Consider excluding large tables

---

### Memory Issues

**Cause**: Batch size too large

**Solution**: Use default batch size (5,000)

---

## See Also

- [Migration Decision Tree](./migration-decision-tree.md) - When to use Medium 3
- [Performance Guide](../performance.md) - Detailed benchmarks
- [Medium 1: Build from DDL](./medium-1-build-from-ddl.md) - For schema setup
- [Example: Production Sync](../../examples/04-production-sync-anonymization/) - Complete example
- [CLI Reference](../reference/cli.md) - All sync commands

---

## Quick Reference

### Commands
```bash
confiture sync --from production --to local                    # Basic sync
confiture sync --from prod --to local --anonymize              # With anonymization
confiture sync --from prod --to staging --show-progress        # Progress bar
confiture sync --from prod --to local --tables users,posts     # Specific tables
confiture sync --from prod --to local --exclude logs,metrics   # Exclude tables
confiture sync --from prod --to staging --checkpoint sync.json # Save checkpoint
confiture sync --from prod --to staging --resume               # Resume sync
```

### Anonymization Strategies
- `email` → `user_a1b2c3d4@example.com`
- `phone` → `+1-555-4567`
- `name` → `User A1B2`
- `redact` → `[REDACTED]`
- `hash` → `a1b2c3d4e5f6789a`

### Performance
- **COPY (no anonymization)**: 70,396 rows/sec
- **With anonymization (3 columns)**: 6,515 rows/sec
- **Optimal batch size**: 5,000 rows
- **Memory**: ~1MB per batch

### Best Practices
- ✅ Use read-only credentials for production
- ✅ Always anonymize PII
- ✅ Test anonymization locally first
- ✅ Exclude large, non-essential tables
- ✅ Use checkpoints for long syncs
- ✅ Verify anonymization with queries

---

## 🎯 Next Steps

**Ready to use Medium 3?**
- ✅ You now understand: data syncing, anonymization strategies, performance optimization

**What to do next:**

1. **[Migration Decision Tree](./migration-decision-tree.md)** - When to use Medium 3 vs other mediums

2. **[Anonymization Strategy Framework](./anonymization-strategy-framework.md)** - Create custom anonymization strategies

3. **[Advanced Patterns](./advanced-patterns.md)** - Custom anonymization, complex data transformations

4. **[Security Considerations](../security/)** - GDPR compliance, threat model, safe data handling

5. **[Examples](../../examples/)** - See Medium 3 in action with production-like workflows

**Common Use Cases:**
- **Debugging production issues locally** - [See Medium 3 scenario](./migration-decision-tree.md#scenario-3-debugging-production-issue)
- **Testing with real data** - Apply anonymization then test features
- **QA environments** - Populate staging with production-like data
- **Performance testing** - Use realistic data volumes

**Got questions?**
- **[Glossary](../glossary.md)** - Terms like anonymization, PII, FDW explained
- **[Troubleshooting](./troubleshooting.md)** - Data sync issues and solutions
- **[Getting Started by Role](../getting-started-by-role.md)** - Security officer guide for compliance

---

**Part of the Confiture documentation** 🍓

*Production data, safely synced*
