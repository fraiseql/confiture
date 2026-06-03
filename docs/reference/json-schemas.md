# JSON Output Schemas

Many Confiture commands that support `--format json` ship with a
machine-validatable JSON Schema — currently the `migrate` family (`current`,
`down-to`, `fix`, `preflight`, `preflight --against`, `status`, and the
`validate` modes), `drift` (and `drift --check-acls`), and `validate-config`,
plus the shared error envelope. Commands such as `build`, `migrate up`/`down`,
`migrate diff`, and `seed apply` emit JSON but do not yet ship a schema. Schemas
use Draft 2020-12 and live in `docs/reference/json-schemas/`.

## For agents and tooling

If you are writing a script, agent, or pipeline that consumes Confiture's
JSON output, **read the schema for the relevant subcommand before
depending on field names**. Schemas record exact field shapes; the
`--help` text only describes flags.

To validate output programmatically:

```python
import json
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

# Load the schema and the shared $defs file (referenced by relative URI).
schema = json.loads(open("docs/reference/json-schemas/migrate-validate-idempotent.schema.json").read())
common = json.loads(open("docs/reference/json-schemas/_common.schema.json").read())

registry = Registry().with_resource(
    uri="_common.schema.json",
    resource=Resource.from_contents(common, default_specification=DRAFT202012),
)
validator = Draft202012Validator(schema, registry=registry)
validator.validate(your_payload)  # raises ValidationError on mismatch
```

## Stability

