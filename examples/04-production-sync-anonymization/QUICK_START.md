# Quick Start Guide - Production Data Sync with Anonymization

**5-Minute Setup for Confiture Production Sync**

---

## Prerequisites Checklist

- [ ] Confiture installed: `pip install confiture`
- [ ] PostgreSQL client tools: `psql`, `pg_dump`
- [ ] Production database credentials (read-only)
- [ ] Staging database credentials (read-write)
- [ ] VPN access (if required)

---

## Step 1: Set Environment Variables (2 minutes)

```bash
# Export database passwords
export PROD_DB_PASSWORD="your-production-password"
export STAGING_DB_PASSWORD="your-staging-password"

# Optional: Slack notifications
export SLACK_WEBHOOK_URL="https://hooks.slack.com/services/YOUR/WEBHOOK/URL"

# Verify
echo $PROD_DB_PASSWORD | wc -c  # Should show character count (not empty)
```

**Security Tip**: Add these to your `~/.bashrc` or use a credential manager:
```bash
# AWS Secrets Manager
export PROD_DB_PASSWORD=$(aws secretsmanager get-secret-value \
  --secret-id prod-db-password --query SecretString --output text)
```

---

## Step 2: Configure Database Connections (3 minutes)

Edit `db/environments/production.yaml`:
```yaml
host: your-prod-host.example.com
database: your_database_name
user: confiture_sync_user
password: ${PROD_DB_PASSWORD}
```

Edit `db/environments/staging.yaml`:
```yaml
host: your-staging-host.example.com
database: your_database_name
user: confiture_sync_user
password: ${STAGING_DB_PASSWORD}
```

**Test connections**:
```bash
# Test production (read-only)
psql postgresql://$PROD_DB_PASSWORD@your-prod-host/your_db -c "SELECT version();"

# Test staging (read-write)
psql postgresql://$STAGING_DB_PASSWORD@your-staging-host/your_db -c "SELECT version();"
```

---

## Step 3: Customize Anonymization Rules (5 minutes)

Edit `anonymization_config.yaml` to match your schema:

```yaml
tables:
  # Add your tables here
  users:
    anonymization:
      - column: email
        strategy: email
      - column: phone
        strategy: phone
      - column: ssn
        strategy: redact

  # Tables without PII (no anonymization needed)
  products:
    # No anonymization block = direct copy
```

**Finding PII columns**:
```bash
# Connect to production and list columns
psql postgresql://prod-host/db -c "
  SELECT table_name, column_name
  FROM information_schema.columns
  WHERE column_name ILIKE ANY(ARRAY['%email%', '%phone%', '%ssn%', '%address%'])
  ORDER BY table_name, column_name;
"
```

---

## Step 4: Dry Run (1 minute)

Validate configuration without copying data:

```bash
./sync_script.sh --dry-run
```

**Expected Output**:
```
Pre-Sync Validation Report
==========================

Source Database: your_prod_db (250 GB, 45 tables)
Target Database: your_staging_db (will be overwritten)

PII Columns Detected: 12
  users.email              → email strategy
  users.phone              → phone strategy
  users.ssn                → redact strategy

Estimated Sync Time: 35 minutes

✓ Configuration valid
```

**If errors**: Fix configuration and re-run dry-run.

---

## Step 5: Run Actual Sync (30-60 minutes depending on size)

Execute production-to-staging sync:

```bash
./sync_script.sh
```

**Progress Output**:
```
Syncing Production → Staging
============================

[✓] users (50,000 rows, 12 MB) - 3s - 3 columns anonymized
[✓] orders (250,000 rows, 450 MB) - 45s - 1 column anonymized
[✓] products (5,000 rows, 2 MB) - 1s - no PII
...

Total: 45 tables, 1.2M rows, 1.8 GB in 8m 23s
Anonymized: 12 PII columns across 4 tables
```

**If sync fails mid-process**:
```bash
# Resume from checkpoint
./sync_script.sh --resume
```

---

## Step 6: Verify Anonymization (2 minutes)

Check that PII was properly anonymized:

```bash
# Connect to staging
psql postgresql://staging-host/staging_db

# Run verification SQL
\i verify_anonymization.sql
```

**Expected Results**: All checks should show `✓ PASS`:
```
Test 1: Email Anonymization Check
  users.email: 50,000 emails, 50,000 anonymized, 0 violations ✓ PASS

Test 2: Phone Number Anonymization Check
  users.phone: 48,523 phones, 48,523 anonymized, 0 violations ✓ PASS

Test 3: SSN Redaction Check
  users.ssn: 50,000 SSNs, 50,000 redacted, 0 violations ✓ PASS

Overall: ✓ ALL CHECKS PASSED - DATABASE IS SAFE TO USE
```

