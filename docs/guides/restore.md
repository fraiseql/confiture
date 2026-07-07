# Restoring a backup with `confiture restore`

`confiture restore` restores a PostgreSQL `pg_dump` archive using a **three-phase
`pg_restore`** that avoids the foreign-key race conditions a naive parallel
restore hits, and defers materialized-view refreshes until after `ANALYZE` so
they never replan on empty statistics.

It requires a **custom-format (`-Fc`)** or **directory-format (`-Fd`)** archive —
the `--section` machinery it relies on does not work on plain-text SQL dumps.

```bash
pg_dump -Fc mydb > backup.pgdump

confiture restore backup.pgdump --database staging --jobs 4
```

## The phases

| Phase | Parallel | What runs |
|-------|----------|-----------|
| `pre-data`  | no  | Schema DDL, types, sequences, matview *definitions* (`WITH NO DATA`) |
| `data`      | `--jobs` | Table rows (no FK constraints exist yet, so parallel is safe) |
| `post-data` | no  | Indexes, primary keys, FK constraints |

When the archive contains **materialized views**, two more serial steps run:

| Phase | What runs |
|-------|-----------|
| `analyze` | A database-wide `ANALYZE`, so the just-loaded tables have planner statistics |
| `refresh-matviews` | `REFRESH MATERIALIZED VIEW` for every deferred matview — now on real stats |

### Why matviews are deferred

A logical dump never carries planner statistics (`pg_statistic` is not dumped), so
a freshly loaded database starts with **empty stats**. A stats-sensitive matview
(self-joins, window functions, date-segmented views) that refreshes against empty
stats can replan into a catastrophic nested loop — turning a ~5-second refresh
into **tens of minutes to hours**, which then blows past deploy timeouts and can
wedge the whole restore.

`pg_restore` on its own cannot fix this: it never runs `ANALYZE`, and the matview
`REFRESH` is bundled into the archive's data/post-data phases. `confiture restore`
solves it by holding the matview refreshes out of **every** restore phase, running
`ANALYZE`, and only then refreshing — so each refresh sees real statistics.

This is the default. Backups **without** materialized views take the classic
three-phase path unchanged.

## Deferring the refresh to your own schedule

If you would rather restore fast and refresh the matviews later (for example, to
bring an environment online quickly and warm the matviews out of band):

```bash
confiture restore backup.pgdump --database staging --no-refresh-matviews
```

The matviews are restored **`WITH NO DATA`** (unpopulated). Refresh them yourself
once statistics exist:

```sql
ANALYZE;
REFRESH MATERIALIZED VIEW mv_one;
REFRESH MATERIALIZED VIEW mv_two;
```

Querying an unpopulated matview raises
`materialized view "…" has not been populated` until you refresh it.

## Options

| Flag | Default | Purpose |
|------|---------|---------|
| `--database`, `-d` | *(required)* | Target database name |
| `--jobs`, `-j` | `4` | Parallel workers for the data phase |
| `--refresh-matviews` / `--no-refresh-matviews` | refresh | Refresh matviews after `ANALYZE`, or leave them empty |
| `--no-owner` / `--owner` | owner | Skip object ownership restoration |
| `--no-acl` / `--acl` | acl | Skip access-privilege restoration |
| `--exit-on-error` / `--no-exit-on-error` | exit-on-error | Abort on the first error |
| `--min-tables` | `0` | Post-restore: fail unless at least N tables exist |
| `--superuser` | *(none)* | Run `pg_restore`/`psql` via `sudo -u <user>` |

## Backup-side alternative

If you maintain the backups yourself, you can also keep a stats-sensitive matview
out of the archive entirely and refresh it after restore:

```bash
pg_dump -Fc --exclude-table-data=public.mv_maintenance_price mydb > backup.pgdump
```

The matview then restores `WITH NO DATA` regardless of the restore flags; run
`ANALYZE` and `REFRESH MATERIALIZED VIEW` afterwards. `confiture restore`'s default
deferral makes this unnecessary, but it is a useful belt-and-braces option when a
single matview dominates restore time.
