# Parallel, cacheable CI provisioning

Three confiture capabilities turn the slow, serial "apply the schema on every CI
run" step into a cached, parallel one. They compose, but each is useful alone:

| Capability | What it gives you | Command / API |
|---|---|---|
| **Cacheable artifact** | A content-addressed `pg_dump -Fc` of a fully-built DB, cached by `db/` hash | `confiture build --dump` + `confiture restore` |
| **Template / clone primitive** | Build a template once, hand out lock-free per-worker clones | `confiture test-db …` |
| **Per-worker fixtures** | Each pytest-xdist worker gets its own isolated database | `confiture.testing` fixtures |
| **Slim seed profile** | Apply a lean subset of seeds for fast, RAM-cheap clones | `seed.profiles.<name>` |

> This is a **CI-path** capability — developer/CI tooling. It is independent of
> the confiture-at-deploy-time path (the fraisier adapter contract is unaffected).

---

## 1. Cacheable build artifacts

`confiture build --dump` builds your schema (and seeds) into an **ephemeral
throwaway database**, then `pg_dump -Fc`s it to a content-addressed file:

```bash
confiture build --env test --database-url "$PG_SERVER_URL" \
  --dump db/generated/            # a directory → auto-named by hash
# → db/generated/schema_test.full.ab12cd34ef56.pgdump
```

Because the dump comes from a freshly-built ephemeral DB (not a live database
that may have drifted), the artifact's content always matches the `db/` hash in
its name. An unchanged `db/` resolves to the same filename — so the dump is a
**no-op cache hit**, and Dagger/BuildKit caches the whole step by `db/` hash
instead of treating schema-apply as an uncacheable live-DB side effect.

Restore it — in parallel — with the three-phase restorer:

```bash
createdb app_ci   # pg_restore needs the target to exist
confiture restore db/generated/schema_test.full.ab12cd34ef56.pgdump \
  --database app_ci --jobs 8 --no-owner --no-acl
```

Use `--dump-format directory` for `-Fd` (parallel *dump* as well as restore).

> **Version skew:** a `-Fc`/`-Fd` archive produced by a newer `pg_dump` will not
> restore under an older `pg_restore`. Build and restore the artifact with
> **matching** PostgreSQL client major versions (pin the same client image in CI).

---

## 2. The `test-db` primitive

Build a template once, then clone it per worker:

```bash
# Build (or refresh) the template from db/schema (+ seeds), stamping the db/ hash.
confiture test-db provision-template --env test --template app_tmpl
#   …or restore a P1 artifact instead of applying DDL:
confiture test-db provision-template --template app_tmpl \
  --from-artifact db/generated/schema_test.full.ab12cd34ef56.pgdump

# Is the template still current? exit 0 = current, 1 = stale/absent.
confiture test-db status --env test --template app_tmpl || \
  confiture test-db provision-template --env test --template app_tmpl

confiture test-db clone --template app_tmpl --target app_gw0   # ~1s
confiture test-db drop  --target app_gw0
confiture test-db prune --template app_tmpl    # reap clones leaked by crashed workers
confiture test-db list                         # all confiture-managed DBs
```

Staleness is stored as a `COMMENT ON DATABASE` on the template and read
connection-free from the maintenance database, so `status` never connects to the
template and never races a concurrent clone. The same comment marks
confiture-managed databases, so `drop` refuses to remove a database it did not
create (pass `--force` to override).

---

## 3. Per-worker pytest-xdist fixtures

> ⚠️ **The import-order seam — read this first.** An xdist worker resolves its
> database name from `PYTEST_XDIST_WORKER`, but a *fixture* runs at test time —
> **too late** for an application that freezes a `Settings()` / connection-pool
> singleton at *module import*. If your app does that, the supported integration
> is the **import-time helper**, called from `conftest.py` before the app is
> imported:

```python
# conftest.py — runs before your app package is imported
import os
from confiture.testing.worker_db import resolve_worker_db_url

os.environ["DATABASE_URL"] = resolve_worker_db_url(os.environ["DATABASE_URL"])
# only now import anything that reads DATABASE_URL into a frozen singleton
```

