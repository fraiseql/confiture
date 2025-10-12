# Production Data Sync with PII Anonymization

**Example 04** - Confiture Migration Tool

---

## Table of Contents

1. [Overview](#overview)
2. [Use Case](#use-case)
3. [What This Example Demonstrates](#what-this-example-demonstrates)
4. [Prerequisites](#prerequisites)
5. [Quick Start](#quick-start)
6. [Detailed Workflow](#detailed-workflow)
7. [Anonymization Strategies](#anonymization-strategies)
8. [Configuration Reference](#configuration-reference)
9. [Verification and Testing](#verification-and-testing)
10. [GDPR Compliance](#gdpr-compliance)
11. [Best Practices](#best-practices)
12. [Troubleshooting](#troubleshooting)
13. [Security Considerations](#security-considerations)
14. [Performance Tuning](#performance-tuning)

---

## Overview

This example demonstrates **Medium 3** of Confiture: Production Data Sync with PII (Personally Identifiable Information) anonymization.

### The Challenge

You need production data locally to debug issues, but:
- Production contains sensitive customer data (emails, SSNs, phone numbers)
- GDPR/CCPA require protecting PII
- Manual anonymization is error-prone
- You need realistic data volumes and patterns

### The Solution

Confiture's `sync` command:
1. Copies production schema and data to staging/local
2. Automatically anonymizes PII based on configuration
3. Preserves data relationships and referential integrity
4. Provides verification tools to ensure compliance

---

## Use Case

### Scenario: E-Commerce Debugging

**Problem**: Production users report checkout failures, but you can't reproduce locally with synthetic data.

**Solution**: Sync production to staging with anonymization:
```bash
# Copy production data to staging, anonymize PII
confiture sync production-to-staging --anonymize

# Now debug locally with realistic data
confiture sync staging-to-local --anonymize
```

**Result**:
- 50,000 real orders with anonymized customer data
- Actual payment patterns, edge cases, and data distributions
- Zero PII exposure - GDPR compliant

---

## What This Example Demonstrates

### Core Features

1. **Production-to-Staging Sync**
   - Full database copy with pg_dump/restore
   - Parallel data transfer for speed
   - Progress reporting

2. **PII Anonymization**
   - Email anonymization (preserves format)
   - Phone number masking
   - SSN redaction
   - Address anonymization
   - Custom anonymization rules

3. **Referential Integrity**
   - Foreign keys remain valid
   - Deterministic anonymization (same input → same output)
   - Data relationships preserved

4. **Verification**
   - SQL queries to check anonymization
   - Pattern matching to find leaked PII
   - Compliance reports

---

## Prerequisites

### Infrastructure

```bash
# Production database (source)
postgresql://prod-host:5432/ecommerce_prod

# Staging database (target)
postgresql://staging-host:5432/ecommerce_staging

# Local database (optional)
postgresql://localhost:5432/ecommerce_local
```

### Permissions Required

**Source (Production)**:
```sql
-- Read-only access is sufficient
GRANT CONNECT ON DATABASE ecommerce_prod TO confiture_sync_user;
GRANT USAGE ON SCHEMA public TO confiture_sync_user;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO confiture_sync_user;
GRANT SELECT ON ALL SEQUENCES IN SCHEMA public TO confiture_sync_user;
```

**Target (Staging)**:
```sql
-- Full access required
GRANT ALL PRIVILEGES ON DATABASE ecommerce_staging TO confiture_sync_user;
```

### Software

```bash
# Confiture installed
pip install confiture

# PostgreSQL client tools (for pg_dump/restore)
sudo apt-get install postgresql-client-15

# Optional: AWS CLI (if using RDS)
pip install awscli
```

---

## Quick Start

### 1. Clone This Example

```bash
cd /home/lionel/code/confiture/examples
cp -r 04-production-sync-anonymization my-sync-project
cd my-sync-project
```

### 2. Configure Environments

Edit `db/environments/production.yaml`:
```yaml
host: prod-db.example.com
port: 5432
database: ecommerce_prod
user: confiture_sync_user
# Use environment variable for password
password: ${PROD_DB_PASSWORD}
```

Edit `db/environments/staging.yaml`:
```yaml
host: staging-db.example.com
port: 5432
database: ecommerce_staging
user: confiture_sync_user
password: ${STAGING_DB_PASSWORD}
```

### 3. Configure Anonymization

Review `anonymization_config.yaml` and adjust for your schema:
```yaml
tables:
  users:
    anonymization:
      - column: email
        strategy: email
        seed: 12345
      - column: phone
        strategy: phone
```

### 4. Run Sync

```bash
# Set passwords
export PROD_DB_PASSWORD="your-prod-password"
export STAGING_DB_PASSWORD="your-staging-password"

# Execute sync with anonymization
./sync_script.sh
```

### 5. Verify Anonymization

```bash
# Connect to staging
psql postgresql://staging-db.example.com/ecommerce_staging

# Run verification queries
\i verify_anonymization.sql
```

---

## Detailed Workflow

### Step 1: Pre-Sync Checks

Before syncing, Confiture validates:

```bash
confiture sync production-to-staging --dry-run --anonymize
```

**Checks**:
- Source database connectivity
- Target database connectivity
- Sufficient disk space on target
- Anonymization config validity
- PII columns identified
- No missing anonymization rules

**Output**:
```
Pre-Sync Validation Report
==========================

Source Database: ecommerce_prod (250 GB, 45 tables)
Target Database: ecommerce_staging (will be overwritten)

PII Columns Detected: 12
  users.email              → email strategy
  users.phone              → phone strategy
  users.ssn                → redact strategy
  orders.billing_address   → redact strategy
  ...

Estimated Sync Time: 35 minutes
Estimated Anonymization Time: 8 minutes

Warnings:
  - Target database will be dropped and recreated
  - 3 foreign key constraints will be temporarily disabled

Proceed? [y/N]
```

### Step 2: Schema Copy

Confiture copies the schema first:

```bash
# Internally runs:
pg_dump --schema-only --no-owner --no-acl \
  postgresql://prod-host/ecommerce_prod | \
psql postgresql://staging-host/ecommerce_staging
```

**Features**:
- Excludes ownership (--no-owner)
- Excludes privileges (--no-acl)
- Includes indexes, constraints, triggers
- Creates sequences with correct values

### Step 3: Data Copy with Anonymization

Confiture streams data table-by-table:

```python
# Pseudocode
for table in database.tables:
    if table.has_pii:
        # Copy with anonymization
        COPY (
            SELECT
                id,
                anonymize_email(email, seed=12345) AS email,
                anonymize_phone(phone) AS phone,
                created_at
            FROM production.{table}
        ) TO staging.{table}
    else:
        # Direct copy (faster)
        COPY production.{table} TO staging.{table}
```

**Progress Output**:
```
Syncing Production → Staging
============================

[✓] users (50,000 rows, 12 MB) - 3s - 3 columns anonymized
[✓] orders (250,000 rows, 450 MB) - 45s - 1 column anonymized
[✓] products (5,000 rows, 2 MB) - 1s - no PII
[✓] order_items (800,000 rows, 120 MB) - 18s - no PII
...

Total: 45 tables, 1.2M rows, 1.8 GB in 8m 23s
Anonymized: 12 PII columns across 4 tables
```

### Step 4: Post-Sync Verification

Confiture automatically verifies:

```sql
-- Check for leaked emails
SELECT COUNT(*) FROM users
WHERE email LIKE '%@realdomain.com';
-- Expected: 0

-- Check for leaked phone numbers
SELECT COUNT(*) FROM users
WHERE phone ~ '^[0-9]{3}-[0-9]{3}-[0-9]{4}$';
-- Expected: 0 (should be anonymized format)

-- Check referential integrity
SELECT COUNT(*) FROM orders o
LEFT JOIN users u ON o.user_id = u.id
WHERE u.id IS NULL;
-- Expected: 0 (no orphaned orders)
```

### Step 5: Resume Support

If sync fails mid-process:

```bash
# Confiture tracks progress
confiture sync production-to-staging --resume
```

**Resume Logic**:
```
Resuming from checkpoint: 18/45 tables completed

Skipping:
  [✓] users (already synced)
  [✓] orders (already synced)
  ...

Continuing from:
  [ ] products (pending)
  [ ] order_items (pending)
  ...
```

---

## Anonymization Strategies

Confiture provides built-in strategies for common PII types:

### 1. Email Anonymization

**Strategy**: `email`

**How It Works**:
```python
# Input:  john.doe@gmail.com
# Output: user_a3f5e9b2@anon.local

# Deterministic: same email always generates same anonymized version
anonymize_email("john.doe@gmail.com", seed=12345)
# → user_a3f5e9b2@anon.local (always)

anonymize_email("john.doe@gmail.com", seed=12345)
# → user_a3f5e9b2@anon.local (same output)
```

**Configuration**:
```yaml
- column: email
  strategy: email
  seed: 12345                    # Optional: for deterministic output
  domain: anon.local             # Optional: custom domain
  preserve_domain: false         # Optional: keep original domain
```

**Preservation Options**:
```yaml
# Preserve domain for testing email delivery
- column: email
  strategy: email
  preserve_domain: true

# Input:  john.doe@gmail.com
# Output: user_a3f5e9b2@gmail.com (domain preserved)
```

### 2. Phone Number Anonymization

**Strategy**: `phone`

**How It Works**:
```python
# Input:  +1-555-123-4567
# Output: +1-555-000-0000

# Preserves format, redacts last 7 digits
anonymize_phone("+1-555-123-4567")
# → +1-555-000-0000
```

**Configuration**:
```yaml
- column: phone
  strategy: phone
  format: national               # Options: e164, national, international
  redact_digits: 7               # How many digits to redact
```

### 3. SSN Redaction

**Strategy**: `redact`

**How It Works**:
```python
# Input:  123-45-6789
# Output: ***-**-****

anonymize_ssn("123-45-6789")
# → ***-**-****
```

**Configuration**:
```yaml
- column: ssn
  strategy: redact
  replacement: "***-**-****"     # Custom redaction string
```

### 4. Address Anonymization

**Strategy**: `address`

**How It Works**:
```python
# Input:  1234 Main St, San Francisco, CA 94102
# Output: [REDACTED ADDRESS]

anonymize_address("1234 Main St, San Francisco, CA 94102")
# → [REDACTED ADDRESS]
```

**Advanced** (preserve city/state for analytics):
```yaml
- column: billing_address
  strategy: address
  preserve_fields: [city, state, zip]

# Input:  1234 Main St, San Francisco, CA 94102
# Output: [REDACTED], San Francisco, CA 94102
```

### 5. Name Anonymization

**Strategy**: `name`

**How It Works**:
```python
# Input:  John Doe
# Output: User-A3F5E9B2

anonymize_name("John Doe", seed=12345)
# → User-A3F5E9B2 (deterministic)
```

**Configuration**:
```yaml
- column: first_name
  strategy: name
  seed: 12345
  preserve_initial: true         # Optional: preserve first letter

# Input:  John
# Output: J-User-A3F5E9 (starts with J)
```

### 6. Custom Anonymization

**Strategy**: `custom`

**How It Works**:
```yaml
- column: credit_card_last4
  strategy: custom
  function: |
    -- SQL function
    CREATE OR REPLACE FUNCTION anonymize_cc_last4(cc TEXT)
    RETURNS TEXT AS $$
    BEGIN
        RETURN '****';
    END;
    $$ LANGUAGE plpgsql;
```

### Strategy Selection Guide

| Data Type | Recommended Strategy | Preserves Format | Deterministic | Use Case |
|-----------|---------------------|------------------|---------------|----------|
| Email | `email` | Yes | Yes | User accounts, testing email logic |
| Phone | `phone` | Yes | No | Contact info, SMS testing |
| SSN | `redact` | Yes | No | Tax IDs, compliance |
| Address | `address` | Optional | No | Shipping, analytics |
| Name | `name` | No | Yes | User profiles, foreign keys |
| Credit Card | `custom` | Custom | Custom | Payment testing |

---

## Configuration Reference

### anonymization_config.yaml Structure

```yaml
# Global settings
global:
  seed: 12345                      # Global seed for deterministic anonymization
  verify_after_sync: true          # Run verification queries automatically
  fail_on_pii_leak: true           # Exit with error if PII detected post-sync

# Per-table configuration
tables:
  users:
    # Anonymization rules
    anonymization:
      - column: email
        strategy: email
        seed: 12345
        domain: anon.local

      - column: phone
        strategy: phone
        format: national

      - column: ssn
        strategy: redact
        replacement: "***-**-****"

      - column: first_name
        strategy: name
        seed: 12345

      - column: last_name
        strategy: name
        seed: 12345

    # Optional: custom WHERE clause to filter data
    filter: "created_at > NOW() - INTERVAL '1 year'"

    # Optional: sample data (for large tables)
    sample_rate: 0.1               # Copy 10% of rows

  orders:
    anonymization:
      - column: billing_address
        strategy: address
        preserve_fields: [city, state, zip]

      - column: shipping_address
        strategy: address
        preserve_fields: [city, state, zip]

    # Preserve all data (no sampling)
    sample_rate: 1.0

  # Tables without PII (no anonymization needed)
  products:
    # No anonymization block = direct copy

  order_items:
    # No anonymization needed

# Exclusions
exclude_tables:
  - audit_logs                     # Skip sensitive audit logs
  - session_data                   # Skip temporary session data

# Performance tuning
performance:
  parallel_workers: 4              # Number of parallel table copies
  batch_size: 10000                # Rows per batch
  disable_triggers: true           # Disable triggers during sync
  disable_indexes: true            # Recreate indexes after sync
```

### Environment Configuration

**db/environments/production.yaml**:
```yaml
# Production (source) configuration
host: prod-db.example.com
port: 5432
database: ecommerce_prod
user: confiture_sync_user
password: ${PROD_DB_PASSWORD}      # From environment variable

# Connection pooling
pool_size: 5
max_overflow: 10

# SSL configuration
ssl_mode: require
ssl_cert: /path/to/client-cert.pem
ssl_key: /path/to/client-key.pem
ssl_root_cert: /path/to/ca-cert.pem

# Read-only safety
readonly: true                     # Prevent accidental writes

# Connection timeout
connect_timeout: 30
statement_timeout: 3600            # 1 hour for long-running queries
```

**db/environments/staging.yaml**:
```yaml
# Staging (target) configuration
host: staging-db.example.com
port: 5432
database: ecommerce_staging
user: confiture_sync_user
password: ${STAGING_DB_PASSWORD}

# Allow writes
readonly: false

# Disable connection pooling (direct connection)
pool_size: 1
max_overflow: 0
```

---

## Verification and Testing

### Automated Verification

After sync, Confiture runs verification queries automatically:

```bash
confiture sync production-to-staging --anonymize --verify
```

**Built-in Checks**:

1. **Email Pattern Check**
```sql
-- Should return 0
SELECT COUNT(*)
FROM users
WHERE email NOT LIKE '%@anon.local';
```

2. **Phone Pattern Check**
```sql
-- Should return 0 (all phones should be anonymized)
SELECT COUNT(*)
FROM users
WHERE phone ~ '^[0-9]{3}-[0-9]{3}-[0-9]{4}$';
```

3. **SSN Pattern Check**
```sql
-- Should return 0 (all SSNs should be redacted)
SELECT COUNT(*)
FROM users
WHERE ssn ~ '^[0-9]{3}-[0-9]{2}-[0-9]{4}$';
```

4. **Referential Integrity Check**
```sql
-- Should return 0 (no orphaned orders)
SELECT COUNT(*)
FROM orders o
LEFT JOIN users u ON o.user_id = u.id
WHERE u.id IS NULL;
```

### Manual Verification

Use `verify_anonymization.sql` for manual checks:

```bash
psql postgresql://staging-db.example.com/ecommerce_staging < verify_anonymization.sql
```

**Sample Output**:
```
Verification Report
===================

Email Anonymization:
  Total emails: 50,000
  Anonymized: 50,000 (100%)
  Format: user_XXXXXXXX@anon.local
  ✓ PASS

Phone Anonymization:
  Total phones: 48,523
  Anonymized: 48,523 (100%)
  Format: +1-555-000-0000
  ✓ PASS

SSN Redaction:
  Total SSNs: 50,000
  Redacted: 50,000 (100%)
  Format: ***-**-****
  ✓ PASS

Referential Integrity:
  Orders with valid users: 250,000 (100%)
  Orphaned orders: 0
  ✓ PASS

Overall: ✓ ALL CHECKS PASSED
```

### Custom Verification Queries

Add custom checks to `verify_anonymization.sql`:

```sql
-- Check for leaked production domains
SELECT 'Email Domain Check' AS test_name,
       COUNT(*) AS violations,
       CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'FAIL' END AS status
FROM users
WHERE email LIKE '%@gmail.com'
   OR email LIKE '%@yahoo.com'
   OR email LIKE '%@hotmail.com';

-- Check for realistic phone area codes (should be anonymized)
SELECT 'Phone Area Code Check' AS test_name,
       COUNT(*) AS violations,
       CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'FAIL' END AS status
FROM users
WHERE phone ~ '^[0-9]{3}'
  AND phone !~ '^555';  -- 555 is anonymized area code
```

---

## GDPR Compliance

### Legal Requirements

Confiture's anonymization helps meet GDPR requirements:

| GDPR Requirement | Confiture Feature | Compliance Status |
|------------------|-------------------|-------------------|
| Right to Erasure (Art. 17) | PII redaction | ✓ Supported |
| Data Minimization (Art. 5) | Column-level anonymization | ✓ Supported |
| Purpose Limitation (Art. 5) | Environment-specific configs | ✓ Supported |
| Storage Limitation (Art. 5) | Temporary staging data | ✓ Manual process |
| Integrity & Confidentiality (Art. 32) | Encrypted connections | ✓ Supported |

### GDPR Anonymization vs. Pseudonymization

**Anonymization** (Confiture default):
- Irreversibly removes PII
- Data cannot be linked back to individuals
- No longer subject to GDPR

**Pseudonymization** (optional):
- Replaces identifiers with pseudonyms
- Reversible with additional information
- Still subject to GDPR

**Configuration**:
```yaml
# Anonymization (GDPR-exempt)
- column: email
  strategy: email
  seed: 12345                # Deterministic but irreversible

# Pseudonymization (still GDPR-covered)
- column: user_id
  strategy: custom
  function: encrypt_id       # Reversible with key
```

### Data Protection Impact Assessment (DPIA)

When syncing production data, document:

1. **Purpose**: Why do you need production data?
   - Example: "Debugging checkout failures requires realistic order patterns"

2. **Legal Basis**: What justifies this processing?
   - Example: "Legitimate interest (Art. 6(1)(f)) - business continuity"

3. **Risks**: What could go wrong?
   - Example: "PII leak if anonymization fails"

4. **Mitigations**: How do you prevent harm?
   - Example: "Automated verification, encrypted connections, access controls"

5. **Retention**: How long will staging data exist?
   - Example: "Staging database refreshed weekly, old data purged"

### Compliance Checklist

- [ ] Anonymization config reviewed by DPO (Data Protection Officer)
- [ ] Verification queries validate anonymization
- [ ] Access to staging database restricted (principle of least privilege)
- [ ] Staging data retention policy defined (e.g., 7 days)
- [ ] Sync operations logged for audit trail
- [ ] Encrypted connections (SSL/TLS) enforced
- [ ] DPIA completed and approved
- [ ] Data breach response plan in place

---

## Best Practices

### 1. Start with Dry Run

Always test sync configuration before production:

```bash
# Validate config without copying data
confiture sync production-to-staging --dry-run --anonymize

# Review the report
confiture sync production-to-staging --dry-run --anonymize --verbose > sync-report.txt
```

### 2. Use Deterministic Anonymization

For data with foreign key relationships:

```yaml
tables:
  users:
    anonymization:
      - column: email
        strategy: email
        seed: 12345           # Same seed = consistent anonymization

  orders:
    anonymization:
      - column: customer_email
        strategy: email
        seed: 12345           # Same seed as users.email
```

**Why**: Ensures `orders.customer_email` matches anonymized `users.email`.

### 3. Sample Large Tables

For massive tables, sync a representative sample:

```yaml
tables:
  page_views:
    sample_rate: 0.01         # Copy 1% of rows
    sampling_method: random   # Options: random, stratified, time-based
```

**Stratified Sampling** (better for analytics):
```yaml
tables:
  page_views:
    sample_rate: 0.01
    sampling_method: stratified
    stratify_by: user_id      # Ensure all users represented
```

### 4. Automate with CI/CD

Refresh staging weekly:

```yaml
# .github/workflows/refresh-staging.yml
name: Refresh Staging Database

on:
  schedule:
    - cron: '0 2 * * 1'       # Every Monday at 2 AM

jobs:
  sync:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3

      - name: Install Confiture
        run: pip install confiture

      - name: Sync Production to Staging
        env:
          PROD_DB_PASSWORD: ${{ secrets.PROD_DB_PASSWORD }}
          STAGING_DB_PASSWORD: ${{ secrets.STAGING_DB_PASSWORD }}
        run: |
          confiture sync production-to-staging --anonymize --verify

      - name: Notify Team
        run: |
          echo "Staging refreshed with production data (anonymized)"
```

### 5. Monitor Anonymization Drift

Track schema changes that might introduce new PII:

```bash
# Weekly audit: check for columns with "email", "phone", "ssn" in name
confiture audit-pii --warn-on-new-columns
```

**Output**:
```
PII Audit Report
================

New Columns Detected:
  users.backup_email (added 2024-10-01)
  → WARNING: Contains "email" in name
  → Recommendation: Add to anonymization config

Changed Columns:
  users.phone_verified (type changed: boolean → text)
  → WARNING: May now contain PII
  → Recommendation: Review and update anonymization strategy

Overall: 2 warnings, 0 errors
```

---

## Troubleshooting

### Issue 1: Sync Fails Mid-Process

**Symptoms**:
```
Error: Connection lost to staging database
Synced 18/45 tables before failure
```

**Solution**:
```bash
# Resume from last checkpoint
confiture sync production-to-staging --resume

# If resume fails, start fresh
confiture sync production-to-staging --force --anonymize
```

### Issue 2: Referential Integrity Violations

**Symptoms**:
```
Error: Foreign key constraint violated
  orders.user_id references users.id
  Orphaned order IDs: 1234, 5678, 9012
```

**Cause**: Non-deterministic anonymization broke foreign keys.

**Solution**:
```yaml
# Use same seed for related columns
tables:
  users:
    anonymization:
      - column: id
        strategy: preserve    # Don't anonymize primary keys
      - column: email
        strategy: email
        seed: 12345

  orders:
    # user_id not anonymized (references users.id)
```

### Issue 3: PII Detected After Sync

**Symptoms**:
```
Verification FAILED:
  Found 23 emails not matching anonymization pattern
  Sample: john.doe@gmail.com, jane.smith@yahoo.com
```

**Cause**: Missing anonymization rule for new column.

**Solution**:
```yaml
tables:
  users:
    anonymization:
      # ... existing rules ...

      # Add missing column
      - column: backup_email
        strategy: email
        seed: 12345
```

Then re-run sync:
```bash
confiture sync production-to-staging --anonymize --force
```

### Issue 4: Slow Sync Performance

**Symptoms**:
```
Syncing users table: 50,000 rows in 15 minutes (55 rows/sec)
Estimated remaining time: 3 hours
```

**Solution 1**: Increase parallelism
```yaml
performance:
  parallel_workers: 8         # Increase from default 4
  batch_size: 50000           # Larger batches
```

**Solution 2**: Disable indexes during sync
```yaml
performance:
  disable_indexes: true       # Recreate after data copy
  disable_triggers: true      # Skip trigger execution
```

**Solution 3**: Use direct copy for non-PII tables
```yaml
tables:
  products:
    # No anonymization = faster direct copy

  order_items:
    # No anonymization = faster direct copy
```

---

## Security Considerations

### 1. Credential Management

**Bad** (hardcoded passwords):
```yaml
# db/environments/production.yaml
password: "my-secret-password"    # ❌ Never commit credentials
```

**Good** (environment variables):
```yaml
# db/environments/production.yaml
password: ${PROD_DB_PASSWORD}     # ✓ Use environment variables
```

**Better** (credential manager):
```bash
# Use AWS Secrets Manager
export PROD_DB_PASSWORD=$(aws secretsmanager get-secret-value \
  --secret-id prod-db-password --query SecretString --output text)

confiture sync production-to-staging --anonymize
```

### 2. Network Security

**Require SSL**:
```yaml
# db/environments/production.yaml
ssl_mode: require                 # Enforce encrypted connections
ssl_root_cert: /path/to/ca.pem    # Verify server identity
```

**Use SSH Tunnels** (for locked-down production):
```bash
# Open SSH tunnel to production
ssh -L 5433:prod-db-internal:5432 bastion-host -N &

# Connect through tunnel
confiture sync production-to-staging \
  --source-host localhost \
  --source-port 5433 \
  --anonymize
```

### 3. Access Controls

**Principle of Least Privilege**:
```sql
-- Create read-only sync user
CREATE USER confiture_sync_user WITH PASSWORD 'strong-password';

-- Grant minimal permissions
GRANT CONNECT ON DATABASE ecommerce_prod TO confiture_sync_user;
GRANT USAGE ON SCHEMA public TO confiture_sync_user;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO confiture_sync_user;

-- Explicitly deny write access
REVOKE INSERT, UPDATE, DELETE, TRUNCATE
ON ALL TABLES IN SCHEMA public
FROM confiture_sync_user;
```

### 4. Audit Logging

Track all sync operations:

```bash
# Enable audit logging
confiture sync production-to-staging --anonymize --audit-log sync-audit.log
```

**Audit Log Format**:
```json
{
  "timestamp": "2024-10-12T14:30:00Z",
  "operation": "sync",
  "source": "production",
  "target": "staging",
  "user": "john.doe@example.com",
  "anonymization_enabled": true,
  "tables_synced": 45,
  "rows_copied": 1250000,
  "pii_columns_anonymized": 12,
  "verification_passed": true,
  "duration_seconds": 503
}
```

---

## Performance Tuning

### Baseline Performance

**Typical Sync Performance** (single worker):
- **Small databases** (<1 GB): 2-5 minutes
- **Medium databases** (1-10 GB): 10-30 minutes
- **Large databases** (10-100 GB): 1-3 hours
- **Very large databases** (>100 GB): 3+ hours

### Optimization 1: Parallel Workers

```yaml
performance:
  parallel_workers: 8           # Copy 8 tables simultaneously
```

**Benchmark**:
- 1 worker: 45 tables in 60 minutes
- 4 workers: 45 tables in 18 minutes (3.3x faster)
- 8 workers: 45 tables in 11 minutes (5.5x faster)

**Diminishing Returns**: Beyond 8 workers, performance plateaus due to I/O limits.

### Optimization 2: Batch Size

```yaml
performance:
  batch_size: 50000             # Rows per batch (default: 10000)
```

**Benchmark**:
- 1,000 rows/batch: 100,000 rows in 15 minutes
- 10,000 rows/batch: 100,000 rows in 8 minutes (1.9x faster)
- 50,000 rows/batch: 100,000 rows in 5 minutes (3x faster)

**Trade-off**: Larger batches use more memory.

### Optimization 3: Index Management

```yaml
performance:
  disable_indexes: true         # Drop indexes before sync, recreate after
```

**Benchmark** (10 indexes on users table):
- Indexes enabled: 50,000 rows in 12 minutes
- Indexes disabled: 50,000 rows in 3 minutes (4x faster)

**Caveat**: Index recreation adds 2-5 minutes after sync.

### Optimization 4: Sampling

For non-production environments:

```yaml
tables:
  page_views:
    sample_rate: 0.1            # Copy 10% of rows
```

**Benchmark** (10M row table):
- 100% sample: 45 minutes
- 10% sample: 5 minutes (9x faster)
- 1% sample: 30 seconds (90x faster)

---

## Additional Resources

### Documentation

- [Confiture Sync Command Reference](../../docs/cli-reference.md#sync)
- [Anonymization Strategies Guide](../../docs/anonymization-strategies.md)
- [GDPR Compliance Checklist](../../docs/gdpr-compliance.md)

### Related Examples

- [Example 03: Zero-Downtime Migration](../03-zero-downtime-migration/)
- [Example 05: FraiseQL Integration](../05-fraiseql-integration/)

### External Resources

- [GDPR Official Text](https://gdpr-info.eu/)
- [PostgreSQL Security Best Practices](https://www.postgresql.org/docs/current/security-best-practices.html)
- [PII Anonymization Techniques (NIST)](https://www.nist.gov/privacy-framework/de-identification)

---

## Summary

This example demonstrated:

1. **Production Data Sync**: Copy production databases to staging/local
2. **PII Anonymization**: 6 built-in strategies (email, phone, SSN, etc.)
3. **Verification**: Automated checks to ensure compliance
4. **GDPR Compliance**: Legal considerations and best practices
5. **Performance**: Optimization techniques for large databases

**Key Takeaways**:

- Use deterministic anonymization for referential integrity
- Always verify anonymization with SQL queries
- Automate staging refreshes with CI/CD
- Follow GDPR guidelines for data protection
- Optimize with parallel workers and batching

**Next Steps**:

1. Customize `anonymization_config.yaml` for your schema
2. Run dry-run sync to validate configuration
3. Execute production-to-staging sync
4. Verify anonymization with `verify_anonymization.sql`
5. Automate weekly staging refreshes

---

*Making production data safe for development, one sync at a time.*
