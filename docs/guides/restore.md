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

## Library use, and the children's environment

`confiture restore` is `DatabaseRestorer` over `RestoreOptions`. Every step runs a
child process — the `pg_restore -l` listing, the three `pg_restore` phases, the
`psql` `ANALYZE` and the matview refresh — and by default each inherits the
caller's environment: `PGSERVICE`, `PGOPTIONS`, `PGUSER`, `PGSSLMODE` or a stray
`PGPASSWORD` in it reaches every one. The CLI keeps that behaviour, so `~/.pgpass`
and an operator's `PG*` variables still apply.

A tool that calls confiture as a library and wants the restore to reach exactly
the target it named passes `env`, the **whole** environment of every child:

```python
import os
from pathlib import Path

from confiture.core.restorer import DatabaseRestorer, RestoreOptions

opts = RestoreOptions(
    backup_path=Path("prod.pgdump"),
    target_db="staging",
    host="db.internal",
    username="restorer",
    password=secret,                  # laid on top of env as PGPASSWORD
    env={
        "PATH": "/usr/lib/postgresql/18/bin:/usr/bin",   # where pg_restore and psql are found
        "PGSSLMODE": "verify-full",
        "PGSSLROOTCERT": "/etc/ssl/db-ca.pem",
    },
    min_tables=300,
)
result = DatabaseRestorer().restore(opts)
```

- `pg_restore` and `psql` are looked up on `env`'s `PATH`; when they are not
  there, the restore fails with a `RestoreError` naming the binary.
- The `--min-tables` check connects in-process, so it cannot be handed an
  environment. It is given every libpq key instead, read from `env` or libpq's
  default: `options` is empty whatever `PGOPTIONS` the process holds, and the
  role is `username`, then `env["PGUSER"]`, then the OS user. Five keys refuse an
  empty value (`service`, `sslcertmode`, `min_protocol_version`,
  `max_protocol_version`, `connect_timeout`) and are passed only when `env` sets
  them; an ambient `PGSERVICE` can still name a service there, which fills only
  keys left unset — never the host, port, database, role, password or options.
- `env` cannot be combined with `superuser`: `sudo`'s `env_reset` decides what
  reaches its command (by default it drops every `PG*` variable), and
  `sudo --preserve-env` is refused under a command-scoped sudoers rule. The
  combination is refused before anything starts.

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