For apps that read their URL lazily, the fixtures are convenience. Point them at
your project and override the defaults as needed:

```python
# conftest.py
import pytest
from pathlib import Path

@pytest.fixture(scope="session")
def confiture_project_dir():
    return Path(__file__).parent

@pytest.fixture(scope="session")
def confiture_template_name():
    return "app_tmpl"

def test_widgets(confiture_worker_db):          # yields this worker's DB URL
    import psycopg
    with psycopg.connect(confiture_worker_db) as conn:
        ...
```

`confiture_template_db` builds the shared template exactly once even under
`-n N` (single-flight via a PostgreSQL advisory lock); `confiture_worker_db`
clones `{template}_db_gwN` for the running worker and drops it on teardown.

Run it: `pytest -n auto` (requires the `[testing]` extra, which pulls in
`pytest-xdist`).

---

## 4. Slim seed profiles

A 1 GB ETL-statistics seed inflates apply time, clone time, and per-worker RAM
(`6 × 1.3 GB ≈ 8 GB` caps your `-n`). Declare a lean subset in env config:

```yaml
# db/environments/test.yaml
seed:
  execution_mode: sequential
  profiles:
    slim:
      exclude:
        - "stats_*.sql"      # skip the heavy ETL-statistics partitions
    core:
      include:
        - "core_*.sql"       # only the reference data
```

```bash
confiture seed apply --sequential --env test --profile slim
confiture build --sequential --env test --seed-profile slim --dump db/generated/
confiture test-db provision-template --env test --template app_tmpl --seed-profile slim
```

Profile globs match seed **filenames** (discovery is top-level, non-recursive).
An absent profile keeps today's apply-all behaviour; an unknown name exits 5
listing the defined profiles. The artifact filename carries the profile segment
(`schema_test.slim.<hash>.pgdump`) so slim and full dumps never collide.

> Tip: run a **slim** seed for the fast parallel unit/integration lanes and the
> **full** seed for the stat/dashboard suites — a seed-by-tier split.

---

## 5. RAM tablespace for fast clones

Two independent costs dominate per-worker provisioning, and you need to fix
**both** — one without the other "leaves a wall":

- **The commit cost.** Every transaction in the cloned DB pays an `fsync` wait on
  a developer's `fsync=on` cluster. confiture sets `synchronous_commit = off` as a
  **per-database** default on every clone (opt out with `clone --no-sync-commit-off`).
  This is a per-database GUC — it touches only sessions connecting to that throwaway
  clone, never other databases on a shared cluster — so it is safe where a
  cluster-wide `fsync=off` is not.
- **The clone cost.** `CREATE DATABASE … WITH TEMPLATE` copies the template's files.
  On a ~1 GB+ template that is ~15–20 s on disk; from a **tmpfs** (RAM) tablespace
  it drops to ~3–5 s. The template stays on disk (it is the durable, rebuilt-on-hash
  source and survives a reboot); only the throwaway **clones** go to RAM.

> One anonymized real suite: **~355 s** single-process → **~130 s** at `-n6` with a
> RAM tablespace (~2.7×). Illustrative, not a benchmark — your numbers depend on
> template size, core count, and disk.

### `confiture test-db ram-setup`

Create (or idempotently reset) a tmpfs tablespace once per host:

```bash
confiture test-db ram-setup --tablespace ram_test --location /dev/shm/ram_test
```

It runs in one of **two auto-selected modes**:

- **Self-service** — confiture can create and `chown` the LOCATION dir to the PG
  server's OS user (it *is* that user, or has the rights). It does so, then
  `CREATE TABLESPACE`.
- **Guided** — confiture is a client and lacks the rights (PG runs as another
  user, or is remote). It does **not** fail silently: it prints the exact
  privileged command and exits `5` with `action_required` so a script can detect
  "human step needed":

  ```bash
  sudo install -d -o postgres -g postgres -m 700 /dev/shm/ram_test
  # …then re-run the ram-setup command above.
  ```

`ram-setup` is a **reset**: it drops the databases living in the tablespace (only
**confiture-managed** clones unless `--force`), drops and re-creates the
tablespace, and verifies it is usable. It refuses a LOCATION outside `/dev/shm`
or `/run` without `--force` — a guard against a fat-fingered real path becoming a
dropped tablespace.

