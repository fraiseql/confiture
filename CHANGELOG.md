# Changelog

All notable changes to Confiture will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.16.1] - 2026-05-27

### Fixed

- **`confiture build` no longer corrupts `CREATE TABLE` bodies when a `--`
  comment sits between table-level `CONSTRAINT … FOREIGN KEY` clauses.**
  The FK extractor was running its regex twice — once on a
  comment-stripped view, once on the original — and the start/end
  whitespace expansion ate the comment's terminating newline, gluing the
  comment onto the previous column line and leaving a trailing comma
  before `)`. Now positions are projected back via an index map, and
  newline consumption is skipped on either side of a comment-only line,
  so the comment stays on its own line and `_fix_trailing_commas` walks
  back through comment/blank lines to find the last data column. FKs are
  still extracted correctly into the Pass-2 ALTER block. Closes
  [#128](https://github.com/evoludigit/confiture/issues/128).

## [0.16.0] - 2026-05-27

Agent-experience punch-list for the idempotency stack. Closes
[#123](https://github.com/fraiseql/confiture/issues/123).

### Added

- **`migrate validate --list-patterns`** — machine-readable catalog of
  every idempotency detection pattern. Read-only (no DB, no config, no
  migrations directory required). JSON output frozen at `version: "1"`,
  documented under `docs/reference/json-schemas/`. Each entry now carries
  `template_fillable: bool` alongside `has_skip_regex`, `skip_hint`, and
  `has_auto_fix`.
- **JSON schemas under `docs/reference/json-schemas/`** — nine schemas
  covering every machine-readable CLI output, plus a shared
  `_common.schema.json` for the `HintsArray` and `BackendMeta` refs.
  Every documented success-path emitter pre-allocates `"hints": []`.
- **`--idempotent` backend banner** — `payload["meta"]["backend"]`
  ("ast" or "regex") in JSON output; a one-line annotated banner in
  text mode so the active backend is never silent.
- **Captures-driven suggestion templates.** Idempotency violations now
  carry copy-pasteable SQL fix templates with captured identifiers
  inlined (schema/table/constraint/column). Both the regex and the AST
  backend feed a normalized `Captures` instance through the shared
  template module, so the rendered suggestion is identical regardless
  of which backend matched.
- **Quiet-success hints.** `migrate validate --idempotent` on an empty
  directory, `migrate status` against a database with no tracking
  table, and `migrate preflight --against` against an empty
  `tb_confiture` now emit advisory hints — stderr in text mode,
  `payload["hints"][…]` in JSON mode. Hints never change exit codes.

### Reference

- New: `docs/reference/json-schemas.md` and the directory of nine
  schemas it links.
- Updated: `migrate-validate-list-patterns.schema.json` documents the
  new `template_fillable` field.

## [0.15.0] - 2026-05-27

Ownership coverage — the ownership axis of the same drift class that
[#120](https://github.com/fraiseql/confiture/issues/120) covered on the
ACL axis. Catches relations that ship with the wrong `pg_class.relowner`
before schema-wide `GRANT` statements blow up in production with
`grantor must own the object`. Closes
[#124](https://github.com/fraiseql/confiture/issues/124).

### Added

- **`ownership:` block in environment YAML.** Single declaration: one
  canonical `expected_owner` per environment, with per-schema `apply_to`
  + `relkinds` filters, an `ignore` glob list, and a `lint_enabled` flag
  (defaults to `True`, opt-in by default).
- **`confiture drift --check-ownership`** — runtime check against
  `pg_class.relowner`. Composes with `--check-acls` and `--schema` in a
  single report. JSON output includes a `wrong_owner` drift type.
- **`migrate validate --check-ownership-coverage`** — static lint rule
  `own_001` that flags `CREATE { TABLE | VIEW | MATERIALIZED VIEW |
  SEQUENCE }` without a matching `ALTER … OWNER TO <expected_owner>`
  later in the same migration file. AST-only (requires the `[ast]`
  extra); a single skip notice is emitted when pglast is missing.
- **`-- confiture:owner-skip`** directive opts the next CREATE out of
  the rule (for genuinely extension-owned objects).
- **`-- confiture:run-as <role>`** front-matter directive skips the
  whole file when the declared role matches `expected_owner`. The
  directive is declarative only — the runtime drift detector is the
  production-time check.
- **`migrate fix --ownership`** — auto-inserts the missing
  `ALTER … OWNER TO` line immediately after each offending CREATE.
  Composable with `--idempotent`. Includes a checksum-drift guard that
  refuses to rewrite already-applied migrations unless `--force` is set.
- **Docs:** `docs/guides/ownership-coverage.md`, sibling to
  `docs/guides/acl-coverage.md` with cross-references.

### Fixed

- **`AclDriftDetector.check()` no longer crashes** with `missing
  FROM-clause entry` on every invocation. The inline
  `"schema"."table"::regclass` was parsed as a column reference; the
  qualified name is now passed as a TEXT parameter through the
  `::regclass` cast (pre-existing bug surfaced when the suite was
  re-run from scratch).
- **`DryRunExecutor.run()` accepts positional `(migration_name,
  statements)`** to match the documented new-API call sites; the legacy
  keyword form remains supported.
- **`ViewManager.recreate_saved_views()` integration tests** updated to
  the `RecreateResult` return type (the previous int-return API was
  replaced before 0.14.0; tests had drifted).

## [0.14.0] - 2026-05-25

`migrate validate --idempotent` now uses PostgreSQL's own parser (via
[pglast](https://github.com/lelit/pglast)) instead of regex. The cutover
closes four regex-specific defects that issue #122 surfaced.

### Fixed

- **Schema-qualified `ADD COLUMN IF NOT EXISTS` no longer produces a
  phantom violation.** Pre-0.14.0, `ALTER TABLE app.users ADD COLUMN IF
  NOT EXISTS email TEXT;` was incorrectly reported as a
  `ALTER_TABLE_ADD_COLUMN` violation because the regex's negative
  lookahead competed with the schema-prefix capture (issue #122 Bug 1).
- **Long identifiers in DROP+CREATE pairs are now recognized as
  idempotent.** The regex pair recognizer truncated `pg_constraint` /
  view / function names past a certain length, so the DROP and CREATE
  appeared to target different objects (issue #122 Bug 2).
- **Quoted identifiers** (`"My-Table"`, `"chk-x"`) are now flagged when
  non-idempotent and matched correctly by pair recognizers. The regex
  backend's `\w+` capture skipped them entirely.
- **Multi-clause `ALTER TABLE` statements** flag every clause. The regex
  backend only saw the first `ADD CONSTRAINT` in a comma-separated list.

### Added

- **Cross-snippet pair recognition for `.py` migrations.** A `DROP X IF
  EXISTS` in one `self.execute()` followed by `CREATE X` in the next is
  now treated as the idempotent pattern (pre-0.14.0 the second call was
  flagged because each snippet went through the detector independently).
- **`CONFITURE_IDEMPOTENCY_FORCE_REGEX=1` escape hatch.** Pins the
  detector to the regex backend for one release. Use if you hit an AST
  regression; the variable will be removed in a future release.

### Changed

- `detect_non_idempotent_patterns` now dispatches to a two-tier
  implementation: pglast-backed `_detect_via_ast` when available,
  regex-only `_detect_via_regex` as the slim-install fallback. The
  public interface is unchanged.
- `IdempotencyValidator.validate_directory` combines all snippets per
  `.py` file before running detection (the change that enables
  cross-snippet pair recognition). `PatternMatch` and
  `IdempotencyViolation` shapes are unchanged — `IdempotencyFixer`
  produces byte-identical `fix()` and `dry_run()` output on both
  backends (verified by `test_backend_dispatch.py`).

### Performance

- AST backend benchmarked against the regex backend over three
  representative fixtures (4 KB → 11 KB schemas, 1000 iterations each):
  AST is faster on the largest file (0.65 ms vs 1.52 ms p95) and ≤1.6×
  slower on the smallest. All measurements under 1.5 ms p95 — well
  under the 50 ms threshold from the cutover plan.

## [0.13.0] - 2026-05-25

`migrate validate --idempotent` overhaul plus a live-DB dependent-objects
check in `migrate preflight`: Python migrations are now scanned, pattern
coverage is broader, `CREATE OR REPLACE` shape-risk heuristics surface a
class of fragile statements that previously slipped through silently, and
the new `--check-dependents` flag closes the transitive-dependent blind
spot by walking `pg_depend` against a live preflight DB.

### Fixed

- `confiture migrate validate --idempotent` now discovers `*.py` Confiture
  migrations alongside `*.up.sql`. Inline `self.execute(...)` and
  `self.execute_file(...)` SQL is extracted via the stdlib `ast` module and
  run through the existing idempotency validator. Mixed `.up.sql` + `.py`
  directories are supported; previously, Python-only migration directories
  reported "✅ No migration files found to validate" and exited 0, making
  any CI gate built on this command a no-op.

### Added — Python migration support

- New `confiture.core.idempotency.python_migration_extractor` module
  (`extract_sql_from_python_migration`) is part of the public API for
  callers who want to do their own preflight checks against Python
  migrations. The extractor never imports or executes the migration file
  — it parses the source with `ast.parse`. `execute_file()` paths are
  bounded to a configurable `project_root`; paths that resolve outside
  the root are rejected with an `EXECUTE_FILE_ESCAPED` warning instead
  of being read.

- Extractor warnings: when a `.py` migration contains dynamic SQL
  (`self.execute(var)`, f-strings with interpolated values), the
  validator emits a structured warning rather than silently treating the
  file as validated. Warnings appear in both human and JSON output
  (`warnings: [...]`, `has_warnings: bool`).

- `IdempotencyViolation.source_line: int | None` — line number within
  the originating `.py` file where `self.execute()` was called. `None`
  for `.sql`-origin violations (back-compat preserved). `to_dict()`
  omits the key when `None`, so JSON output for `.sql`-only runs is
  byte-identical to 0.12.0.

- `confiture migrate fix --idempotent` is now Python-aware: `.py`
  migrations with violations are reported under `manual_fix_required` in
  JSON and listed in text output. `.py` source is **never** written to —
  AST-unparsing would lose formatting and comments.

- `IdempotencyValidator.validate_directory()` now scans `*.py` migrations
  alongside SQL via a new `include_python: bool = True` parameter. Library
  callers that previously relied on the directory glob seeing only `.sql`
  files can pass `include_python=False` for the old behavior.

- `confiture.core.idempotency.is_migration_file` is exported (shared
  between the CLI, the validator, and the fix command).

### Added — pattern coverage

- **New non-idempotent patterns detected by `migrate validate --idempotent`**:
  - `ALTER TABLE … ADD CONSTRAINT <name> CHECK (…)`
  - `ALTER TABLE … ADD CONSTRAINT <name> PRIMARY KEY (…)`
  - `ALTER TABLE … ADD CONSTRAINT <name> UNIQUE (…)`
  - `ALTER TABLE … RENAME COLUMN`
  - `ALTER TABLE … OWNER TO`, `ALTER VIEW … OWNER TO`, and
    `ALTER MATERIALIZED VIEW … OWNER TO` — all flagged together (same root
    cause: the prior `CREATE` may have been rolled back)

  Each new pattern has actionable suggestion text. Auto-fix is **not**
  available — the safe form is a state-dependent DO block that users should
  write by hand.

- `DROP CONSTRAINT IF EXISTS <name>; ALTER TABLE … ADD CONSTRAINT <name> …`
  pairs are now recognized as idempotent and not flagged (matching the
  existing recognizer for `DROP VIEW IF EXISTS` + `CREATE VIEW`).

### Added — CREATE OR REPLACE shape-risk heuristics

- **Info-severity findings** for `CREATE OR REPLACE VIEW`,
  `CREATE OR REPLACE FUNCTION`, and `CREATE OR REPLACE PROCEDURE`
  statements not preceded by a matching `DROP … IF EXISTS`. CoR is
  *almost* idempotent but fails on shape changes (view column add/remove,
  function parameter rename); the heuristic surfaces awareness without
  failing the gate.

- New `--strict-cor` flag on `confiture migrate validate --idempotent`
  treats info-severity findings as blocking (exit 1). Severity stays
  `info`; only the gate's reaction changes.

- `IdempotencyViolation.severity: "error" | "info"` field (default
  `"error"`, so existing constructions are byte-identical). Reflected in
  `to_dict()` always (cheap, avoids consumer ambiguity).

- `IdempotencyReport.has_blocking_violations` property — True only when at
  least one `error`-severity violation exists. Use this in CI gates;
  `has_violations` still counts all severities for back-compat.

### Added — live dependent-objects check in preflight

- New `confiture migrate preflight --check-dependents` flag enumerates the
  views, matviews, functions, and procedures that depend on each
  `CREATE OR REPLACE` target in the pending migrations, via `pg_depend`
  against the `--against` preflight DB. Closes the transitive-dependent
  blind spot that the static CoR heuristic above cannot reach.

  - `--check-dependents=fail` (or just `--check-dependents fail`): exit 1
    when any target has live dependents.
  - `--check-dependents=warn`: render dependents as informational; exit
    code unaffected.
  - Default `off` — no behavior change on upgrade.

- Without `--against`, the check prints a loud "skipped" message and
  exits 0 (deliberately not silent). When `--against` is set but the
  live DB connection fails, the report status flips to `skipped` with a
  `connection_failed` reason.

- `--check-dependents` requires the `[ast]` extra (`pglast`). Without it
  installed, the flag emits a clean install hint and exits with the
  report's `pglast_not_installed` skip reason.

- New public modules: `confiture.core.cor_extractor`
  (`find_cor_targets`, `find_cor_targets_in_file`) — pglast walker for
  CoR targets, supports both `.sql` and `.py` migrations via the Phase 01
  extractor; `confiture.core.dependent_objects`
  (`DependentObjectsChecker`) — runs the `pg_depend` queries.

- New types in `confiture.models.preflight`: `CorTarget`,
  `DependentObject`, `DependentEntry`, `DependentAnalysisReport` — all
  with `to_dict()` for JSON output.

### Contract notes

- `IdempotencyReport.to_dict()` is additive-only across releases. Existing
  keys keep their names and types. Consumers using
  `.get("violations", [])` stay safe; consumers asserting on exact key
  sets must update for the new `warnings`, `has_warnings`,
  `has_blocking_violations`, per-violation `severity`, and per-violation
  `source_line` keys.

### Known limitations

- Quoted identifiers (e.g. `ALTER TABLE "My-Table" ADD CONSTRAINT "chk-x"
  CHECK …`) are not matched by the regex-based detectors. Documented
  per-pattern; a future `pglast`-backed detector will close this gap
  uniformly.
- Multi-clause `ALTER TABLE foo ADD CONSTRAINT a, ADD CONSTRAINT b`
  flags only the first clause. Comma-split parsing belongs in a future
  SQL-AST upgrade.
- Subclassed helpers (`self.run_template(...)` wrapping `self.execute`)
  are not statically detectable. Documented in the migrate-validate
  guide; use `execute()` directly for migration SQL.
- `--check-dependents` covers views, matviews, functions, and
  procedures. Composite types and trigger functions are out of scope
  for this release. The check enumerates dependents — it does not
  predict which will actually break (no static shape diff yet).

## [0.12.0] - 2026-05-22

Post-review tightening of the ACL coverage feature (#120): parser parity
between pglast and sqlparse, correct owner-only directive scoping, an
opt-in lint gate, a consistent library API, fail-loud env-var expansion,
and proper declarative-partition handling.

### Breaking

- `confiture lint` no longer auto-runs the ACL coverage rule when
  `acls:` is configured.  Set `acls.lint_enabled: true` in the
  environment YAML (nested shape) to restore the previous behavior.
  The flat-list YAML form (`acls: [...]`) keeps loading; it simply
  defaults `lint_enabled` to `false`.
- `AclDriftDetector.check()` now returns `DriftReport` instead of
  `list[DriftItem]`.  Migrate library callers by accessing
  `result.drift_items`.
- `AclExpectation` renamed to `AclTableExpectation` to leave namespace
  open for future column- and sequence-level variants.  The old name
  remains importable as a back-compat alias.

### Added

- `confiture migrate validate --check-acls` — canonical spelling on the
  `migrate validate` command.  `--check-acl-coverage` is preserved as a
  deprecated alias.
- Declarative partitioning is handled correctly: partitioned parents
  (`relkind = 'p'`) are included in runtime drift discovery; partition
  children (`relispartition = true`) are excluded from both static lint
  and runtime checks because their grants are inherited from the parent.
- Mixed-case identifiers (`CREATE TABLE "MyTable"`) resolve correctly in
  the drift detector via `psycopg.sql.Identifier`-based quoting; the
  WARNING diagnostic now hints at the casing cause when resolution
  fails.

### Fixed

- **Parser parity:** `MigrationGrantExtractor`'s sqlparse fallback now
  matches the pglast path on multi-target `GRANT a, b, c TO r;`,
  multi-target `DROP TABLE a, b, c;`, `WITH GRANT OPTION` role
  normalization, `PUBLIC` pseudo-role (now emitted as the literal
  `"PUBLIC"` by both paths), and `CREATE TEMP/UNLOGGED TABLE` (TEMP
  tables are excluded from coverage; UNLOGGED tables are included).
- **Owner-only directive scoping:** `-- confiture:owner-only` no longer
  leaks to adjacent or substring-prefix tables.  The directive now
  applies only to the immediately-following `CREATE TABLE`, and
  uppercase / CRLF variants are accepted.  Inline and block-comment
  forms remain unsupported by design.
- **`${VAR}` expansion** now raises `ConfigurationError` on
  `${VAR:-default}`, lowercase var names, unclosed braces, and nested
  forms instead of silently passing them through to psycopg.  The
  error message names the unsupported syntax.

### Docs

- New "Adopting on an existing project" section in
  `docs/guides/acl-coverage.md` with a backfill recipe that emits a
  YAML draft from `information_schema.role_table_grants`.
- "Use sparingly" warning on the `-- confiture:owner-only` directive.
- Exit code table rewritten with one-line cause + one-line operator
  action per row.
- Implementation rationale block trimmed to a single sentence; full
  discussion lives in `python/confiture/core/drift.py`.

### Tests

- New `test_pglast_sqlparse_parity` parametrized harness runs every
  fixture against both backends.  Add a case there to pin both
  backends to the same answer.
- Integration tests for role inheritance, PUBLIC pseudo-role,
  ownership, `WITH GRANT OPTION`, partition handling, and quoted
  mixed-case identifiers.

## [0.11.0] - 2026-05-22

ACL coverage — catch tables that ship without their expected `GRANT`s,
both before they merge (static lint, issue #120 phase 2) and after they
reach a real database (runtime drift, phase 1).

### Added

- **`confiture drift --check-acls`** (#120) — compares live
  `pg_class.relacl` against a new `acls:` block in the environment
  config.  Two distinct query paths kept visually separate by design:
  `MISSING_GRANT` uses `has_table_privilege` (hypothesis-checking; sees
  PUBLIC, inheritance, ownership), `EXTRA_GRANT` uses
  `information_schema.role_table_grants` (enumeration of *direct*
  grants only, so PUBLIC-inherited privileges don't surface as
  extras).  Operates on base tables only (`relkind = 'r'`); views,
  materialized views, and foreign tables are out of scope for v1.
  - `--warn-only` demotes `MISSING_GRANT` to WARNING for progressive
    rollouts.
  - `--schema` is optional when `--check-acls` is set, so the ACL
    check can run on its own.
  - Exit 2 with a helpful message when `--check-acls` is used without
    an `acls:` block in the config.
  - JSON shape preserved — new items live inside the existing
    `drift_items` array.
  - Missing roles emit a single WARNING `DriftItem` instead of
    crashing.

- **`acls:` config block** (#120) — declarative expectation of which
  roles should hold which privileges on which tables:
  ```yaml
  acls:
    - schema: tenant
      apply_to: ALL_TABLES               # or list of relname glob patterns
      ignore: [tb_*_legacy, "*_tmp"]
      grants:
        - role: ${APP_ROLE}              # ${VAR} expansion, missing var fails loud
          privileges: [SELECT, INSERT, UPDATE, DELETE]
  ```
  Pydantic-validated (`extra="forbid"`, privilege whitelist,
  case-normalized).  Same block feeds the runtime check and the static
  lint rule.

- **`confiture lint` / `confiture migrate validate --check-acl-coverage`**
  (#120) — static `ACL001` rule.  Parses every `*.up.sql` in
  `db/migrations/`, builds an `(schema, table) → {(role, privilege)}`
  coverage map from both inline `GRANT`s and the configured global
  grant sweep directory (`db/7_grant/` by default), then flags any
  in-scope `CREATE TABLE` whose expected coverage is incomplete.
  - On by default in `confiture lint` when the environment has an
    `acls:` block; no-op otherwise.
  - Flag-gated in `confiture migrate validate` (parallel to
    `--require-migration` and friends).
  - Two-tier SQL parsing — pglast primary (limit-free, syntax-accurate),
    sqlparse + regex fallback.  Both paths exercised by parameterized
    tests against identical fixtures.
  - Tables created and dropped in the same migration net out.
  - Magic-comment opt-out: `-- confiture:owner-only` in the contiguous
    comment block immediately preceding `CREATE TABLE`.  Line-based
    detection (parser-agnostic; survives `pg_format` re-indenting).
  - Violation messages include a paste-ready `GRANT` statement.

- **Documentation**
  - `docs/guides/acl-coverage.md` — full guide covering runtime and
    static checks, YAML, magic-comment opt-out, CI/CD recipe, and the
    `MISSING_GRANT` / `EXTRA_GRANT` query-path asymmetry.
  - `docs/reference/configuration.md` — `acls:` block reference with
    all options.
  - `docs/reference/cli.md` — `confiture drift` section added;
    `--check-acls`, `--warn-only`, `--check-acl-coverage` flags
    documented.

### Changed

- `_expand_env_vars` lifted from `core/hooks/notifications/config.py`
  into a shared `config/_env_vars.py` module.  One source of truth for
  `${VAR}` expansion across the notifications block, the new `acls:`
  block, and future YAML-fed features.  Notifications behavior
  unchanged.

## [0.10.0] - 2026-05-20

Coordinated release bundling three phases of work plus the
`migrate baseline --from-db` primitive: README repositioning + new reference
docs (Phase 01, #118), `generate scaffold/renumber` hardening + emitter
protocol docs (Phase 02, #111), a full notification rewrite behind a single
YAML config surface (Phase 03, #105–#110), and `baseline --from-db` (#119).

### Added

- **`confiture migrate baseline --from-db <DSN>`** (#119) — copy
  `tb_confiture` rows from another database verbatim, preserving `version`,
  `name`, `applied_at`, `execution_time_ms`, and `checksum`. Removes the
  manual-checkpoint guesswork when refreshing a target from a `pg_restore`
  of another environment.
  - Compatible with `--through <version>` for capping the copy at a known
    checkpoint; the CLI warns when the cap excludes source rows.
  - Filters to the intersection of source-applied versions and locally
    present migration files — orphan source rows surface as warnings rather
    than silently copying history the operator can't reproduce.
  - Optional `--source-table` for when the source's tracking table is
    named differently from the target's.
  - Honours `--dry-run`.

- **Notification hooks — Transport / Renderer / Hook architecture** (#105 #106 #107 #108 #109 #110)
  A single layered architecture replaces five per-service hook classes.
  Configure via the `notifications:` block in the environment YAML:
  ```yaml
  notifications:
    hooks:
      - id: prod-slack
        phase: after_execute
        transport: {type: http, url: ${SLACK_WEBHOOK_URL}, retry: {attempts: 3}}
        renderer: {type: slack, mention_on_failure: "@oncall"}
  ```
  - Transports: `http`, `smtp`, `stdout`.
  - Renderers: `slack`, `discord`, `teams`, `email`, `pagerduty`, `opsgenie`,
    `raw_json`, `jinja`.
  - HTTP retries fire on 5xx + connection errors only; 4xx is final.
  - SMTP passwords use `pydantic.SecretStr`; tracebacks are scrubbed so
    `rich.traceback(show_locals=True)` / Sentry cannot leak the cleartext.
  - PagerDuty + OpsGenie are stateless (one event per migration; success
    resolves the dedup_key, failure triggers).
  - Jinja renderer is opt-in via `notifications.allow_templated_renderers: true`
    with a v1 security envelope (flat-dict context, no block tags, allow-listed
    filters, `threading.Timer` timeout). New optional `[notifications]` extra
    for the Jinja dependency.
  - Discriminated-union validation surfaces typos with the valid options.
  - `${VAR}` substitution fails loud on missing env vars at config-load.
- **`confiture hooks test [--id <id>] [--no-dry-run]`** — fire a synthetic
  event through a configured notification hook for verification.  Defaults
  to dry-run (swaps the configured transport for `StdoutTransport`).
- **Documentation**
  - `docs/guides/notifications.md` — user-facing recipes, one example per renderer.
  - `docs/reference/notification-architecture.md` — three-layer design doc.
  - `docs/reference/notification-context.md` — Jinja context vars + security envelope.
- **Reference + adoption docs landing for Phase 01** (#118): repositioned
  README plus new reference and adoption guides authored against the
  evaluator's missing-section checklist.
- **`generate scaffold` + `generate renumber` hardening** (#111): atomic
  rename, repo-root sandbox enforcement, cross-repo grep refusal without
  `--force`. Emitter protocol documented in
  `docs/reference/emitter-protocol.md`.

### Removed

- **Five per-service notification hook classes**: `SlackNotificationHook`,
  `DiscordNotificationHook`, `TeamsNotificationHook`, `EmailNotificationHook`,
  `WebhookNotificationHook`. The new `confiture.core.hooks.notifications`
  package is the only notification surface. Net deletion: ~1,250 LoC across
  source + tests.

## [0.9.5] - 2026-05-12

### Added

- **`confiture migrate generate --live-snapshot`** — Issue #117
  Snapshot schema via a temporary database + `pg_dump --schema-only`, capturing
  objects created dynamically by DO blocks (e.g. partition tables generated with
  `EXECUTE format(...)`). Static snapshots miss these objects, causing false
  positives in `migrate introspect` and `--auto-detect-baseline`.
  - New `TempDatabase` context manager creates a throwaway PostgreSQL database,
    applies the full schema DDL (including DO blocks), dumps the result with
    `pg_dump`, and drops the temp DB on exit.
  - `pg_dump` output is cleaned: `SET` session variables, `SELECT pg_catalog`,
    `CREATE/COMMENT ON EXTENSION`, and version comments are stripped.
  - Non-fatal fallback: if the live snapshot fails (no DB connection, missing
    `pg_dump`), confiture falls back to a static snapshot with a warning.
  - Config-level default: `migration.live_snapshot: true` in environment YAML.
  - JSON output includes `"snapshot_mode": "live"` or `"static"`.

## [0.9.4] - 2026-04-29

### Added

- **`confiture migrate preflight --against <url>`** — Issue #116
  Test pending migrations against a disposable database (e.g. seeded from
  `pg_dump --schema-only`) and report **all failures in one pass** using
  per-migration SAVEPOINTs. The outer transaction is always rolled back,
  leaving the preflight DB unchanged. Supports:
  - `--config` / `--env` for pending-migration detection from a live tracking table
  - `--since <version>` as a lightweight alternative (no second DB connection)
  - `--allow-non-transactional` to run non-transactional migrations
    (e.g. `CREATE INDEX CONCURRENTLY`) in autocommit mode
  - `--format json` outputs a `{"static": …, "against": …}` envelope
  - Exit 0 if all pass (skipped non-transactional migrations are neutral),
    exit 1 on failures, exit 2 on config/connection errors
  Also adds `PreflightAgainstMigration` and `PreflightAgainstResult` to the
  public API (`from confiture import PreflightAgainstResult`), and
  `MigratorSession.run_against()` as a public method for library callers.

## [0.9.3] - 2026-04-27

### Fixed

- **`migrate up` crash: `'Composed' object has no attribute 'strip'`** — Issue #115
  - `_execute_sql` passed `psycopg.sql.Composable` queries directly to `SQLError`,
    whose constructor called `.strip()` on the SQL, expecting a plain string.
  - Any database error during table initialization, index creation, or migration
    recording was masked by this secondary `AttributeError`.
  - **Fix 1 (engine):** `_execute_sql` now renders the query to a string before
    raising `SQLError`, using `as_string(connection)` with a `as_string(None)` fallback.
  - **Fix 2 (exceptions):** `SQLError.__init__` defensively normalises its `sql`
    parameter so it never crashes regardless of input type.
  - 4 new tests covering both fixes.

## [0.9.2] - 2026-04-27

### Added

- **`Migration.execute_file()`** — Issue #113
  - New method on the `Migration` base class to load and execute SQL from external `.sql` files.
  - Accepts `str` or `Path`, resolves relative to CWD (consistent with CLI conventions).
  - Clear errors for missing files (`FileNotFoundError`) and empty files (`ValueError`).
  - Enables hybrid Python+SQL migrations without inlining hundreds of lines of SQL.

- **`migrate validate --check-imports`** — Issue #114
  - Three-level import validation for pending Python migration modules:
    - **Level 1** (IMP001–IMP002): Catches syntax errors, missing imports, absent Migration subclass.
    - **Level 2** (IMP003–IMP007): Verifies `version`, `name`, `up()`, `down()` are defined and well-formed.
    - **Level 3** (IMP008–IMP009): AST-based static analysis detects calls to nonexistent `self.` methods.
  - **File reference validation** (IMP010–IMP011): Verifies `self.execute_file("path")` references exist on disk; warns on dynamic paths that cannot be validated.
  - Supports `--format json` for CI integration.
  - No database connection required — purely static analysis.

### Technical

- New module: `confiture.core.import_checker` — `ImportChecker`, `ImportCheckResult`, `ImportCheckViolation`.
- 44 new unit tests (11 for `execute_file`, 33 for `--check-imports`).

## [0.9.1] - 2026-04-19

### Added

- **`lint-unified --check tree`** — Issue #112
  - Integrates GEN001–GEN004 file-numbering lint rules into `confiture lint-unified`.
  - New `--schema-dir` option to specify the DDL file tree root (defaults to `db/schema`).
  - New `--overrides-dir` option for GEN004 orphan check.
  - `tree` is included in the default run (no `--check` flag) alongside `safety`, `format`, and `schema`.
  - JSON output includes `"tool": "tree"` on each issue for downstream CI parsing.
  - 7 new unit tests covering flag acceptance, per-rule reporting, JSON output, inclusion/exclusion logic, and `--overrides-dir` forwarding.

## [0.9.0] - 2026-04-16

### Added

- **CLI-Managed SQL Function Tree** (`confiture generate`) — Issue #111
  - **`confiture generate alloc <dir>`** — Returns the next sort-stable numeric filename for a schema subtree. Auto-detects decimal or hex prefix scheme from existing files. Supports `--verb <verb>` suffix, `--json` output, and `--schema-dir` override.
  - **`confiture generate scaffold --from <module:factory>`** — Invokes a pluggable `ConfitureEmitter` to emit function definitions, allocates paths via `TreeAllocator`, and writes generated SQL files with a `-- GENERATED by <marker> on <ISO date>` header. Supports `--dry-run`, `--json`, and `overrides/` mirror to skip manually-curated files.
  - **`confiture generate renumber <old> <new>`** — Moves a file or entire subtree to a new location, recomputes numeric prefixes, and rewrites cross-references across the schema tree. `--dry-run` previews all moves and rewrites without touching disk. Exits 2 if dangling references remain.
  - **Four new lint rules** integrated into `confiture lint`:
    - **GEN001** — Prefix uniqueness: no two files in the same directory share a numeric prefix.
    - **GEN002** — Verb suffix: filenames match the configured `<prefix>_<verb>.sql` pattern.
    - **GEN003** — Gap policy: warns on gaps in prefix sequence when project config forbids gaps.
    - **GEN004** — Orphaned overrides: every file under `overrides/` mirrors a file in the schema dir.
  - `ConfitureEmitter` Protocol and `EmittedFunction` dataclass are importable from `confiture`.

### Technical

- `TreeAllocator` — stateless, deterministic prefix-allocation engine; parallel-branch collisions are resolved at rebase time.
- `ScaffoldOrchestrator` — pluggable emitter orchestration with override-mirror support.
- `TreeRenumber` — atomic rename/rewrite via `RenumberPlan`; never leaves the tree in a half-moved state.
- Type safety: fixed three pre-existing `str | None` slicing errors in checksum display paths and one missing `console` argument in the preflight JSON output path.

## [0.8.22] - 2026-04-03

### Added

- **Additional Notification Hooks** — Extended communication capabilities
  - **EmailNotificationHook**: Send rich HTML emails via SMTP with migration details
  - **TeamsNotificationHook**: Microsoft Teams adaptive cards via webhook
  - **DiscordNotificationHook**: Discord rich embeds with custom bot configuration
  - **WebhookNotificationHook**: Generic HTTP webhook for custom integrations with template support
  - All hooks support selective success/failure notifications and graceful error handling

### Enhanced

- **Hook System**: Added StatementResult export for dry-run result access
- **Builtin Hooks**: Updated exports to include all 6 notification hook types
- **Documentation**: Expanded hook configuration examples and usage patterns

### Technical

- **Backward Compatibility**: Maintained full compatibility with existing hook APIs
- **Type Safety**: All new hooks properly typed with comprehensive test coverage
- **Error Handling**: Consistent failure handling across all notification channels

## [0.8.21] - 2026-04-03

### Added

- **SAVEPOINT-Based Dry-Run Execution** — Phase 1 of reimplementation plan
  - Replaced simulation-only `DryRunExecutor` with real database execution inside SAVEPOINT
  - Executes SQL statements against actual database with guaranteed rollback (no side effects)
  - Increased confidence from 40% to 85% with real constraint validation and timing metrics
  - Per-statement timing, rowcount capture, and detailed error reporting
  - Updated `Migrator.dry_run()` to parse and execute SQL from migration files
  - Enhanced CLI formatters to display per-statement results with rich console output

- **Strategy Plugin Sandbox** — Phase 2 of reimplementation plan
  - Implemented AST-based import checker blocking dangerous modules (`os`, `sys`, `subprocess`, etc.)
  - Added secure execution sandbox with timeout monitoring and error logging
  - Created strategy loading with pre-execution security validation
  - Integrated with `StrategyRegistry.register_from_file()` method
  - Comprehensive test coverage for all security scenarios and edge cases

- **Builtin Migration Hooks** — Phase 3 of reimplementation plan
  - **BackupHook**: Pre-migration `pg_dump` with gzip compression and retention policy
  - **AuditHook**: Post-migration logging with HMAC-SHA256 tamper detection
  - **SlackNotificationHook**: Webhook notifications with failure mentions and color coding
  - **Hook Integration**: Wired hooks into migration engine at `BEFORE_EXECUTE`/`AFTER_EXECUTE` phases
  - **Async/Sync Bridge**: Seamless async hook execution within synchronous migration flow
  - **Production Ready**: All hooks fail gracefully and never block migrations

### Technical Implementation

**Phase 1 - Dry-Run Enhancement**:
- `python/confiture/core/dry_run.py` — Complete SAVEPOINT executor rewrite
- `python/confiture/core/_migrator/engine.py` — Migration engine integration
- `python/confiture/cli/dry_run.py` — Result formatting updates
- `python/confiture/cli/formatters/dry_run_formatter.py` — New formatter
- 4 unit tests covering executor logic, integration, and CLI display

**Phase 2 - Plugin Security**:
- `python/confiture/core/anonymization/plugins/` — Complete security sandbox
- AST-based import checker with blocked modules list
- Strategy loading and execution sandbox with timeout protection
- `StrategyRegistry.register_from_file()` integration
- 6 unit tests covering import validation, sandbox execution, and registry integration

**Phase 3 - Production Hooks**:
- `python/confiture/core/hooks/builtin/` — Three production-ready hooks
- `python/confiture/core/_migrator/engine.py` — Hook triggering integration
- Async hook execution within synchronous migration flow
- 6 unit tests covering hook functionality and integration

### Security & Production Features

- **Import Security**: Blocks 20+ dangerous modules in custom strategies
- **Execution Safety**: Timeout protection and error isolation for strategy plugins
- **Audit Integrity**: HMAC-SHA256 signatures prevent audit log tampering
- **Backup Reliability**: Automated pre-migration backups with retention management
- **Notification Resilience**: Slack webhooks with failure mentions and graceful error handling
- **Migration Safety**: Hook failures never block core migration execution

### Testing & Quality

- **25 new tests** across all components (unit and integration)
- **Clean code** passing Ruff linting and Astral type checking
- **Comprehensive mocking** for external dependencies (PostgreSQL, HTTP, subprocess)
- **Backward compatibility** maintained across all changes
- **TDD approach** with RED→GREEN→REFACTOR→CLEANUP cycles

### Impact

This release transforms Confiture from a basic migration tool into a **production-grade deployment platform** with:

- ✅ **Accurate dry-run testing** with real database validation
- ✅ **Secure plugin ecosystem** for custom anonymization strategies
- ✅ **Enterprise-grade observability** with backups, audit trails, and notifications
- ✅ **Extensible architecture** supporting custom hook development
- ✅ **Zero-downtime deployment capabilities** with comprehensive safety features

## [0.8.20] - 2026-03-31

### Added

- **Three-phase `build_split()` with `superuser_post_dirs`** (issue #104).
  Environment YAML now accepts `superuser_post_dirs` for SQL that requires both
  superuser privileges and existing app objects (e.g. `GRANT SELECT ON table`).
  `build_split()` produces three output files — `schema_{env}_superuser_pre.sql`,
  `schema_{env}_app.sql`, and `schema_{env}_superuser_post.sql` — enabling correct
  privilege separation in production deployments. Routing priority:
  `superuser_post > superuser_pre > app`. Hash computation remains independent of
  directory classification config.

### Changed

- **`SplitBuildResult` fields renamed** for three-phase clarity: `superuser_path` →
  `superuser_pre_path`, `superuser_files` → `superuser_pre_files`,
  `superuser_size_bytes` → `superuser_pre_size_bytes`. New fields added:
  `superuser_post_path`, `superuser_post_files`, `superuser_post_size_bytes`.

- **Split build output file renamed**: `schema_{env}_superuser.sql` →
  `schema_{env}_superuser_pre.sql`.

- **`fastapi` and `httpx` added to dev dependencies** so MCP HTTP server tests
  run during development and CI.

### Fixed

- **MCP HTTP endpoint returned 422** when `fastapi` was installed. Caused by
  `from __future__ import annotations` in `mcp_http.py` which turned FastAPI's
  `Request` type hint into a string, breaking parameter resolution at runtime.

- **6 database-dependent tests moved from `tests/unit/` to
  `tests/integration/`** — drift detector, health check, schema analyzer, and
  strict mode integration tests now live where they belong.

## [0.8.19] - 2026-03-30

### Fixed

- **`compute_hash()` is now explicitly independent of `superuser_dirs`**
  (issue #103). Adding or changing `superuser_dirs` in the environment YAML
  no longer risks invalidating caches or triggering unnecessary rebuilds.
  The hash reflects only file content and paths from `include_dirs`, not
  deployment-time partitioning config. Added regression test.

## [0.8.18] - 2026-03-30

### Fixed

- **`SchemaBuilder` now accepts a pre-loaded `Environment` object**
  (fraiseql/fraiseql#160). `SchemaBuilder(env=env_obj)` no longer calls
  `Environment.load()` on an already-loaded instance.

- **`build_split()` accepts `str | Path` for `output_dir`**
  (fraiseql/fraiseql#161). Passing a plain string no longer raises `TypeError`.

## [0.8.17] - 2026-03-30

### Added

- **`superuser_dirs` config for split schema builds** (issue #100).
  Environment YAML now accepts a `superuser_dirs` list to classify directories
  whose SQL requires PostgreSQL superuser privileges (roles, extensions).
  `SchemaBuilder.build_split()` partitions files into two output files —
  `schema_{env}_superuser.sql` and `schema_{env}_app.sql` — for two-phase
  apply by deployment tools. Existing `build()` is unaffected.

- **`SplitBuildResult` dataclass** in `confiture.models.results` — captures
  paths, file counts, and sizes for both superuser and app outputs.

## [0.8.16] - 2026-03-29

### Fixed

- **`reinit()` no longer fails with NOT NULL violation on `tb_confiture.id`**
  (issue #99). All tracking table INSERTs (`_record_migration`, `mark_applied`,
  `reinit`) now explicitly provide `gen_random_uuid()` for the `id` column
  instead of relying on the table's DEFAULT. This also removes the dependency
  on the `uuid-ossp` extension for the tracking table — `gen_random_uuid()` is
  built into PostgreSQL 13+ with no extension required.

### Changed

- **Tracking table creation uses `gen_random_uuid()`** instead of
  `uuid_generate_v4()`. The `CREATE EXTENSION "uuid-ossp"` call has been
  removed from `initialize()` since it is no longer needed for the tracking
  table. User schemas that depend on `uuid-ossp` are unaffected — they should
  declare the extension in their own DDL files.

## [0.8.15] - 2026-03-29

### Fixed

- **IdempotencyFixer no longer produces `CREATE OR REPLACE VIEW`** (issue #98).
  The fixer rewrote `CREATE VIEW` → `CREATE OR REPLACE VIEW`, which PostgreSQL
  rejects with "cannot change name of view column" when columns are renamed or
  reordered. The safe idempotent pattern is now `DROP VIEW IF EXISTS CASCADE` +
  `CREATE VIEW`. When a `DROP VIEW` already precedes the `CREATE VIEW`, the
  fixer leaves it unchanged.

- **Idempotency validator recognizes `DROP + CREATE VIEW` as idempotent**
  (issue #98). `confiture migrate validate --idempotent` no longer reports
  false positives after `confiture migrate fix --idempotent` has been applied.

### Changed

- **`recreate_saved_views()` is now resilient to partial failures** (issue #98).
  Views that fail to recreate (e.g. after a column rename that invalidates their
  saved definition) are skipped instead of aborting the entire batch. Failed
  definitions are preserved in `confiture.saved_views` with an `error_message`
  column for inspection. The SQL function emits `RAISE NOTICE` diagnostics and
  the Python API returns a `RecreateResult` with `.recreated` / `.failed` lists.

- **`RecreateResult` dataclass** added to `confiture.core.view_manager` with
  structured output (`.to_dict()`) for JSON consumers.

## [0.8.14] - 2026-03-29

### Added

- **Two-pass FK emission for `confiture build`** (issue #94). New `--two-pass`
  CLI flag and `build.two_pass` config option. When enabled, `REFERENCES` and
  `FOREIGN KEY` clauses are stripped from `CREATE TABLE` statements (pass 1)
  and emitted as `ALTER TABLE ADD CONSTRAINT` at the end (pass 2). Eliminates
  cross-schema FK ordering failures without requiring directory restructuring
  or deferred constraints.

### Fixed

- **Multi-line FK constraints now fully stripped in two-pass mode** (issue #95).
  `CONSTRAINT name` on a separate line from `FOREIGN KEY` was left behind,
  producing invalid SQL. The FK extractor now matches against the full table
  body instead of line-by-line, correctly removing multi-line constraints and
  cleaning up trailing commas.

- **Checksum verification crashes on NULL checksum** (issue #96). When a
  migration record in `tb_confiture` has `checksum = NULL` (e.g. manually
  inserted hotfix), `_handle_mismatches` crashed with `TypeError: 'NoneType'
  object is not subscriptable`. NULL checksums are now displayed as `(none)`
  and `ChecksumMismatch.expected` type annotation corrected to `str | None`.

## [0.8.13] - 2026-03-29

### Fixed

- **`_drop_user_schemas` and `_apply_ddl_string` rollback open transactions
  before switching to autocommit** (issue #93). When the connection was in
  `INTRANS` state (e.g. after a tracking table backup), setting `autocommit = True`
  raised `ProgrammingError`. Both methods now call `rollback()` first — a safe
  no-op when no transaction is open.

## [0.8.12] - 2026-03-29

### Fixed

- **`MigratorSession.rebuild()` now forwards `env_config`** (issue #92).
  The session wrapper was not passing the loaded `Environment` config to the
  engine's `rebuild()`, causing `SchemaBuilder` to fall back to `env="rebuild"`
  — a non-existent environment. The session now forwards `self._config` as
  `env_config`, so the correct environment name is used.

## [0.8.11] - 2026-03-24

### Added

- **`MigrationLock` and `LockConfig` public exports** (issue #91).
  Both classes are now importable from the top-level `confiture` package and
  listed in `__all__`. Enables deployment orchestrators to inspect lock state
  without reaching into internal modules.

- **`MigratorSession.is_locked()` and `get_lock_holder()`** convenience methods
  (issue #91). Check whether the migration advisory lock is held and retrieve
  diagnostic info (PID, user, application, client address, session start time)
  about the holder — all without acquiring the lock.

- **`require_reversible` parameter on `MigratorSession.up()`** (issue #89).
  When `True`, runs `preflight()` and aborts with `MigrateUpResult(success=False)`
  listing the irreversible versions before any SQL is executed. Guarantees that
  every applied migration can be rolled back.

- **`--require-reversible` CLI flag on `confiture migrate up`** (issue #89).
  Aborts with exit code 1 if any pending migration lacks a `.down.sql` file.
  Supports `--format json` for structured error output.

- **`dry_run_execute` parameter on `MigratorSession.up()`** (issue #90).
  Runs all pending migrations inside a `SAVEPOINT`, verifies they succeed, then
  rolls back — catching real SQL errors (syntax, constraints, type mismatches)
  without persisting changes. Mutually exclusive with `dry_run`.

- **`dry_run_execute` field on `MigrateUpResult`** (issue #90).
  Distinguishes SAVEPOINT-based verification (`dry_run_execute=True`) from
  analysis-only dry runs (`dry_run=True`). Included in `to_dict()` serialization.

## [0.8.10] - 2026-03-23

### Added

- **Pre-flight migration check** (issue #88).
  New `MigratorSession.preflight()` method and `confiture migrate preflight` CLI
  command that answer four questions before deploying migrations:
  - Are all pending migrations reversible? (`.down.sql` exists)
  - Do any contain non-transactional statements? (`CREATE INDEX CONCURRENTLY`, etc.)
  - Are there duplicate migration versions on disk?
  - Have applied migration files been tampered with? (checksum verification)

- **`MigrationAnalyzer`** — detects non-transactional SQL statements using pglast
  (PostgreSQL's C parser) as primary path and regex as fallback. Detects:
  `CREATE/DROP INDEX CONCURRENTLY`, `ALTER TYPE ... ADD VALUE`, `VACUUM`,
  `CLUSTER`, `CREATE/DROP DATABASE`, `REINDEX CONCURRENTLY`.

- **`PreflightResult` and `MigrationPreflightInfo`** dataclasses with
  `safe_to_deploy`, `all_reversible`, `all_transactional`, `has_duplicates`,
  `has_checksum_mismatches` properties and full `to_dict()` serialization.

- **CLI `migrate preflight`** with rich table output and `--format json` for
  CI/CD integration. Exit code 0 = safe, 1 = issues found.

- Lazy exports: `PreflightResult`, `MigrationPreflightInfo`, `MigrationAnalyzer`
  importable from top-level `confiture` package.

## [0.8.9] - 2026-03-23

### Added

- **Semantic exit codes for `migrate up`, `migrate down`, `migrate generate`** (issue #87).
  Exit codes now differentiate error categories for scripting and CI/CD:
  - `0`: success
  - `1`: generic/unknown error
  - `2`: validation or configuration error (bad flags, missing config)
  - `3`: migration execution error (SQL failure, duplicate versions)
  - `6`: lock/pool error (retriable — another process holds the lock)

  The outer exception handlers in `migrate up` and `migrate down` now use
  `handle_cli_error()` to derive exit codes from the error code registry.

- **CLI reference: `migrate status` exit codes** (issue #85).
  Documents the semantic exit codes (0/1/2/3) that have been available since v0.6.2
  but were missing from the CLI reference.

- **CLI reference: `migrate rebuild` command** (issue #86).
  Full documentation section with usage, options, examples, process steps,
  use cases, and exit codes.

### Changed

- **Project status upgraded to production-ready**. Removed all beta/untested
  disclaimers from README, docs, CLAUDE.md, and ARCHITECTURE.md.

- **README rewritten**. New structure with "Why Confiture?" differentiators,
  library API quick start, and comprehensive feature list covering all v0.5–v0.8.9
  additions (semantic exit codes, `migrate rebuild`, `fix-signatures`, structured
  output, distributed locking, etc.).

- **Documentation updated** across `docs/index.md`, `docs/getting-started.md`,
  `docs/comparison-with-alembic.md`, `docs/api/index.md`, and
  `docs/security/seed-management.md` to reflect production-ready status.
  Updated test count to 4,420+. Comparison table now shows production-tested.

### Fixed

- **`--auto-detect-baseline` now errors on missing or empty snapshots directory**
  (issue #84). Previously printed a warning and silently continued; now exits 2
  with an actionable hint to generate snapshots or remove the flag.

## [0.8.8] - 2026-03-19

### Added

- **`--check-body` flag for `migrate fix-signatures`** (issue #83).
  Extends body-drift remediation to the fix command — not just detection.

  - Dry-run: prints `CREATE OR REPLACE` blocks for each body-drifted function alongside
    any signature-drift `DROP + CREATE` blocks.
  - `--apply`: runs all body CORF statements in the same atomic transaction as signature
    fixes; rolls back everything on any failure.
  - After `--apply`, re-runs body comparison to confirm zero residual drift (exits 1 if
    any drift persists).
  - Body fixes for functions already covered by a `DROP + CREATE` overload fix are skipped
    (the recreate from source already restores the correct body).
  - Functions whose source cannot be found in the schema SQL are reported as
    `body_drift_missing_source` but do not block the transaction.
  - JSON output adds `body_drift_fixes_planned` / `body_drift_fixes_applied`,
    `body_drift_blocks`, `body_drift_applied`, and `remaining_body_drift` keys.
    These keys are absent when `--check-body` is not passed (no breaking change).

### Fixed

- `datetime.utcnow()` deprecated calls replaced with `datetime.now(UTC)` in
  `logging.py`, `metrics.py`, and `metrics_aggregator.py`. Eliminates
  `DeprecationWarning` on Python 3.12+.
- `open_connection`: `config.database_url` now wrapped in `str()` to handle typed
  URL objects (e.g. `pydantic.networks.PostgresDsn`) without implicit coercion errors.
- `# type: ignore[import]` added to optional `fraiseql.data` and `sqlfluff` imports in
  `seed_bridge.py` and `unified_linter.py` to silence `ty` false positives for
  intentionally-absent optional dependencies.

## [0.8.7] - 2026-03-19

### Added

- **`--check-body` flag for `migrate validate --check-signatures`** (issue #82).
  Detects function body drift — cases where a function was modified directly in the
  database (e.g. via an ad-hoc `CREATE OR REPLACE`) without updating the source SQL.

  - `FunctionBodyNormalizer` strips comments, collapses whitespace, and lowercases
    before hashing, so cosmetic differences (formatting, comments, casing) are ignored.
  - `FunctionSignatureParser.parse_with_bodies()` extracts raw dollar-quoted bodies
    alongside signatures; returns `None` for `LANGUAGE C`/`LANGUAGE internal` functions.
  - `FunctionBodyDriftDetector` compares normalised SHA-256 hashes for the intersection
    of source and live signatures; `None`-body functions are counted but never reported.
  - `LiveFunctionCatalog.get_bodies()` fetches `pg_proc.prosrc` from the live DB,
    returning `None` for C/internal languages; caches alongside `get_signatures()` so
    only one DB query is needed per invocation.
  - CLI: `--check-body` requires `--check-signatures` (guard exits 2 otherwise).
    Text output shows source hash vs DB hash with a hint to run `fix-signatures --apply`.
    JSON output adds a `body_drift` key to the existing signature-drift response.
    Exit code 1 if either signature drift **or** body drift is detected.

## [0.8.6] - 2026-03-19

### Fixed

- **False positive in `--check-signatures` with composite-type DEFAULT values** (issue #81).
  The regex parser (`_parse_regex`) had two coupled bugs:
  1. `_FUNC_RE` used `[^)]*` to capture the argument list, which stopped at the first `)`
     inside a `DEFAULT ROW(NULL, NULL, NULL)::mytype` expression, truncating the real args.
  2. `_parse_args_regex` split on all commas, so the `NULL`s inside `ROW(...)` were treated
     as separate parameter types.

  Fixed by introducing `_FUNC_HEADER_RE` (matches the function header up to `(`) and
  `_extract_balanced_args` (scans for the matching `)` tracking paren depth), and
  replacing the naive `split(",")` with a depth-aware comma split that ignores commas
  inside nested parentheses.  Both the `pglast` path (which uses the AST's typed param
  nodes directly) and the regex fallback now produce identical, correct results.

## [0.8.5] - 2026-03-19

### Added

- **`confiture migrate fix-signatures`** — atomic remediation command for stale function
  overloads detected by `--check-signatures` (issue #80).
  - Dry-run by default: generates and prints `DROP FUNCTION <stale> + CREATE OR REPLACE`
    SQL for every stale overload without touching the database.
  - `--apply`: executes all fixes in a single transaction; rolls back on any error.
  - After `--apply`, re-runs signature comparison to confirm zero residual drift.
  - Never drops a function without recreating it: skips overloads whose source definition
    cannot be found in the schema SQL (avoids leaving the function undefined).
  - Same `--env` / `--config` / `--schema` / `--schemas` / `--ssh` / `--format` /
    `--output` flags as `migrate validate --check-signatures`.
  - Supports JSON output (`--format json`) for CI/CD integration.

## [0.8.4] - 2026-03-19

### Security

- **SQL injection via table/column identifiers** — All f-string SQL in `ProductionSyncer`
  (`syncer.py`) and `Migrator` (`_migrator/engine.py`) replaced with `psycopg.sql.Identifier`
  and `psycopg.sql.SQL`. Affects `TRUNCATE`, `ALTER TABLE`, `COPY`, `SELECT`, `INSERT`,
  `DELETE`, `CREATE TABLE`, `CREATE INDEX`, `DROP SCHEMA`, and savepoint operations.
  Table and column names supplied by callers are now always double-quoted by the database
  driver, making injection structurally impossible regardless of input.

- **Connection string injection in `RestoreOptions` table-count check** — `restorer.py`
  built a `conninfo` string with f-string interpolation of `host`, `port`, `dbname`, and
  `username`. Replaced with keyword arguments to `psycopg.connect()`, which are never
  concatenated into a string by the driver.

- **SSH parameter injection in `SshTunnelConfig`** — Added `@field_validator` on `host`
  and `user` fields that reject values containing shell metacharacters. Hostnames must
  match `[a-zA-Z0-9][a-zA-Z0-9\-._]*`; usernames `[a-zA-Z0-9_\-.@]+`. Validation runs
  at config-load time, before any subprocess is spawned.

- **Path traversal via `--env` flag** — `_resolve_config()` in `cli/helpers.py` now
  validates the environment name against `[a-zA-Z0-9][a-zA-Z0-9_\-]*` before constructing
  the `db/environments/{name}.yaml` path. Values containing `../` or absolute path
  components are rejected with a `ConfigurationError`.

- **Git reference injection** — `GitRepository.get_file_at_ref()` and
  `get_changed_files()` now validate refs against a safe character set before passing
  them to `subprocess.run`. Refs containing shell metacharacters raise `GitError`.

- **PostgreSQL reserved words as tracking table name** — `Migrator.__init__` now rejects
  migration table names that are PostgreSQL reserved words (e.g. `select`, `table`,
  `user`). Even though `psycopg.sql.Identifier` quotes them correctly, using reserved
  words as table names causes confusion in ad-hoc SQL. A `ValueError` is raised with a
  suggestion to use a descriptive name like `tb_confiture`.

---

## [0.8.3] - 2026-03-18

### Fixed

- **`migrate validate --require-migration` always reports "no migrations" for `.py` migrations** —
  `MigrationAccompanimentChecker._get_new_migrations()` only matched `.up.sql` files, but
  `confiture migrate generate` produces Python `.py` migration files. Projects using the default
  migration format were always told their DDL changes had no accompanying migrations (Issue #78
  follow-up). The filter now accepts both `.up.sql` and `.py` files (excluding `__init__.py`
  and `_`-prefixed private modules).

---

## [0.8.2] - 2026-03-17

### Fixed

- **`migrate validate` crashes on large schemas** — `SchemaDiffer.parse_schema()` previously
  passed the entire concatenated schema SQL to `sqlparse.parse()` in one call, hitting
  sqlparse's `MAX_GROUPING_TOKENS = 10000` limit when schema files contained bulk `INSERT`
  seed data or many `CREATE TABLE` statements (Issue #78).

  **Primary fix**: pglast (PostgreSQL's own C parser, optional dependency) is now used when
  available — it has no token limits and handles all PostgreSQL DDL accurately. Install with
  `pip install "fraiseql-confiture[ast]"`.

  **Fallback fix**: when pglast is not installed, the sqlparse path now splits SQL into
  individual statements with `sqlparse.split()` and filters to DDL-only before calling
  `sqlparse.parse()` per-statement, keeping each call well within the token budget.

- **`migrate validate --require-migration` exits 1 on parse failure** — when schema parsing
  failed, the accompaniment check propagated the error as a hard validation failure. The
  checker now returns a report with `migration_error` set and `is_valid=True` (check
  skipped ≠ check failed). The CLI prints a yellow `⚠️` warning instead of a red `❌` error.

---

## [0.8.1] - 2026-03-17

### Added

- **`confiture diff` command** — Compare two SQL schema files and report structural
  differences (Issue #75).

  ```bash
  confiture diff --from db/schema/old.sql --to db/schema/new.sql
  confiture diff --from old.sql --to new.sql --format json
  ```

  Exit codes: `0` = no changes, `1` = changes detected, `2` = parse or file error.
  JSON output includes a structured `summary` object with per-category counts
  (tables, columns, indexes, foreign keys, constraints, enums, sequences).

- **Extended schema parser** — `SchemaDiffer` now parses and diffs indexes,
  foreign keys, check constraints, unique constraints, enum types, and sequences
  in addition to tables and columns (Issue #76). Both `ALTER TABLE … ADD CONSTRAINT`
  and inline `CONSTRAINT … FOREIGN KEY / CHECK / UNIQUE` forms inside `CREATE TABLE`
  bodies are supported.

- **`DiffResult` public API export** — `from confiture import DiffResult` now works
  from the top-level package.

### Fixed

- **Silent diff misses for domain/custom column types** — Columns whose type could
  not be mapped to a known `ColumnType` were previously stored as `UNKNOWN` with
  the raw SQL type captured separately, but the differ never compared `raw_sql_type`
  between old and new schemas. Changes between two UNKNOWN types with different raw
  strings, or between UNKNOWN and a known type, now correctly produce a
  `CHANGE_COLUMN_TYPE` change (Issue #77).

---

## [0.8.0] - 2026-03-10

### Added

- **`confiture mcp` command** — Expose Confiture operations and PostgreSQL stored functions as
  MCP (Model Context Protocol) tools, enabling direct agent integration (Issue #68).

  ```bash
  # stdio mode (Claude Code, local agents)
  confiture mcp --database-url $DB_URL --stdio

  # HTTP mode for remote/containerised agents (requires [mcp-http] extras)
  confiture mcp --database-url $DB_URL --port 8080
  # POST http://localhost:8080/mcp  {"jsonrpc":"2.0","id":1,"method":"tools/list"}
  # GET  http://localhost:8080/health
  ```

  Built-in tools (`confiture__*` prefix): `migrate_status`, `migrate_up`, `migrate_down`,
  `schema_introspect`, `drift_check`. PostgreSQL stored functions discovered automatically.

  HTTP transport ships as an optional extra to preserve the minimal psycopg footprint:
  ```bash
  uv add 'fraiseql-confiture[mcp-http]'
  ```

- **`confiture generate stubs` command** — Generate Python type stubs for PostgreSQL stored
  functions, enabling IDE autocompletion and static analysis (Issue #67).

- **`confiture generate pgtap` command** — Generate pgTAP test scaffolding from introspected
  stored functions (Issue #69).

- **`confiture lint` command** — Unified schema linting running Squawk and SQLFluff rules
  across all migration and schema files (Issue #72).

- **`confiture seed generate` command** — Generate seed data via the fraiseql-data bridge,
  transforming UUID-keyed data into BIGINT-keyed COPY format (Issue #71).

- **`confiture debug` command** — CTE step-through debugger for complex queries, letting
  agents inspect intermediate result sets one CTE at a time (Issue #73).

- **`confiture migrate verify` command** — Verify applied migrations using `.verify.sql` sidecar
  files (Issue #65).

  ```bash
  confiture migrate verify -c db/environments/local.yaml
  confiture migrate verify --version 20260228180602 -c db/environments/local.yaml
  confiture migrate verify --format json -c db/environments/local.yaml
  ```

  File format:
  ```sql
  -- db/migrations/20260228180602_add_users.verify.sql
  SELECT COUNT(*) > 0 FROM information_schema.columns
    WHERE table_name = 'users' AND column_name = 'email'
  ```

  Queries run inside SAVEPOINT/ROLLBACK (read-only). DDL/DML in verify files raises
  `VerifyFileError`. Migrations without verify files shown as `SKIP`.

- **`--require-grant-migration` flag on `migrate validate`** — Detects `db/7_grant/` changes
  without a corresponding migration file (Issue #66).

  ```bash
  confiture migrate validate --require-grant-migration --staged
  confiture migrate validate --require-grant-migration --base-ref origin/main
  ```

- **Schema drift detection** — `confiture drift` command and `migrate validate --check-live-drift`
  compare live database schema against DDL source and report divergence.

- **`confiture migrate estimate` / `migrate up --batched`** — Large-table migration support with
  row-count estimation and batched execution to avoid lock exhaustion.

- **Introspection layer** — `FunctionIntrospector`, `TypeMapper`, and `DependencyGraph` now in
  the public API for programmatic schema analysis:

  ```python
  from confiture import FunctionIntrospector, TypeMapper, DependencyGraph
  ```

- **JSON Schema files for all result types** — 16 pre-generated JSON Schema v7 files ship in
  the package, enabling agents to validate structured output without reading source:

  ```python
  from importlib.resources import files
  import json

  schema = json.loads(
      files("confiture.schemas").joinpath("migrate_up_result.json").read_text()
  )
  # or via public API:
  from confiture import generate_schema
  schema = generate_schema("MigrateUpResult")
  ```

  Also available as CLI: `confiture schemas generate --output ./my-schemas/`

- **`IntentRegistry`, `ConflictSeverity`, `IntentStatus` in public API** — Multi-agent
  coordination classes now importable directly from `confiture`:

  ```python
  from confiture import IntentRegistry, ConflictSeverity, IntentStatus
  ```

### Improved

- **Granular `error_code` at public API raise sites** — All `MigrationError`,
  `ConfigurationError`, and `SchemaError` raised from the public API now carry a specific
  error code that agents can pattern-match on:

  | Code | Meaning |
  |------|---------|
  | `MIGR_100` | Migration version not found / not applied |
  | `MIGR_101` | Migration already applied |
  | `MIGR_010` | Lock timeout |
  | `MIGR_011` | Checksum mismatch |
  | `CONFIG_001` | Session used outside context manager |
  | `CONFIG_004` | Config file not found |
  | `CONFIG_010` | Database URL not set |

  ```python
  except MigrationError as e:
      if e.error_code == "MIGR_010":
          retry_with_backoff()
  ```

- **Missing config raises `ConfigurationError` (not `MigrationError`)** — `Migrator.from_config()`
  now raises `ConfigurationError(error_code="CONFIG_004")` when the YAML file does not exist.
  More semantically correct; `error_code` gives agents the exit code and resolution hint.

- **`MigrationVerifier` and `GrantAccompanimentChecker` public API** — Both now importable from
  the top-level `confiture` package.

- **`VerifyFileError` exception** — Raised when a `.verify.sql` file contains forbidden SQL
  (DDL/DML). Importable from `confiture`.

- **`GrantAccompanimentChecker` public API**:

  ```python
  from confiture import GrantAccompanimentChecker

  checker = GrantAccompanimentChecker(grant_dir="db/7_grant")
  report = checker.check_accompaniment(staged_only=True)
  ```

- **`migration.grant_dir` config option** — Override the grant directory path in YAML.

- **CLI restructure** — `python/confiture/cli/` split into focused command modules
  (`schema`, `migrate_core`, `migrate_state`, `migrate_analysis`, `admin`, `drift`);
  no user-visible changes.

- **Codebase hygiene** — Removed ~10,000 lines of orphaned enterprise modules (scenarios,
  workflows, observability, theatre tests). `DryRunExecutor` now correctly reports simulation
  confidence. All `ty` type errors resolved. All stub parameters removed from `MigratorSession`.

### Breaking changes

- `MigratorSession.up()` no longer accepts `dry_run_execute`, `auto_detect_baseline`,
  `snapshots_dir`, or `on_checksum_mismatch` keyword arguments (they were stubs). Use the
  `dry_run=True` parameter instead.
- `Migrator.from_config()` raises `ConfigurationError` (not `MigrationError`) for a missing
  config file.

### Closed

- Issue #64: `BEGIN`/`COMMIT` auto-stripping (fixed in v0.7.0, documented here).
- Issue #65: `confiture migrate verify` command.
- Issue #66: `--require-grant-migration` flag.
- Issue #67: `confiture generate stubs`.
- Issue #68: `confiture mcp` (stdio + HTTP).
- Issue #69: `confiture generate pgtap`.
- Issue #71: `confiture seed generate`.
- Issue #72: `confiture lint`.
- Issue #73: `confiture debug`.

## [0.7.0] - 2026-03-01

### Added

- **`confiture migrate rebuild` command** — Rebuilds database from DDL schema and bootstraps the
  tracking table in a single operation. Designed for staging/QA environments restored from
  production backups where `migrate up` fails due to large migration gaps, lock exhaustion, or
  cumulative DDL complexity.

  ```bash
  # Full rebuild: drop schemas, apply DDL, mark all migrations, apply seeds
  confiture migrate rebuild --drop-schemas --seed --verify --yes

  # Preview what would happen
  confiture migrate rebuild --dry-run

  # Backup tracking table before rebuild
  confiture migrate rebuild --backup-tracking --drop-schemas --yes
  ```

  Key features:
  - `--drop-schemas` — drops all user schemas (CASCADE) and recreates `public`
  - `--seed` — applies seed files after DDL via existing `SeedApplier`
  - `--backup-tracking` — dumps `tb_confiture` to JSON before clearing
  - `--verify` — runs `migrate status` after rebuild to confirm 0 pending
  - `--format json` — structured output following the established `handle_output()` pattern
  - `--dry-run` — shows what would happen without making changes
  - Semantic exit codes: 0 (success), 3 (fatal error)
  - CREATE EXTENSION failures captured as warnings, not errors

- **Python library API for rebuild** — `MigratorSession.rebuild()` provides programmatic access:

  ```python
  from confiture import Migrator

  with Migrator.from_config("db/environments/staging.yaml") as m:
      result = m.rebuild(drop_schemas=True, apply_seeds=True)
      print(f"Applied {result.ddl_statements_executed} DDL statements")
  ```

- **`--check-rebuild` flag on `migrate status`** — Checks whether a full rebuild is recommended
  instead of `migrate up`, based on configurable threshold and strategy headers:

  ```bash
  confiture migrate status --check-rebuild -c db/environments/staging.yaml
  # 🔄 Rebuild recommended:
  #   • 12 pending migrations exceed threshold of 5
  #   • Migration 008_refactor_schema.up.sql has '-- Strategy: rebuild' header
  ```

- **`-- Strategy: rebuild` header** — Migration files can declare their preferred strategy in the
  first 10 lines. Detected by `--check-rebuild` and `find_rebuild_strategy_files()`:

  ```sql
  -- Strategy: rebuild
  CREATE TABLE users (id BIGINT PRIMARY KEY, name TEXT NOT NULL);
  ```

- **`rebuild_threshold` config field** — `migration.rebuild_threshold` in environment YAML
  (default: 5) controls when `--check-rebuild` triggers the rebuild advisory.

- **`BEFORE_REBUILD` / `AFTER_REBUILD` hook phases** — New lifecycle events for hook integrations.

- **`RebuildError` exception** — New exception type for rebuild-specific failures, inherits
  `ConfiturError`.

- **`MigrateRebuildResult` model** — Structured result with `schemas_dropped`, `ddl_statements_executed`,
  `migrations_marked`, `seeds_applied`, `verified`, `warnings`, and `to_dict()` for JSON output.

- **`rebuild_recommended` / `rebuild_reasons` on `StatusResult`** — Populated by `--check-rebuild`
  and included in JSON output.

## [0.6.3] - 2026-03-01

### Fixed

- **Handle explicit `BEGIN`/`COMMIT` in migration SQL files** (#64) — `.up.sql` and `.down.sql`
  files containing explicit transaction control statements no longer break confiture's
  savepoint-based execution. The statements are stripped automatically before execution and a
  `WARNING` is logged so users know to omit them from future migration files.

  Before this fix, running a migration file that started with `BEGIN;` caused:
  ```
  ERROR: savepoint "migration_004" does not exist
  STATEMENT: RELEASE SAVEPOINT migration_004
  ```
  This was a common pain point for teams migrating from workflows where files were applied
  directly via `psql -f`.

  The stripping logic is intentionally narrow: only lines that are *exactly* `BEGIN` or
  `COMMIT` (with optional semicolon and surrounding whitespace, case-insensitive) are removed.
  `BEGIN` appearing inside a comment, string literal, or compound statement is preserved.

### Internal

- Extracted shared `strip_transaction_wrappers()` utility to `confiture.core.sql_utils`.
  Previously this logic existed only inside the external migration generator; it is now reused
  by `FileSQLMigration` as well.

## [0.6.2] - 2026-02-28

### Added

- **Python library API** (#63) - Confiture can now be used as a Python library without going
  through the CLI. `Migrator.from_config()` returns a `MigratorSession` context manager that
  handles connection lifecycle automatically:

  ```python
  from confiture import Migrator

  with Migrator.from_config("db/environments/prod.yaml") as m:
      result = m.status()
      if result.has_pending:
          m.up()
  ```

  New public surface:
  - `Migrator.from_config(config, *, migrations_dir)` — accepts `Environment`, `Path`, or `str`
  - `MigratorSession` — context manager wrapping `Migrator` with connection lifecycle
  - `MigratorSession.status() → StatusResult` — returns structured migration status
  - `MigratorSession.up(**kwargs) → MigrateUpResult` — applies pending migrations
  - `MigratorSession.down(*, steps, dry_run) → MigrateDownResult` — rolls back migrations
  - `MigratorSession.reinit(*, through, dry_run) → MigrateReinitResult` — resets tracking table
  - `StatusResult` and `MigrationInfo` models in `confiture.models.results`

- **Complete JSON output for `migrate status`** (#61) - `--format json` now includes:
  - `tracking_table` field — the configured tracking table name
  - `applied_at` per migration entry — ISO 8601 timestamp for applied migrations, `null` for pending
  - `summary` sub-object — `{applied, pending, total}` counts

- **Semantic exit codes for `migrate status`** (#62) - Exit codes now carry actionable meaning
  for use in deployment scripts:
  - `0` — all migrations applied (up to date)
  - `1` — pending migrations exist
  - `2` — tracking table absent from the target database
  - `3` — fatal error (connection failure, bad config, permission denied)

### Changed

- **`migrate up` JSON key names** (#61) - `MigrateUpResult.to_dict()` now uses canonical names:
  - `migrations_applied` → `applied`
  - `total_execution_time_ms` → `total_duration_ms`
  - `execution_time_ms` (per migration) → `duration_ms`
  - `error` (singular) removed; replaced by `errors: list[str]`
  - `skipped: list[str]` added — versions present in the tracking table that were skipped

- **`migrate reinit` now uses managed connection** (#63) - The `migrate reinit` CLI command
  uses `MigratorSession` internally, ensuring the database connection is always closed even
  when an error occurs.

### Fixed

- **Config attribute access bug in CLI** (#63) - `migrate up`, `migrate down`, `migrate status`,
  and `migrate reinit` accessed `config_data.migration.tracking_table` on the raw `dict` returned
  by `load_config()`. This raised `AttributeError` in production when the YAML file used the
  standard format. A `_get_tracking_table()` helper now handles `Environment` objects, raw dicts,
  and legacy config formats uniformly.

---

## [0.6.1] - 2026-02-28

### Fixed

- **`migration.tracking_table` now respected** (#60) - The tracking table name configured in
  environment YAML was previously defined but silently ignored; all SQL always used the
  hardcoded name `tb_confiture`. Schema-qualified names such as `public.tb_confiture` now flow
  through to every SQL statement (`CREATE TABLE`, `INSERT`, `SELECT`, `DELETE`, index creation)
  and to the `information_schema` existence checks, so `search_path` can no longer redirect
  the table to an unintended schema.

### Changed

- `tracking_table` is now nested under `migration:` (consistent with `strict_mode`, `locking`,
  `view_helpers`, and all other migration options) instead of being a top-level field:

  ```yaml
  migration:
    tracking_table: public.tb_confiture   # was: migration_table: public.tb_confiture
  ```

- `Migrator.__init__` accepts an explicit `migration_table` keyword argument (default:
  `"tb_confiture"`). Invalid names (anything other than letters, digits, underscores, and an
  optional `schema.` prefix) raise `ValueError` immediately, preventing SQL injection through
  configuration.

---

## [0.6.0] - 2026-02-28 ⚠️ Breaking change: Migration version format

### Added

- **Timestamp-based migration versioning** - Migration files now use `YYYYMMDDHHMMSS` format
  instead of 3-digit zero-padded integers. Example: `20260228120530_add_users_table.py`.
  This eliminates the 999 migration limit and prevents merge conflicts in multi-developer
  environments. All existing migrations continue to work unchanged. See GitHub Issue #XX.

- **Fuzzy matching for sparse snapshots** (#58) - `--auto-detect-baseline` now uses structural
  similarity matching (85% threshold, configurable) instead of requiring exact schema match.
  This makes baseline detection work reliably after migration consolidation when only
  boundary snapshots exist (e.g., snapshots for 001 and 015 out of 15 total migrations).
  Database schemas at intermediate states now match their closest snapshot.

- **Proper stderr output for errors** (#59) - Error messages from `confiture migrate up --dry-run`
  and other commands now write to stderr instead of stdout. Deployment automation using
  `subprocess.run(capture_output=True)` can now correctly capture error details on stderr.

### Changed

- **Breaking**: Generated migrations now use timestamp prefixes (14-digit, second precision).
  Migration files generated by prior versions will continue to work alongside new migrations.
  Old-style `001`-style migrations sort before `2026...`-style migrations lexicographically,
  preserving correct execution order.

- `BaselineDetector` now accepts `similarity_threshold` parameter (default: 0.85) for configurable
  fuzzy matching behavior. Exact matches still take priority; fuzzy matching only applies when
  no exact match is found.

---

## [0.5.10] - 2026-02-27

### Added

- `RestoreOptions.parallel_restore` flag: when `True`, automatically sets
  `exit_on_error=False` for parallel restores. FK violations during the data
  phase are transient and non-fatal when running with multiple workers.
  Logs a warning when the override is applied. See #54.
- `RestoreResult.diagnostics`: list of actionable hints emitted when known
  error patterns are detected after the post-data phase. Currently detects
  `"out of shared memory"` and suggests raising `max_locks_per_transaction`
  to 256+ for heavily partitioned schemas. See #55.

### Changed

- `migrate status` now reports all migrations as `"pending"` (not `"unknown"`)
  when the `tb_confiture` tracking table is absent from the target database,
  and exits with code 1 with an actionable advisory message. See #57.

### Fixed

- `migrate status` could not distinguish between "tracking table missing" and
  "migrations applied but nothing recorded". These states now produce different
  outputs and exit codes. See #57.

---

## [0.5.9] - 2026-02-27 ⚠️ Contains breaking CLI change — see below

### Added

- Schema history snapshots: `confiture migrate generate` now writes a DDL snapshot to
  `db/schema_history/` after generating a migration. Opt out with `--no-snapshot`. See #53.
- Auto-detect baseline: `confiture migrate up --auto-detect-baseline` compares the current
  database schema against the nearest snapshot and marks matching migrations as baseline
  without applying them. See #53.
- `confiture migrate introspect` command to inspect live database schema. See #53.
- External migration generator support: `confiture migrate generate --generator <name>`
  delegates diff generation to a configurable external tool. See #49.

### Fixed

- `confiture seed convert` now correctly handles SQL files that contain multiple
  `INSERT` statements. See #44.

### Breaking Changes

- **CLI: `-c` flag now comes after the subcommand name** (#56)

  The config flag for `migrate status` changed position between 0.5.8 and 0.5.9:

  ```sh
  # Before (0.5.8) — no longer works:
  confiture migrate -c config.yaml status

  # After (0.5.9) — required form:
  confiture migrate status -c config.yaml
  ```

  **Migration**: Update any automation scripts or aliases that use the old form.
  The symptom of using the old form is `No such option: -c` at the group level.

  This aligns `-c` with other `migrate` sub-commands and avoids ambiguity with
  the top-level `confiture -c` option.

---

## [0.5.0] - 2026-02-14

### Added

- **COPY Format Seed Loading** - Phase 12 (GitHub Issue #34)
  - Native PostgreSQL COPY format for 2-10x faster seed data loading
  - Automatic format selection: VALUES for small datasets, COPY for large (>1000 rows configurable)
  - `confiture seed convert` command to transform INSERT to COPY format
  - `confiture seed benchmark` command to compare VALUES vs COPY performance
  - `--copy-format` and `--copy-threshold` options for all seed commands
  - Full transaction safety with savepoint isolation per-table
  - Graceful fallback for unconvertible SQL patterns (functions, subqueries, CTEs)
  - Mixed format support (some tables COPY, others VALUES)
  - Integration with `confiture build --sequential --copy-format`

- **Comprehensive Documentation** (2,067 new lines)
  - **docs/guides/copy-format-index.md** - Master navigation guide with learning paths
  - **docs/guides/copy-format-loading.md** - Complete guide (20+ min read)
    - What is COPY format and why it's faster
    - 3 quick start approaches
    - Decision tree for when to use
    - How it works (technical details, escaping, transaction safety)
    - 5 real-world use cases
    - Advanced configuration
    - Troubleshooting and performance tuning
    - Integration examples (Makefile, Docker, GitHub Actions)
    - 10-question FAQ
  - **docs/guides/seed-loading-decision-tree.md** - Strategy selection guide (15+ min read)
    - 4 strategies (Concatenate, Sequential, Sequential+COPY, Pre-converted)
    - Decision matrices by data size
    - Performance tiers (2-10x speedup)
    - Migration paths
  - **docs/guides/copy-format-examples.md** - Practical examples (25+ min read)
    - 8 real-world scenarios with code
    - CI/CD integration (GitHub Actions)
    - Docker deployment
    - Performance comparisons

- **Enhanced CLI Documentation**
  - `confiture seed apply` - Added COMMON USAGE, PERFORMANCE TIPS, DOCUMENTATION references
  - `confiture seed convert` - Added HOW IT WORKS, SPEED IMPROVEMENT, example outputs
  - `confiture seed benchmark` - Added WHEN TO USE, EXAMPLE OUTPUT, NEXT STEPS
  - `confiture seed validate` - Added documentation references
  - All commands now link to detailed guides

### Technical Details

**COPY Format Module**:
- `CopyFormatter` - Converts data to PostgreSQL COPY format
- `CopyParser` - Parses COPY format back to data structures
- `CopyExecutor` - Executes COPY with savepoint isolation
- `SeedBatchBuilder` - Intelligently selects VALUES vs COPY per table
- `PerformanceBenchmark` - Compares VALUES vs COPY performance
- `InsertToCopyConverter` - SQLglot AST-based INSERT→COPY transformation
- `InsertValidator` - Detects SQL patterns that can't be converted

**Testing**:
- 205 comprehensive COPY format tests (99 core + 106 extended)
- All 3,920+ total tests passing
- Real-world scenario coverage
- Performance benchmarking verified

**Features**:
- Automatic format detection (configurable threshold, default 1000 rows)
- Per-table format selection (not all-or-nothing)
- Full transaction safety with SAVEPOINT isolation
- Clear error messages for unconvertible patterns
- Performance metrics in output (time saved, speedup factor)
- Integration with existing sequential execution
- Backward compatible (disabled by default, enabled with `--copy-format`)

### Performance Improvements

- **2-10x faster** seed loading for large datasets
- Performance depends on:
  - Data size (bigger = more improvement)
  - Network latency (better connection = more improvement)
  - Row count (more rows = higher speedup)
- Example: 50K rows in 0.6s (COPY) vs 4.5s (VALUES) = 7.2x faster
- Pre-converted files add zero conversion overhead

### Documentation Highlights

**For Users**:
- Multiple entry points (CLI help, guides, examples)
- Decision support (which strategy to use)
- Copy-paste ready code examples
- Integration patterns (Docker, CI/CD, Makefile)
- Troubleshooting solutions

**For Agents**:
- Clear decision trees (aid reasoning)
- Concrete examples (enable pattern matching)
- Quantified metrics (reduce uncertainty)
- Structured sections (easy parsing)
- Multiple documentation entry points

### Backward Compatibility

✅ **Fully backward compatible**:
- COPY format disabled by default
- Existing workflows unchanged
- Enable with `--copy-format` flag
- All 3,920+ existing tests passing
- No breaking changes to API or CLI

## [0.4.1] - 2026-02-05

### Added

- **Sequential Seed Execution in Build Command** (GitHub Issue #32)
  - New `confiture build --sequential` flag to apply seeds sequentially after schema build
  - Avoids PostgreSQL parser limits when building fresh databases with large seed files
  - Single-command solution for schema + seeds (replaces separate build + seed apply)
  - Respects `seed.execution_mode: sequential` from environment configuration
  - New `--database-url` parameter for database connection during seed application
  - New `--continue-on-error` flag to skip failed seed files and continue
  - Perfect for CI/CD pipelines and fresh database initialization

### Details

**Features**:
- Schema builder now separates schema files from seed files using path heuristic
- New `SchemaBuilder.categorize_sql_files()` method returns (schema_files, seed_files) tuple
- New `SchemaBuilder.build(schema_only=True)` parameter to build schema without seeds
- Build command applies seeds via existing `SeedApplier` infrastructure
- Configuration-driven execution: `seed.execution_mode: sequential` in environment YAML
- CLI flag precedence: `--sequential` > config > default (concatenate)

**CLI Options**:
- `confiture build --sequential`: Apply seeds sequentially after schema
- `--database-url URL`: Database connection URL (required for sequential mode)
- `--continue-on-error`: Skip failed seed files and continue execution
- Works with all existing build flags: `--env`, `--output`, `--show-hash`, etc.

**Examples**:
```bash
# Build schema and apply seeds sequentially
confiture build --sequential --database-url postgresql://localhost/myapp

# Environment-specific
confiture build --env production --sequential --database-url $DATABASE_URL

# With error recovery
confiture build --sequential --continue-on-error --database-url postgresql://localhost/myapp

# Or configure in environment
# db/environments/local.yaml:
seed:
  execution_mode: sequential
confiture build  # Automatically uses sequential mode
```

**Testing**:
- 37 new tests (9 unit + 11 integration + 17 edge cases)
- All 3,803+ total tests passing
- Edge cases: no seeds, large files (650+), nested directories, case variations
- Backward compatible: default behavior unchanged

**Documentation**:
- Updated CLI help with `--sequential` examples
- Added sequential execution section to Build from DDL guide
- New Seed Configuration reference in docs/reference/configuration.md
- Updated Sequential Seed Execution guide with build command examples

### Backward Compatibility

✅ **Fully backward compatible**:
- Default behavior unchanged: `confiture build` still concatenates schema + seeds
- Existing `--schema-only` flag continues to work
- Configuration without `seed.execution_mode` defaults to concatenation
- No breaking changes to API or CLI

## [0.4.0] - 2026-02-04

### Added

- **Sequential Seed File Execution** - Phase 9 (Issue #30 context)
  - **Solves PostgreSQL Parser Limit**: 650+ row seed files now execute without "syntax error at or near ;" errors
  - **Per-File Savepoint Isolation**: Each seed file executes within its own `SAVEPOINT sp_seed_NNN` for error recovery
  - **Continue-on-Error Mode**: Optional `--continue-on-error` flag to skip failed files and continue execution
  - **Transaction Validation**: Rejects seed files containing BEGIN/COMMIT/ROLLBACK commands
  - **Rich Console Progress**: Real-time progress reporting with ✓ (success) and ✗ (failed) indicators
  - **Comprehensive Testing**: 29 new tests (5 configuration + 7 discovery + 8 executor + 9 workflow)
  - **Production-Grade Documentation**: 500+ line guide with 8 practical examples, troubleshooting, best practices

### Details

**Features**:
- New CLI command: `confiture seed apply --sequential`
- Sequential execution mode (opt-in, concatenation is default)
- Per-file transaction isolation with savepoints
- Automatic rollback on failure (no partial data)
- Continue-on-error mode for resilient seeding
- File ordering verification (sorted alphabetically)
- Configuration support via `SeedConfig` in environment YAML

**Components**:
- `SeedConfig` model: execution_mode, continue_on_error, transaction_mode
- `SeedApplier`: File discovery and orchestration
- `SeedExecutor`: Savepoint management and execution
- `SeedError`: Enhanced exception with file context

**Testing**:
- 5 unit tests: SeedConfig model validation
- 7 unit tests: File discovery with sorting and filtering
- 8 integration tests: SeedExecutor with mocks
- 9 end-to-end workflow tests: Real PostgreSQL database
- 650-row batch test: Verified parser limit is solved
- Complex SQL support: CTEs, subqueries, nested queries
- Error scenarios: Rollback, FK violations, transaction rejection
- Transaction isolation: Verified per-file savepoint safety

**Documentation**:
- New guide: `docs/guides/sequential-seed-execution.md`
- Problem statement with real PostgreSQL errors
- Solution explanation with transaction isolation diagrams
- Quick start with 3 usage examples
- Configuration reference (YAML format)
- CLI reference with all options and exit codes
- 8 practical examples (basic, large files, error recovery, complex SQL, etc.)
- Troubleshooting section for common issues
- Best practices for production deployments
- Performance analysis and recommendations

**CLI Options**:
- `confiture seed apply --sequential`: Enable sequential execution
- `--continue-on-error`: Skip failed files and continue
- `--seeds-dir PATH`: Custom seeds directory (default: db/seeds)
- `--env NAME`: Environment name (default: local)
- `--database-url URL`: Explicit database URL

**Examples**:
```bash
# Sequential execution (solve parser limits)
confiture seed apply --sequential --env local

# With error recovery
confiture seed apply --sequential --continue-on-error --env local

# Explicit database
confiture seed apply --sequential --database-url postgresql://localhost/db
```

### Implementation Details

**Transaction Strategy**:
- Outer transaction begins
- For each seed file: `SAVEPOINT sp_seed_NNN`
- Execute file SQL
- On success: `RELEASE SAVEPOINT sp_seed_NNN`
- On error: `ROLLBACK TO SAVEPOINT sp_seed_NNN` and either stop or continue
- Finally: `COMMIT` outer transaction

**Parser Limit Solution**:
- Problem: PostgreSQL's parser accumulates context across concatenated SQL
- Root Cause: Large files (650+ rows) exceed parser capacity
- Solution: Fresh parser state per file via savepoints
- Result: 650-row files now execute successfully

**Error Handling**:
- Automatic rollback prevents partial data
- File context included in error messages
- Optional continue-on-error for resilience
- Clear, actionable error messages with line numbers

**Backward Compatibility**: ✅ 100%
- Default behavior unchanged (concatenation mode)
- Sequential mode is opt-in via `--sequential` flag
- All existing functionality unaffected
- No breaking changes to APIs or configuration

**Performance**:
- Setup overhead: ~10ms per file (savepoint creation)
- Execution time: Same as concatenation
- Cleanup overhead: ~5ms per file (savepoint release)
- Total overhead: ~15ms per 650-row file
- Negligible impact on overall performance

### Statistics

- **New Code**: ~2,800 LOC (implementation + tests + docs)
- **Tests Added**: 29 (all passing, 100% success rate)
- **Real Database Tests**: 9 end-to-end workflows
- **Documentation**: 500+ lines with examples
- **Test Coverage**: 100% of new code
- **Linting**: 0 errors, 0 warnings
- **Type Hints**: Complete on all functions
- **Backward Compatibility**: 100%

### Known Limitations

- Sequential mode best for files up to 10,000 INSERT statements
- For very large datasets (>1M rows): Consider database bulk tools
- Savepoint overhead minimal but present for tiny files
- Continue-on-error only available in sequential mode

### Migration Guide

**For Existing Users**:
1. No action required (backward compatible)
2. Default behavior unchanged
3. To enable sequential: add `--sequential` flag
4. Update configuration (optional): add `seed:` section to environment YAML

**For New Projects**:
1. Use `--sequential` for seed files with 500+ rows
2. Use default concatenation for smaller seeds
3. Add documentation for your seed file organization

## [0.3.18] - 2026-02-04

### Added

- **UNION Query Type Validation** - Issue #29
  - **Level 1 Pre-commit Validation**: Detects UNION queries with inconsistent column types (NULL vs NULL::type)
  - **Type Mismatch Detection**: Catches untyped NULL columns mismatched with typed NULL expressions
  - **Column Count Validation**: Ensures all UNION branches have consistent column counts
  - **Multiple Branch Support**: Validates UNION and UNION ALL with 3+ branches correctly
  - **Performance Optimized**: Regex pre-filter skips non-UNION files for fast pre-commit validation
  - **Comprehensive Error Messages**: Actionable suggestions provided with line numbers

### Details

**Features**:
- Level 1 validator now catches Issue #29 pattern: `SELECT col, NULL::type UNION ALL SELECT col, NULL`
- New `UNION_TYPE_MISMATCH` pattern in `PrepSeedPattern` enum
- Detects both column count and type inconsistencies in UNION branches
- Provides specific error messages with fix suggestions
- ERROR severity blocks deployment while allowing batch validation

**Implementation**:
- Regex-based parsing for fast pre-commit validation (~1-5ms per file)
- Handles `INSERT INTO prep_seed.table SELECT ... UNION [ALL] SELECT ...` patterns
- Robust column extraction respecting nested parentheses and function calls
- Line number tracking for precise error reporting

**Testing**:
- 6 new unit tests covering UNION scenarios (100% pass rate)
- Tests for NULL type mismatches, UNION/UNION ALL variants, multi-branch scenarios
- All 104 seed validation tests passing
- Integration tests verify orchestrator integration

**Backward Compatibility**: ✅ 100% backward compatible - new validation adds early error detection without breaking existing features

## [0.3.17] - 2026-02-04

### Added

- **CLI Flags for Comment Validation & File Separators** - Issue #28
  - **Comment Validation Flags**: `--validate-comments`, `--no-validate-comments`, `--fail-on-unclosed`, `--fail-on-spillover`
  - **Separator Style Flags**: `--separator-style` (block_comment, line_comment, mysql, custom), `--separator-template`
  - **CLI Flag Overrides**: All flags override environment config when provided, with visual confirmation
  - **Comprehensive Testing**: 13 new unit tests covering all flag combinations and edge cases
  - **Documentation**: Updated CLI reference with new flags, added CI/CD patterns, enhanced build-validation guide
  - **Example Project**: New `examples/07-comment-validation/` with README and automated test scenarios

### Details

**Features**:
- Comment validation can now be toggled per-build with `--validate-comments` / `--no-validate-comments`
- Stricter modes: `--fail-on-unclosed` and `--fail-on-spillover` for production builds
- Separator style can be overridden: `--separator-style block_comment|line_comment|mysql|custom`
- Custom separator templates: `--separator-template "\\n/* {file_path} */\\n"`
- Visual confirmation when CLI flags override config

**Testing**:
- 13 new unit tests for CLI flag behavior
- 12 integration tests for validation pipeline
- 3,748 total tests passing
- All flag combinations tested
- Invalid input validation tested

**Documentation**:
- CLI reference updated with complete options table
- Comment Validation Flags section with 6 examples
- Separator Style Flags section with 4 examples
- CI/CD Patterns section showing production workflows
- Build validation guide enhanced with CLI override examples
- Example project demonstrates real-world scenarios

**Backward Compatibility**: ✅ 100% backward compatible - all flags optional, environment config as default

## [0.3.16] - 2026-02-04

### Added

- **Enhanced `confiture migrate generate` Command** - Critical safety validations and agent-friendly features
  - **Safety Validations**: Duplicate version detection, file existence checks, name conflict detection, concurrent creation protection with file locking
  - **Agent-Friendly Features**: JSON output format (`--format json`), dry-run mode (`--dry-run`), verbose debugging (`--verbose`)
  - **Comprehensive Testing**: 32 new tests (17 unit + 15 integration), 100% passing with no regressions
  - **Documentation**: Complete guide with examples for all features, safety patterns, and CI/CD automation

### Details

**Validation Safety**:
- Detects duplicate version numbers and warns users
- Prevents accidental file overwrites
- Detects same migration name in different versions
- File locking prevents race conditions in CI/CD pipelines

**Agent Features**:
- `--format json` outputs structured JSON for programmatic parsing
- `--dry-run` previews migration without creating files
- `--verbose` shows version calculation and directory scanning details

**Quality**:
- 17 new unit tests for validation logic
- 15 new integration tests for CLI features
- 431 migration-related tests passing
- 3,248 unit tests with zero regressions
- All linting checks pass

**Documentation**:
- New "Generating Migration Files" section in incremental migrations guide
- Examples for dry-run, verbose, and JSON modes
- Safety features documentation
- CI/CD automation patterns

**Backward Compatibility**: ✅ 100% backward compatible - text output remains default

## [0.3.15] - 2026-02-03

### Fixed

- **Rust Schema Builder Trailing Newline Bug** - Fixed issue where SQL files without trailing newlines could produce invalid SQL when concatenated
  - Added defensive check to ensure final output always ends with newline per POSIX standard
  - Prevents SQL parsing issues with PL/pgSQL dollar-quoted functions (`$$...$$`)
  - Handles edge cases: empty files, whitespace-only files, mixed newline scenarios
  - Added 8 comprehensive edge case tests to catch similar issues
  - Rust and Python implementations now have identical behavior for all file variations
  - Particularly important for large codebases with auto-generated SQL files (e.g., 376+ files)

## [0.3.14] - 2026-01-31

## [0.3.13] - 2026-01-31

## [Unreleased]

## [0.3.11] - 2026-01-29

### Added - Git-Aware Schema Validation

**New Commands and Flags**:
- `confiture migrate validate --check-drift` - Detect schema differences between git refs
- `confiture migrate validate --require-migration` - Ensure DDL changes have corresponding migration files
- `confiture migrate validate --base-ref <ref>` - Compare against specific git reference (branch, tag, commit)
- `confiture migrate validate --since <ref>` - Alias for `--base-ref`
- `confiture migrate validate --staged` - Validate only staged files (pre-commit hook mode)

**New Core Modules**:
- `GitRepository` class - Interface to git operations via subprocess
  - `get_file_at_ref()` - Retrieve file content from specific git refs
  - `get_changed_files()` - List files changed between git refs
  - `get_staged_files()` - List currently staged files
  - `is_git_repo()` - Check if in git repository
- `GitSchemaBuilder` class - Build schemas from files at specific git refs
- `GitSchemaDiffer` class - Compare schemas between refs
- `MigrationAccompanimentChecker` class - Validate DDL changes have migration files
- `MigrationAccompanimentReport` data model - Structured validation results

**Use Cases**:
- Pre-commit hooks for schema validation (<500ms for staged files)
- GitHub Actions CI/CD pipelines
- GitLab CI integration
- Code review gates (prevent merging without proper migrations)
- Local development validation

**Features**:
- Schema drift detection - Find untracked schema changes
- Migration enforcement - Require migration files for every DDL change
- Flexible git references - Compare against branches, tags, commits, relative refs (HEAD~10)
- Performance optimized - <500ms for pre-commit, <5s for full repo
- JSON output support for CI/CD automation
- Text and JSON output formats
- Proper exit codes (0: pass, 1: validation failed, 2: error)

**Documentation**:
- Comprehensive user guide: docs/guides/git-aware-validation.md (850+ lines)
  - Quick start examples
  - 4 detailed use case sections (pre-commit, GitHub Actions, GitLab CI, code review)
  - Complete command reference
  - Decision tree for choosing right flags
  - 4 detailed common scenarios with solutions
  - Performance tips for large repositories
  - Complete troubleshooting guide
  - API reference with Python code examples
  - Best practices and glossary
- Updated CLI reference with all git-aware validation flags
- Updated getting-started guide with validation section and 5-minute pre-commit setup
- Updated README.md with feature announcement
- Updated docs/index.md with guide links

### Quality & Testing

**Test Coverage**:
- 24 comprehensive tests (unit + integration)
- GitRepository: 8 unit tests for all git operations
- Schema building: 6 unit tests for building and comparing schemas
- Migration validation: 5 unit tests for accompaniment checking
- CLI integration: 5 integration tests for flag combinations
- 100% coverage for new modules

**Code Quality**:
- Full type hints throughout (Python 3.11+ union syntax)
- Complete docstrings with examples
- All linting passes (ruff)
- All type checking passes (ty)
- Proper error handling with timeouts on all git operations
- No new dependencies added

**Security**:
- Input validation on all git operations
- Subprocess timeout protection (10-30 seconds)
- No command injection (list-based args, no shell=True)
- No hardcoded credentials or secrets

### Backward Compatibility

- ✅ No breaking changes
- ✅ All new flags are optional
- ✅ All new features are additive
- ✅ Existing `confiture migrate validate` behavior unchanged

## [0.3.10] - 2026-01-29

### Fixed - Type Safety and Quality Improvements

**Type Checking**:
- Resolved all 102 type checking diagnostics (ty type checker)
- Fixed null handling for `cursor.fetchone()` calls (13+ locations)
- Fixed return type annotations in migrator
- Fixed method signature compatibility (LoggerAdapter.process)
- Corrected type hints for generator cleanup handlers
- Suppressed optional dependency import errors (prometheus_client, opentelemetry)

**Development Cleanup**:
- Removed development archaeology (TODO markers, phase/week/day references)
- Removed 6 tracked `.claude/` phase planning artifacts from git
- Added `.claude/*.md` to .gitignore for local development notes
- Replaced deprecated `mypy` with `ty` in Makefile

**Documentation Fixes**:
- Fixed broken README link (cli-dry-run.md → dry-run.md)
- Cleaned up development phase references in performance and security docs

**CI/CD**:
- Fixed GitHub Actions type-check job (removed unnecessary pip caching)
- All 18 quality gate checks now passing

### Testing

- All 2,861 unit tests passing
- All ruff linting checks passing
- Type checking clean (ty diagnostics: 0)
- Connection pool stats mock updated to use dict-like access

### Backward Compatibility

- ✅ No breaking changes
- ✅ No API changes
- ✅ All existing functionality preserved

## [0.3.9] - 2026-01-27

### Added - Migration File Validation and Auto-Fix

**Migration Validation**:
- `confiture migrate validate` - Comprehensive migration file validation command
- Orphaned migration file detection (missing `.up.sql` suffix)
- Auto-fix capability with `--fix-naming` flag
- Dry-run preview mode with `--dry-run` flag
- JSON output support for CI/CD integration
- Safe file renaming (atomic operations, error handling)

**Warnings in Existing Commands**:
- `confiture migrate status` - Shows orphaned files in text and JSON output
- `confiture migrate up` - Warns before applying migrations
- `--strict` mode - Fail if orphaned files exist

**New Migrator Methods**:
- `find_orphaned_sql_files()` - Detect misnamed migration files
- `fix_orphaned_sql_files()` - Safely rename files to match pattern

**Documentation**:
- New comprehensive guide: "Migration Naming Best Practices" (500+ lines)
- Updated CLI reference with validate command documentation
- Updated troubleshooting guide with orphaned files section
- Updated incremental migrations guide with naming requirements
- CI/CD pipeline integration examples
- Real-world scenarios and troubleshooting FAQ

### Features

**Three Recognized Migration Patterns**:
```
{NNN}_{name}.py             # Python migrations
{NNN}_{name}.up.sql         # Forward migrations
{NNN}_{name}.down.sql       # Rollback migrations
```

**Auto-Fix Workflow**:
```bash
# Detect orphaned files
confiture migrate validate

# Preview fixes
confiture migrate validate --fix-naming --dry-run

# Apply fixes
confiture migrate validate --fix-naming

# CI/CD integration
confiture migrate validate --format json
```

### Testing

- 8 new tests for validate command (6 CLI + 2 Migrator)
- Dry-run mode tests
- JSON output tests
- Auto-fix tests with content preservation
- 2,660 unit tests passing
- Full backward compatibility verified

### Issue Resolution

- Resolves [GitHub Issue #13](https://github.com/evoludigit/confiture/issues/13) - Migration Discovery Validation
- Three-phase implementation:
  - Phase 1: Detection and warnings
  - Phase 2: Validation command with auto-fix
  - Phase 3: Comprehensive documentation

### Backward Compatibility

- ✅ No breaking changes
- ✅ All existing migrations continue to work
- ✅ Warnings are non-blocking (informational only)
- ✅ New features are opt-in
- ✅ Full backward compatibility verified

## [0.3.8] - 2026-01-22

### Added - Multi-Agent Coordination System (Phase 4)

**Core Coordination Features**:
- **Intent Registry**: Declare schema change intentions before implementation
- **Automatic Conflict Detection**: Analyzes DDL for 6 conflict types (TABLE, COLUMN, FUNCTION, INDEX, CONSTRAINT, TIMING)
- **Branch Allocation**: Unique pgGit branch assignment for each intent
- **Status Tracking**: Complete lifecycle management (REGISTERED → IN_PROGRESS → COMPLETED → MERGED)
- **Audit Trail**: Full history of all coordination decisions and status changes
- **Resolution Workflows**: Guided conflict resolution with actionable suggestions

**CLI Commands** (`confiture coordinate`):
- `register` - Declare intention to make schema changes
- `list-intents` - View all registered intentions with filtering
- `status` - Get detailed status of specific intention
- `check` - Pre-flight conflict check before registration
- `conflicts` - List all detected conflicts
- `resolve` - Mark conflict as reviewed with resolution notes
- `abandon` - Abandon intention with reason tracking

**JSON Output Support**:
- `--format json` flag for all coordinate commands
- Machine-readable output for CI/CD integration
- Parsing examples for Bash (jq), Python, Node.js
- Backward compatible (defaults to Rich-formatted text output)

**Database Schema** (Trinity Pattern):
- `tb_pggit_intent` - Intent storage with JSONB metadata
- `tb_pggit_conflict` - Conflict tracking and resolution
- `tb_pggit_intent_history` - Complete audit trail of status changes
- Optimized indexes for sub-millisecond queries

**Performance**:
- Intent registration: ~1.3ms (76x faster than target)
- Conflict detection: <1ms even with 100 active intents
- Database queries: <1ms for most operations
- Linear scaling: 1,000 intents in 1.54s
- 18 comprehensive performance benchmarks
- Production-ready without optimization

**Documentation**:
- Architecture documentation (1,030 lines) - Complete system design
- User guide (1,056 lines) - CLI commands, workflows, best practices
- Performance benchmarks (454 lines) - Detailed analysis and recommendations
- 3 executable example workflows
- JSON integration examples

**Testing**:
- 123 coordination tests (unit + integration + E2E + CLI + performance)
- 100% test pass rate
- ~95%+ code coverage for coordination package
- 20 E2E workflow scenarios
- Zero known issues

**Key Benefits**:
- Enables parallel schema development with confidence
- Early conflict detection (before code is written)
- Clear visibility into all active schema work
- Audit trail for compliance and debugging
- Production-tested and performant

### Files Added

- `python/confiture/integrations/pggit/coordination/models.py` - Data models (Intent, ConflictReport, enums)
- `python/confiture/integrations/pggit/coordination/detector.py` - Conflict detection algorithm
- `python/confiture/integrations/pggit/coordination/registry.py` - Database-backed intent registry
- `python/confiture/cli/coordinate.py` - CLI commands (7 commands)
- `tests/unit/test_coordination.py` - Unit tests (25 tests)
- `tests/integration/test_coordination_registry.py` - Integration tests (52 tests)
- `tests/e2e/test_coordination_e2e.py` - E2E workflow tests (20 tests)
- `tests/unit/test_cli_coordinate.py` - CLI tests (28 tests)
- `tests/performance/test_coordination_benchmarks.py` - Performance benchmarks (18 tests)
- `docs/architecture/multi-agent-coordination.md` - Architecture documentation
- `docs/guides/multi-agent-coordination.md` - User guide
- `docs/performance/coordination-performance.md` - Performance analysis
- `examples/multi-agent-workflow/` - 3 executable example scripts

### Example Usage

```bash
# Register intention to add Stripe integration
confiture coordinate register \
    --agent-id claude-payments \
    --feature-name stripe_integration \
    --schema-changes "ALTER TABLE users ADD COLUMN stripe_customer_id TEXT" \
    --tables-affected users \
    --risk-level medium

# Check for conflicts before starting work
confiture coordinate check \
    --agent-id claude-auth \
    --feature-name oauth2 \
    --schema-changes "ALTER TABLE users ADD COLUMN oauth_provider TEXT" \
    --tables-affected users

# List all active work
confiture coordinate list-intents --status-filter in_progress

# Get JSON output for automation
confiture coordinate list-intents --format json | jq '.total'

# Mark conflict as resolved
confiture coordinate resolve \
    --conflict-id 42 \
    --notes "Coordinated with team, applying changes sequentially"
```

### Closes

- Phase 4 implementation complete (100% of acceptance criteria met)
- All Week 3 objectives exceeded (architecture, JSON, performance benchmarks)

## [0.3.7] - 2026-01-18

### Fixed

**SQL-Only Migration Support in Testing Framework** (Issue #8):
- `load_migration()` now automatically detects and loads SQL-only migrations
- Searches for `.up.sql`/`.down.sql` file pairs when Python migration not found
- `find_migration_by_version()` also updated to search both formats
- Python migrations are still tried first for backwards compatibility

### Added

- 17 new unit tests for `load_migration()` covering all migration formats
- Helpful error messages when `.down.sql` file is missing

### Example

```python
from confiture.testing import load_migration

# Both formats work now:
Migration = load_migration("003_move_tables")  # Python or SQL auto-detected
Migration = load_migration(version="003")       # Version lookup works too

# SQL-only migrations are discovered automatically:
# db/migrations/003_move_tables.up.sql
# db/migrations/003_move_tables.down.sql
```

### Closes

- GitHub Issue #8: load_migration() should support SQL-only migrations

## [0.3.6] - 2026-01-18

### Added - Developer Experience Improvements (Issue #7)

**Migration Loader Utility** (`load_migration`):
- Simple function to load migrations without importlib boilerplate
- Support loading by full name: `load_migration("003_move_tables")`
- Support loading by version prefix: `load_migration(version="003")`
- Custom migrations directory support
- Clear error messages with `MigrationNotFoundError` and `MigrationLoadError`

**JSON Output for Status Command**:
- New `--format json` flag for `migrate status` command
- New `--output` / `-o` flag to save status to file
- Structured JSON output with applied, pending, current version, and migration details
- Machine-readable format for CI/CD integration

**Baseline Command** (`migrate baseline`):
- Mark migrations as applied without executing them
- `--through` flag to mark all migrations up to a version
- `--dry-run` support to preview what would be marked
- Perfect for adopting confiture on existing databases
- Records baseline operations with `execution_time_ms = 0`

**SQL-Only Migration Files**:
- **File pairs**: `.up.sql` / `.down.sql` files (no Python needed)
- **Class attributes**: `SQLMigration` with `up_sql` / `down_sql` attributes
- Automatic discovery alongside Python migrations
- Full support for checksums, dry-run, and status tracking
- Mixed Python + SQL migrations in same directory

**Migration Testing Sandbox** (`MigrationSandbox`):
- Context manager with automatic transaction rollback
- Pre-loaded testing utilities (validator, snapshotter)
- Works with URL (creates connection) or existing connection (uses savepoint)
- Convenience methods: `capture_baseline()`, `assert_no_data_loss()`, `assert_constraints_valid()`
- Direct SQL execution: `execute()` and `query()` methods

**Pytest Plugin**:
- Auto-registered via pytest11 entry point (works when confiture is installed)
- Manual registration: `pytest_plugins = ["confiture.testing.pytest"]`
- Fixtures: `confiture_sandbox`, `confiture_validator`, `confiture_snapshotter`
- Overridable: `confiture_db_url`, `confiture_migrations_dir`
- `@migration_test("003")` decorator for class-based migration tests

**Top-Level Testing Imports**:
- All fixtures importable from `confiture.testing`
- `from confiture.testing import SchemaSnapshotter, DataValidator, MigrationRunner`
- `from confiture.testing import load_migration, MigrationSandbox`
- Backwards compatible with existing deep imports

### New Files

- `python/confiture/testing/loader.py` - Migration loader utility
- `python/confiture/testing/sandbox.py` - MigrationSandbox context manager
- `python/confiture/testing/pytest_plugin.py` - Pytest fixtures and plugin
- `python/confiture/testing/pytest/__init__.py` - Pytest namespace exports
- `python/confiture/models/sql_file_migration.py` - FileSQLMigration for .sql file pairs

### Modified Files

- `python/confiture/testing/__init__.py` - Top-level exports
- `python/confiture/cli/main.py` - JSON status output, baseline command
- `python/confiture/core/connection.py` - `load_migration_class()` for Python + SQL
- `python/confiture/core/migrator.py` - SQL file discovery, `mark_applied()`
- `python/confiture/models/__init__.py` - SQLMigration export
- `python/confiture/models/migration.py` - SQLMigration class
- `pyproject.toml` - pytest11 entry point

### Example Usage

**Load migrations easily**:
```python
from confiture.testing import load_migration

Migration003 = load_migration("003_move_catalog_tables")
# or by version:
Migration003 = load_migration(version="003")
```

**JSON status output**:
```bash
confiture migrate status --format json
# {"applied": ["001", "002"], "pending": ["003"], "current": "002", ...}

confiture migrate status -f json -o status.json
```

**SQL-only migrations**:
```
db/migrations/
├── 003_move_tables.up.sql
├── 003_move_tables.down.sql
```

Or with Python class:
```python
class MoveTables(SQLMigration):
    version = "003"
    name = "move_tables"
    up_sql = "ALTER TABLE foo SET SCHEMA bar;"
    down_sql = "ALTER TABLE bar.foo SET SCHEMA public;"
```

**Baseline command**:
```bash
confiture migrate baseline --through 002
# Marks 001, 002 as applied without executing
```

**Testing sandbox**:
```python
from confiture.testing import MigrationSandbox

with MigrationSandbox(db_url) as sandbox:
    migration = sandbox.load("003")
    baseline = sandbox.capture_baseline()
    migration.up()
    sandbox.assert_no_data_loss(baseline)
# Auto-rollback on exit
```

**Pytest plugin**:
```python
# conftest.py
pytest_plugins = ["confiture.testing.pytest"]

# test file
def test_migration(confiture_sandbox):
    migration = confiture_sandbox.load("003")
    migration.up()
    assert confiture_sandbox.validator.constraints_valid()
```

### Compatibility

- ✅ All existing functionality preserved
- ✅ No breaking changes
- ✅ Backwards compatible imports
- ✅ Python 3.11, 3.12, 3.13 supported

### Closes

- GitHub Issue #7: DX Improvements

## [0.4.0] - 2025-12-27

### Added - Phase 5: CLI Integration for Dry-Run Mode

**Dry-Run Analysis** (`--dry-run` flag):
- Analyze migrations without executing them
- Preview impact before applying: estimated time, disk usage, CPU
- Works with both `migrate up` and `migrate down` commands
- No database changes, safe for production planning
- Exit immediately after analysis (no execution)

**SAVEPOINT Testing** (`--dry-run-execute` flag):
- Execute migrations in guaranteed-rollback transaction
- Test actual migration logic with automatic rollback
- Measure real execution time and verify constraints
- User confirmation prompt before real execution
- Perfect for pre-production validation

**Output Formats**:
- **Text format** (default) - Human-readable, colorized output
- **JSON format** (`--format json`) - Structured data for CI/CD integration
- **File output** (`--output file.txt`) - Save analysis reports for review

**Rollback Analysis** (`migrate down --dry-run`):
- Analyze what gets undone before rollback
- Preview which migrations would be reversed
- Safe exploration of rollback scenarios

**Validation & Safety**:
- `--dry-run` and `--dry-run-execute` are mutually exclusive
- `--dry-run` incompatible with `--force` flag
- Clear error messages for invalid flag combinations
- User confirmation required for SAVEPOINT execution

### CLI Additions

**New flags for `migrate up`**:
- `--dry-run` - Analyze without execution
- `--dry-run-execute` - Test in SAVEPOINT, ask for confirmation
- `--format / -f` - Output format (text, json)
- `--output / -o` - Save report to file
- `--verbose / -v` - Detailed output

**New flags for `migrate down`**:
- `--dry-run` - Analyze rollback without execution
- `--format / -f` - Output format (text, json)
- `--output / -o` - Save report to file
- `--verbose / -v` - Detailed output

### Documentation

**New comprehensive guides**:
- `docs/guides/cli-dry-run.md` - 500+ line user guide covering:
  - Analyze without execution
  - SAVEPOINT testing workflow
  - Rollback analysis
  - Output format comparison
  - Real-world examples (5 scenarios)
  - Troubleshooting guide
  - CI/CD integration example
  - Best practices and FAQ

**Updated documentation**:
- `README.md` - Added dry-run section with examples
- `docs/index.md` - Added link to dry-run guide

### Testing

**New test file**: `tests/unit/test_cli_dry_run.py`
- 12 comprehensive test cases covering:
  - Dry-run analysis mode (3 tests)
  - JSON/text output formats (4 tests)
  - File output (1 test)
  - SAVEPOINT execution with confirmation (1 test)
  - Rollback analysis (2 tests)
  - Flag validation (3 tests)
  - User cancellation (1 test)
  - Edge cases (2 tests)

**Test Coverage**:
- All critical paths covered
- 30/30 total CLI tests passing (100%)
- 0 new regressions
- All existing functionality preserved

### Code Changes

**New helper module**: `python/confiture/cli/dry_run.py`
- `display_dry_run_header()` - Show analysis mode indicator
- `save_text_report()` - Generate human-readable reports
- `save_json_report()` - Generate structured JSON reports
- `print_json_report()` - Output JSON to console
- `show_report_summary()` - Display summary statistics
- `ask_dry_run_execute_confirmation()` - User confirmation prompt
- `extract_sql_statements_from_migration()` - SQL extraction utilities

**Modified**: `python/confiture/cli/main.py`
- Added dry-run logic to `migrate_up()` command
- Added dry-run logic to `migrate_down()` command
- Migration metadata collection for analysis
- Report generation and formatting
- Early returns for analysis-only mode
- Confirmation flow for SAVEPOINT execution

### Quality Metrics

**Code Quality**:
- 0 linting issues in main code
- 100% type hint coverage
- Comprehensive docstrings
- All functions tested

**Test Results**:
- 12 new tests for dry-run features
- 30 total CLI tests (18 existing + 12 new)
- 100% passing (30/30)
- No regressions

**Documentation**:
- 500+ lines of user guide
- 5 real-world examples
- Troubleshooting section
- CI/CD integration example
- Complete CLI reference

### Example Usage

**Analyze before applying**:
```bash
$ confiture migrate up --dry-run
🔍 Analyzing migrations without execution...

Migration Analysis Summary
================================================================================
Migrations to apply: 2

  001: create_initial_schema
    Estimated time: 500ms | Disk: 1.0MB | CPU: 30%
  002: add_user_table
    Estimated time: 500ms | Disk: 1.0MB | CPU: 30%

✓ All migrations appear safe to execute
================================================================================
```

**Test in SAVEPOINT**:
```bash
$ confiture migrate up --dry-run-execute
🧪 Executing migrations in SAVEPOINT (guaranteed rollback)...
[shows analysis]
🔄 Proceed with real execution? [y/N]: y
✅ Successfully applied 2 migration(s)!
```

**Save JSON report**:
```bash
$ confiture migrate up --dry-run --format json --output report.json
🔍 Analyzing migrations without execution...
✅ Report saved to report.json
```

**Analyze rollback**:
```bash
$ confiture migrate down --dry-run --steps 2
🔍 Analyzing migrations without execution...

Rollback Analysis Summary
================================================================================
Migrations to rollback: 2

  002: add_user_table
  001: create_initial_schema
================================================================================
```

### Performance Impact

- Minimal overhead: analysis adds <10ms per migration
- No actual execution unless `--dry-run-execute` with confirmation
- JSON output for fast CI/CD parsing
- File output for auditing and sharing

### Compatibility

- ✅ All existing functionality preserved
- ✅ No breaking changes
- ✅ Works with all environment configurations
- ✅ Compatible with database_url configuration
- ✅ Works alongside `--target`, `--config`, `--strict` flags

### Known Limitations

- Conservative estimates (500ms, 1MB, 30% CPU) until full analysis added
- Estimates don't include index creation time (will be enhanced)
- SQL statement extraction is basic (enhanced parsing planned for Phase 6)

### Future Enhancements

- Full actual dry-run execution with async connections
- Resource impact analysis (real measurements)
- Custom estimate functions per migration
- Report comparison tools
- Interactive migration review mode
- Integration with CI/CD providers (GitHub, GitLab, etc.)

## [0.3.2] - 2025-11-20

### Added
- **`--force` flag for `migrate up` command** - Force migration reapplication even when tracking shows migrations as already applied (#4)
- Warning messages when force mode is enabled to prevent accidental misuse
- New `Migrator.migrate_up()` method for complete migration workflow with force support
- Comprehensive troubleshooting guide (`docs/guides/troubleshooting.md`) with 400+ lines covering common migration issues
- `database_url` connection format support for simpler configuration

### Changed
- `Migrator.apply()` now accepts `force` parameter to skip "already applied" checks
- Force mode skips migration state checks but still updates tracking after successful application
- Enhanced CLI output with force-specific messages and warnings

### Documentation
- New `docs/guides/troubleshooting.md` - Complete troubleshooting guide
- Updated `docs/reference/cli.md` - Full `--force` flag documentation with examples and safety warnings
- Updated `README.md` - Added `--force` flag to feature list
- Updated `docs/index.md` - Added troubleshooting guide link

### Testing
- Added `tests/unit/test_cli_migrate.py` - CLI flag parsing tests (4 tests)
- Added `tests/unit/test_migrator.py` - Force logic unit tests (4 tests)
- Added `tests/integration/test_migrate_force.py` - Complete force workflow integration tests (4 scenarios)

### Fixed
- Migration state tracking now correctly handles force reapplication
- Connection handling improved with `database_url` support for testing workflows

## [0.3.0] - 2025-11-09

### Added
- **Hexadecimal Sorting** - Support for hex-prefixed schema files (e.g., `0x01_`, `0x0A_`) for better organization of large schemas
- **Dynamic Discovery** - Enhanced SQL file discovery with include/exclude patterns, recursive directory control, and flexible project structures
- **Recursive Directory Support** - Automatic discovery of SQL files in nested directory hierarchies with deterministic ordering
- New configuration options for advanced file discovery (`include`, `exclude`, `recursive`, `order`, `auto_discover`)
- Build configuration section with `sort_mode` option for hex vs alphabetical sorting
- Comprehensive documentation for all new features with examples and migration guides
- 3 new test files covering hex sorting, dynamic discovery, and recursive directories

### Changed
- Enhanced `include_dirs` configuration to support object format with advanced options while maintaining backward compatibility
- Schema builder now supports multiple file naming conventions simultaneously
- File discovery logic refactored for flexibility and performance
- Updated documentation structure with dedicated features section

### Documentation
- Added 3 new feature documentation pages (hex sorting, dynamic discovery, recursive directories)
- Updated organizing-sql-files.md with hex sorting examples and patterns
- Enhanced configuration reference with new include_dirs options and build configuration
- Updated main documentation index to highlight new v0.3.0 features

### Performance
- Improved file discovery caching for better performance with complex directory structures
- Optimized recursive directory scanning algorithms

## [0.2.0] - 2025-11-09

### Added
- **Production-ready CI/CD workflows** inspired by FraiseQL patterns
- GitHub Actions Quality Gate workflow (tests, lint, type-check, rust, security)
- Multi-platform wheel building (Linux, macOS, Windows)
- **PyPI Trusted Publishing** - secure publishing without API tokens
- Python version matrix testing (3.11, 3.12, 3.13)
- Comprehensive documentation for trusted publishing setup

### Fixed
- **CI database creation issue** - properly connect to postgres database when creating test databases
- Quality gate blocking on any failed check (enforced quality standards)
- PostgreSQL service configuration for consistent testing

### Changed
- Upgraded from alpha to stable release
- Replaced legacy ci.yml with comprehensive quality-gate.yml
- Merged wheels.yml into publish.yml with full release automation
- Improved workflow documentation and setup guides

### Infrastructure
- Quality gate pattern with 6 parallel jobs
- Security scanning with Bandit + Trivy
- Rust checks (fmt + clippy) in CI
- Automated GitHub Releases with artifacts
- 255 tests passing with 89.35% coverage

## [0.2.0-alpha] - 2025-10-11

### Added
- **Rust performance layer** with PyO3 bindings (Phase 2)
- Fast schema builder using parallel file I/O (rayon)
- Fast SHA256 hashing (30-60x faster than Python)
- Graceful fallback to Python when Rust unavailable
- Performance benchmarks in `tests/performance/`
- Maturin build system for binary wheels
- Support for Python 3.11, 3.12, 3.13
- Comprehensive test coverage (212 tests, 91.76%)

### Changed
- `SchemaBuilder.build()` now uses Rust for 10-50x speedup
- `SchemaBuilder.compute_hash()` now uses Rust for 30-60x speedup
- Build system migrated from hatchling to maturin
- Version bumped to 0.2.0-alpha

### Performance
- Schema building: 5-10x faster with Rust
- Hash computation: 30-60x faster with Rust
- Parallel file operations on multi-core systems

### Documentation
- Added PHASE2_SUMMARY.md (Rust layer documentation)
- Added performance benchmarking guide
- Updated README with Rust installation notes

## [0.1.0-alpha] - 2025-10-11

### Added
- **Core schema builder** (Medium 1: Build from DDL)
- Environment configuration system with YAML
- SQL file discovery and concatenation
- Deterministic file ordering (alphabetical)
- Schema hash computation (SHA256)
- File exclusion filtering
- Multiple include directories support
- Relative path calculation for nested structures

### Added - CLI Commands
- `confiture init` - Initialize project structure
- `confiture build` - Build schema from DDL files
  - `--env` flag for environment selection
  - `--output` flag for custom output path
  - `--show-hash` flag for schema hash display
  - `--schema-only` flag to exclude seed data

### Added - Migration System
- Migration base class with up/down methods
- Migration executor with transaction support
- Migration discovery and tracking
- Schema diff detection (basic)
- Migration generator from schema diffs
- Migration status command
- Version sequencing

### Added - Testing
- 212 unit tests with 91.76% coverage
- Integration test framework
- Test fixtures for schema files
- Comprehensive error path testing
- Edge case coverage

### Added - Configuration
- Environment config (db/environments/*.yaml)
- Include/exclude directory patterns
- Database URL configuration
- Project directory support

### Added - Documentation
- README with quick start guide
- PHASES.md with development roadmap
- CLAUDE.md with AI development guide
- PRD.md with product requirements
- Code examples in examples/

### Infrastructure
- Python 3.11+ support
- pytest test framework
- ruff linting and formatting
- mypy type checking
- pre-commit hooks
- uv package manager integration

## [0.0.1] - 2025-10-10

### Added
- Initial project structure
- Basic package scaffolding
- Development environment setup

---

## Version History Summary

| Version | Date | Key Features |
|---------|------|--------------|
| 0.3.7 | 2026-01-18 | Fix: load_migration() now supports SQL-only migrations |
| 0.3.6 | 2026-01-18 | DX improvements: migration loader, JSON status, baseline command, SQL migrations, testing sandbox, pytest plugin |
| 0.3.2 | 2025-11-20 | --force flag for migrate up, troubleshooting guide, database_url support |
| 0.3.0 | 2025-11-09 | Hexadecimal sorting, dynamic discovery, recursive directories |
| 0.2.0 | 2025-11-09 | Production CI/CD, Trusted Publishing, Multi-platform wheels |
| 0.2.0-alpha | 2025-10-11 | Rust performance layer, 10-50x speedup |
| 0.1.0-alpha | 2025-10-11 | Core schema builder, CLI, migrations |
| 0.0.1 | 2025-10-10 | Initial setup |

## Migration Guide

### From 0.1.0 to 0.2.0

No breaking changes! Upgrade is seamless:

```bash
pip install --upgrade confiture
```

**What's New:**
- Rust extension auto-detected and used for performance
- Falls back to Python if Rust unavailable
- All existing code continues to work unchanged

**To verify Rust extension:**
```python
from confiture.core.builder import HAS_RUST
print(f"Rust available: {HAS_RUST}")
```

**Performance improvements:**
- `SchemaBuilder.build()`: 5-10x faster
- `SchemaBuilder.compute_hash()`: 30-60x faster

## Deprecations

No deprecated features yet.

## Security

No security advisories yet.

To report security vulnerabilities, please email security@fraiseql.com or create a private security advisory on GitHub.

---

## Links

- [GitHub Repository](https://github.com/fraiseql/confiture)
- [Issue Tracker](https://github.com/fraiseql/confiture/issues)
- [PyPI Package](https://pypi.org/project/confiture/)
- [Documentation](https://github.com/fraiseql/confiture)
- [FraiseQL](https://github.com/fraiseql/fraiseql)

---

*Making jam from strawberries, one version at a time.* 🍓
