# Adopting Confiture on a database that already has migrations applied

You already have a production database. You've been running migrations with `psql`, or `dbmate`, or a hand-rolled script. You want to switch to Confiture without re-running the SQL you've already shipped. This guide is for you.

## The problem in one sentence

If Confiture sees migration files in `db/migrations/` and an empty tracking table, it assumes nothing is applied and tries to run every `up.sql` from scratch. The first `CREATE TABLE` fails because the table already exists. Stuck.

The fix is **`confiture migrate baseline`** — it walks `db/migrations/` and writes each `version` into `tb_confiture` without running any SQL. After baselining, Confiture knows the database is at that version and only `up.sql` files newer than it will be applied.

## End-to-end recipe

The scenario: your database is at migration `004_add_user_preferences`. You've been applying these with `psql -f` for the past year. You want Confiture to take over from migration `005` onwards.

### 1. Vendor your existing migrations into `db/migrations/`

Confiture needs to see the migrations you've already applied, with **filenames that match its naming convention**: `{version}_{name}.up.sql` and `{version}_{name}.down.sql`. The `.up.sql` / `.down.sql` suffix is mandatory — files without it are silently ignored. See [migration naming best practices](migration-naming-best-practices.md) for the full rules.

```text
db/migrations/
├── 001_create_users.up.sql
├── 001_create_users.down.sql
├── 002_create_orders.up.sql
├── 002_create_orders.down.sql
├── 003_add_user_email.up.sql
├── 003_add_user_email.down.sql
├── 004_add_user_preferences.up.sql
└── 004_add_user_preferences.down.sql
```

The contents must match what's already applied — if you reformat or "improve" the SQL, Confiture's checksum check will flag drift on the next `migrate validate`. Either match what shipped exactly, or accept the drift warning once.

### 2. Confirm what version the live database is at

```bash
psql "$DATABASE_URL" -c "\\d"
```

Or whatever bespoke approach you used. The goal is to know the highest migration version that has actually been applied. In this example, it's `004`.

### 3. Write the Confiture environment config

```yaml
# db/environments/production.yaml
name: production
database_url: ${DATABASE_URL}

include_dirs:
  - db/schema

migration:
  tracking_table: public.tb_confiture
```

(`${DATABASE_URL}` is the shell-substituted form — see [the prerequisites doc](../reference/prerequisites.md#secrets-and-environment-variables) for how to wire secrets in.)

### 4. Run baseline

```bash
$ confiture migrate baseline --through 004_add_user_preferences -c db/environments/production.yaml

📋 Baseline: marking migrations through 004_add_user_preferences

  ✅ 001 create_users (marked as applied)
  ✅ 002 create_orders (marked as applied)
  ✅ 003 add_user_email (marked as applied)
  ✅ 004 add_user_preferences (marked as applied)

✅ Marked 4 migration(s) as applied, skipped 0 already applied
```

Confiture has created `tb_confiture` and written one row per baselined migration. The `checksum` and `execution_time_ms` columns are `NULL` for these rows — they were never actually executed by Confiture.

Sanity-check before continuing:

```bash
$ confiture migrate status -c db/environments/production.yaml --format json | jq '.applied | length, .pending | length'
4
0
```

### 5. Make a new migration the normal way

```bash
confiture migrate generate --name "add_user_phone"
```

Confiture allocates the next version (`20260520143015` or `005` depending on your configured naming). Edit the new file, commit, deploy.

```bash
$ confiture migrate up -c db/environments/production.yaml

▸ 1 pending migration
  ► 20260520143015_add_user_phone.up.sql

✓ Applied 20260520143015_add_user_phone (24 ms)
```

The 4 baselined rows remain untouched. Only the new migration ran.

## Failure modes to know about

### "relation already exists" when you skip baseline

Skipping baseline and running `migrate up` is the classic mistake:

```bash
$ confiture migrate up
✗ MigrationError: relation "users" already exists
  Migration: 001_create_users
  Hint: If the schema already exists, run `confiture migrate baseline --through <last-applied-version>` first.
exit 3
```

Solution: run `migrate baseline` with the highest version that's actually been applied.

### Wrong `--through` value

If you tell baseline to mark `--through 004` but only `001`-`003` are actually in the database, the next `migrate up` will succeed (skipping `001`-`004` as baselined) and skip `004` even though it was never applied. Take ten seconds to confirm the real state with `psql` before baselining.

### Already-applied detection

If you re-run `migrate baseline` after a successful one, it skips rows that already exist in `tb_confiture` rather than duplicating them. Safe to repeat.

### `tb_confiture` already exists from a previous Confiture install

If a previous attempt left a populated `tb_confiture` lying around, `migrate baseline` adds rows on top of what's there. To start fresh:

```bash
confiture migrate reinit   # clears the tracking table and re-baselines from disk
```

`reinit` is the bigger hammer. Prefer `baseline` unless you know you need it.

## Alternative: copy history from another database (`--from-db`)

When you're refreshing a target from another environment — typical staging-from-production refresh or a DR drill — the `pg_restore` ought to bring `tb_confiture` over with the rest of the schema. When that doesn't happen (or when the dump excluded the table for size or sensitivity reasons), `confiture migrate baseline --through <version>` forces the operator to know the right checkpoint by hand. That's brittle.

`--from-db` removes the manual step. Point it at a database that's already correct, and the rows get copied:

```bash
$ confiture migrate baseline --from-db postgresql://prod-host/myapp \
    -c db/environments/staging.yaml
⚠️  Source DB has 1 version(s) not present in local migrations: 042.  These rows will NOT be copied.
📋 Baseline from postgresql://prod-host/myapp
  ✅ 001 create_users (copied)
  ✅ 002 add_posts (copied)
  ✅ 003 add_comments (copied)
✅ Copied 3 row(s); 0 already applied.
```

What it does:

1. Opens the source DSN and reads its `tb_confiture`.
2. Filters to versions that exist in both the source DB **and** the local `db/migrations/` directory — orphan source rows are surfaced as warnings, not silently copied.
3. Inserts the surviving rows verbatim into the target's tracking table, preserving `version`, `name`, `applied_at`, `execution_time_ms`, and `checksum`. The target gets a fresh `id` and a `slug` that records the copy operation.
4. Rows already present on the target are skipped.

Combined with `--through`, the copy is capped at the named version — useful when the target should intentionally lag behind the source. The CLI warns when the cap excludes source rows so the asymmetry is visible.

Use `--dry-run` to preview without writing.

`--source-table` overrides the source's tracking-table name when it differs from the target (the default is to use the same name on both ends).

## Done — what just happened?

You now have a populated `tb_confiture` matching the live database state, and `migrate up` will apply only new migrations from this point forward. The on-disk migrations `001`-`004` are immutable history — don't edit them.

See [the tracking-table reference](../reference/tracking-table.md) for what's in the table, and [the incremental migrations guide](02-incremental-migrations.md) for day-to-day workflow.

## Verifying the recipe in CI

The `migrate baseline` recipe above is exercised end-to-end in
[`tests/integration/test_legacy_bootstrap_guide.py`](../../tests/integration/test_legacy_bootstrap_guide.py) — that test spins up a Postgres, applies migrations `001`-`004` directly with `psql`, then drives the exact CLI sequence shown above and asserts the resulting `migrate status` reports the right counts of applied vs pending.

If you change this guide, update that test (and vice versa).
