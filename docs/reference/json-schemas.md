# JSON Output Schemas

> **Frozen at 1.0.0.** The published schemas are a stability contract: fields are added, never renamed or removed. A change here is a breaking change: it needs a major version and a CHANGELOG entry.

The commands whose `--format json` output ships a machine-validatable JSON
Schema are `bootstrap`, `build` (and `build --list-files`), `debug cte`, `diff`, `drift` (and
`drift --check-acls`), `install-helpers`, `introspect`, `lint` (and
`lint --list-rules`), `lint-unified`, `schema dump-model`, `sync`,
`validate-config`, `validate-profile`, `verify-checksums` and, in the migrate
family, `up`, `down`, `down-to`, `apply-as`, `baseline`, `rebuild`, `reinit`,
`status`, `current`, `diff`, `fix`, `fix-signatures`, `generate`, `introspect`, `preflight` (and `--against`),
`steps`, `validate` (every mode) and `verify` — plus the shared error envelope.
The other JSON payloads have no published schema yet;
`tests/unit/json_schemas/test_every_json_command_has_a_schema.py` lists them, with
the reason, and that list only shrinks. Schemas
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

## One source

The schema files live in the package — `python/confiture/schemas/*.schema.json`,
shipped in the wheel and loadable with `confiture.core.schema_exporter.load_schema()`
or copied out with `confiture.export_all(dir)`. This directory is a byte-identical
copy written by `scripts/gen_schemas.py`; CI fails when it drifts. For every
result model that *is* a command's payload (`MigrateUpResult` → `migrate-up`,
`VerifyAllResult` → `migrate-verify`, …) a test populates the model and validates
its `to_dict()` against the schema, so a field added to a model without its
schema fails the build.

## Stability

