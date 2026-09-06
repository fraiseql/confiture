# `migrate validate`

`confiture migrate validate` runs a battery of checks over your pending
migrations and exits non-zero if anything is wrong. This guide covers the
checks the command performs, the flags that toggle each, and what the
output means.

## Quick reference

```bash
# Naming convention (always on)
confiture migrate validate

# Idempotency: every CREATE / ALTER / DROP can safely re-run
confiture migrate validate --idempotent

# Same, but also fail on info-severity CREATE OR REPLACE shape-risk notes
confiture migrate validate --idempotent --strict-cor

# Auto-rewrite SQL where a safe idempotent form exists.
# Python migrations are detected but never rewritten — they're listed
# under "manual_fix_required" so you know to edit them by hand.
confiture migrate fix --idempotent

# Verify changed grants are carried by an accompanying migration
confiture migrate validate --require-grant-migration --staged

# Compose: every check you pass runs, and all of them report
confiture migrate validate --check-acls --check-imports --check-ownership-coverage
```

JSON output is available with `--format json` for every variant.

## Checks compose (0.40.0)

Pass as many checks as you like — **all of them run** and the exit code is the
worst outcome across them.

Until 0.40.0 this was not true. The command was a flat chain of
`if <flag>: … return` blocks evaluated in source order, so
`--check-acls --check-imports` ran only the ACL check and exited 0. In a
pre-commit hook or a CI gate that is a silent false pass: a green result for a
check that never executed. #187 replaced the chain with a registry of check
descriptors that the runner executes in full.

What this means in practice:

- **One invocation, one connection.** Checks that need a database share it (and
  share one SSH tunnel), and the config is parsed once. Splitting a gate across
  two invocations to work around the old behaviour is no longer necessary — and
  costs you a second connection.
- **One JSON document.** A single check emits exactly the payload it always did.
  Two or more are wrapped in a small envelope keyed by check name — see
  [migrate-validate-composed.schema.json](../reference/json-schemas/migrate-validate-composed.schema.json).
- **Order is unchanged.** Checks run in the order the old dispatch listed them,
  so single-flag output is byte-for-byte what 0.39.0 produced.

One combination is rejected loudly instead of composed:

| Combination | Exit | Why |
|---|---|---|
| `--list-patterns` or `--list-unmigrated-bodies` with anything else | 5 | Report modes. Both always exit 0, so there is no result to compose into a gate decision. |

