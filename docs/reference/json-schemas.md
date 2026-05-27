# JSON Output Schemas

Every Confiture command that supports `--format json` ships with a
machine-validatable JSON Schema. Schemas use Draft 2020-12 and live in
`docs/reference/json-schemas/`.

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
      "has_auto_fix": true
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

Static preflight analysis — per-migration reversibility, transactionality, duplicate version prefixes, checksum mismatches. No DB required.

### `confiture migrate preflight --against <url> --format json`

[migrate-preflight-against.schema.json](./json-schemas/migrate-preflight-against.schema.json)

Static analysis + exhaustive execution against a preflight database. Returns a two-level shape: `static` (same as no-`--against`) and `against` (execution outcomes).

```json
{
  "static": { "...": "PreflightResult.to_dict() shape" },
  "against": {
    "against_url": "postgresql://user@host/preflight",
    "all_passed": true,
    "total": 1,
    "passed": 1,
    "failed": 0,
    "skipped": 0,
    "db_consumed": false,
    "migrations": [
      {
        "version": "20260527000000",
        "name": "init",
        "success": true,
        "error": null,
        "skipped": false,
        "skipped_reason": null,
        "execution_time_ms": 42
      }
    ]
  },
  "hints": []
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

### `against.migrations[].success` (NOT `passed`)

Each per-migration entry in `migrate preflight --against` carries
`success: bool` — not `passed`. The aggregate counters at the
`against.` level use both: `against.passed` is an integer count;
`against.all_passed` is the boolean aggregate. Don't confuse them.

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
sub-schemas shared between `migrate-preflight.schema.json` and
`migrate-preflight-against.schema.json`:

* `StaticPreflight` — the `PreflightResult.to_dict()` shape
* `DependentAnalysis` — the optional dependent-objects analysis
