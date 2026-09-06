# Test suite

## Layers

| Directory | What it needs |
|---|---|
| `tests/unit` | nothing — no database, no network |
| `tests/integration`, `tests/e2e`, `tests/contract` | a PostgreSQL server (see below) |
| `tests/performance` | the same server, plus the sync source/target pair; wall-clock assertions |

## Markers

Every test carries exactly one **layer** marker, assigned from its directory by
`tests/conftest.py`: `unit`, `integration`, `e2e`, `performance`, `contract`. Do not add
them by hand; `-m integration` selects the whole layer. Two orthogonal markers exist:

* `benchmark` — the test asserts an upper bound on a measured duration. Such tests pass or
  fail with the load on the machine, so `addopts` excludes them (`-m "not benchmark"`) and
  the performance workflow runs them (`pytest tests -m benchmark`). Every duration upper
  bound must sit in a `benchmark`-marked test (`tests/unit/test_markers.py` checks); a
  lower bound (`elapsed >= timeout`) is fine anywhere.
* `slow` — long-running; informational.

## Where the database comes from

Every database test reaches its server through `tests/conftest.py`; no test module
carries a connection string (`tests/unit/test_no_literal_dsn.py` enforces it, with a
short allowlist of sentinel URLs written into config files that are never dialled).

```
CONFITURE_TEST_DB_URL         default postgresql://localhost/confiture_test
CONFITURE_SOURCE_DB_URL       default postgresql://localhost/confiture_source_test
CONFITURE_TARGET_DB_URL       default postgresql://localhost/confiture_target_test
```

The rule for a server that cannot be reached:

* the variable is **set** — a failed connection is a **failure**, not a skip. CI sets it;
  a database test cannot skip its way to green there.
* the variable is **unset** — the local default is probed once per session and, if
  unreachable, the test skips with that reason.

Every remaining skip names a missing capability (the pgGit extension, a tmpfs
tablespace, a superuser role), never a missing URL.

Fixtures: `test_db_url`, `test_db_connection`, `clean_test_db` (drops every user schema
and recreates `public`), `maintenance_url` / `maintenance_connection` (same server,
database `postgres`), `fresh_database` / `fresh_database_factory` (throwaway databases,
dropped after the test), `superuser_db_url`, `drop_roles`.

## Running in parallel

```
uv run pytest tests/unit -n auto
uv run pytest tests/integration tests/e2e tests/contract -n 4
```

Under pytest-xdist every worker gets its own databases: `confiture_test` becomes
`confiture_test_gw0` for worker `gw0` (resolved through
`confiture.testing.worker_db.resolve_worker_db_url`, created on first use and left in
place for the next run). Two workers therefore never share a ledger, an advisory lock or a
`DROP SCHEMA`. `--dist=loadfile` (in `addopts`) keeps a module's tests on one worker, so
the fixed role names some modules create — roles are server-global — cannot race.

When a test derives another database's URL, use `maintenance_url` or
`database_url_for(url, name)`; a string replace on the database *name* breaks under the
worker suffix.

CI runs the database suites both serially (the `Tests` job, with coverage) and with
`-n 4` (the `Integration (parallel, -n 4)` job).

## Test doubles

`Migrator`, `MigratorSession` and `SchemaBuilder` are never patched with a bare mock:
every `patch("….Migrator")` carries `autospec=True` (or a `spec`), and stand-in
instances come from `tests/unit/_doubles.py` (`migrator_double()`, `session_double()`,
`builder_double()`), which are autospecced and pre-populate the constructor-set
attributes. A mock that answers every attribute agrees with any refactor; an
autospecced one fails when a method is renamed. `tests/unit/test_double_discipline.py`
enforces both rules. `tests/_helpers.py` holds `strip_ansi`, used by the CLI tests that
compare Rich output.

Still open: 59 tests patch `confiture.core.connection.create_connection`. Phase 04
gives the CLI an injected connection factory and converts them (Cycle 9).

