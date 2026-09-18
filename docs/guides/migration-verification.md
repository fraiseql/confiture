# Verifying migrations: what runs where, and where assertions belong

Confiture has three separate questions about a migration, and three separate
commands answering them. Mixing them up is the most expensive mistake this page
can save you, so start here:

| Question | Command | When |
|---|---|---|
| Will this migration apply cleanly? | `migrate preflight --against <dsn>` | Before deploying |
| Did it achieve what it was for? | `migrate verify` | After applying |
| Do my files still match what was applied? | `verify-checksums` | Any time, read-only |

The first two look alike and are not. `migrate preflight` **executes your
`up()`**. `migrate verify` executes your `.verify.sql` sidecars. The difference
determines where an assertion about data can live.

---

## `migrate preflight` runs `up()` against an empty database

`migrate preflight --against <dsn>` replays every pending migration inside a
transaction it always rolls back. The database you point it at is conventionally
a **schema-only** one — confiture's own help says so twice:

```
--against   PostgreSQL URL of the preflight database to test migrations
            against. Typically seeded from pg_dump --schema-only.
```

```bash
# The recommended topology
pg_dump --schema-only "$PROD_URL" | psql "$PREFLIGHT_URL"
confiture migrate preflight --against "$PREFLIGHT_URL"
```

`--against` accepts any DSN, so nothing *enforces* the topology. But it is what
the help recommends, it is what downstream tooling assumes, and it has one
consequence you inherit whether or not anyone told you:

!!! warning "`up()` must survive empty tables"

    On a schema-only database every table has zero rows. A migration whose
    `up()` asserts on data — `SELECT count(*) INTO v; IF v <> 2 THEN RAISE
    EXCEPTION ...` — raises there, every time, no matter how correct the
    migration is. If your deploy is gated on the preflight, that aborts the
    deploy.

This is the obligation the rest of this page is about. It is easy to satisfy
and hard to guess.

### Why it is hard to notice

The failure has a shape that reads like flakiness rather than a defect.

If your preflight database is seeded from the previous day's dump, a migration
shipped on day D is *pending* in day D's dump, replayed by day D+1's preflight,
and already *applied* in day D+2's. So it fails for exactly one night and then
stops, under a different migration's name each time. Two separate nightly
restores can abort, weeks apart, for the same root cause, and look like two
unrelated infrastructure blips.

---

## Where assertions belong: the `.verify.sql` sidecar

Next to each migration, confiture looks for a sidecar named after its version:

```
db/migrations/
├── 20260520143015_add_bio.py
├── 20260520143015_add_bio.verify.sql      ← assertions go here
```

`confiture migrate generate` writes one for you (pass `--no-verify-sidecar` if
you do not want it). The sidecar is run by `confiture migrate verify` —
**separately, after the migration is applied, against the real database** —
inside a `SAVEPOINT` that is rolled back afterwards. It never runs during
`migrate up`, and therefore never during `migrate preflight`.

That is the whole trick: the assertion runs where the data exists, and does not
run where it does not.

### The contract

- Exactly one `SELECT` (or `WITH ... SELECT`). DDL and DML are rejected by
  statement verb, not by regex.
- It must return at least one row, and the first column of the first row must
  be truthy.
- Zero rows, or `false` / `0` / `NULL` in that column, is a failure.
- It runs in a `SAVEPOINT` that is always rolled back, so it cannot have side
  effects even if you get the first rule wrong.

```sql
-- 20260520143015_add_bio.verify.sql
SELECT count(*) = 2 AS ok
  FROM catalog.tb_field
 WHERE identifier IN ('meter_a4_color', 'volume_a4_color');
```

### Rewriting an assertion out of `up()`

Before — fails under `migrate preflight`:

