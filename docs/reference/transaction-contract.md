# Transaction & SAVEPOINT Compatibility Contract

[← Back to Reference](../index.md) · [Dry-Run Guide](../guides/dry-run.md) · [Incremental Migrations](../guides/02-incremental-migrations.md)

Confiture wraps every migration in a transaction with savepoints.  This
page is the **load-bearing contract** for migration authors who want to
open their own savepoints, use `psycopg`'s `conn.transaction()`, or
embed `DO $$ … EXCEPTION WHEN … $$` blocks.

If you only run plain DDL (`CREATE TABLE`, `ALTER TABLE`, …) you can
stop reading.  The contract is for the advanced cases.

> The two integration tests in
> `tests/integration/test_savepoint_contract.py` are the executable
> form of this contract.  If they fail, the contract is broken — fix
> the code, not this page.

---

## 1. Confiture wraps every applied migration in a transaction

A `confiture migrate up` invocation runs each pending migration inside
a database transaction owned by confiture:

- For transactional migrations (the default) — confiture opens a
  per-migration `SAVEPOINT migration_<version>`, executes `up()`, then
  releases the savepoint and `COMMIT`s on success.
- On failure, confiture issues `ROLLBACK TO SAVEPOINT
  migration_<version>` and re-raises a `MigrationError`.
- Migrations declared `transactional = False` opt out — see
  point 5 below.

**Implication for authors:** by default, your migration runs inside an
already-open transaction.  Do not call `BEGIN` (it will warn or no-op);
do not call `COMMIT` (it ends the wrapping transaction — see point 5).

---

## 2. `--dry-run-execute` and `preflight --against` add an outer SAVEPOINT

Both verification modes open a second savepoint *outside* the
per-migration one, then `ROLLBACK TO` it unconditionally at the end:

| Mode | Outer SAVEPOINT name | Final action |
|------|----------------------|--------------|
| `migrate up --dry-run-execute` | `dry_run_execute` | `ROLLBACK TO SAVEPOINT dry_run_execute; RELEASE` |
| `migrate preflight --against <db>` | `preflight_run` | `ROLLBACK TO SAVEPOINT preflight_run; RELEASE` |

Inside that envelope the per-migration savepoint is created and
released exactly as in normal `migrate up`, but the final `COMMIT` is
suppressed (issue #126) so the outer SAVEPOINT remains valid for the
caller's rollback.

```sql
-- Conceptual structure under --dry-run-execute:
BEGIN;
SAVEPOINT dry_run_execute;
  SAVEPOINT migration_20260528120000;
    -- migration body executes here
  RELEASE SAVEPOINT migration_20260528120000;
ROLLBACK TO SAVEPOINT dry_run_execute;
RELEASE SAVEPOINT dry_run_execute;
ROLLBACK;
```

**Implication for authors:** verification modes are *guaranteed* to
leave the database unchanged — including the tracking table.  You can
rely on this for CI gates.

---

## 3. Migration bodies MAY open their own SAVEPOINTs

`psycopg`'s `conn.transaction()` context manager and an explicit
`SAVEPOINT … RELEASE` pair both work without conflict.  The inner
savepoint nests cleanly below the per-migration savepoint:

```python
from confiture.models.migration import Migration


class StagedBackfill(Migration):
    version = "20260528120000"
    name = "staged_backfill"

    def up(self) -> None:
        self.execute("CREATE TABLE staged (id int PRIMARY KEY, label text)")

        # psycopg conn.transaction() opens an inner SAVEPOINT.
        with self.connection.transaction():
            self.execute("INSERT INTO staged VALUES (1, 'first')")
            self.execute("INSERT INTO staged VALUES (2, 'second')")

        # Explicit SAVEPOINT/RELEASE also works.
        self.execute("SAVEPOINT staged_explicit")
        self.execute("INSERT INTO staged VALUES (3, 'third') ON CONFLICT DO NOTHING")
        self.execute("RELEASE SAVEPOINT staged_explicit")
```

Under `migrate up`, all inserts persist.  Under
`migrate up --dry-run-execute` and `migrate preflight --against`, the
outer rollback discards everything — including the inner savepoint's
work — and the database is left unchanged.

**Implication for authors:** use inner savepoints freely for staged
data backfills, conditional logic with rollback, or any place you would
reach for `try/except` around DDL.

---

## 4. `DO $$ … EXCEPTION WHEN … $$` blocks compose

PL/pgSQL `EXCEPTION` handlers open server-side savepoints.  Those
savepoints live below any client-side savepoint confiture has set up,
so they do not interact:

```sql
DO $$
BEGIN
  EXECUTE 'CREATE INDEX CONCURRENTLY idx_users_email ON users(email)';
EXCEPTION
  WHEN duplicate_table THEN
    RAISE NOTICE 'idx_users_email already exists — skipping';
END $$;
```

(Note: `CREATE INDEX CONCURRENTLY` itself cannot run inside any
transaction; the example is illustrative of the `EXCEPTION` block
pattern.  Real `CONCURRENTLY` work needs `transactional = False`.)

**Implication for authors:** `EXCEPTION WHEN` handlers, including the
`IF EXISTS` / `IF NOT EXISTS` idioms inside `DO` blocks, are safe under
all three execution modes.

---

## 5. Calling `COMMIT` / `ROLLBACK` breaks the envelope

A migration body that issues a bare `COMMIT` or `ROLLBACK` ends
confiture's wrapping transaction and invalidates every active
savepoint.  Under `--dry-run-execute` or `preflight --against` the
subsequent `ROLLBACK TO SAVEPOINT` will fail with
`savepoint "dry_run_execute" does not exist` (or the preflight
equivalent).

The supported escape hatch is to declare the migration
non-transactional:

```python
class CreateIndexConcurrently(Migration):
    version = "20260528121500"
    name = "create_index_concurrently"
    transactional = False  # required for CONCURRENTLY, VACUUM, REINDEX

    def up(self) -> None:
        self.execute("CREATE INDEX CONCURRENTLY idx_users_email ON users(email)")
```

Non-transactional migrations:

- Are skipped under `--dry-run-execute` (no savepoint envelope can
  contain them).
- Are skipped by default under `preflight --against`; pass
  `allow_non_transactional=True` to run them — the preflight database
  is then **consumed** (committed DDL cannot be rolled back) and must
  be reprovisioned before the next run.
- Have no automatic rollback on failure under regular `migrate up` —
  manual cleanup may be required.

**Implication for authors:** if you need `CONCURRENTLY`, `VACUUM`,
`REINDEX CONCURRENTLY`, or another statement that PostgreSQL forbids
inside a transaction, set `transactional = False` on the migration
class.  Never call `COMMIT` or `ROLLBACK` from inside a transactional
migration body.

---

## Cheat sheet

| You want to … | How |
|---------------|-----|
| Group inserts/updates under a sub-rollback | `with self.connection.transaction(): …` |
| Run `IF EXISTS`-style conditional DDL | `DO $$ … EXCEPTION WHEN … END $$` |
| Run `CREATE INDEX CONCURRENTLY` | `transactional = False` |
| Run `VACUUM` / `REINDEX CONCURRENTLY` | `transactional = False` |
| Test the migration without persisting | `migrate up --dry-run-execute` |
| Test against a parallel database | `migrate preflight --against <db>` |

---

## See Also

- [Dry-Run Guide](../guides/dry-run.md) — when to use which mode
- [Incremental Migrations](../guides/02-incremental-migrations.md) — full migration authoring guide
- [Hooks](../guides/hooks.md) — lifecycle hooks that wrap migration execution
- `tests/integration/test_savepoint_contract.py` — executable form of this contract