`--idempotent` composes with the git checks **from 0.41.0**. It was rejected
alongside `--check-drift` / `--require-migration` / `--require-migration-bodies`
/ `--require-grant-migration` in 0.37.0 through 0.40.0: the pre-composition
dispatch ran the git branch and silently skipped idempotency, so a loud error
was the only honest answer (#181). Composition landed in 0.40.0 and the guard
was held one release past it so the refactor got production exposure before its
safety net came off. Both checks now run and the exit code is the worse of the
two.

## `--idempotent`

A migration is **idempotent** when applying it more than once leaves the
schema in the same state without raising an error. Confiture flags SQL
patterns that are not idempotent by default — `CREATE TABLE foo (…)`,
`CREATE INDEX idx_x …`, `ALTER TABLE foo ADD COLUMN bar …`, and so on —
and suggests the idempotent rewrite (typically the `IF [NOT] EXISTS`
variant or a `DO` block guard).

### Pattern coverage

The detector recognizes:

| Statement shape | Suggested fix | Auto-fix? |
|---|---|---|
| `CREATE TABLE / INDEX / EXTENSION / SCHEMA / SEQUENCE` | `IF NOT EXISTS` | ✅ |
| `CREATE FUNCTION / PROCEDURE / VIEW` | `OR REPLACE` (or `DROP IF EXISTS` + `CREATE` for shape changes) | ✅ |
| `CREATE TYPE` | DO block with `pg_type` check | ❌ |
| `ALTER TABLE … ADD COLUMN` | `ADD COLUMN IF NOT EXISTS` | ✅ |
| `DROP TABLE / INDEX / FUNCTION / VIEW / TYPE / SCHEMA / SEQUENCE` | `IF EXISTS` | ✅ |
| `ALTER TABLE … ADD CONSTRAINT … CHECK / PRIMARY KEY / UNIQUE` | `DROP CONSTRAINT IF EXISTS` + `ADD` (or DO block guarded by `pg_constraint`) | ❌ (state-dependent) |
| `ALTER TABLE … RENAME COLUMN` | DO block guarded by `information_schema.columns` lookups | ❌ (state-dependent) |
| `ALTER (TABLE\|VIEW\|MATERIALIZED VIEW) … OWNER TO` | DO block with `pg_class` / `pg_matviews` existence check | ❌ |

`DROP CONSTRAINT IF EXISTS <name>; ALTER TABLE … ADD CONSTRAINT <name> …`
is recognized as already-idempotent and not flagged (matches the existing
`DROP VIEW IF EXISTS` + `CREATE VIEW` recognizer).

### AST-backed detector (default in 0.14.0)

Starting in 0.14.0 the detector uses PostgreSQL's own parser (via
[pglast](https://github.com/lelit/pglast)) to recognize statements
structurally instead of via regex. The cutover closes four cases the
regex backend mishandled or missed:

- **`ADD COLUMN IF NOT EXISTS` on a schema-qualified table** — previously
  reported a phantom `ALTER_TABLE_ADD_COLUMN` violation (issue #122 Bug 1).
- **Long constraint / view / function names in `DROP IF EXISTS` + `CREATE`
  pairs** — previously the pair recognizer truncated the name, so the
  pair wasn't recognized as idempotent (issue #122 Bug 2).
- **Quoted identifiers** (`"My-Table"`, `"chk-x"`) — previously slipped
  through every regex pattern because `\w+` doesn't match `-`.
- **Multi-clause `ALTER`** — `ALTER TABLE foo ADD CONSTRAINT a …, ADD
  CONSTRAINT b …` now flags both clauses (regex only saw the first).

The detector also recognizes cross-snippet DROP+CREATE pairs in
``.py`` migrations: a `DROP VIEW IF EXISTS v;` in one `self.execute()`
followed by `CREATE VIEW v …` in the next is now treated as the
idempotent DROP+CREATE pattern (pre-0.14.0 the second call was flagged).

`pglast` is a dependency since 0.50.0, so every install runs the AST
detector. The regex backend still exists as an escape hatch for one
release: set `CONFITURE_IDEMPOTENCY_FORCE_REGEX=1` to pin the dispatcher
to it if you hit an AST regression. The env var is removed with the
backend.

```bash
# Pin to regex (one-release escape hatch)
CONFITURE_IDEMPOTENCY_FORCE_REGEX=1 confiture migrate validate --idempotent
```

### Three signal types

The report uses three distinct words. Keep them straight:

- **Violation (error)** — a SQL pattern that is not idempotent and will
  fail re-application. Fails the gate (`has_blocking_violations: true`).
- **Violation (info)** — a heuristic note, currently only emitted for
  `CREATE OR REPLACE VIEW/FUNCTION/PROCEDURE` not preceded by a matching
  `DROP … IF EXISTS`. Does *not* fail the gate by default. Render-only.
  Promote to a gate failure with `--strict-cor`.
- **Warning** — an *extractor*-level signal that a `.py` file's
  `execute`/`execute_file` call could not be statically read (an f-string
  over a loop variable, a parameter, a missing file). Each one states the
  reason and a remedy. The verdict counts them (`⚠️ N call(s) unverified`,
  `status: "unverified"`); the gate fails on them only with
  `--fail-on-unanalyzable`.

### `--strict-cor`

`CREATE OR REPLACE VIEW v_users AS SELECT …;` works fine until you drop
a column from the view's projection — then Postgres raises
"cannot drop columns from view." Same shape for
`CREATE OR REPLACE FUNCTION` with renamed parameters: "cannot change
name of input parameter." The safe alternative is
`DROP VIEW IF EXISTS v_users; CREATE VIEW v_users AS …;` (which loses
privileges and dependencies — there are tradeoffs).

Confiture can't statically know whether a given `CREATE OR REPLACE` is
about to fail. Instead, it emits an **info-severity** note suggesting
the safer form. The note is rendered in both human and JSON output and
*does not fail the gate*. If you want to enforce the safer form in CI,
pass `--strict-cor`:

```bash
# Default: render info-severity notes but exit 0
confiture migrate validate --idempotent

# Strict: info-severity findings also fail the gate
confiture migrate validate --idempotent --strict-cor
```

Adding a preceding `DROP <KIND> IF EXISTS <name>` for the same object
silences the note — that's the explicit "I've thought about this"
signal.

### `--fail-on-unanalyzable`

*New in 0.46.0 (#213).* A call the analyzer could not read is not a pass, and
the verdict says so (`⚠️ … unverified`, `status: "unverified"`), but by
default it does not change the exit code — a green CI that holds dynamic SQL
stays green. A gate that wants "could not check" to be fatal opts in:

```bash
# Pre-merge gate: new migrations must be readable AND idempotent
confiture migrate validate --idempotent --base-ref origin/main --fail-on-unanalyzable
```

With the flag, a run with an unverified call exits **1** (the existing
findings class; a distinct exit code is parked, not refused) and the headline
is `❌`. `meta.fail_on_unanalyzable` in the JSON payload records that the flag
was on, so a reader can tell "unverified, exit 1" from "unverified, exit 0"
without the command line. Pair it with `--base-ref` or `--staged`: an
existing backlog of genuinely dynamic migrations would otherwise fail every
run. An empty scope is still a pass — the flag fails on files it could not
read, not on having none to read. It requires `--idempotent`; alone it is a
configuration error (exit 5).

### Closing the transitive-dependent gap with `migrate preflight --check-dependents`

The `CREATE OR REPLACE` info-severity note above is purely static: it
flags any bare CoR statement, but can't tell you *which* of the
object's live dependents are about to break.

`confiture migrate preflight --against <url> --check-dependents` closes
that gap. Against a live preflight DB, it enumerates the views,
matviews, and functions that depend on each `CREATE OR REPLACE` target
in the pending migrations (via `pg_depend`).

```bash
# Fail the gate if any CoR target has live dependents
confiture migrate preflight --against postgresql://localhost/preflight \
  --check-dependents fail

# Render dependents informationally; exit code unaffected
confiture migrate preflight --against postgresql://localhost/preflight \
  --check-dependents warn

# Off by default — no behavior change unless you opt in
confiture migrate preflight --against postgresql://localhost/preflight
```

When `--check-dependents` is on without `--against`, the check prints a
loud skip message and exits 0 (it's deliberately not silent — the
absence of a preflight DB is something you should see). When `--against`
is set but the live DB connection fails, the report status flips to
`skipped` with a `connection_failed` reason.

`--check-dependents` parses the migrations with `pglast`, a dependency
since 0.50.0.

**Object types covered**: views, materialized views, functions, and
procedures referenced by CoR statements. Tables, composite types, and
trigger functions are out of scope for now. The check enumerates
dependents — it does not predict which will actually break. Use the
list as a checklist for manual review.

JSON output adds a top-level `dependent_analysis` entry:

```json
{
  "dependent_analysis": {
    "status": "ok",
    "has_blocking": true,
    "entries": [
      {
        "kind": "view",
        "qualified": "public.v_users",
        "source_file": "db/migrations/001_cor.up.sql",
        "source_line": null,
        "severity": "error",
        "dependents": [
          {
            "kind": "view",
            "schema": "public",
            "name": "v_active_users",
            "referenced_columns": ["email", "id"]
          }
        ]
      }
    ]
  }
}
```

### What gets scanned

- Every `*.up.sql` file in the migrations directory.
- Every Python migration (`*.py` whose stem starts with a digit, e.g.
  `20260101000000_add_users.py`). Inline `self.execute("…")` and
  `self.execute_file("path/to.sql")` calls are extracted statically with
  the stdlib `ast` module and run through the same validator.

Files starting with `_` (e.g. `__init__.py`, `_helpers.py`) and files
without a digit prefix are skipped — they aren't migrations under the
Confiture naming convention.

### Python-migration support

Confiture statically evaluates what each `self.execute(...)` and
`self.execute_file(...)` call receives, without importing or executing the
migration. *Since 0.46.0* (#213) the evaluator reads every form that is a
pure function of the migration file's own text:

- **Literals**, static f-strings, and `+` concatenation:
  `self.execute("CREATE TABLE IF NOT EXISTS foo (id int);")`
- **Names bound once** in the scope that reads them, by a plain top-level
  assignment — a module constant (`DDL = "…"`; annotated `DDL: Final = "…"`;
  defined above or below the class), a single-assignment local inside `up()`,
  or a class attribute read through `self.NAME`. Constants may be built from
  other constants.
- **Path arithmetic from `__file__`**: `Path(__file__).resolve().parent.parent
  / "schema" / "fn.sql"`, `pathlib.Path(...)`, `.parents[N]`, `.joinpath(...)`,
  `.resolve()` / `.absolute()`.
- **File reads**: `self.execute_file(<path>)` and `self.execute(<path>.read_text())`
  for any path expression above. Relative paths resolve against the **project
  root**, then the migration's own directory, then the working directory — the
  same order the runtime's `execute_file` uses, so the gate reads the file the
  deploy will run, from any cwd. A path that resolves outside the project root
  is refused, never read (`execute_file_escaped`).
- **Pure string operations** on static inputs: `.replace()`, `.strip()` /
  `.lstrip()` / `.rstrip()`, `.upper()` / `.lower()`, `.format()` with static
  arguments, `sep.join(<static sequence>)`, `dedent()` / `textwrap.dedent()`.
- **One-line reader helpers**: a module-level `def _read_sql(*parts): return
  (_SCHEMA / Path(*parts)).read_text()`, or a method reached through
  `self._read(...)`, whose body is an optional docstring plus one `return`,
  undecorated. Arguments bind from the call site; defaults are honoured.
- **Keyword form**: `self.execute(sql="…")`.

Scoping is decided by the interpreter's own analysis (`symtable`), so a name
resolves only when Python would read that binding there. Everything that
cannot be read is a **warning** that states the reason and the remedy —
never a silent pass. What refuses, and why:

| Shape | Warning kind | Reason it is refused |
|---|---|---|
| `f"… {table} …"` over a loop variable or parameter | `unresolved_fstring` | the value is not fixed by the file's text |
| `{x!r}` / `{x:>10}` | `unresolved_fstring` | conversion or format spec |
| `self.execute(sql)` where `sql` is a parameter, a loop/`with`/`except` target, a comprehension or walrus target, an import, a nested `def` | `dynamic_execute` | bound by something other than a plain assignment |
| a name assigned twice, augmented (`+=`), or reassigned through `global` | `dynamic_execute` | not a single binding |
| a name assigned inside `if`/`for`/`try`/`with` | `dynamic_execute` | conditional |
| `self.X` when anything assigns `self.X` anywhere in the file | `dynamic_execute` | the class attribute is not its only binding |
| `"…" % args`, `.title()`, any call outside the list above | `dynamic_execute` | outside the grammar |
| a helper with two statements, a decorator, or `**kwargs` | `dynamic_execute` | not a single `return <expression>` |
| `<expr>.read_text()` whose path depends on a runtime value | `dynamic_read_text` | the path is not static |
| `self.execute_file(<runtime value>)` | `dynamic_execute_file` | the path is not static |
| a path naming no file at any base | `execute_file_missing` | the message lists every base tried |
| a path resolving outside the project root | `execute_file_escaped` | refused, never read |
| a file that does not parse | `syntax_error` | nothing in it was read |

Every warning appears under its own `⚠️` section in text output — with the
reason, and a `→` line naming the rewrite — and as a top-level `warnings[]`
array in JSON, each entry carrying `kind`, `message`, `reason_code` and
`remedy`. The verdict is honest about them: a run that could not read a call
prints `⚠️  N call(s) unverified — idempotency not established` instead of the
green line, and reports `status: "unverified"` in JSON. The exit code stays 0
unless you opt in with [`--fail-on-unanalyzable`](#--fail-on-unanalyzable).

### Sample output

```
$ confiture migrate validate --idempotent
✓ AST backend (pglast)
❌ Found 2 idempotency violation(s)
   1 call(s) unverified — idempotency not established

001_add_orders.up.sql
  Line 1: CREATE_INDEX
    CREATE INDEX idx_orders_user ON orders (user_id);
    💡 CREATE INDEX IF NOT EXISTS idx_orders_user ON orders ( ... );

20260101000000_add_users.py
  Line 11 (SQL line 1): CREATE_TABLE
    CREATE TABLE users (id int);
    💡 CREATE TABLE IF NOT EXISTS users ( ... );

⚠️  1 dynamic SQL call(s) could not be statically analyzed:
  20260101000001_legacy_load.py:10 — unresolved_fstring
    self.execute() f-string was not resolved statically — f-string interpolates `table`, which is not static: `table` is bound by a `for` target at line 9, not by a plain assignment; SQL was not scanned
    → Parameterise at the DDL level, or hoist the static parts into module constants and execute one constant per statement.
    These calls were skipped. Idempotency cannot be guaranteed.

To auto-fix .sql files, run:
  confiture migrate fix --idempotent --migrations-dir db/migrations
For .py migrations, edit them manually.
```

The `CREATE TABLE` in `add_users.py` sits in a module constant (`DDL = …`,
`self.execute(DDL)`); before 0.46.0 it was reported as unreadable and the run
was green. The same directory with only the unreadable migration:

```
$ confiture migrate validate --idempotent; echo "exit=$?"
✓ AST backend (pglast)
⚠️  1 call(s) unverified — idempotency not established
   Scanned 1 file(s)
⚠️  1 dynamic SQL call(s) could not be statically analyzed:
  20260101000001_legacy_load.py:10 — unresolved_fstring
    …
exit=0

$ confiture migrate validate --idempotent --fail-on-unanalyzable; echo "exit=$?"
✓ AST backend (pglast)
❌ 1 call(s) unverified — idempotency not established
   Scanned 1 file(s)
   …
exit=1
```

For Python-origin violations, the line shown is the source line of the
`self.execute()` call in the `.py` file. The "SQL line" annotation is
the line within the extracted SQL snippet (useful for multi-statement
strings).

### JSON shape

```json
{
  "status": "issues_found",
  "violations": [
    {
      "pattern": "CREATE_TABLE",
      "sql_snippet": "CREATE TABLE users (id int);",
      "line_number": 1,
      "file_path": "db/migrations/20260101000000_add_users.py",
      "suggestion": "Use CREATE TABLE IF NOT EXISTS",
      "fix_available": true,
      "source_line": 9
    }
  ],
  "violation_count": 1,
  "files_scanned": 2,
  "scanned_files": ["..."],
  "has_violations": true,
  "warnings": [
    {
      "kind": "dynamic_execute",
      "source_file": "db/migrations/20260101000001_legacy_load.py",
      "source_line": 14,
      "message": "self.execute() called with a non-literal argument; SQL was not scanned"
    }
  ],
  "has_warnings": true
}
```

`source_line` on a violation is **only present** for Python-origin
findings. SQL-origin violations omit the key entirely so JSON consumers
written before 0.12.1 keep working.

### Auto-fix and Python migrations

`confiture migrate fix --idempotent` rewrites `*.up.sql` files in place.
Python migrations are intentionally **not** auto-rewritten — unparsing
the AST would lose comments and formatting. Violations in `.py` files
must be fixed by hand.

### Scoping to changed migrations — `--base-ref` / `--since` / `--staged`

*New in 0.37.0.*

By default `--idempotent` scans **every** migration in the directory. In a
project that adopted the check after accumulating a back-catalogue, that makes
it unusable as a hard gate: every branch fails on violations it did not
introduce, so the gate gets set to warn-only and stops protecting anything.

Scope it instead to what the branch actually changed, and the gate becomes a
ratchet — new migrations must be idempotent, the backlog drains on its own
schedule:

```bash
confiture migrate validate --idempotent --base-ref origin/main
```

⚠️ *0.46.0 widens what is read.* SQL held in module constants, computed file
paths and reader helpers is now analyzed (#213), so an **unscoped** run on an
existing repository can newly fail on migrations the gate silently skipped
before — on the project that reported the issue, 49 blocking findings across
14 migrations. Scoped runs judge only what the branch touched and are not
affected retroactively; scoping is how you drain that backlog.

**In CI, `fetch-depth: 0` is required.** `actions/checkout` defaults to a
shallow clone with no `origin/main` and no merge base:

```yaml
- uses: actions/checkout@v4
  with:
    fetch-depth: 0          # ← required
- run: confiture migrate validate --idempotent --base-ref origin/main
```

Omit it and the run fails with `GIT_003` (exit 7) naming the remedy. That is
deliberate — see *fail loud*, below.

#### Pre-commit hooks: use `--staged`

`--base-ref` compares **committed trees**, so a migration that is staged but
not yet committed is invisible to it and a pre-commit hook would scope to zero
and pass. `--staged` reads the **staging index** instead:

```yaml
# .pre-commit-config.yaml
- repo: local
  hooks:
    - id: confiture-idempotent
      name: Validate staged migrations are idempotent
      entry: confiture migrate validate --idempotent --staged
      language: system
      pass_filenames: false
```

It analyzes the index blob, not the working tree — the two differ when a file is
staged and then edited further, and the hook must judge what is about to be
committed. When both `--staged` and `--base-ref` are passed, `--staged` wins.

*Since 0.42.0* the same flag scopes `--check-drift`, `--require-migration` and
`--require-migration-bodies` as well (#184); before that it reached only
`--require-grant-migration`, and the others silently compared committed refs.
See [git-aware validation](./git-aware-validation.md#what---staged-compares-0420).

#### Scoping requires an explicit flag

⚠️ `--base-ref` carries a default value of `origin/main`, but **that default
does not scope**. A bare `confiture migrate validate --idempotent` scans
everything, exactly as it did before 0.37.0, and still works outside a git
repository entirely. Only an explicitly passed `--base-ref`, `--since`, or
`--staged` turns scoping on.

This matters more than it looks: gating on the *value* rather than on whether
the flag was passed would silently scope every run in the project, and make a
plain `--idempotent` fail on any non-git tree.

#### Fail loud, never silently empty

Scoping errors are hard failures rather than empty selections, because a gate
that scanned zero files reports success while checking nothing — strictly worse
than the backlog problem it was introduced to solve:

| Situation | Outcome |
|---|---|
| Base ref not in this checkout (shallow clone) | `GIT_003`, exit 7, message names `fetch-depth: 0` |
| Not in a git repository, with an explicit scope flag | `GIT_002`, exit 7 |
| `--migrations-dir` outside the repository | Configuration error — the intersection could only ever be empty |
| Nothing changed since the base ref | **Exit 0**, with a message distinct from "directory is empty" |

Shallow clones that *do* have the ref but no merge base still work: scoping
anchors on `git merge-base` and diffs two-dot, which is equivalent to three-dot
wherever a merge base exists and survives where it cannot be computed.

#### Reporting

Text mode prints the selection before the backend banner:

```
🔍 Scoped to 3 migration(s) changed since origin/main (412 skipped)
```

JSON reports it under `meta.scope`:

```json
"meta": {
  "backend": "ast",
  "scope": {"mode": "base-ref", "base_ref": "origin/main",
            "files_selected": 3, "files_skipped": 412}
}
```

An unscoped run emits no `scope` key at all, so a consumer can tell the two
apart.

⚠️ Only `--idempotent` is scopable today. The other directory-wide checks —
`--check-acls`, `--check-ownership-coverage`, `--check-function-uniqueness`,
`--check-security-definer`, `--check-imports` — still scan everything.

## `--check-signatures` and `--check-body`

These two flags compare the functions declared in your source DDL against the
**live** database, catching functions that were changed out-of-band (an ad-hoc
`CREATE OR REPLACE` on production) without the repo being updated. Both require
`--config` (or `--env`) and connect to the database; pass `--schema` to compare
against an explicit schema file, otherwise the schema is auto-built from your DDL.

- **`--check-signatures`** compares function *signatures*, detecting stale
  overloads left behind when a `CREATE OR REPLACE` changed a parameter type
  (the old overload lingers under the previous signature).
- **`--check-body`** (requires `--check-signatures`) additionally compares each
  function *body* (`pg_proc.prosrc`) against the source. Bodies are compared
  after normalisation — comments, whitespace, and keyword casing are ignored — so
  only genuine logic changes register as drift. Opt-in because body comparison is
  heavier than signature-only.

Either flag exits `1` when drift is found, `0` when clean.

### `--show-diff` — see *what* changed, not just *that* it changed

By default a body drift reports only two 12-char hashes (`source_hash`,
`db_hash`) — enough to know a function drifted, but not what to do about it.
`--show-diff` (requires `--check-body`) surfaces, per drifted function, the
**expected body**, the **live body**, and a **unified diff** of the two. The diff
is computed over a line-oriented normalisation (comments stripped, indentation
and blank-line churn collapsed), so it pinpoints the changed lines instead of
drowning them in reformatting noise.

```bash
# Terse (default): hash-only, ideal for CI logs
confiture migrate validate --check-signatures --check-body --config confiture.yaml

# Triage: show the expected/live bodies and a unified diff per drift
confiture migrate validate --check-signatures --check-body --show-diff \
    --config confiture.yaml
```

Text output under `--show-diff` prints a rich-highlighted `+/-` diff beneath each
drifted function. The JSON payload (`--format json`) gains the bodies and diff on
each entry — but **only** when `--show-diff` is set; the default JSON shape stays
hash-only for back-compatibility:

```json
{
  "check": "function_signature_drift",
  "body_drift": {
    "has_drift": true,
    "body_drifts": [
      {
        "schema": "public",
        "name": "calc_total",
        "signature_key": "public.calc_total(numeric)",
        "source_hash": "f111676f0375",
        "db_hash": "6dc531b06f14",
        "expected_body": "BEGIN\n  RETURN amount * 1.20;\nEND;",
        "live_body": "BEGIN\n  RETURN amount * 1.196;\nEND;",
        "unified_diff": "--- public.calc_total(numeric) (expected)\n+++ public.calc_total(numeric) (live)\n@@ -1,3 +1,3 @@\n begin\n-return amount * 1.20;\n+return amount * 1.196;\n end;"
      }
    ],
    "functions_checked": 1,
    "detection_time_ms": 0.08
  }
}
```

To re-apply the source body over the live drift, use
`confiture migrate fix-signatures --check-body --apply` (dry-run without
`--apply`).

## `--check-body-views`

The view/materialized-view counterpart to `--check-body`. It catches a view whose
predicate or projection was changed directly in the database — an out-of-band
`CREATE OR REPLACE VIEW` on production — without the DDL being updated. (This is
the class of bug behind a real ETL incident where a committed
`meter_at > max_volume_date` had silently become `meter_at > (max_volume_date + 1)`
on prod, dropping every other day's data for months.)

Views are harder than functions: PostgreSQL doesn't store a view's text, so
`pg_get_viewdef` returns a *deparsed* rendering (schema-qualified, `*`-expanded,
reparenthesised). A naive text compare of your `CREATE VIEW` DDL against that would
report **false positives** on views that are only formatted differently. Instead,
`--check-body-views` builds the expected views into a throwaway **scratch
database** and reads them back through the **same** `pg_get_viewdef` deparser as
live — so string equality means semantic equality, and only genuine logic changes
register.

```bash
# Terse: hash-only, exits 1 on drift
confiture migrate validate --check-body-views --config confiture.yaml --schema db/generated/schema.sql

# Triage: unified diff of the deparsed definitions per drifted view
confiture migrate validate --check-body-views --show-diff \
    --schemas public,catalog --config confiture.yaml --schema db/generated/schema.sql
```

- Covers **regular and materialized** views; honours `--schemas`.
- `--show-diff` adds `expected_def`, `live_def`, and `unified_diff` to each drifted
  view (text and JSON). Default output is hash-only.
- **Remote read-only live (`--ssh`)**: the scratch database is built on a
  *writable* server, which the read-only production replica is not. Pass
  `--scratch-url postgresql://localhost/postgres` (or a CI server) so the expected
  side builds locally while the live side is read over the tunnel.

The JSON payload mirrors `--check-body`:

```json
{
  "check": "view_body_drift",
  "has_drift": true,
  "body_drifts": [
    {
      "schema": "public",
      "name": "v_etl_unused_meters",
      "relkind": "v",
      "source_hash": "e442d2211789",
      "db_hash": "251751b4699c"
    }
  ],
  "views_checked": 2,
  "detection_time_ms": 0.18
}
```

## `--check-body-replay` — the production drift guard

`--check-body` and `--check-body-replay` both detect function/procedure body drift
against live, but they build the **expected** side differently:

| | Expected side | Best for |
|---|---|---|
| `--check-body` | source DDL (`build`) | a repo where DDL *is* the source of truth |
| `--check-body-replay` | replay of all migrations | migrate-strategy prod: isolate a *new* hot-patch |

On a migrate-strategy database (staging, production), `--check-body`'s
source-DDL expectation is swamped by the **build-vs-migrate backlog**: every body
that shipped to dev/test (rebuilt from DDL) but never got a migration reads as
"drift", so a genuinely new out-of-band `CREATE OR REPLACE` on prod is lost in the
noise.

`--check-body-replay` gives the clean signal. It rebuilds the expected database by
replaying **all migrations** into a throwaway scratch DB — no source DDL, no
hot-patches — and diffs `pg_proc.prosrc` against live. The difference is exactly
the definitions **no migration produced**: true out-of-band hot-patches.

```bash
# Isolate live hot-patches that no migration carries
confiture migrate validate --check-body-replay --env production \
    --schemas public,catalog

# With the diff, over an SSH tunnel to a read-only replica
confiture migrate validate --check-body-replay --show-diff \
    --env production --ssh deploy@db.internal \
    --scratch-url postgresql://localhost/postgres
```

- Both sides are real databases introspected identically, so signature pairing is
  exact — this path never text-parses signatures.
- A migration that **fails at HEAD** surfaces as an error (non-zero exit), *not*
  as false drift.
- Heaviest drift check (replays the whole migration history). Explicitly opt-in.
- `--scratch-url` is **required** with `--ssh` (the replay needs a writable server;
  the read-only replica is not one). JSON `check` is `replay_body_drift`; the
  `body_drifts` shape matches `--check-body` (with `--show-diff` adding
  `expected_body`/`live_body`/`unified_diff`).

A deploy scheduler (e.g. fraisier) can run this post-deploy and on a timer as a
standing production drift guard — the consuming repo keeps only config.

## `--require-migration-bodies` — gate un-migrated body edits at PR time

`--require-migration` ensures table/column DDL changes and function *signature*
changes have a migration, but it does **not** check function/procedure *bodies*.
So a body edit in the schema DDL that ships to rebuilt-from-DDL environments
(dev/test) without a migration silently never reaches migrate-only environments
(staging/production) — the root cause of a whole class of prod↔source drift (in
one audit, ~120 functions ran different bodies in prod for exactly this reason).

`--require-migration-bodies` closes the gap. It is **static and git-based (no
DB)**: it diffs function bodies between `--base-ref` and HEAD and requires each
changed body to be carried by a migration that re-defines the function (a
`CREATE OR REPLACE`, in a `.sql` or `.py` migration). Comment/whitespace/case-only
changes don't count; parameter-type changes are the existing signature check's
job. Because it's diff-scoped, it flags only what changed in the changeset — not
your standing backlog.

This is the PR-time static gate. Its runtime counterpart, which verifies the
migration actually *produces* the intended body against a live database, is
[`--check-body-replay`](#--check-body-replay--the-production-drift-guard).

### Drain-first workflow

It is **off by default**: an existing repo carries a backlog of body edits that
predate the check, and turning it on cold would fail the first PR that touches any
of them. Adopt it in three steps:

```bash
# 1. Size the backlog (report-only, never fails — exit 0)
confiture migrate validate --list-unmigrated-bodies --base-ref origin/main

# 2. Drain it: add migrations that re-apply each listed function, or accept them
#    into a baseline. Re-run step 1 until the list is empty.

# 3. Enforce in CI (fails the build on a new un-migrated body change)
confiture migrate validate --require-migration-bodies --base-ref origin/main
```

`--require-migration-bodies` implies `--require-migration` (it runs the full
accompaniment check plus the body check). On violation it names each function,
shows a unified diff of the change, and exits 1. JSON failures carry a
`body_violations` array (`function_key`, `signature_key`, `unified_diff`); the
report-only mode emits `{"check": "unmigrated_bodies", "count": N, ...}`.

## `--require-grant-migration`

Build environments apply grants straight from the grant sweep directory
(`db/7_grant/` by default); migrate environments (staging, production) apply
grants **only** through migrations. So a grant changed in the sweep directory
without a migration that carries it silently never reaches production. This
flag closes that gap.

It is **semantic** (issue #162): it verifies that each *changed* `GRANT` /
`REVOKE` statement is actually present in an accompanying migration — not
merely that *some* migration happens to be in the changeset.

- **Both migration formats are recognized.** A `.up.sql` migration *or* a `.py`
  migration (its `self.execute("GRANT …")` / `self.execute_file(...)` calls are
  statically extracted) can carry the grant. `_`-prefixed modules
  (`__init__.py`, `_helpers.py`) are not migrations.
- **Diff-aware.** Only the *added or changed* grants are required. Editing one
  grant in a 50-grant file requires only that one grant in a migration; the
  required set is diffed against the **merge-base** of your base and target
  refs (consistent with three-dot changed-file semantics).
- **Broad coverage.** `GRANT` and `REVOKE`, across **table**, **schema-wide**
  (`… IN SCHEMA`), **sequence**, and **function** objects. `GRANT ALL` and an
  explicit privilege list compare equal (both expand to the same per-object-type
  set), so you can write `ALL` in the sweep and enumerate in the migration.

### Honest degradation — what is *not* semantically verified

Some grant forms parse cleanly but can't be turned into a comparable key. Rather
than silently pass them (the exact bug this flag exists to prevent), they
**degrade to a file-presence check** — a migration must be present — and the
reason is surfaced as a note. These are:

- Object classes outside table/schema/sequence/function: `GRANT … ON DATABASE`,
  `LANGUAGE`, `TYPE`, `DOMAIN`, `FOREIGN DATA WRAPPER`, `TABLESPACE`, …
- `ALTER DEFAULT PRIVILEGES … GRANT/REVOKE …`
- Column-level privileges (`GRANT SELECT (col) ON t …`)
- `WITH GRANT OPTION`-only changes (the option is outside the match key)
- Grants behind a non-public `SET search_path` (the unqualified object name is
  ambiguous — qualify it explicitly to get full semantic verification)
- Dynamic SQL (`EXECUTE format('GRANT …')`) and parse failures
- A grant *removed* from a file (v1 does not auto-require a `REVOKE` migration)

A no-op edit (comment-only, whitespace, reorder) changes nothing representable
and is **not** unverifiable, so it passes without requiring a migration.

### Bypass

`--allow-grant-only` suppresses the check for build-only branches that don't
deploy through migrations.

```bash
confiture migrate validate --require-grant-migration --allow-grant-only --staged
```

## `--check-imports`

`--check-imports` **imports each Python migration module** — Level 1 of the
check calls `load_migration_module()` on every `*.py` under the migrations
directory, so module-level code in a migration executes in the confiture
process, with confiture's privileges, on the host running the gate. Levels 2
and 3 (class attributes, `self.*` access) then inspect the loaded class and
the AST. None of the other checks import or execute a migration; only this
flag does. Run it on code you would run anyway, the same way you would run
the migration itself.

## Known limitations

- **Subclassed helpers.** If you wrap `self.execute()` in a project-local
  mixin (`self.run_template(...)`), the extractor can't statically tell
  that wraps `execute`. The call is ignored. Workaround: use `execute()`
  directly for migration SQL, or split helpers into a separate non-call
  surface.
- **SQL that depends on a runtime value.** An f-string over a loop variable
  or a parameter, `%`-formatting, a path built from a parameter, a helper
  with more than one statement: these are refused with the reason and the
  remedy (see the table under *Python-migration support*). Static
  `.format()` and `.replace()` are read; `%` is not.
- **Only this file is read.** A constant imported from another module, or a
  helper defined elsewhere, is not followed — the evaluator never imports.

These cases produce **warnings with a remedy**, never silent passes. A
Python-only migrations directory full of dynamic SQL reports
`⚠️ N call(s) unverified` (`status: "unverified"`) and, by default, still exits
0 so an existing pipeline keeps working; pass `--fail-on-unanalyzable` to make
that a failure, and pair it with `--base-ref` to ratchet.
