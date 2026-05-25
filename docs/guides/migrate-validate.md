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
```

JSON output is available with `--format json` for every variant.

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

### Three signal types

The report uses three distinct words. Keep them straight:

- **Violation (error)** — a SQL pattern that is not idempotent and will
  fail re-application. Fails the gate (`has_blocking_violations: true`).
- **Violation (info)** — a heuristic note, currently only emitted for
  `CREATE OR REPLACE VIEW/FUNCTION/PROCEDURE` not preceded by a matching
  `DROP … IF EXISTS`. Does *not* fail the gate by default. Render-only.
  Promote to a gate failure with `--strict-cor`.
- **Warning** — an *extractor*-level signal that we couldn't statically
  analyze part of a `.py` file (dynamic `execute(var)`, f-strings with
  interpolation). Never fails the gate; tells you which calls were
  skipped.

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

Confiture statically extracts SQL strings from `up()` and `down()`
without importing or executing the migration. The extractor handles:

- String constants: `self.execute("CREATE TABLE foo (id int);")`
- f-strings with only literal parts: `self.execute(f"CREATE TABLE foo;")`
- Constant string concatenation: `self.execute("CREATE " + "TABLE foo;")`
- File references: `self.execute_file("db/schema/foo.sql")`
- Keyword form: `self.execute(sql="…")`

Calls whose argument can't be statically resolved produce a structured
**warning** in the report (rather than silently passing the file).
Warnings appear under their own `⚠️` section in text output and as a
top-level `warnings` array in JSON. Examples:

- `self.execute(sql)` where `sql` is a variable → `dynamic_execute`
- `self.execute(f"CREATE TABLE {table};")` → `unresolved_fstring`
- `self.execute_file(computed_path)` → `dynamic_execute_file`
- `self.execute_file("../../../outside/file.sql")` resolving outside the
  project root → `execute_file_escaped` (the file is **not** read)
- `self.execute_file("db/schema/missing.sql")` → `execute_file_missing`

Warnings do not fail the gate. Violations do. Combine the two
appropriately for your CI policy: if you require zero dynamic SQL,
grep for `has_warnings: true` in the JSON output.

### Sample output

```
$ confiture migrate validate --idempotent
❌ Found 2 idempotency violation(s)

20260101000000_add_users.py
  Line 9 (SQL line 1): CREATE_TABLE
    CREATE TABLE users (id int);
    💡 Use CREATE TABLE IF NOT EXISTS

001_add_orders.up.sql
  Line 3: CREATE_INDEX
    CREATE INDEX idx_orders_user ON orders (user_id);
    💡 Use CREATE INDEX IF NOT EXISTS

⚠️  1 dynamic SQL call(s) could not be statically analyzed:
  20260101000001_legacy_load.py:14 — dynamic_execute
    self.execute() called with a non-literal argument; SQL was not scanned
    These calls were skipped. Idempotency cannot be guaranteed.

To auto-fix .sql files, run:
  confiture migrate fix --idempotent --migrations-dir db/migrations
For .py migrations, edit them manually.
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

## Known limitations

- **Subclassed helpers.** If you wrap `self.execute()` in a project-local
  mixin (`self.run_template(...)`), the extractor can't statically tell
  that wraps `execute`. The call is ignored. Workaround: use `execute()`
  directly for migration SQL, or split helpers into a separate non-call
  surface.
- **SQL built by `str.format` / `%`-format.** Treated as dynamic. The
  template is not extracted even if the placeholders are not used.
- **`Path(...).read_text()` outside of `execute_file()`.** Loaded SQL that
  doesn't go through the official helper is invisible to the extractor.

These cases produce **warnings**, never silent passes — so a Python-only
migrations directory full of dynamic SQL still exits 0 but tells you
clearly which files were not scanned. Tighten your CI gate accordingly.
