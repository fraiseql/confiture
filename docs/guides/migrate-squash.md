# Squashing old migrations

A long-lived project keeps every migration it ever wrote. Replaying that history on a
fresh database gets slower, and more fragile, as it grows: an old migration names an
object a later one renamed, and one that reads a schema file by path installs today's
file rather than the body it shipped with. `confiture migrate squash` replaces every
migration up to a version with **one baseline**, the schema they build, and keeps
each environment's ledger history.

```bash
confiture migrate squash --through 20260301000000 --dry-run   # see the plan
confiture migrate squash --through 20260301000000             # write it
git add db/migrations && git commit -m "chore(migrations): squash through 20260301000000"
```

Then deploy as usual. `confiture migrate up` knows what to do with the baseline on
each database.

## What the squash writes

Run it in the repository with a local `--config`: its `database_url`'s server holds
the scratch database.

1. **It asks every environment first.** For each `db/environments/*.yaml`, it reads
   the ledger: every squashed migration must be applied there, the cut must have been
   applied at least `squash.min_age_days` ago, and no online (expand/contract)
   migration up to the cut may be unfinished. Otherwise it refuses with `VALID_009`,
   naming each environment and why. An environment it cannot reach refuses too,
   unless it is listed in `squash.skip_environments`:

    ```yaml
    # db/project.yaml
    squash:
      min_age_days: 90          # default; 0 turns the age check off
      skip_environments: [ci]   # environments not reachable from where you squash
    ```

   The age matters because of backups. A restore from a backup taken before the cut
   was applied would need the squashed migrations to catch up, and they are gone.

2. **It builds the baseline.** The migrations up to `--through` replay into a scratch
   database, and its schema is dumped: extensions included, confiture's own tables
   (ledger, steps, lock holder) left out. With `--from-build`, the baseline is your
   tree instead (what `confiture build` produces for the config's environment), once a
   drift check between it and the replayed database comes back empty. Otherwise it
   refuses with `VALID_006` and lists the differences.

3. **It writes one migration.** `<version>_squashed_baseline.up.sql` holds the SQL,
   embedded, under a header naming what it replaced:

    ```sql
    -- confiture:squashed-baseline through=20260301000000 versions=214 digest=3f9c…
    ```

   Its version is the one right after `--through` (one second later for a timestamp,
   plus one for a number). When that version is taken, pass `--version` with one that
   sorts after `--through` and before every later migration (`VALID_007`). Its
   `.down.sql` refuses: the history before the baseline is archived, so there is
   nothing to roll back to.

4. **It archives what it replaced.** Every file of the squashed versions (`.py`,
   `.up.sql`, `.down.sql`, `.verify.sql`) moves to `db/migrations/archive/`, which
   discovery does not read. With `--delete`, they are deleted instead; git still
   has them.

## What each database does with it

`migrate up` meets the baseline as a pending migration, under the migration lock, and
the database's ledger decides:

| The ledger holds | `migrate up` |
|---|---|
| nothing (a fresh database) | applies the baseline, then what came after it |
| every squashed version, with the checksums the baseline's digest was made from | **records the baseline without running it**, marks those rows `archived_into`, in one transaction, then applies what came after |
| part of the history, or a checksum that differs (a file edited after it was applied) | refuses with `VALID_008`, before changing anything |

An archived row keeps its `applied_at`, checksum and `applied_by`. It is history:
never pending, never checked against a file (`verify-checksums` stays green), never
rolled back. See the [tracking table reference](../reference/tracking-table.md).

`confiture migrate squash-ledger` does only the recording step, and applies nothing
else. Use it to move an environment's ledger ahead of a deploy.

## A database that fell behind

`VALID_008` means the database applied some of the squashed migrations but not all.
The squash's own check (`VALID_009`) exists to catch this before the cut, for every
environment it can reach. If it happens anyway (an environment in
`skip_environments`, a restore from an old backup), bring the database up to the cut
with the archived files, then deploy:

```bash
cp db/migrations/archive/* /tmp/catch-up/
confiture migrate up --migrations-dir /tmp/catch-up --config db/environments/staging.yaml
confiture migrate up --config db/environments/staging.yaml   # records the baseline
```

## Squashing again

A later squash can include an earlier baseline: the baseline is a migration like any
other. Its ledger row becomes `archived_into` the new baseline, and the rows already
archived keep pointing at the first one.

## Related

- [`migrate validate --check-path-reads`](./migrate-validate.md#-check-path-reads) keeps
  new migrations from reading schema files by path, which is what makes old ones
  worth squashing.
- [`generate renumber`](../reference/cli.md#confiture-generate-renumber) never moves a
  file a migration reads (`VALID_003`). Once the squash archives that migration, the
  file is free to move.