---

## Step 7: Use Staging Database

Your staging database now has anonymized production data!

```bash
# Connect to staging
psql postgresql://staging-host/staging_db

# Example: Check anonymized emails
SELECT id, email, first_name, created_at
FROM users
LIMIT 5;

# Output:
#  id |        email         | first_name  |     created_at
# ----+----------------------+-------------+-------------------
#   1 | user_a3f5e9b2@anon.local | User-A3F5E9 | 2024-01-15 10:23:45
#   2 | user_b7d2c4e1@anon.local | User-B7D2C4 | 2024-01-16 14:56:12
```

---

## Common Issues and Solutions

### Issue 1: Connection Refused

**Error**: `psql: could not connect to server: Connection refused`

**Solution**:
1. Check VPN connection
2. Verify hostname: `ping prod-db.example.com`
3. Check firewall rules
4. Verify credentials

### Issue 2: Permission Denied

**Error**: `ERROR: permission denied for table users`

**Solution**:
```sql
-- Grant SELECT on production (read-only user)
GRANT CONNECT ON DATABASE your_db TO confiture_sync_user;
GRANT USAGE ON SCHEMA public TO confiture_sync_user;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO confiture_sync_user;

-- Grant ALL on staging (write access needed)
GRANT ALL PRIVILEGES ON DATABASE staging_db TO confiture_sync_user;
```

### Issue 3: Verification Failed (PII Detected)

**Error**: `✗ FAIL - LEAKED EMAILS DETECTED`

**Solution**:
1. Check `anonymization_config.yaml` - missing column?
2. Add missing anonymization rule:
   ```yaml
   tables:
     users:
       anonymization:
         - column: backup_email  # Add this!
           strategy: email
   ```
3. Re-run sync: `./sync_script.sh --force`

### Issue 4: Slow Sync Performance

**Symptom**: Sync taking >2 hours for 100 GB database

**Solution**:
```yaml
# In anonymization_config.yaml
performance:
  parallel_workers: 8           # Increase from 4
  batch_size: 50000             # Increase from 10000
  disable_indexes: true         # Drop indexes, recreate after
```

---

## Automation (Weekly Staging Refresh)

### Option 1: Cron Job

```bash
# Add to crontab: crontab -e
0 2 * * 1 cd /path/to/example && ./sync_script.sh >> /var/log/confiture-sync.log 2>&1
```

### Option 2: CI/CD (GitHub Actions)

```yaml
# .github/workflows/refresh-staging.yml
name: Refresh Staging DB

on:
  schedule:
    - cron: '0 2 * * 1'  # Monday 2 AM

jobs:
  sync:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Sync Production to Staging
        env:
          PROD_DB_PASSWORD: ${{ secrets.PROD_DB_PASSWORD }}
          STAGING_DB_PASSWORD: ${{ secrets.STAGING_DB_PASSWORD }}
        run: |
          cd examples/04-production-sync-anonymization
          ./sync_script.sh
```

---

## Next Steps

1. **Schedule Weekly Refreshes**: Set up cron or CI/CD automation
2. **Sync to Local**: `confiture sync staging-to-local --anonymize`
3. **Customize Verification**: Add custom checks to `verify_anonymization.sql`
4. **Monitor Performance**: Track sync duration and optimize

---

## Useful Commands

```bash
# Dry run (no data copied)
./sync_script.sh --dry-run

# Normal sync
./sync_script.sh

# Resume failed sync
./sync_script.sh --resume

# Force sync (overwrite even if newer)
./sync_script.sh --force

# Verbose logging
./sync_script.sh --verbose

# Skip verification (not recommended)
./sync_script.sh --skip-verify

# Check last sync status
tail -n 100 sync-*.log | grep -E "(PASS|FAIL|ERROR)"

# Connect to staging
psql postgresql://staging-host/staging_db
```

---

## Help and Support

- **Documentation**: See [README.md](./README.md) for detailed guide
- **Configuration Reference**: See [anonymization_config.yaml](./anonymization_config.yaml)
- **Verification SQL**: See [verify_anonymization.sql](./verify_anonymization.sql)
- **Confiture Docs**: https://confiture.readthedocs.io

---

**Total Setup Time**: ~15 minutes + sync time (30-60 minutes for typical database)

**You're Done!** Your staging database now has safe, anonymized production data for debugging and testing.