```python
def up(self) -> None:
    self.execute("ALTER TABLE catalog.tb_field ADD COLUMN bio TEXT")
    self.execute("""
        DO $$
        DECLARE v_ok int;
        BEGIN
          SELECT count(*) INTO v_ok FROM catalog.tb_field
           WHERE identifier IN ('meter_a4_color', 'volume_a4_color');
          IF v_ok <> 2 THEN RAISE EXCEPTION 'expected 2 fields, got %', v_ok; END IF;
        END $$;
    """)
```

After — the schema change stays in `up()`, the claim about data moves out:

```python
def up(self) -> None:
    self.execute("ALTER TABLE catalog.tb_field ADD COLUMN bio TEXT")
```

```sql
-- 20260520143015_add_bio.verify.sql
SELECT count(*) = 2 AS ok
  FROM catalog.tb_field
 WHERE identifier IN ('meter_a4_color', 'volume_a4_color');
```

The preflight now passes because `up()` makes no claim about rows. The claim is
still checked — on the database where those rows actually are.

### Running it

```bash
confiture migrate up
confiture migrate verify                       # every applied migration
confiture migrate verify --format json         # for a CI gate
```

A migration with no sidecar is reported `no_file`; one whose sidecar has no
statement in it yet is reported `skipped`. Both count in `skipped_count` and
neither is a failure — so adding sidecars gradually across an existing project
never turns the gate red. Exit 1 means an assertion genuinely failed.

### What does *not* belong in a sidecar

Structural facts. That a column exists, that a constraint is present, that a
function has the signature you expect — `confiture drift`,
`migrate validate --check-live-drift` and the linter already compare your
schema tree against the live database, across every object kind, without you
writing anything. Sidecars are for claims only you can make: *this* data
landed, *these* rows were backfilled, *that* count reconciles.

---

## `verify-checksums`: do my files still match what was applied?

A different question again, and the one most often asked the hard way. It is
read-only — no migrations applied, no ledger writes, no deployment semantics:

```bash
confiture verify-checksums -c db/environments/production.yaml

# Same command; both names are permanent
confiture migrate verify-checksums -c db/environments/production.yaml
```

Exit `0` means every applied migration's file still hashes to what was stored
when it ran. Exit `1` means at least one does not — someone edited applied
history. If the edit was deliberate, `--fix` re-records exactly the migrations
that run reported, in one transaction:

```bash
confiture verify-checksums --fix
```

Do not hand-write an `UPDATE` against the ledger's `checksum` column. See
[the tracking table reference](../reference/tracking-table.md#checksum-mismatches).

!!! danger "`--allow-uninitialized` is not a pass"

    A database with no migration ledger — one built from schema files, say —
    exits `2` unless you pass `--allow-uninitialized`, which makes it exit `0`.
    Such a run compares **nothing**, and says so: `ok: false` with
    `was_skipped: true`.

    Through confiture 1.11.0 that payload said `ok: true`, so a CI gate reading
    `ok` went green on a run that verified zero files. If you gate on
    `verify-checksums --allow-uninitialized` and it has never once failed,
    check what it is pointed at before trusting it.

---

## Putting it in CI

```bash
# Before deploying: will it apply?
pg_dump --schema-only "$PROD_URL" | psql "$PREFLIGHT_URL"
confiture migrate preflight --against "$PREFLIGHT_URL" --format json

# Applied history is intact (against a database that HAS a ledger)
confiture verify-checksums -c db/environments/production.yaml

# Deploy
confiture migrate up -c db/environments/production.yaml

# After deploying: did it do what it was for?
confiture migrate verify -c db/environments/production.yaml
```

The ordering is the point. `preflight` is the only one that runs `up()` against
a database that is not yours, and it is the reason `up()` cannot assert on data.

## See also

- [`migrate validate` guide](migrate-validate.md) — the pre-apply gate and its check flags.
- [Migration decision tree](migration-decision-tree.md) — which of the four mediums to reach for.
- [Tracking table reference](../reference/tracking-table.md) — the ledger, and checksum mismatches.
- [CLI reference](../reference/cli.md#confiture-migrate-verify-runtime-correctness) — every flag on these commands.