The `hints: list[string]` field is pre-allocated on every top-level
schema and emitted as `[]` today. Future releases may populate it on
quiet-success ambiguities (issue #123). Consumers should
*accept* the field today but not depend on specific content.

Every top-level payload and the error envelope carry `parser` (0.50.0):
`{"pglast": "<release>", "pg_major": <PostgreSQL grammar major>}` — what
parsed the SQL behind the verdict. It is declared (`_common.schema.json#/$defs/Parser`)
but not required, so payloads from earlier versions stay valid.

Since 1.16.0 they also carry `ok` and `command` — the envelope, written by the
one emitter every command's JSON goes through. `command` is the command as typed
after `confiture` (`migrate up`). `ok` is `true` when the command produced its
report and `false` in the error envelope; what the report *found* is in its own
fields (`success`, `is_valid`, `status`). A payload that carries an `ok` of its
own keeps it: `migrate preflight`, `migrate verify` and `verify-checksums` define
`ok` as their verdict, which their schemas require. The three keys come after
every key the payload already had. Every payload schema declares them; besides
those verdicts, only `schema-dump-model` and `sync` require them, as they always
have — a schema published since does not, so a consumer that validates an older
capture is not refused for a key the envelope added later.

Aside from `hints` population, schemas are additive — new optional fields
may appear in patch releases, but documented `required` fields will not
change without a top-level version bump.

## Timing vocabulary

Every duration a payload carries is an integer number of milliseconds under a
key ending in `_ms`. The migrate family uses two words: `total_duration_ms` for
the whole run and `duration_ms` for each applied item. Build, lint and the CTE
debugger emit `execution_time_ms`; the drift reports emit `detection_time_ms`.
Five models keep an older attribute name behind their wire key
(since 1.0.0 the migrate family's attributes carry their wire names:
`total_duration_ms` and `MigrationApplied.duration_ms`). The table below is the
one mapping from attribute to key; `tests/unit/json_schemas/test_timing_vocabulary.py`
derives the same rows from every `to_dict()` in the package and from every
`*_ms` property in the shipped schemas, so a new timing key, a renamed
attribute or a stale row fails the build. The JSON keys are the contract; the
attribute names are scheduled to follow them at 1.0.0.

| Model | Attribute | JSON key | Where it appears |
|---|---|---|---|
| `confiture.models.results.MigrateUpResult` | `total_duration_ms` | `total_duration_ms` | `migrate up --format json` ([`migrate-up.schema.json`](json-schemas/migrate-up.schema.json)) |
| `confiture.models.results.MigrationApplied` | `duration_ms` | `duration_ms` | `migrate up` — each `applied[]` item |
| `confiture.models.results.MigrateDownResult` | `total_duration_ms` | `total_duration_ms` | `migrate down --format json` |
| `confiture.models.results.MigrateRebuildResult` | `total_duration_ms` | `total_duration_ms` | `migrate rebuild --format json` |
| `confiture.models.results.MigrateReinitResult` | `total_duration_ms` | `total_duration_ms` | library result of `MigratorSession.reinit()` (text output only) |
| `confiture.models.results.BuildResult` | `execution_time_ms` | `execution_time_ms` | `build --format json` ([`build.schema.json`](json-schemas/build.schema.json)) |
| `confiture.models.results.SplitBuildResult` | `execution_time_ms` | `execution_time_ms` | library result of the split build |
| `confiture.models.results.PreflightAgainstMigration` | `execution_time_ms` | `execution_time_ms` | library result of `run_against()`; the CLI prints it as text |
| `confiture.models.lint.LintReport` | `execution_time_ms` | `execution_time_ms` | `lint --format json` ([`lint.schema.json`](json-schemas/lint.schema.json)) |
| `confiture.models.debug_models.CTEStepResult` | `execution_time_ms` | `execution_time_ms` | `debug cte --format json` ([`debug-cte.schema.json`](json-schemas/debug-cte.schema.json)) — each `steps[]` item |
| `confiture.core.drift.DriftReport` | `detection_time_ms` | `detection_time_ms` | `drift --format json` ([`drift.schema.json`](json-schemas/drift.schema.json)) |
| `confiture.core.function_signature_drift.FunctionSignatureDriftReport` | `detection_time_ms` | `detection_time_ms` | `migrate validate --check-signatures --format json` |
| `confiture.core.function_body_drift.FunctionBodyDriftReport` | `detection_time_ms` | `detection_time_ms` | `migrate validate --check-body` (`body_drift`) |
| `confiture.core.view_body_drift.ViewBodyDriftReport` | `detection_time_ms` | `detection_time_ms` | `migrate validate --check-body-views` (`view_body_drift`) |
| `confiture.core.schema_analyzer.ValidationResult` | `validation_time_ms` | `validation_time_ms` | library result of `SchemaAnalyzer.validate()` |

---

## Schemas by command

### Error envelope (any migrate command, `--format json` error path)

[error-envelope.schema.json](./json-schemas/error-envelope.schema.json) — `{ "ok": false, "error": { … } }`, where `error` is the shared [issue-object.schema.json](./json-schemas/issue-object.schema.json). Emitted on stdout when a migrate-family command fails in JSON mode; the process exits with the matching [exit code](exit-codes.md). The full code list is the [error-code codebook](error-codes.md).

### `confiture validate-config --format json`

[validate-config.schema.json](./json-schemas/validate-config.schema.json) — `{valid, config_source, migrations_path, migration_count, issues[]}` for offline config + migrations-tree validation (#144). **Never connects to a database.** Each `issues[]` element is the shared [issue object](./json-schemas/issue-object.schema.json). Invalid config exits 5.

### `confiture validate-profile <path> --format json`

[validate-profile.schema.json](./json-schemas/validate-profile.schema.json) — `{valid, path, name, version, has_global_seed, strategies{}, tables{}}` for an anonymization profile that validated: each strategy's `{type, seed_env_var}` and each table's rules `{column, strategy, has_seed}`. A seed is never written, only whether one is set. An invalid profile emits the [error envelope](./json-schemas/error-envelope.schema.json) (`ANON_1400`).

### `confiture migrate current --format json`

[migrate-current.schema.json](./json-schemas/migrate-current.schema.json) — `{revision, name, applied_at, checksum}` for the latest applied migration (all `null` when the tracking table is empty). An absent tracking table is an error path emitting the [error envelope](./json-schemas/error-envelope.schema.json) at exit 2.

### `confiture migrate up --format json`

[migrate-up.schema.json](./json-schemas/migrate-up.schema.json) — `{success, applied[], skipped, skipped_superuser[], pending, errors, total_duration_ms, checksums_verified, dry_run, dry_run_execute, warnings}` after applying pending migrations. The fraisier migration adapter reads `applied[].version` as the new head. A failure that aborts execution emits the [error envelope](./json-schemas/error-envelope.schema.json) instead; a failed migration or a `requires_superuser` halt keeps this shape with `success: false`, and `errors` is then never empty.

### `confiture migrate verify --format json`

[migrate-verify.schema.json](./json-schemas/migrate-verify.schema.json) — `{verified_count, failed_count, skipped_count, total_applied, results[]}` for `.verify.sql` runtime-correctness checks. The fraisier adapter treats the run as ok ⇔ `failed_count == 0`, and reads each `results[].{version, name, status, error}`. Migrations with no sidecar are `status: "no_file"` (counted in `skipped_count`).

### `confiture migrate introspect --format json`

[migrate-introspect.schema.json](./json-schemas/migrate-introspect.schema.json) — `{ledger_present, detected_version, …}` for recovering which migration level a database is at by matching its live schema against `db/schema_history/`.

⚠️ **`tb_confiture_present` was removed in 0.40.0**, after the one-release deprecation window opened in 0.39.0. It hardcoded the default table name, which is wrong for any project that configured `tracking_table` (#186). Use **`ledger_present`**, the table-name-agnostic spelling `migrate verify` adopted in 0.37.0.

### `confiture verify-checksums --format json`

[verify-checksums.schema.json](./json-schemas/verify-checksums.schema.json) — `{ok, ledger_present, summary{checked, mismatched, tracking_table}, issues[]}` for **file-integrity** verification: the SHA-256 of each migration file against the checksum stored when it was applied. Distinct from `migrate verify`, which checks runtime state via `.verify.sql` sidecars. Added in 0.39.0 (#189).

`ok ⇔ summary.mismatched == 0`. Exit 1 on mismatches is a *success-signal* — the gate tripped — so it still carries this shape; a real error (config/DB failure, or an absent ledger without `--allow-uninitialized`) emits the [error envelope](./json-schemas/error-envelope.schema.json) instead. `issues[]` uses the shared [issue object](./json-schemas/issue-object.schema.json) with code `CHECKSUM_MISMATCH`.

`summary.tracking_table` reports the ledger actually queried — the configured `tracking_table`, not necessarily the `tb_confiture` default (#190). Not part of the fraisier adapter contract.

### `confiture migrate down-to <revision> --format json`

[migrate-down-to.schema.json](./json-schemas/migrate-down-to.schema.json) — `{from, to, rolled_back, skipped, errors}` for an absolute rollback. An invalid plan (unknown/forward target, or a missing `.down.sql`) emits the [error envelope](./json-schemas/error-envelope.schema.json) and applies nothing.

### `confiture migrate down --format json`

[migrate-down.schema.json](./json-schemas/migrate-down.schema.json) — `{success, rolled_back[], total_duration_ms, checksums_verified, warnings, error}` for a relative rollback (`--steps`). `rolled_back` is newest → oldest, each entry `{version, name, duration_ms, rows_affected}`; it carries the same name as `migrate down-to`'s, so a consumer counting it reads either command. A failure emits the [error envelope](./json-schemas/error-envelope.schema.json) instead.

### `confiture migrate reinit --format json`

[migrate-reinit.schema.json](./json-schemas/migrate-reinit.schema.json) — `{success, deleted_count, marked[], total_duration_ms, dry_run, warnings, error}` after clearing the tracking table and re-marking the migration files as applied.

### `confiture migrate rebuild --format json`

[migrate-rebuild.schema.json](./json-schemas/migrate-rebuild.schema.json) — `{success, schemas_dropped, ddl_statements_executed, marked[], total_duration_ms, dry_run, warnings, error, seeds_applied, verified}` after dropping the schemas, building from DDL and marking every migration applied. `seeds_applied` is `null` unless `--seed` was given, `verified` `null` unless `--verify` ran.

### `confiture migrate baseline --format json`

[migrate-baseline.schema.json](./json-schemas/migrate-baseline.schema.json) — migrations recorded as applied without running them; `mode` names the shape. `through`: `{mode, through, dry_run, migrations[], marked_count, skipped_count}`, each entry `{version, name, status}` with `status` one of `marked`, `would_mark` (`--dry-run`), `already_applied`. `from_db`: `{mode, source, through, copied[], skipped, source_only, warnings, dry_run}` — `copied[]` holds the source ledger's rows `{version, name, applied_at, execution_time_ms, checksum}`, and `source` is the `--from-db` DSN with its password replaced by `***`.

### `confiture migrate apply-as --format json`

[migrate-apply-as.schema.json](./json-schemas/migrate-apply-as.schema.json) — `{success, version, name, applied_by}` for the one migration applied as `<role>` through `apply_as.<role>.url`. A missing URL, an unknown or already-applied version, or a failed migration emits the [error envelope](./json-schemas/error-envelope.schema.json) instead.

### `confiture migrate generate --format json`

[migrate-generate.schema.json](./json-schemas/migrate-generate.schema.json) — the migration written: `{status, version, name, filepath, verify_file, class_name, migrations_dir, next_available_version, snapshot, snapshot_mode, warnings}`, or under `--dry-run` `{status: "dry_run", version, name, filepath, class_name, template, warnings}`. With `--generator` the external generator writes the `.up.sql`, and the payload is `{status, version, name, filepath, generator, resolved_command}` (`status` `dry_run` when it only resolved the command). `--verbose` narrates the directory scan on stderr. An invalid name, an existing file without `--force`, a `--generator` without `--from`/`--to` or not in `migration.migration_generators` (`CONFIG_001`), or a generator that fails (`GEN_001`) emits the [error envelope](./json-schemas/error-envelope.schema.json) instead.

### `confiture migrate fix-signatures --format json`

[migrate-fix-signatures.schema.json](./json-schemas/migrate-fix-signatures.schema.json) — stale function overloads and their fix, `status` naming the shape: `clean` `{message, fixes_applied: 0}`; `unfixable` `{message, fixes_applied: 0, missing_source[]}` at exit 1, when drift remains and nothing has a source definition to fix it with; `dry_run` (`--mode plan`, the default) `{fixes_planned, missing_source[], sql, blocks[]}`; `applied`, or `partial` at exit 1 when the re-check still finds drift, `{fixes_applied, applied[], missing_source[], remaining_drift, remaining_stale[]}`. `--check-body` adds the `body_drift_*` keys to each. A schema auto-build that fails (the build's own code), an unreachable database, or a fix PostgreSQL refuses — the transaction rolled back, `SQL_001` — emits the [error envelope](./json-schemas/error-envelope.schema.json) instead.

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

`status` has three values (since 0.46.0, #213): `issues_found` when any violation
exists, `unverified` when nothing was found **but** at least one
`execute`/`execute_file` call could not be statically read, and `ok` only when
every call was read and nothing was found. `analysis_complete` and
`unanalyzed_count` carry the same fact as data; `unanalyzed_count` counts calls,
not statements, and equals `len(warnings)`. Exit code is unchanged by
`unverified` unless `--fail-on-unanalyzable` is passed; `meta.fail_on_unanalyzable`
records whether it was. Each entry of `warnings[]` carries `reason_code` (the
evaluator's refusal category) and `remedy` (the rewrite that makes the call
readable) in addition to `kind`, `source_file`, `source_line` and `message`.

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
  "analysis_complete": true,
  "unanalyzed_count": 0,
  "meta": {"backend": "ast"},
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

### `confiture migrate validate --require-grant-migration --format json`

[migrate-validate-grant.schema.json](./json-schemas/migrate-validate-grant.schema.json)

Semantic grant-accompaniment report (issue #162): verifies that each *changed* `GRANT`/`REVOKE` in the grant directory is carried by an accompanying migration (`.up.sql` or `.py`). Emitted as a failure envelope. **Not part of the fraisier adapter contract** — provided for completeness.

```json
{
  "status": "failed",
  "check": "grant_accompaniment",
  "is_valid": false,
  "has_grant_changes": true,
  "has_migration_changes": true,
  "grant_files_changed": ["db/7_grant/71_grant.sql"],
  "migration_files_staged": ["db/migrations/20260613130000_x.py"],
  "unmatched_grants": [
    {
      "statement": "GRANT SELECT ON s.t TO reporter",
      "action": "GRANT",
      "objtype": "TABLE",
      "target_kind": "OBJECT",
      "schema": "s",
      "object": "t",
      "grantee": "reporter",
      "privilege": "SELECT",
      "changed_in": "db/7_grant/71_grant.sql",
      "migrations_inspected": ["db/migrations/20260613130000_x.py"]
    }
  ],
  "unverifiable_notes": []
}
```

### `confiture migrate validate --check-function-uniqueness --format json`

[migrate-validate-check-function-uniqueness.schema.json](./json-schemas/migrate-validate-check-function-uniqueness.schema.json)

Static check that every `CREATE FUNCTION` / `CREATE PROCEDURE` across the configured DDL directories has a unique fully-qualified signature. Opt-in via a `function_coverage:` block in the env config. No DB required.

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

### `confiture migrate validate` with two or more checks — the composed envelope

[migrate-validate-composed.schema.json](./json-schemas/migrate-validate-composed.schema.json)

Since 0.40.0 (#187), `migrate validate` runs **every** check the invocation asks
for instead of whichever appeared first in the source. One invocation therefore
produces several payloads, and they go out as one document.

**A single check is unaffected**: it still emits its own payload verbatim — every
schema above holds byte-for-byte. The wrapper appears only for two or more, keyed
by the check's stable machine name, with each value exactly the payload that check
would have emitted alone.

```json
{
  "version": "1",
  "status": "failed",
  "checks": {
    "acl_coverage": { "check": "acl_coverage", "violations": [], "hints": [] },
    "ownership_coverage": {
      "check": "ownership_coverage",
      "violations": [
        {
          "rule_id": "own_001",
          "severity": "error",
          "object_name": "public.orders",
          "message": "…",
          "file_path": "db/migrations/20260527000000_init.up.sql",
          "line_number": 1
        }
      ]
    }
  },
  "hints": []
}
```

`status` is `failed` when any check that ran reported a finding, and the process
exits 1 — the worst outcome across the checks that ran, so a passing check can no
longer mask a failing one. Check names: `list_patterns`, `unmigrated_bodies`,
`git_accompaniment`, `acl_coverage`, `ownership_coverage`, `function_uniqueness`,
`security_definer`, `imports`, `live_drift`, `function_signature_drift`,
`view_body_drift`, `replay_body_drift`, `idempotent`, `naming`.

`--list-patterns` and `--list-unmigrated-bodies` are report modes and refuse to
compose (exit 5, both flags named) — they always exit 0, so they have no result
to combine.

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

### `confiture migrate diff --format json`

[migrate-diff.schema.json](./json-schemas/migrate-diff.schema.json)

The structural changes between the current state (`--from`: a schema file, a directory of DDL files, `-` for stdin, or `db` for the configured database) and the desired state (`--to`: a schema file, a directory such as `fraiseql compile --emit-ddl` writes, or `-`), and the migration written under `--generate`. `source` says where the desired state came from.

```json
{
  "success": true,
  "has_changes": true,
  "changes": [
    {"type": "ADD_TABLE", "details": "ADD TABLE tb_post"}
  ],
  "change_count": 1,
  "migration_generated": true,
  "migration_file": "20260907120000_add_posts.py",
  "error": null,
  "source": {"kind": "sql", "path": "build/ddl"}
}
```

### `confiture migrate steps --format json`

[migrate-steps.schema.json](./json-schemas/migrate-steps.schema.json)

The online runner's checkpoints (#200): one row per (migration, plan, stage) in `<tracking_table>_steps`, and the version `--resume` continued to completion, if any. A `running` row after a crash is the stage to resume from.

```json
{
  "steps": [
    {"migration": "20260101000000", "plan_index": 0, "stage": "expand", "state": "done", "batch_cursor": null, "rows_done": 0, "updated_at": "2026-01-01T00:00:00+00:00"},
    {"migration": "20260101000000", "plan_index": 0, "stage": "backfill", "state": "running", "batch_cursor": 4096, "rows_done": 200000, "updated_at": "2026-01-01T00:00:05+00:00"}
  ],
  "resumed": null
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

> **New in 0.43.0 (#197).** The payload also carries `change_set` — per-change
> risk tiers (`additive` / `reversible` / `lock_risky` / `destructive` /
> `irreversible`). The **object wrapper is load-bearing**: `{"changes": []}`
> means "classified, nothing to change", while an *absent* `change_set` means
> "did not classify". A change confiture cannot tier honestly carries **no
> `tier` key** rather than a guess, and is never dropped from the set. It is
> declared but not required, so older payloads stay valid. See the
> [fraisier adapter contract](./fraisier-adapter-contract.md#per-change-risk-tier-change_set).

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

### `confiture migrate schema-to-schema setup --format json`

[migrate-schema-to-schema-setup.schema.json](./json-schemas/migrate-schema-to-schema-setup.schema.json) — `{ok, command, skip_import, parser}` after creating the FDW server and user mapping on the target and, unless `--skip-import`, importing the source's `public` schema as foreign tables. In every schema-to-schema success payload `command` is the bare subcommand name (`"setup"`), where the error envelope carries the full path (`"migrate schema-to-schema setup"`).

### `confiture migrate schema-to-schema analyze --format json`

[migrate-schema-to-schema-analyze.schema.json](./json-schemas/migrate-schema-to-schema-analyze.schema.json) — `{command, tables, ok, parser}`: each source table by name, `{strategy, row_count, estimated_seconds}`, with `strategy` `copy` at 10,000,000 rows or more and `fdw` below.

### `confiture migrate schema-to-schema migrate --format json`

[migrate-schema-to-schema-migrate.schema.json](./json-schemas/migrate-schema-to-schema-migrate.schema.json) — `{command, strategy, migrated, ok, parser}`: `migrated` maps each entry of the `--mapping` YAML to the rows inserted into its target table.

### `confiture migrate schema-to-schema migrate-table --format json`

[migrate-schema-to-schema-migrate-table.schema.json](./json-schemas/migrate-schema-to-schema-migrate-table.schema.json) — `{command, target_table, rows, ok, parser}` for one table; the payload does not name the strategy.

### `confiture migrate schema-to-schema verify --format json`

[migrate-schema-to-schema-verify.schema.json](./json-schemas/migrate-schema-to-schema-verify.schema.json) — `{command, tables, matched, ok, parser}`: each target table by name, `{source_count, target_count, match, difference}`. A row-count mismatch writes the same shape with `matched: false` and exits 1.

### `confiture migrate schema-to-schema cleanup --format json`

[migrate-schema-to-schema-cleanup.schema.json](./json-schemas/migrate-schema-to-schema-cleanup.schema.json) — `{ok, command, parser}` alone, after dropping the foreign server and foreign schema from the target.

### `confiture drift --format json`

[drift.schema.json](./json-schemas/drift.schema.json)

Live-database drift report against expected DDL.

### `confiture drift --check-acls --format json`

[drift-check-acls.schema.json](./json-schemas/drift-check-acls.schema.json)

Shape is identical to plain `drift` — items of type `missing_grant` / `extra_grant` may appear in `drift_items`.

### `confiture build --format json`

**Schema**: [`build.schema.json`](json-schemas/build.schema.json) — `BuildResult.to_dict()`: files processed, schema size and hash, output and artifact paths, seed files applied, warnings, error.

`warnings[]` carries the build's own diagnostics — what the run has to say that is not a failure — as typed entries `{code, severity, message, file}`, so a consumer matches a code rather than a sentence. Since 1.6.0 (#268); before, the array was published on every run and written to by nothing, and its entries were typed as plain strings. What can appear there today:

| code | severity | when |
|---|---|---|
| `SEED_002` | `warning` | `--sequential` applied seeds and some failed (`--continue-on-error`, or `seed.continue_on_error`). `seed_files_applied` counts the ones that worked; this counts the ones that did not. |
| `SEED_003` | `info` | `--sequential` found no seed files at all. |
| `SCHEMA_206` | `warning` | `--warn-duplicates` / `--fail-on-duplicates` could not parse a file, so it was not checked; `file` names it. |

`severity` is the one the [error-code registry](./error-codes.md) publishes for `code` and is never `error` — a build that failed says so in `error`, not here. A build with nothing to report publishes `[]`.

### `confiture build --list-files --format json`

**Schema**: [`build-list-files.schema.json`](json-schemas/build-list-files.schema.json) — what the build *would* read, and why: `files[]` in build order, each naming the `include_dirs` entry that selected it, that entry's `order` and the include pattern that matched. Nothing is built.

### `confiture lint --format json`

**Schema**: [`lint.schema.json`](json-schemas/lint.schema.json) — `LintReport.to_dict()`: the counts and the violation items (`rule_id`, `severity`, `location`, `file`, `line`, `message`, `suggested_fix`). `file` and `line` are `null` together when the rule read a string rather than a file tree. `gate` reports the `--fail-on` threshold and whether any selected rule could have reached it (#247). `documentation` — present when the `doc` family ran — reports how much of the schema carries a `COMMENT` and the length percentiles of those comments, per rule and for the family, so "100 % documented" can be told apart from "100 restatements" (#250).

### `confiture introspect --format json`

**Schema**: [`introspect.schema.json`](json-schemas/introspect.schema.json) — `IntrospectionResult.to_dict()`: the tables with their columns, foreign keys and hints.

### `confiture sync --format json`

**Schema**: [`sync.schema.json`](json-schemas/sync.schema.json) — `SyncResult.to_dict()`: rows copied per table, the total, and whether values were anonymized.

### `confiture lint-unified --format json`

**Schema**: [`lint-unified.schema.json`](json-schemas/lint-unified.schema.json) — `UnifiedLintResult.to_dict()`: every finding with its tool, file and 1-based line, and under `skipped` each check that was asked for and could not run (a tool not installed, a file it failed on), with the reason.

### `confiture lint --list-rules --format json`

[lint-list-rules.schema.json](./json-schemas/lint-list-rules.schema.json)

The rule catalogue: one entry per rule `confiture lint` can apply, carrying the
`code` that `--select` / `--ignore` accept, its `family`, default severity,
whether it runs by default, the deprecated per-rule flag it replaces (or
`null`), and any configuration it additionally requires (#150). Report mode —
always exits 0, never reads a schema.

`code` matches the `rule_id` field on lint violations, so a finding can be
mapped back to the selector that turns it off.

### `confiture diff --format json`

[diff.schema.json](./json-schemas/diff.schema.json) — `DiffResult.to_dict()`: `{has_changes, summary{}, changes[]}` between two schema files. `summary` counts fifteen kinds (`tables_added`, `columns_dropped`, …), each always present; each `changes[]` entry is `{type, table, column, old_value, new_value, details}`, with the keys a kind does not use `null`. Exit 1 when `has_changes`.

### `confiture bootstrap --format json`

[bootstrap.schema.json](./json-schemas/bootstrap.schema.json) — the ownership plan `{steps[], observed_postgres_owned_schemas, apply_to_schemas, is_empty}` under `plan`, with `mode` naming the shape: `check` adds `drift` (exit 1 when true), `dry-run` (`--mode plan`) has the plan alone, `apply` adds `{success, error, applied_steps}`. A scope refusal or a failed apply emits the [error envelope](./json-schemas/error-envelope.schema.json) instead.

### `confiture install-helpers --format json`

[install-helpers.schema.json](./json-schemas/install-helpers.schema.json) — `{status, schema, functions}` with `status` `installed` or `already_installed`; `--dry-run` reports `dry_run` and adds `sql`, the script it would run.

### `confiture schema dump-model --format json`

[schema-dump-model.schema.json](./json-schemas/schema-dump-model.schema.json) —
`{model, ok, command, parser}`: the schema model below, from DDL, a project's build
or a live database, keys sorted so the same model is the same bytes.

### `confiture test-db provision-template --format json`

[test-db-provision-template.schema.json](./json-schemas/test-db-provision-template.schema.json) — `{name, state, stored_hash, current_hash}` for the template just built (or restored) and stamped with the `db/` hash: `TemplateStatus.to_dict()`, the shape `test-db status` writes, with `state` always `current` and the two hashes equal.

### `confiture test-db status --format json`

[test-db-status.schema.json](./json-schemas/test-db-status.schema.json) — `{name, state, stored_hash, current_hash}`: `state` is `current`, `stale` or `absent` (`stored_hash` is then `null`). The exit code carries the verdict — 0 current, 1 stale or absent — and the shape is the same in all three.

### `confiture test-db clone --format json`

[test-db-clone.schema.json](./json-schemas/test-db-clone.schema.json) — `{template, target, target_url, tablespace}` for a clone made with `CREATE DATABASE … WITH TEMPLATE`. `target_url` has its password redacted; `tablespace` is `null` for an on-disk clone.

### `confiture test-db drop --format json`

[test-db-drop.schema.json](./json-schemas/test-db-drop.schema.json) — `{target, dropped}`: `dropped` is `false`, at exit 0, when the database did not exist. Dropping a database that is not confiture-managed without `--force` writes the [error envelope](./json-schemas/error-envelope.schema.json).

### `confiture test-db list --format json`

[test-db-list.schema.json](./json-schemas/test-db-list.schema.json) — `{databases[]}`, each `{name, kind, detail}`: every confiture-managed database on the server, whichever project made it. `detail` is a template's `db/` hash or a clone's template name.

### `confiture test-db prune --format json`

[test-db-prune.schema.json](./json-schemas/test-db-prune.schema.json) — `{template, dropped[]}`: the clones of the template that were dropped; empty, at exit 0, when none was left.

### `confiture test-db ram-setup --format json`

[test-db-ram-setup.schema.json](./json-schemas/test-db-ram-setup.schema.json) — `{tablespace, location, owner, recreated, action_required, dropped_databases[]}` after (re)creating a tmpfs tablespace. When confiture cannot hand the location to the server's OS user, nothing is created: `action_required` is `true`, `action_command` names the privileged step, and the command exits 5.
### `confiture seed apply --format json`
[seed-apply.schema.json](./json-schemas/seed-apply.schema.json) — `{total, succeeded, failed, failed_files[], success, seed_profile}`: the seed files selected, how many applied, the paths below the seeds directory of those that failed (only under `--continue-on-error`, which exits 0), and the `--profile` applied or `null`. A file that fails without `--continue-on-error` rolls the run back and emits the [error envelope](./json-schemas/error-envelope.schema.json) (`SEED_001`) instead.
### `confiture seed generate --format json`
[seed-generate.schema.json](./json-schemas/seed-generate.schema.json) — `{table, output_path, row_count, column_count, success, error}`: the stub written, or, with `success: false` and exit 1, why none was (the table not found, the file already there without `--overwrite`).
### `confiture seed validate --format json`
[seed-validate.schema.json](./json-schemas/seed-validate.schema.json) — one of two shapes, exit 1 when there are violations. The default checks: `{violations[], violation_count, files_scanned, has_violations}`, each violation `{pattern, sql_snippet, line_number, file_path, suggestion, fix_available}`; with `--fix`, a `fixes[]` of `{file, fixes_applied, written}` says which files were rewritten (`written: false` under `--dry-run`), and stdout holds nothing but the report. The violations are found before `--fix` runs. With `--prep-seed`: `PrepSeedReport.to_dict()`, which adds `scanned_files[]`, `uuid_basis`, `rows_read{}` and `violations_by_severity{}`, each violation `{pattern, severity, message, file_path, line_number, impact, fix_available, suggestion}`. A seeds directory that does not exist emits the [error envelope](./json-schemas/error-envelope.schema.json) (`CONFIG_004`) instead.

### `confiture debug cte --format json`

[debug-cte.schema.json](./json-schemas/debug-cte.schema.json) — `CTEDebugSession.to_dict()`: `{total_ctes, all_succeeded, failed_at, steps[]}`, each step `{cte_name, row_count, columns[], rows[], execution_time_ms, error}` in whole milliseconds. A CTE that fails is the query's finding: exit 1, this shape, `failed_at` naming it. A missing `--sql`/`--file` or a connection failure emits the [error envelope](./json-schemas/error-envelope.schema.json). The `debug` group is experimental; its output may change in any release.

### The schema model (`confiture.platform`)

[schema-model.schema.json](./json-schemas/schema-model.schema.json)

`SchemaModel.to_json()`: the one model of what a schema declares — `tables`,
`enum_types`, `sequences`, `routines` (one entry per overload), `views` and
`triggers` — as `confiture.platform.parse_schema` reads it from DDL and
`confiture.platform.introspect` reads it from a database. Keys are sorted, so one
model is one text, and `SchemaModel.from_json()` reads it back. No command emits
it on its own; it is the wire of the library seam, `confiture.platform`
([Building on confiture](../guides/building-on-confiture.md)).

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
* `HintsArray` — the `hints` field

The `_preflight_defs.schema.json` file holds preflight-specific
sub-schemas:

* `ChangeSet` / `SchemaChange` — the #197 risk-tier change set, referenced by
  both `migrate-preflight.schema.json` and `migrate-preflight-against.schema.json`.
  A cross-repo contract with fraisier-core#44; the five tier values and the
  `contract_version` rule are pinned by `tests/contract/` against the shared
  fixtures in `tests/fixtures/preflight-contract/`
* `DependentAnalysis` — the optional dependent-objects analysis, referenced by
  both `migrate-preflight.schema.json` and `migrate-preflight-against.schema.json`
* `StaticPreflight` — the legacy `PreflightResult.to_dict()` shape. **Unused
  since 0.21.0 (#151)** — the `--against` `static` block it described was folded
  into the unified `issues[]`. Retained for back-reference only.