The `hints: list[string]` field is pre-allocated on every top-level
schema and emitted as `[]` today. Future releases may populate it on
quiet-success ambiguities (Phase 05 of issue #123). Consumers should
*accept* the field today but not depend on specific content.

Aside from `hints` population, schemas are additive — new optional fields
may appear in patch releases, but documented `required` fields will not
change without a top-level version bump.

---

## Schemas by command

### Error envelope (any migrate command, `--format json` error path)

[error-envelope.schema.json](./json-schemas/error-envelope.schema.json) — `{ "ok": false, "error": { … } }`, where `error` is the shared [issue-object.schema.json](./json-schemas/issue-object.schema.json). Emitted on stdout when a migrate-family command fails in JSON mode; the process exits with the matching [exit code](exit-codes.md). The full code list is the [error-code codebook](error-codes.md).

### `confiture validate-config --format json`

[validate-config.schema.json](./json-schemas/validate-config.schema.json) — `{valid, config_source, migrations_path, migration_count, issues[]}` for offline config + migrations-tree validation (#144). **Never connects to a database.** Each `issues[]` element is the shared [issue object](./json-schemas/issue-object.schema.json). Invalid config exits 5.

### `confiture migrate current --format json`

[migrate-current.schema.json](./json-schemas/migrate-current.schema.json) — `{revision, name, applied_at, checksum}` for the latest applied migration (all `null` when the tracking table is empty). An absent tracking table is an error path emitting the [error envelope](./json-schemas/error-envelope.schema.json) at exit 2.

### `confiture migrate down-to <revision> --format json`

[migrate-down-to.schema.json](./json-schemas/migrate-down-to.schema.json) — `{from, to, rolled_back, skipped, errors}` for an absolute rollback. An invalid plan (unknown/forward target, or a missing `.down.sql`) emits the [error envelope](./json-schemas/error-envelope.schema.json) and applies nothing.

### `confiture migrate validate --list-patterns --format json`

[migrate-validate-list-patterns.schema.json](./json-schemas/migrate-validate-list-patterns.schema.json)

Machine-readable catalog of every idempotency detection pattern. **Read-only** — no DB, no config, no migrations directory required. Frozen at `version: "1"`.

Minimal example:

```json
{
  "version": "1",
  "patterns": [
    {
      "id": "CREATE_TABLE",
      "description": "CREATE TABLE without IF NOT EXISTS.",
      "severity": "error",
      "has_skip_regex": true,
      "skip_hint": "CREATE TABLE IF NOT EXISTS",
      "has_auto_fix": true,
      "template_fillable": true
    }
  ],
  "hints": []
}
```

### `confiture migrate validate --idempotent --format json`

[migrate-validate-idempotent.schema.json](./json-schemas/migrate-validate-idempotent.schema.json)

Scans every migration file (`.up.sql` and embedded SQL in Python migrations) for non-idempotent patterns. Exit code 1 when blocking violations exist.

```json
{
  "status": "issues_found",
  "violations": [
    {
      "pattern": "CREATE_TABLE",
      "sql_snippet": "CREATE TABLE users (...);",
      "line_number": 3,
      "file_path": "db/migrations/20260527000000_init.up.sql",
      "source_line": null,
      "suggestion": "Use CREATE TABLE IF NOT EXISTS",
      "fix_available": true,
      "severity": "error"
    }
  ],
  "violation_count": 1,
  "files_scanned": 1,
  "scanned_files": ["..."],
  "has_violations": true,
  "has_blocking_violations": true,
  "warnings": [],
  "has_warnings": false,
  "hints": []
}
```

### `confiture migrate validate --check-acls --format json`

[migrate-validate-check-acl-coverage.schema.json](./json-schemas/migrate-validate-check-acl-coverage.schema.json)

Static check that every `CREATE TABLE` in `db/migrations/` has a matching `GRANT` either in the same migration or in the configured grant-sweep directory. No DB required.

```json
{
  "check": "acl_coverage",
  "violations": [
    {
      "rule_id": "ACL001",
      "severity": "error",
      "object_name": "public.orders",
      "message": "No GRANT statement found for public.orders",
      "file_path": "db/migrations/20260527000000_init.up.sql"
    }
  ],
  "hints": []
}
```

### `confiture migrate validate --check-function-uniqueness --format json`

[migrate-validate-check-function-uniqueness.schema.json](./json-schemas/migrate-validate-check-function-uniqueness.schema.json)

Static check that every `CREATE FUNCTION` / `CREATE PROCEDURE` across the configured DDL directories has a unique fully-qualified signature. Opt-in via a `function_coverage:` block in the env config. Requires the `[ast]` extra (pglast). No DB required.

```json
{
  "check": "function_uniqueness",
  "violations": [
    {
      "rule_id": "func_001",
      "severity": "error",
      "object_name": "stat_etl.sync_tv_dimensions",
      "object_type": "function",
      "message": "Function 'stat_etl.sync_tv_dimensions()' is defined in 2 files: 03970_sync_tv_dimensions.sql, 039700_sync_tv_dimensions.sql. ...",
      "file_path": "db/schema/0397_maintenance/03970_sync_tv_dimensions.sql",
      "line_number": 14
    }
  ]
}
```

### `confiture migrate status --format json`

[migrate-status.schema.json](./json-schemas/migrate-status.schema.json)

Migration status report. Without `--config`, per-migration `status` is `unknown` (file-based listing only). With `--config`, status is `applied` or `pending`.

```json
{
  "tracking_table": "tb_confiture",
  "applied": ["20260101000000"],
  "pending": ["20260527000000"],
  "current": "20260101000000",
  "total": 2,
  "migrations": [
    {"version": "20260101000000", "name": "init", "status": "applied", "applied_at": "2026-01-01T00:00:00Z"},
    {"version": "20260527000000", "name": "add_orders", "status": "pending", "applied_at": null}
  ],
  "summary": {"applied": 1, "pending": 1, "total": 2},
  "hints": []
}
```

### `confiture migrate fix --idempotent --format json`

[migrate-fix.schema.json](./json-schemas/migrate-fix.schema.json)

Rewrites non-idempotent SQL files in place (or previews with `--dry-run`). Python migrations are listed under `manual_fix_required` — never rewritten.

```json
{
  "status": "fixed",
  "files": [
    {
      "file": "20260527000000_init.up.sql",
      "changes": [
        {"pattern": "CREATE_TABLE", "original": "...", "suggested_fix": "...", "line": 3}
      ]
    }
  ],
  "total_files_changed": 1,
  "manual_fix_required": [],
  "hints": []
}
```

### `confiture migrate preflight --format json` (no `--against`)

[migrate-preflight.schema.json](./json-schemas/migrate-preflight.schema.json)

Structured preflight report (#148): `{ok, summary, issues[]}`, where each `issues[]` element is the shared [issue object](./json-schemas/issue-object.schema.json) (`PFLIGHT_*` codes). Covers reversibility, transactionality, duplicate version prefixes, and checksum mismatches. No DB required. Errors → exit 7; warnings are non-fatal unless `--strict`. A preflight that *crashes* (config/DB error) emits the [error envelope](./json-schemas/error-envelope.schema.json) instead.

### `confiture migrate preflight --against <url> --format json`

[migrate-preflight-against.schema.json](./json-schemas/migrate-preflight-against.schema.json)

> **Changed in 0.21.0 (#151).** `--against` now emits the **same** `{ok, summary, issues[]}`
> envelope as the no-`--against` path — one schema, one parser. The legacy
> `{static, against, hints}` shape is gone.

Static findings + replica-forward-compat lints + execution-replay results, unified into one `issues[]`. A migration that fails to replay against the `--against` database appears as a `PFLIGHT_REPLAY_FAILED` issue, with the database error in `details.error`; the run exits 7 (via `preflight_exit_code`). Run-level metadata that is not a finding — `db_consumed` — rides in `summary`. `summary.migrations_checked` is the number of migrations *replayed* (the pending set). An unreachable `--against` URL is a connection failure → the [error envelope](./json-schemas/error-envelope.schema.json) with `CONFIG_006` (exit 3).

```json
{
  "ok": false,
  "summary": {
    "errors": 1,
    "warnings": 0,
    "info": 0,
    "migrations_checked": 1,
    "db_consumed": false
  },
  "issues": [
    {
      "severity": "error",
      "code": "PFLIGHT_REPLAY_FAILED",
      "message": "Migration 20260527000000 (init) failed to replay against the preflight DB.",
      "migration": "20260527000000",
      "file": null,
      "line": null,
      "actionable": "Fix the failing migration SQL; see details for the database error.",
      "details": { "error": "relation \"x\" already exists" }
    }
  ]
}
```

### `confiture drift --format json`

[drift.schema.json](./json-schemas/drift.schema.json)

Live-database drift report against expected DDL.

### `confiture drift --check-acls --format json`

[drift-check-acls.schema.json](./json-schemas/drift-check-acls.schema.json)

Shape is identical to plain `drift` — items of type `missing_grant` / `extra_grant` may appear in `drift_items`.

---

## Field-name traps (issue #123)

Several JSON field names have diverged from the obvious guess. The schemas
record the canonical names; this list calls them out explicitly so
agents can grep for the wrong name.

### `ExtractedSQL.source_line` (NOT `line_number`)

When a Python migration embeds SQL (via `cursor.execute(...)` or similar),
the validator records **two** line numbers:

* `line_number` — line within the embedded SQL string
* `source_line` — line within the `.py` file where the call appears

If you only need the file-level position to show the user, use
`source_line`. There is no field named `line_number_py` or
`py_line_number`.

### `ExtractionResult.snippets` (NOT `sql`)

The intermediate representation for extracted SQL is called `snippets`,
not `sql`. There is no `.sql` attribute on `ExtractionResult`. Each
entry in `snippets` is an `ExtractedSQL` with its own `source_line`.

### `severity` is required

Every `Violation` (idempotency) and `DriftItem` (drift) MUST have a
`severity` field. If you see a payload where `severity` is missing,
that's a bug — please file an issue. The schemas mark `severity` as
required so any missing-severity payload fails validation.

---

## Shared sub-schemas

The `_common.schema.json` file holds shared `$defs`:

* `Violation` — used by `migrate validate --idempotent`
* `ExtractorWarning` — dynamic-SQL warnings
* `DriftItem` — used by `drift`
* `HintsArray` — the `hints` field (pre-allocated for Phase 05)

The `_preflight_defs.schema.json` file holds preflight-specific
sub-schemas:

* `DependentAnalysis` — the optional dependent-objects analysis, referenced by
  both `migrate-preflight.schema.json` and `migrate-preflight-against.schema.json`
* `StaticPreflight` — the legacy `PreflightResult.to_dict()` shape. **Unused
  since 0.21.0 (#151)** — the `--against` `static` block it described was folded
  into the unified `issues[]`. Retained for back-reference only.
