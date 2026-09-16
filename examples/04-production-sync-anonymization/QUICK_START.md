# Quick Start — Production Data Sync with Anonymization

The short path. [README.md](README.md) has the reasoning; this is the sequence.

**Time**: ~15 minutes plus however long your data takes to copy.

---

## Try it with no production database at all

```bash
CONFITURE_EXAMPLE_DB_URL=postgresql://localhost/scratch ./run.sh
```

Two scratch databases are created on that server, one seeded with recognisable
PII, synced with masking, verified, and dropped. Nothing in this guide is
claimed that this script does not do.

---

## Prerequisites Checklist

- [ ] `confiture --version` works
- [ ] `psql --version` works (building the target, running verification)
- [ ] `pg_dump --version` works (the pre-overwrite backup in `sync_script.sh`)
- [ ] Read-only credentials for production
- [ ] Write credentials for staging, **owning** the tables (the copy disables triggers)
- [ ] Staging already has the schema — `confiture sync` copies rows, not tables

---

## Step 1: Environment variables (2 minutes)

```bash
export PROD_DB_PASSWORD='…'
export STAGING_DB_PASSWORD='…'
export ANONYMIZATION_SECRET='…'

# Verify all three are set — the sync refuses without the third
: "${PROD_DB_PASSWORD:?}" "${STAGING_DB_PASSWORD:?}" "${ANONYMIZATION_SECRET:?}" && echo ok
```

`ANONYMIZATION_SECRET` is the HMAC key behind every pseudonym. It has **no
default**: `confiture sync --anonymize` stops with `CONFIG_009` rather than
falling back to something guessable.

From a secret store rather than your shell history:

```bash
export ANONYMIZATION_SECRET="$(aws secretsmanager get-secret-value \
    --secret-id staging/anonymization --query SecretString --output text)"
```

Keep it away from the people who have staging access — the secret plus a list of
candidate emails reverses the masking.

---

## Step 2: Database connections (3 minutes)

One file per environment, one `database_url` each:

```yaml
# db/environments/production.yaml
name: production
database_url: postgresql://confiture_sync_user:${PROD_DB_PASSWORD}@prod-db.example.com:5432/ecommerce_prod?sslmode=require
include_dirs:
  - db/schema
exclude_dirs: []
```

Test both ends:

```bash
psql "postgresql://confiture_sync_user:${PROD_DB_PASSWORD}@prod-db.example.com:5432/ecommerce_prod" -c 'SELECT 1'
psql "postgresql://confiture_sync_user:${STAGING_DB_PASSWORD}@staging-db.example.com:5432/ecommerce_staging" -c 'SELECT 1'
```

Build the target if it is empty:

```bash
confiture build --env staging --output /tmp/schema.sql
psql "$STAGING_URL" -v ON_ERROR_STOP=1 -f /tmp/schema.sql
```

---

## Step 3: Anonymization rules (5 minutes)

`db/sync/anonymization.yaml` — the whole grammar:

```yaml
users:
  - column: email
    strategy: email        # -> user_3698af8f@example.com
  - column: full_name
    strategy: name         # -> User 40A9
  - column: phone
    strategy: phone        # -> +1-555-6633
  - column: ssn
    strategy: redact       # -> [REDACTED]

payments:
  - column: stripe_customer_id
    strategy: hash         # -> 9d4e1a77b3c05f28, unique and one-way
```

**A column with no rule is copied verbatim.** So the job is to find every PII
column, not to review the ones already listed:

```bash
psql "$PROD_URL" -Atc "
  SELECT table_name || '.' || column_name
  FROM information_schema.columns
  WHERE table_schema = 'public'
    AND column_name ~ '(email|phone|ssn|name|address|birth|ip_)'
  ORDER BY 1"
```

That regex is a starting point, not an audit — confiture has no PII discovery.

---

## Step 4: Check the preconditions (1 minute)

```bash
./sync_script.sh --dry-run
```

This validates that every strategy named is one of the five that exist. Worth
doing: confiture masks an **unknown strategy to `[REDACTED]`** instead of
failing, so `strategy: emial` would quietly destroy the column.

`--dry-run` is the script's flag. `confiture sync` has none.

