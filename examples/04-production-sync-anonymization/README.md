# Production Data Sync with PII Anonymization

**Medium 3: realistic data in staging, without shipping anyone's personal data into it**

**Time to complete**: 20 minutes

---

## Table of Contents

1. [Overview](#overview)
2. [Use Case](#use-case)
3. [What This Example Demonstrates](#what-this-example-demonstrates)
4. [Run It](#run-it)
5. [Prerequisites](#prerequisites)
6. [Quick Start](#quick-start)
7. [Detailed Workflow](#detailed-workflow)
8. [Anonymization Strategies](#anonymization-strategies)
9. [Configuration Reference](#configuration-reference)
10. [Verification and Testing](#verification-and-testing)
11. [GDPR Compliance](#gdpr-compliance)
12. [Best Practices](#best-practices)
13. [Troubleshooting](#troubleshooting)
14. [Security Considerations](#security-considerations)
15. [Performance](#performance)
16. [Additional Resources](#additional-resources)

---

## Overview

### The Challenge

Staging with synthetic data does not reproduce production bugs. The bugs that
matter live in the shape of real data: the customer with 4,000 orders, the
address with an emoji in it, the row that predates a column's `NOT NULL`.

Staging with a copy of production data reproduces those bugs and creates a much
worse problem — every engineer with staging access now has your customers'
email addresses, phone numbers and national identifiers, in a system with a
fraction of production's controls.

### The Solution

Copy the data, mask the columns that identify people, and prove the masking
worked before anyone connects to it:

```bash
confiture sync --from production --to staging \
    --anonymize --anonymization-config db/sync/anonymization.yaml \
    --exclude audit_logs

psql "$STAGING_URL" -v ON_ERROR_STOP=1 -f verify_anonymization.sql
```

The second command is not optional decoration. A sync that exits 0 tells you
rows moved; it does not tell you they were masked.

---

## Use Case

### Scenario: E-Commerce Debugging

A checkout bug only reproduces for customers with a particular order history.
You want that history in staging on Monday morning, and you want nothing in
staging that could identify the customers it came from.

```bash
# Friday: refresh staging from production, masked
./sync_script.sh

# Monday: debug against realistic data
psql "$STAGING_URL" -c "SELECT * FROM orders WHERE user_id = 1"
#  billing_email is user_3698af8f@example.com, the order history is real
```

---

## What This Example Demonstrates

| | |
|---|---|
| **Column-level masking** | Five strategies, applied per column, opt-in |
| **Keyed pseudonyms** | HMAC under a per-deployment secret — stable inside a deployment, unrelated across deployments |
| **Referential survival** | One customer is one pseudonym in every table, so joins still work |
| **Domain separation** | `seed` keeps staff identities uncorrelated with customer identities |
| **Table exclusion** | Some tables never leave production, masked or not |
| **Proof, not assertion** | Eight SQL checks that fail the build if PII survived |
| **Resumable copies** | `--checkpoint` / `--resume` for syncs that die halfway |

What it deliberately does **not** claim: confiture has no PII discovery, no
sampling, no row filtering, no scheduling and no notification. Those are real
needs and they belong to your tooling — [Best Practices](#best-practices) shows
where to put them.

---

## Run It

```bash
CONFITURE_EXAMPLE_DB_URL=postgresql://localhost/scratch ./run.sh
```

`run.sh` stands up two scratch databases on that server — one playing
production, one playing staging — seeds "production" with deliberately
recognisable PII, syncs with `--anonymize`, runs the full verification, and
drops both. It is what CI runs on every commit, which is the only reason you
should believe anything on this page.

---

## Prerequisites

### Infrastructure

| Role | Needs |
|---|---|
| Production (source) | Reachable, read-only credentials |
| Staging (target) | Reachable, write credentials, **the same schema already built** |

`confiture sync` copies rows, not tables. Build the target first:

```bash
confiture build --env staging --output /tmp/schema.sql
psql "$STAGING_URL" -v ON_ERROR_STOP=1 -f /tmp/schema.sql
```

### Permissions Required

On **production**, the source role needs `CONNECT`, `USAGE` on the schema and
`SELECT` on the tables being copied — nothing more. Sync never writes to its
source:

```sql
CREATE ROLE confiture_sync_user LOGIN PASSWORD '…';
GRANT CONNECT ON DATABASE ecommerce_prod TO confiture_sync_user;
GRANT USAGE ON SCHEMA public TO confiture_sync_user;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO confiture_sync_user;
```

On **staging**, the target role needs `TRUNCATE` and `INSERT`, plus ownership of
the tables (sync disables triggers during the copy, which requires it):

```sql
GRANT INSERT, TRUNCATE ON ALL TABLES IN SCHEMA public TO confiture_sync_user;
ALTER TABLE users OWNER TO confiture_sync_user;  -- and so on
```

### Software

```bash
confiture --version          # the tool
psql --version               # for building the target and running verification
pg_dump --version            # for sync_script.sh's pre-overwrite backup
```

---

## Quick Start

### 1. Configure environments

One file per environment under `db/environments/`, each with a single
`database_url`. `${VAR}` is expanded at load time, so no secret is committed:

```yaml
# db/environments/production.yaml
name: production
database_url: postgresql://confiture_sync_user:${PROD_DB_PASSWORD}@prod-db.example.com:5432/ecommerce_prod?sslmode=require
include_dirs:
  - db/schema
exclude_dirs: []
```

### 2. Configure anonymization

`db/sync/anonymization.yaml` — the path `--anonymization-config` defaults to:

```yaml
users:
  - column: email
    strategy: email
  - column: full_name
    strategy: name
  - column: ssn
    strategy: redact
```

### 3. Set the secret

```bash
export PROD_DB_PASSWORD=…
export STAGING_DB_PASSWORD=…
export ANONYMIZATION_SECRET=…     # no default; see below
```

`ANONYMIZATION_SECRET` is the HMAC key behind every pseudonym. There is no
default — `confiture sync --anonymize` stops with `CONFIG_009` rather than
falling back to something guessable, because a predictable key makes the
pseudonyms reversible by anyone who can guess it.

### 4. Sync

```bash
confiture sync --from production --to staging \
    --anonymize --anonymization-config db/sync/anonymization.yaml \
    --exclude audit_logs
```

### 5. Verify

```bash
psql "$STAGING_URL" -v ON_ERROR_STOP=1 -f verify_anonymization.sql
```

Or let `./sync_script.sh` do steps 4 and 5 with a backup in between.

---

## Detailed Workflow

### Step 1: Pre-sync checks

`sync_script.sh` refuses to start unless `confiture` and `psql` are on PATH, the
anonymization config parses, every strategy in it is one of the five that exist,
and all three environment variables are set.

The strategy check earns its place: confiture masks an **unknown strategy to
`[REDACTED]`** rather than rejecting it. That is the safe default — a typo can
never leak data — but it means `strategy: emial` silently destroys a column.
Catch it before the sync, not after.

```bash
./sync_script.sh --dry-run
```

`--dry-run` here is the script's own flag. `confiture sync` has no `--dry-run`.

### Step 2: Schema copy

There isn't one. The target must already have the tables:

```bash
confiture build --env staging --output /tmp/schema.sql
psql "$STAGING_URL" -v ON_ERROR_STOP=1 -f /tmp/schema.sql
```

This is why both environments in this example list the same `include_dirs`.
Build once, sync often.

### Step 3: Data copy with anonymization

For each selected table, confiture truncates the target, reads the source rows,
applies the column rules, and inserts in batches.

Two details worth knowing:

- **Every selected table is truncated before any is copied**, in one statement.
  Truncating each table just before copying it looks equivalent and is not:
  `TRUNCATE … CASCADE` empties everything referencing the named table, so a
  parent copied late would empty children copied earlier.
- **Triggers are disabled on the target during the copy**, so foreign keys and
  application triggers do not fire per row. They are re-enabled afterwards.

```bash
confiture sync --from production --to staging \
    --anonymize --anonymization-config db/sync/anonymization.yaml \
    --tables users,orders,payments \
    --batch-size 10000
```

### Step 4: Post-sync verification

```bash
psql "$STAGING_URL" -v ON_ERROR_STOP=1 -f verify_anonymization.sql
```

See [Verification and Testing](#verification-and-testing).

### Step 5: Resume support

```bash
confiture sync --from production --to staging --anonymize \
    --checkpoint .sync-checkpoint.json      # writes progress as it goes

confiture sync --from production --to staging --anonymize \
    --checkpoint .sync-checkpoint.json --resume   # skips completed tables
```

Resume is per table, not per row: an interrupted table is redone from the start.

---

## Anonymization Strategies

Five strategies. Four are *keyed* — the output is an HMAC of the input under
`ANONYMIZATION_SECRET`, so it is stable within a deployment and unrelated across
deployments. `redact` is not keyed and needs no secret.

### 1. `email`

```
alice.martin@realmail.example.org  ->  user_3698af8f@example.com
```

Eight hex characters under a fixed domain. The domain is not configurable, and
the original domain is never preserved — `@gmail.com` versus `@yourcompany.com`
is itself information about the person.

### 2. `name`

```
Alice Martin  ->  User 40A9
```

### 3. `phone`

```
+1-617-555-0101  ->  +1-555-6633
```

`555` is the reserved fictional range, so an anonymized number cannot ring a
real phone if some job dials it.

### 4. `hash`

```
cus_NffrFeUfNV2Hib  ->  9d4e1a77b3c05f28
```

Sixteen hex characters, one-way, and **uniqueness-preserving** — distinct inputs
stay distinct. Use it where code needs values to differ but must not resolve
them: processor customer ids, IP addresses, device identifiers.

### 5. `redact`

```
123-45-6789  ->  [REDACTED]
```

The same constant for every row. Not keyed, needs no secret. Use it where even a
stable pseudonym is too much: national identifiers, bank accounts, free-text
fields that may contain anything.

`redact` is also what confiture applies to a strategy name it does not
recognise, which is safe but silent — see [Step 1](#step-1-pre-sync-checks).

### Determinism, and why it matters

```bash
# Same secret, twice:
user_3698af8f@example.com     user_3698af8f@example.com

# Different secret:
user_ff597a71@example.com
```

Stability is what keeps the data *usable*: `users.email` and
`orders.billing_email` share a strategy and a seed, so one customer is one
pseudonym on both sides and "every order this customer placed" is still a
question staging can answer. Randomised masking would break every such join.

Unrelatedness across deployments is what keeps it *safe*: an attacker with an
anonymized dump cannot hash a list of candidate addresses and look for matches,
because they do not have the key.

### Domain separation with `seed`

`seed` is a domain separator, not a secret. Two columns with different seeds get
unrelated pseudonyms from the same input:

```yaml
employees:
  - column: email
    strategy: email
    seed: 2          # unrelated to users.email, which has no seed
```

Without it, a person who is both a customer and an employee appears as the same
pseudonym in both tables, and the two roles can be correlated.

### Strategy selection guide

| Column | Strategy | Why |
|---|---|---|
| `users.email` | `email` | Joinable, plausible shape |
| `orders.billing_email` | `email`, same seed | Must match `users.email` |
| `users.full_name` | `name` | |
| `users.phone` | `phone` | |
| `users.ssn` | `redact` | No stable pseudonym is acceptable |
| `payments.stripe_customer_id` | `hash` | Must stay unique, must not resolve |
| `user_sessions.ip_address` | `hash` | Identifies a household |
| `orders.customer_notes` | `redact` | Free text; nothing can find the PII inside it |
| `payments.billing_zip` | *(none)* | Not an identifier alone; fraud rules need it |
| `user_sessions.user_agent` | *(none)* | What staging is usually debugging |

A column absent from the config is copied **verbatim**. Read that the other way
round: this file, not the schema, decides what reaches staging intact.

---

## Configuration Reference

### `db/sync/anonymization.yaml`

The whole grammar:

```yaml
<table>:
  - column: <name>
    strategy: email | phone | name | hash | redact
    seed: <int>        # optional domain separator
```

There is no `filter:`, no `sample_rate:`, no `exclude_tables:`, no
`performance:` block. Table selection is `--tables` / `--exclude` on the command
line. A key confiture does not read is a key that silently does nothing.

### `confiture sync` options

| Option | Meaning |
|---|---|
| `--from` | Source: environment name or DSN *(required)* |
| `--to` | Target: environment name or DSN *(required)* |
| `--anonymize` | Apply the rules. Without it the copy is verbatim and a warning is printed |
| `--anonymization-config` | Rules file (default `db/sync/anonymization.yaml`) |
| `--tables` | Comma-separated include list (default: all) |
| `--exclude` | Comma-separated exclude list |
| `--batch-size` | Rows per insert batch (default 5000) |
| `--checkpoint` | Progress file for resumable syncs |
| `--resume` | Skip tables the checkpoint marks complete |
| `--format` | `text` or `json` |

### JSON output

```json
{
  "ok": true,
  "command": "sync",
  "anonymized": true,
  "tables": { "users": 3, "orders": 3 },
  "total_rows": 6,
  "warnings": [],
  "parser": { "pglast": "8.4", "pg_major": 18 }
}
```

`anonymized: false` with a populated `warnings` array is what an un-masked copy
looks like — worth alerting on.

---

## Verification and Testing

`verify_anonymization.sql` runs eight checks against the **target**, each
`RAISE`ing on violation so that with `-v ON_ERROR_STOP=1` the exit code is the
verdict:

| # | Check |
|---|---|
| 1 | No source PII survived — the exact values seeded into "production" are absent |
| 2 | Masked values have the shape each strategy promises |
| 3 | `NULL` stayed `NULL` — masking a missing value into a present one invents data |
| 4 | Pseudonyms are stable across tables, so joins work |
| 5 | Different seeds gave unrelated pseudonyms |
| 6 | `hash` preserved uniqueness |
| 7 | Referential integrity survived |
| 8 | Non-PII columns survived intact |

Checks 1 and 2 are deliberately a pair. A column emptied to `NULL`, or dropped
from the sync entirely, contains no PII and is useless; check 8 is the same idea
applied to over-masking.

Check 1 works because `demo/seed_production.sql` uses recognisable values —
real-looking domains, a `+1-617` area code, well-formed national identifiers. A
seed of `aaa`/`bbb` placeholders would let a completely broken sync pass.

### Adding a check

```sql
DO $$
DECLARE bad INTEGER;
BEGIN
    SELECT count(*) INTO bad FROM my_table WHERE my_column LIKE '%@ourcustomers.com';
    IF bad > 0 THEN
        RAISE EXCEPTION 'my_table.my_column: % row(s) not masked', bad;
    END IF;
END $$;
```

---

## GDPR Compliance

### Anonymization vs. pseudonymization

This distinction decides whether the GDPR still applies to your staging
database, so it is worth being precise:

- **Anonymized** data cannot be attributed to a person by *anyone*, by any
  reasonably likely means. It falls outside the GDPR (Recital 26).
- **Pseudonymized** data can be re-attributed with additional information held
  separately. It remains personal data and stays fully in scope (Art. 4(5)).

What confiture produces is **pseudonymized**, not anonymized:

- `hash` and the keyed strategies are reversible by anyone holding
  `ANONYMIZATION_SECRET` plus a list of candidate values.
- Rows that are not masked at all — order totals, timestamps, geography — can
  re-identify an individual in combination even when every masked column holds a
  pseudonym.

Treat the staging database as personal data: access controls, retention limits,
a lawful basis, and inclusion in your records of processing. A page claiming
otherwise would be doing you an active disservice.

### DPIA prompts

- What is the lawful basis for copying production data into staging? (Commonly
  legitimate interest, Art. 6(1)(f) — which requires a balancing test.)
- Who has staging access, and is that list smaller than it was last quarter?
- How long does a staging refresh persist before it is purged?
- Is `ANONYMIZATION_SECRET` held somewhere staging users cannot read?

### Checklist

- [ ] Every PII column has a rule (review after **every** schema change)
- [ ] `ANONYMIZATION_SECRET` lives in a secret store, not a file or CI log
- [ ] Verification runs after every sync and fails the pipeline
- [ ] Staging access is reviewed and logged
- [ ] Retention policy exists and is enforced
- [ ] Tables that must never leave production are in `--exclude`

---

## Best Practices

### 1. Dry-run the preconditions

```bash
./sync_script.sh --dry-run
```

### 2. Keep the config in step with the schema

A new PII column with no rule is copied verbatim, and nothing warns you.
Confiture has no PII discovery, so make it a review checklist item, or write the
check yourself:

```bash
psql "$PROD_URL" -Atc "
  SELECT table_name || '.' || column_name
  FROM information_schema.columns
  WHERE table_schema = 'public'
    AND (column_name ~ '(email|phone|ssn|name|address|birth)')
" | sort > /tmp/candidates.txt
# diff against the columns named in db/sync/anonymization.yaml
```

### 3. Use one seed per identity domain

Customers, staff, and vendors should not share a seed. See
[Domain separation](#domain-separation-with-seed).

### 4. Automate the refresh

Confiture has no scheduler. Use your CI:

```yaml
# .github/workflows/refresh-staging.yml
on:
  schedule:
    - cron: '0 3 * * 1'        # Mondays, 03:00
jobs:
  refresh:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v6
      - run: pip install confiture
      - run: ./examples/04-production-sync-anonymization/sync_script.sh --skip-backup
        env:
          PROD_DB_PASSWORD:     ${{ secrets.PROD_DB_PASSWORD }}
          STAGING_DB_PASSWORD:  ${{ secrets.STAGING_DB_PASSWORD }}
          ANONYMIZATION_SECRET: ${{ secrets.ANONYMIZATION_SECRET }}
```

### 5. Never skip verification

`--skip-verify` exists for debugging the script. If it appears in a scheduled
job, the job is asserting that the masking worked rather than checking.

---

## Troubleshooting

### `CONFIG_009: ANONYMIZATION_SECRET is not set`

Working as intended. There is no default key. Set it from your secret store.

### `CONFIG_002` from the anonymization config

The file is not `table: [{column, strategy}]`. Most often it is a config written
against some other tool's format, or a rule missing `column`/`strategy`.

### A column reached staging unmasked

Three usual causes, in order of likelihood:

1. The column has no rule. Absent means verbatim.
2. The rule names a column that does not exist — a rule whose column is not in
   the table is skipped silently.
3. `--anonymize` was not passed. Check the `warnings` array in `--format json`.

### Sync fails partway

```bash
confiture sync … --checkpoint .sync-checkpoint.json --resume
```

If resume also fails, delete the checkpoint and start fresh; a partial target is
not safe to hand to anyone regardless.

### `permission denied` / `must be owner of table`

Sync disables triggers on the target for the duration of the copy, which
requires table ownership. See [Permissions Required](#permissions-required).

### Slow sync

Raise `--batch-size` (default 5000). Copying is single-threaded — confiture has
no parallel-worker option — so for very large tables, sync a subset with
`--tables` and exclude what staging does not need.

---

## Security Considerations

### 1. Credentials

```yaml
# Good — resolved from the environment at load time
database_url: postgresql://sync_user:${PROD_DB_PASSWORD}@prod-db:5432/app?sslmode=require

# Bad — committed
database_url: postgresql://sync_user:hunter2@prod-db:5432/app
```

Prefer `--from production` (an environment name) over `--from postgresql://…`:
a DSN on the command line is visible in `ps aux` and in shell history.

### 2. Network

Require TLS on the source (`?sslmode=require`), and reach production over a
tunnel rather than exposing it:

```bash
ssh -L 5433:prod-db.internal:5432 bastion.example.com -N &
confiture sync --from postgresql://user@localhost:5433/app --to staging --anonymize
```

### 3. The secret

`ANONYMIZATION_SECRET` reverses the pseudonyms for anyone who holds it plus a
candidate list. It must not be readable by the people with staging access — that
combination reconstitutes the production data you just masked. Keep it in a
secret store, out of CI logs, and rotate it when staging access changes.

### 4. Treat staging as personal data

See [GDPR Compliance](#gdpr-compliance). Access logs, retention, and a smaller
access list than production's.

---

## Performance

Copying is single-threaded and row-by-row when anonymizing (the fast `COPY` path
is only used for tables with no rules). The knobs that exist:

| Knob | Effect |
|---|---|
| `--batch-size` | Rows per insert. Higher trades memory for round trips |
| `--tables` / `--exclude` | The biggest lever by far — do not copy what staging does not need |
| `--checkpoint` | Does not speed anything up; makes a failure cost minutes instead of hours |

Triggers are disabled on the target during the copy, so FK checks and
application triggers do not fire per row.

---

## Additional Resources

### Documentation

- [Production Sync guide](../../docs/guides/03-production-sync.md)
- [Anonymization API](../../docs/api/anonymization.md)
- [Security model](../../docs/security/)

### Related examples

- [01-basic-migration](../01-basic-migration) — Medium 1 and 2
- [02-fraiseql-integration](../02-fraiseql-integration) — build from DDL
- [03-zero-downtime-migration](../03-zero-downtime-migration) — Medium 4

### External

- [GDPR Recital 26](https://gdpr-info.eu/recitals/no-26/) — anonymous information
- [GDPR Art. 4(5)](https://gdpr-info.eu/art-4-gdpr/) — pseudonymisation
- [PostgreSQL Anonymizer](https://postgresql-anonymizer.readthedocs.io/) — an
  in-database alternative, worth comparing
