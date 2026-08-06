# fraisier migration-adapter contract

`fraisier-adapter-confiture` is the FraiseQL stack's **native, in-process
migration adapter** (fraisier-core PRD §6.3) — the privileged path the Rust
deploy engine uses to run schema migrations, distinct from the generic IPC
subprocess adapters. It drives Confiture by spawning the `confiture migrate`
CLI. This document is the **formal contract** between the two: the subcommands,
flags, JSON shapes, and exit codes the adapter depends on.

Because the adapter lives in a separate repository, Confiture CI cannot see it
directly. The contract is therefore enforced from Confiture's side by
[`tests/contract/test_fraisier_adapter_surface.py`](../../tests/contract/test_fraisier_adapter_surface.py),
which mirrors the adapter's argument construction and report parsing. A drift in
any subcommand's flags, JSON shape, or exit code fails Confiture's own CI.

## Minimum version

The adapter requires **Confiture ≥ 0.20.0** — the release that introduced
`migrate current`, `migrate down-to`, and the `--no-config` env-only DSN mode the
adapter relies on. See the [compatibility policy](#compatibility-policy) below.

**Version-gated capabilities.** Some fields exist only from a given release, and
their *absence* is meaningful rather than an error. The minimum stays where it
is; the adapter gates the capability on the detected version instead. Advertising
a capability the installed binary cannot fulfil turns every deploy into a denial
— safe, but useless.

| Capability | From | Field | Absent means |
|------------|------|-------|--------------|
| `window_safe` | 0.23.0 (#154) | top-level `window_safe` on `preflight` | cannot certify → blocked |
| `risk_tier` | **0.43.0** (#197) | `change_set` on `preflight` | did not classify → denied |

## Invocation shape

Every call the adapter makes follows the same shape:

```
confiture migrate <subcommand> [<args>] --no-config --format json --output <file> [--migrations-dir <dir>]
```

- **`--no-config`** — config-file discovery is suppressed; the environment is the
  *sole* DSN source, so a stray `db/environments/*.yaml` in the deploy workdir can
  never shadow the operator's DSN.
- **DSN via `CONFITURE_DATABASE_URL`** — the secret is injected as an environment
  variable on the child process, **never** in argv (so it cannot leak into a
  process listing, log, or panic message).
- **`--format json` + `--output <file>`** — Confiture writes clean JSON to the
  file while human progress goes to stdout, so the adapter never has to
  disentangle the two. The adapter reads the file first and falls back to stdout.
- **`--migrations-dir`** — passed to every subcommand **except `current`**, which
  reads only the tracking table and has no migration-file inputs (and rejects the
  flag).

## Subcommand surface

| Adapter method     | Confiture command                          | JSON schema |
|--------------------|--------------------------------------------|-------------|
| `current_revision` | `migrate current`                          | [migrate-current](json-schemas/migrate-current.schema.json) |
| `up`               | `migrate up [--target <rev>]`              | [migrate-up](json-schemas/migrate-up.schema.json) |
| `down_to`          | `migrate down-to <rev>`                    | [migrate-down-to](json-schemas/migrate-down-to.schema.json) |
| `verify`           | `migrate verify`                           | [migrate-verify](json-schemas/migrate-verify.schema.json) |
| `preflight`        | `migrate preflight`                        | [migrate-preflight](json-schemas/migrate-preflight.schema.json) |
| `describe`         | `confiture --version` (synthesised)        | — (last whitespace token is the version) |

> ℹ️ **Behaviour advisory — ledger-existence probe, 0.41.0 (#188).** Every
> command above that distinguishes "no ledger" from "empty ledger" — `current`,
> `up`, `verify`, `preflight` — goes through one probe, and that probe changed.
> A **bare** `tracking_table` (the `tb_confiture` default) is now resolved
> through `search_path` instead of matching the name in any schema; a
> schema-qualified one is unchanged.
>
> **No minimum-version bump, and the adapter needs no change.** The answer moves
> in exactly one configuration: a bare name whose ledger sits in a schema *off*
> the connection's `search_path`. That configuration never worked — the probe
> reported present and the next statement failed with `relation "tb_confiture"
> does not exist` (measured on PostgreSQL 17.8). For every configuration that
> functioned before, the probe returns what it always did. `migrate up` gained a
> refusal on this state, but only under `--auto-detect-baseline`, which the
> adapter does not pass.
>
> The adapter-consumed fields and exit codes are untouched. `migrate status` and
> `verify-checksums` gained a `resolved_table` key naming the relation actually
> read; neither command is on this surface.

The adapter-consumed fields per command:

- **current** — `revision` (the head, `null` when none applied).
- **up** — `applied[].version` (the new head).
- **down-to** — `from`, `to`, `rolled_back[]`.
- **verify** — `failed_count` (ok ⇔ `0`) and each `results[].{version, name, status, error}`.
  The `ok ⇔ failed_count == 0` rule is **unchanged** in 0.37.0. That release
  added an optional `ledger_present` boolean: `false` means the database has no
  migration ledger at all — typically built from schema files rather than
  migrated — and is only emitted under `--allow-uninitialized`, since without
  that flag the same state raises `PRECON_1001` (exit 2). It is declared in the
  schema but **not required**, so payloads from earlier versions stay valid.
  Note that the schema sets `additionalProperties: false`, so consumers pinned
  to the pre-0.37.0 schema must update to accept the new field.
- **preflight** — `ok`, the top-level `window_safe` verdict (the typed blue-green
  window-safety contract — see [below](#replica-forward-compatibility-namespace-window-safety-seam)),
  `summary`, each `issues[].{severity, code, message, migration}`, and — since
  0.43.0 — the `change_set` object carrying per-change risk tiers (see
  [below](#per-change-risk-tier-change_set)).

## Replica forward-compatibility namespace (window-safety seam)

fraisier's **blue-green window-safety gate** consumes `migrate preflight` to
decide whether a pending migration is forward-compatible for a two-version
shared-DB cutover window (both N-1 and N served against one Postgres during the
swap). It **blocks the deploy on the presence of any `PFLIGHT_REPLICA_*` issue**
(warning *or* error) in `preflight`'s `issues[]`.

`preflight`'s `ok` flag alone **cannot** certify window safety: the replica lint
is warn-by-default unless `infrastructure.replicas` is declared, so an unsafe
`DROP COLUMN` produces `ok == true` with a `warning`-severity
`PFLIGHT_REPLICA_DROP_COLUMN`. The gate therefore keys on the **code prefix**,
which makes the namespace below a wire contract.

The complete namespace the lint can emit:

| Code | Operation |
|------|-----------|
| `PFLIGHT_REPLICA_ADD_COLUMN` | `ADD COLUMN` NOT NULL / DEFAULT |
| `PFLIGHT_REPLICA_DROP_COLUMN` | `DROP COLUMN` |
| `PFLIGHT_REPLICA_RENAME_COLUMN` | `RENAME COLUMN` |
| `PFLIGHT_REPLICA_CHANGE_TYPE` | `ALTER COLUMN ... TYPE` |
| `PFLIGHT_REPLICA_ADD_CONSTRAINT` | immediate `ADD CONSTRAINT` |
| `PFLIGHT_REPLICA_CREATE_INDEX` | non-concurrent `CREATE INDEX` |
| `PFLIGHT_REPLICA_UNCLASSIFIED` | dynamic / unparseable DDL (always a warning) |

This set is a **stability commitment**: existing codes are **never renamed or
removed** (that is a breaking change requiring a major version bump and a
CHANGELOG note); **new codes may be added**. The set is the single value returned
by `confiture.core.linting.libraries.replica.replica_lint_codes()`, and
[`test_fraisier_adapter_surface.py`](../../tests/contract/test_fraisier_adapter_surface.py)
pins it (`test_replica_code_namespace_is_a_stability_commitment`) against a
hardcoded literal — so a rename fails Confiture's CI instead of silently
disarming fraisier's gate. See the per-code remediation table in
[error-codes.md](error-codes.md#replica-safety-codes-pflight_replica_-lint-replica_001-139).

### Non-SQL (`.py`) migrations are covered

The replica classifier reads SQL (`*.up.sql`). A schema change inside a `.py`
migration is **opaque** to it, so Confiture emits a `PFLIGHT_REPLICA_UNCLASSIFIED`
warning for every `.py` migration — "no replica issue" therefore always means
*inspected-and-safe*, never *never-inspected*. The presence rule covers `.py`
migrations automatically; a downstream gate does not need a separate "refuse any
`.py` in the set" rule.

### Typed verdict: top-level `window_safe`

The preferred surface is the single **top-level** boolean `window_safe` (#154),
which a consumer reads instead of prefix-matching codes:

```json
{ "ok": true, "window_safe": true, "summary": { ... }, "issues": [ ... ] }
```

`window_safe == true` iff confiture certifies **every checked migration** is
forward-compatible for a two-version shared-DB window. It is `false` when any
`PFLIGHT_REPLICA_*` finding is present:

- a replica-unsafe op, **or**
- a non-SQL `.py` migration the classifier could not read
  (`PFLIGHT_REPLICA_UNCLASSIFIED`).

Window-safety is purely **forward-compatibility**, not atomicity. Reversibility
(`PFLIGHT_MISSING_DOWN`) and transactionality (`PFLIGHT_NON_TRANSACTIONAL`) are
reported as their own issues but do **not** gate this verdict — in a blue-green
cutover, rollback is a traffic swap-back to the still-hot old version (no DB
rollback), so a non-transactional `CREATE INDEX CONCURRENTLY` — the canonical
online-migration op — is window-safe. Genuine apply failures are caught at the
migrate step, before any traffic moves.

> ⚠️ **Correctness advisory — false `window_safe: true` on pglast 8.x before 0.39.0.**
> The replica classifier compared `AlterTableType` against hardcoded ordinals.
> PostgreSQL 18 inserted a member, so pglast 8 (uploaded 2026-07-09) renumbered
> everything at index ≥ 13 and every comparison past that point missed. The
> `elif` chain fell through, so `ALTER TABLE … DROP COLUMN` classified to `[]` —
> **no `PFLIGHT_REPLICA_*` finding was emitted, and `window_safe` came back
> `true` for a replica-unsafe migration.**
>
> Affected: installs of the `[ast]` extra resolving pglast ≥ 8.0 between
> 2026-07-09 and 0.37.0's `pglast<8` cap. Installs on pglast 7.x, and any
> install using the regex fallback, were never affected.
>
> Fixed in **0.39.0** (#192): the members are resolved by name, a required CI
> leg runs the classifier suites on both ends of the supported pglast range, and
> a partially-resolvable enum surface now degrades to the regex backend instead
> of under-reporting. Consumers relying on `window_safe` as an authoritative
> allow should be on **≥ 0.39.0**.

So `true` means "every pending op is forward-compatible"; `false` means "unsafe
or uninspectable". The fraisier gate consumes it as
`PreflightReport.window_safe: Option<bool>`: `Some(true)` → allowed
(authoritative), `Some(false)` → blocked, **absent → `None` → blocked**
(fail-safe, so an older confiture that cannot certify is refused, not waved
through). It is present at top level in both the default and `--against` payloads
and pinned in the published schemas + the contract test. The `ok` flag **cannot**
substitute for it: replica findings are warn-by-default, so `ok == true` can
coincide with `window_safe == false`.

## Per-change risk tier (`change_set`)

**Since 0.43.0** (#197), paired with
[fraisier-core#44](https://github.com/fraiseql/fraisier-core/issues/44). The
specification is
[`docs/proposals/migration-risk-contract.md`](https://github.com/fraiseql/fraisier-core/blob/main/docs/proposals/migration-risk-contract.md)
in fraisier-core; this section is the producer-side statement of the same
contract.

`window_safe` answers one question — *can N-1 and N share this database for a
cutover window?* — and deliberately answers nothing else. `change_set` answers a
different one: *what does this migration set do to the data, change by change?*
Both ship; neither replaces the other.

```json
{
  "ok": true,
  "window_safe": true,
  "summary": { "...": "unchanged" },
  "issues": [],
  "change_set": {
    "contract_version": 1,
    "changes": [
      {
        "kind": "drop_column",
        "object": "public.tb_user.legacy_flag",
        "migration": "20260804120100",
        "tier": "irreversible",
        "detail": "DROP COLUMN legacy_flag"
      }
    ]
  }
}
```

### The five tiers

`snake_case` on the wire, ordered least- to most-severe:

| Tier | Meaning | Emitted for |
|------|---------|-------------|
| `additive` | Adds a new object; no existing reader or writer can break. | `CREATE TABLE`, `ADD COLUMN … NULL`, `CREATE INDEX CONCURRENTLY`, `INSERT` |
| `reversible` | Changes existing state, with a down path that restores it. | `RENAME COLUMN`, `SET`/`DROP DEFAULT`, `CREATE OR REPLACE`, `GRANT`, `COMMENT` |
| `lock_risky` | Semantically safe, but takes a lock that can stall a hot table. | non-concurrent `CREATE INDEX`, `ADD COLUMN … NOT NULL`, immediate `ADD CONSTRAINT`, `SET NOT NULL` |
| `destructive` | Destroys data or an object; the loss is bounded and restorable from backup. | `DROP INDEX`, `DROP VIEW`, `DROP CONSTRAINT`, `TRUNCATE`, `DELETE`, `UPDATE` |
| `irreversible` | Destroys data with no down path that can restore it. | `DROP COLUMN`, `DROP TABLE`, `DROP SCHEMA`, `DROP SEQUENCE` |

The ordering exists to pick the worst tier in a set and to sort a plan render
worst-first. **It is not how policy decisions are made** — policy maps each tier
to an action independently.

Boundary rulings, so they are not re-litigated per pull request:

- `DROP INDEX` is `destructive`, not `irreversible` — the index is rebuildable
  from the data it indexes.
- `DROP COLUMN` is `irreversible` **even with a `.down.sql`** — the down path
  restores the schema, not the data.
- A change qualifying for two tiers takes the more severe one.
- `RENAME COLUMN` is `reversible`, not `destructive`. It breaks readers on the
  old name, but that is `window_safe`'s question, and this taxonomy classifies on
  data and DDL grounds. Consumers that need the deployment view read both fields.

### Absence is never safety

Four ways the answer can be missing. None of them mean *proceed*:

| Situation | Wire | Meaning |
|---|---|---|
| Confiture < 0.43.0 | `change_set` key absent | The producer cannot classify at all. |
| Classified, nothing to do | `{"contract_version": 1, "changes": []}` | The producer looked. There is nothing to change. **Safe.** |
| `contract_version` too new | present but unreadable | Treat as absent, and name both versions in the refusal. Never a best-effort parse. |
| One change confiture cannot tier | that entry has no `tier` key | That change is unclassified; the others stay classified. |

Confiture emits **no `tier`** rather than a guess. It does so for a non-SQL
`.py` migration (`kind: "python_migration"`), for `ALTER COLUMN … TYPE` (whose
direction needs the source and target types — preflight has no connection), and
for any statement outside the taxonomy (`kind: "unclassified"`). A statement is
never dropped from the set: a shorter list of fully-classified changes would read
as a *cleaner* plan than the truth, which is the one failure direction this
contract exists to prevent.

### Stability

The five tier values and the `contract_version` rule are a **cross-repo
contract**. Adding a field to a change entry does not bump `contract_version`;
removing or renaming a field, or changing what a tier *means*, does. A sixth tier
is a `contract_version` conversation, not a silent addition — a consumer parses
an unrecognised tier string to *unclassified*, never to a nearest match.

Both repositories test against the same bytes:
[`tests/fixtures/preflight-contract/`](../../tests/fixtures/preflight-contract/)
here, `crates/fraisier-adapter-confiture/tests/fixtures/preflight/` there.
`change_set` is declared but **not required** in the published schema, so
payloads from earlier Confiture stay valid and correctly read as "did not
classify".

## Exit codes

The adapter branches on Confiture's [exit-code convention](exit-codes.md). The
codes it specifically recognises:

| Exit | Adapter handling |
|------|------------------|
| `0` | success |
| `2` (`PRECON_1001`) | a reachable-but-uninitialised DB (no migration ledger). From `current` → "no current revision"; from `verify` and `verify-checksums` → "nothing recorded to verify". **Not an error, and never `InvalidConfig`** — pass `--allow-uninitialized` to get exit 0 instead. |
| `2`, `5` | `InvalidConfig` (configuration problem) — only when the code is **not** `PRECON_1001` |
| `6` (`LOCK_1300`) | migration lock held by another process — **retriable** |
| everything else | execution failure |

The full universe of codes is `0..8`; the contract test asserts every observed
exit code falls within it, and that `PRECON_1001`/`CONFIG_010`/`LOCK_1300` keep
the integer values the adapter hardcodes.

### Machine-readable classification seam

Each exit integer maps to a stable **semantic class** (`ok`, `internal_error`,
`precondition_failed`, `db_unreachable`, `schema_error`, `invalid_config`,
`lock_contention`, `git_error`, `irreversible_rollback`) — the taxonomy both
fraisier adapters project onto their own error types. Confiture is the single
source of truth: the table lives in `EXIT_CODE_SEMANTIC_CLASS`
([`error_codes.py`](../../python/confiture/core/error_codes.py)) and is emitted as
JSON by **`confiture --exit-codes-json`** (see
[exit-codes.md](exit-codes.md#semantic-classes-machine-readable)). The Rust adapter
vendors that JSON and diffs it against the live command in its own contract test;
the Python adapter reads it directly when the installed confiture is new enough.
The class names are frozen — a rename is a breaking change requiring a major bump —
and pinned from confiture's side by
[`test_fraisier_adapter_surface.py`](../../tests/contract/test_fraisier_adapter_surface.py).

## Compatibility policy

The exit-code convention and the JSON shapes above are a **stability contract**
(see [exit-codes.md](exit-codes.md#stability-contract)). Going forward:

- The adapter's minimum is **Confiture ≥ 0.20.0**. Any change that would break
  a subcommand's flags, JSON shape, or exit code for the adapter is a
  **breaking change** requiring a major version bump and a CHANGELOG old→new
  note — and should update the contract test in the same commit.
- New fields may be added to a JSON shape additively; the published schemas pin
  the adapter-consumed fields so a removal or rename is caught in CI.
- **A new field is not a floor bump.** 0.43.0 added `change_set` to `migrate
  preflight` — a command on the surface above — and the minimum stayed at
  0.20.0, because the contract makes the field's absence meaningful (§ [Absence is
  never safety](#absence-is-never-safety)). Raising the floor would delete the
  fail-safe path rather than protect it. Record the release in the
  [capability table](#minimum-version) and gate on the detected version instead.
  Bump the floor only when an older Confiture would be *misread*, not merely
  less capable.