### Wiring it into the fixtures

Point the fixtures at the tablespace with one environment variable:

```bash
export CONFITURE_TEST_RAM_TABLESPACE=ram_test
pytest -n auto
```

`confiture_worker_db` then asks for each clone in `ram_test`. When the variable is
unset, clones go to disk exactly as before — **zero-config behaviour is unchanged.**

### Three gotchas this bakes in

1. **Post-reboot tmpfs.** `/dev/shm` is cleared on boot: the `pg_tablespace` row
   and the data-dir symlink survive, but the inner `PG_<version>` directory is
   gone, so a clone fails with *"could not create directory … No such file or
   directory."* Re-creating the empty dir is **not** enough — `ram-setup` does a
   **DROP + re-CREATE** (after dropping the DBs inside), which re-runs PostgreSQL's
   tablespace initialisation. Run it once on every boot before the suite.
2. **The probe can't promise success.** `tablespace_usable()` is a cheap *gate*,
   not a guarantee — a post-reboot-broken tablespace still passes it. (It uses
   `(pg_stat_file(loc, true)).size IS NOT NULL`, because the naive
   `record IS NOT NULL` reads false for an existing dir on Linux.) The real safety
   net is the next point.
3. **The disk fallback, not `pytest.exit()`.** On *any* tablespace failure
   `clone()` falls back **once** to an on-disk clone (logging a WARNING) — so a
   misconfigured or post-reboot tablespace silently degrades instead of breaking
   the suite. The fixtures never call `pytest.exit()` inside a worker (it surfaces
   as an opaque `INTERNALERROR` attributed to a random test); `pytest.skip` stays
   reserved for total DB-unavailability.

### Recommended recipe: CI vs. local

| | Template | Clones |
|---|---|---|
| **CI** | pre-provisioned via `--from-artifact` | **on-disk** — runners rarely have a useful tmpfs, and the PG service image owns its own tablespace config |
| **Local** | built from DDL | **RAM** — `ram-setup` once, then `CONFITURE_TEST_RAM_TABLESPACE=ram_test` |

CI detection is advisory: `confiture.testing.worker_db.is_ci()` (and the
`confiture_ci` fixture) let a consumer's conftest choose `--from-artifact` and
skip the RAM tablespace in CI. `ensure_template` is already idempotent and
single-flight, so the template path does not need divergent CI-vs-local code.

---

## Putting it together (Dagger / GitHub Actions)

```python
# A two-lane CI: build the artifact once (cached by db/ hash), restore per lane.
SERVER = "postgresql://postgres@db:5432/postgres"

# 1) Build the cached artifact — a no-op when db/ is unchanged.
build = base.with_exec([
    "confiture", "build", "--env", "test", "--database-url", SERVER,
    "--seed-profile", "slim", "--dump", "db/generated/",
])

# 2) Parallel lane: provision a template from the artifact, then `pytest -n auto`
#    (the fixtures clone one DB per worker).
parallel = build.with_exec([
    "confiture", "test-db", "provision-template", "--env", "test",
    "--template", "app_tmpl", "--from-artifact", ARTIFACT,
]).with_exec(["pytest", "-n", "auto"])
```

### Server tuning (your responsibility, not confiture's)

For the *ephemeral CI* PostgreSQL only, these unsafe-but-fast **cluster-wide**
settings make template builds and clones cheaper. confiture **documents** them; it
never sets them — they are PostgreSQL server configuration:

```
fsync = off
synchronous_commit = off
full_page_writes = off
```

Never use these on a database whose data you care about.

> Note: confiture *does* set `synchronous_commit = off` as a **per-database**
> default on each clone (§5) — that is safe on a shared cluster because it touches
> only the throwaway clone. The cluster-wide `synchronous_commit`/`fsync` above are
> a different, blunter knob that only makes sense on a disposable CI server.

---

## See also

- [`confiture restore`](../reference/cli.md) — the three-phase parallel restorer
- [Build from DDL](./01-build-from-ddl.md) — Medium 1
- [Prep-seed validation](./prep-seed-validation.md)