---

## Step 5: Sync

```bash
./sync_script.sh
```

or directly:

```bash
confiture sync --from production --to staging \
    --anonymize --anonymization-config db/sync/anonymization.yaml \
    --exclude audit_logs \
    --checkpoint .sync-checkpoint.json
```

If it dies partway:

```bash
confiture sync … --checkpoint .sync-checkpoint.json --resume
```

Resume is per table — an interrupted table is redone from the start.

---

## Step 6: Verify (2 minutes)

```bash
psql "$STAGING_URL" -v ON_ERROR_STOP=1 -f verify_anonymization.sql
```

```
NOTICE:  1. no source PII survived
NOTICE:  2. masked values have the shape each strategy promises
NOTICE:  3. NULL stayed NULL
NOTICE:  4. pseudonyms are stable across tables
NOTICE:  5. seeds separate staff pseudonyms from customer pseudonyms
NOTICE:  6. hash preserved uniqueness
NOTICE:  7. referential integrity survived
NOTICE:  8. non-PII columns survived intact
✅ verification passed: staging holds no source PII, and is still usable
```

Do not skip this. A sync that exits 0 tells you rows moved, not that they were
masked.

---

## Step 7: Use staging

```bash
psql "$STAGING_URL" -c "SELECT id, email, full_name FROM users ORDER BY id LIMIT 3"
```

```
 id |           email           | full_name
----+---------------------------+-----------
  1 | user_3698af8f@example.com | User 40A9
  2 | user_75787de6@example.com | User CE02
  3 | user_4dd48789@example.com | User 8B31
```

Joins still work, because one address masks to one pseudonym everywhere:

```sql
SELECT u.email, count(*) AS orders
FROM users u JOIN orders o ON o.user_id = u.id
GROUP BY u.email;
```

---

## Common Issues

### `CONFIG_009: ANONYMIZATION_SECRET is not set`

Working as intended. Set it (Step 1).

### `CONFIG_002` from the config file

Not in the `table: [{column, strategy}]` shape — often a rule missing `column`
or `strategy`, or a file written for a different tool.

### Verification failed — PII detected

Treat staging as holding production PII: restrict access first, diagnose second.

1. Does the column have a rule? Absent means verbatim.
2. Does the rule's `column` match the real column name? A rule naming a column
   that is not in the table is skipped silently.
3. Was `--anonymize` passed? Check `warnings` in `--format json`.

### `must be owner of table`

The copy disables triggers on the target, which needs table ownership.

### Slow

Raise `--batch-size` (default 5000); copy less with `--tables` / `--exclude`.
There is no parallel-worker option.

---

## Automation

### Cron

```bash
# Mondays at 03:00
0 3 * * 1 cd /srv/app && ./sync_script.sh --skip-backup >> /var/log/staging-refresh.log 2>&1
```

### GitHub Actions

```yaml
on:
  schedule:
    - cron: '0 3 * * 1'
jobs:
  refresh:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v6
      - run: pip install confiture
      - run: ./sync_script.sh --skip-backup
        env:
          PROD_DB_PASSWORD:     ${{ secrets.PROD_DB_PASSWORD }}
          STAGING_DB_PASSWORD:  ${{ secrets.STAGING_DB_PASSWORD }}
          ANONYMIZATION_SECRET: ${{ secrets.ANONYMIZATION_SECRET }}
```

Never add `--skip-verify` to a scheduled job: it turns a check into an
assumption.

---

## Useful Commands

```bash
# The demo, end to end, on scratch databases
CONFITURE_EXAMPLE_DB_URL=postgresql://localhost/scratch ./run.sh

# Preconditions only
./sync_script.sh --dry-run

# Sync a subset
confiture sync --from production --to staging --anonymize --tables users,orders

# Machine-readable result
confiture sync --from production --to staging --anonymize --format json

# Verify
psql "$STAGING_URL" -v ON_ERROR_STOP=1 -f verify_anonymization.sql
```

---

## Next Steps

- [README.md](README.md) — strategies, GDPR posture, security
- [Production Sync guide](../../docs/guides/03-production-sync.md)
- `confiture sync --help`
