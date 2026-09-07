"""`confiture migrate validate`.

Split out of the monolithic migrate command modules.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

import typer

from confiture.cli.commands.validate_checks import (
    ValidateOptions,
    build_registry,
    validate_flag_dependencies,
)
from confiture.cli.dsn import param_is_explicit
from confiture.cli.error_json import cli_boundary
from confiture.cli.helpers import _output_json, _resolve_config, console, is_json
from confiture.cli.options import format_option
from confiture.core.validation.context import ValidationContext
from confiture.core.validation.registry import (
    ValidationCheck,
    aggregate_exit_code,
    compose_payload,
    run_checks,
)
from confiture.exceptions import ConfigurationError


def _pattern_catalog_payload(opts: Any) -> dict[str, Any] | None:
    """Render the idempotency pattern catalog.

    Read-only: no DB, no config, no migrations directory.

    Args:
        opts: The parsed ``migrate validate`` options; only ``json_mode`` is read.

    Returns:
        The JSON catalog envelope, or ``None`` after printing the text table.
    """
    from confiture.core.idempotency.patterns import list_patterns

    entries = list_patterns()

    if opts.json_mode:
        # `hints` is pre-allocated per the documented JSON-schema contract
        # (docs/reference/json-schemas/migrate-validate-list-patterns.schema.json).
        # `--list-patterns` is a read-only catalog query with no ambiguous
        # success state, so the list is always empty; the key still
        # appears so consumers can code against a stable shape.
        return {"version": "1", "patterns": entries, "hints": []}

    # Text mode: compact table for human eyes.
    from rich.table import Table

    table = Table(title="Idempotency detection patterns", expand=False)
    table.add_column("id", style="cyan", no_wrap=True)
    table.add_column("severity")
    table.add_column("skip", justify="center")
    table.add_column("auto-fix", justify="center")
    table.add_column("description")
    for entry in entries:
        table.add_row(
            entry["id"],
            entry["severity"],
            "yes" if entry["has_skip_regex"] else "no",
            "yes" if entry["has_auto_fix"] else "no",
            entry["description"],
        )
    console.print(table)
    return None


MigrationsDirOpt = Annotated[
    Path, typer.Option("--migrations-dir", help="Migrations directory (default: db/migrations)")
]
FixNamingOpt = Annotated[
    bool,
    typer.Option(
        "--fix-naming", help="Auto-rename orphaned files to match convention (default: off)"
    ),
]
IdempotentOpt = Annotated[
    bool,
    typer.Option(
        "--idempotent", help="Validate migrations are idempotent, can re-run (default: off)"
    ),
]
ListPatternsOpt = Annotated[
    bool,
    typer.Option(
        "--list-patterns",
        help="Print machine-readable catalog of detection patterns "
        "(read-only, no DB needed). Use with `--format json` for tooling. "
        "Report mode: cannot be combined with any other check.",
    ),
]
StrictCorOpt = Annotated[
    bool,
    typer.Option(
        "--strict-cor",
        help="Treat info-severity CREATE OR REPLACE shape-risk findings as "
        "blocking (exit 1). Off by default — info findings are still "
        "rendered but don't fail the gate.",
    ),
]
FailOnUnanalyzableOpt = Annotated[
    bool,
    typer.Option(
        "--fail-on-unanalyzable",
        help="Treat statements the analyzer could not read as a failure (exit 1). "
        "Off by default. Pair with --base-ref so an existing backlog of "
        "dynamic SQL does not fail every run. Requires --idempotent.",
    ),
]
CheckDriftOpt = Annotated[
    bool,
    typer.Option("--check-drift", help="Validate schema against git refs for drift (default: off)"),
]
RequireMigrationOpt = Annotated[
    bool,
    typer.Option(
        "--require-migration",
        help="Ensure DDL changes have migration files (static, no DB required). "
        "Also detects function parameter type changes missing a DROP FUNCTION. "
        "Companion to --check-signatures which detects stale overloads in a live DB.",
    ),
]
RequireMigrationBodiesOpt = Annotated[
    bool,
    typer.Option(
        "--require-migration-bodies",
        help="Additionally require a function/procedure BODY change (between --base-ref "
        "and HEAD) to be carried by a migration that re-defines it (#178). Static, "
        "no DB. Implies --require-migration. OFF by default — drain the standing "
        "backlog first (see --list-unmigrated-bodies). The runtime counterpart is "
        "--check-body-replay.",
    ),
]
ListUnmigratedBodiesOpt = Annotated[
    bool,
    typer.Option(
        "--list-unmigrated-bodies",
        help="Report-only: list function body changes (between --base-ref and HEAD) not "
        "carried by a migration, WITHOUT failing (exit 0). Use to size and drain the "
        "backlog before enabling --require-migration-bodies. Report mode: cannot be "
        "combined with any other check.",
    ),
]
BaseRefOpt = Annotated[
    str, typer.Option("--base-ref", help="Base git reference for comparison (default: origin/main)")
]
SinceOpt = Annotated[
    str | None, typer.Option("--since", help="Shortcut for --base-ref (default: none)")
]
StagedOpt = Annotated[
    bool,
    typer.Option("--staged", help="Validate staged files only, pre-commit mode (default: off)"),
]
RequireGrantMigrationOpt = Annotated[
    bool,
    typer.Option(
        "--require-grant-migration",
        help="Verify that each changed GRANT/REVOKE in the grant directory is carried by an "
        "accompanying migration (SQL or Python). Semantic match across "
        "table/schema/sequence/function objects; grants that can't be statically verified "
        "degrade to a file-presence check and are surfaced as notes (default: off).",
    ),
]
AllowGrantOnlyOpt = Annotated[
    bool,
    typer.Option(
        "--allow-grant-only",
        help="Suppress --require-grant-migration failure for build-only branches (default: off)",
    ),
]
DryRunOpt = Annotated[
    bool, typer.Option("--dry-run", help="Preview changes without renaming (default: off)")
]
CheckLiveDriftOpt = Annotated[
    bool,
    typer.Option(
        "--check-live-drift",
        help="Compare the live database schema against the DDL files. "
        "Requires --config and a database connection.",
    ),
]
IgnoreColumnOrderOpt = Annotated[
    bool,
    typer.Option(
        "--ignore-column-order",
        help="With --check-live-drift: do not report column_order_mismatch (#226)",
    ),
]
CheckSignaturesOpt = Annotated[
    bool,
    typer.Option(
        "--check-signatures",
        help="Compare function signatures in --schema against the live DB. "
        "Detects stale overloads created by CREATE OR REPLACE with changed param types. "
        "Companion to --require-migration (static pre-commit check, no DB needed). "
        "Requires --config (or --env) and --schema.",
    ),
]
CheckImportsOpt = Annotated[
    bool,
    typer.Option(
        "--check-imports",
        help="Import-check pending Python migration modules. "
        "Level 1: catches syntax errors and missing imports. "
        "Level 2: verifies version, name, up(), down() are defined. "
        "No database connection required.",
    ),
]
CheckBodyOpt = Annotated[
    bool,
    typer.Option(
        "--check-body",
        help="Compare function bodies (prosrc) between source SQL and the live database. "
        "Requires --check-signatures. Opt-in because body comparison is heavier than "
        "signature-only comparison.",
    ),
]
ShowDiffOpt = Annotated[
    bool,
    typer.Option(
        "--show-diff",
        help="With --check-body: also emit, per drifted function, the expected body, the "
        "live body, and a unified diff of the two (normalised) bodies. Requires "
        "--check-body. Opt-in because bodies can be large; the default output stays "
        "hash-only for terse CI logs. Also applies to --check-body-views.",
    ),
]
CheckBodyViewsOpt = Annotated[
    bool,
    typer.Option(
        "--check-body-views",
        help="Compare view and materialized-view definitions between the source schema "
        "and the live database. The expected views are built into a scratch DB and "
        "read back through the same pg_get_viewdef deparser as live, so only genuine "
        "predicate/projection changes register (formatting, schema-qualification and "
        "*-expansion differences do not). Requires --config (or --env) and --schema. "
        "Honours --schemas and --ssh (with --scratch-url).",
    ),
]
CheckBodyReplayOpt = Annotated[
    bool,
    typer.Option(
        "--check-body-replay",
        help="Detect out-of-band function/procedure hot-patches by REPLAY: rebuild the "
        "expected database by replaying all migrations into a scratch DB, then diff "
        "prosrc against live. Unlike --check-body (expected = source DDL, swamped by "
        "the build-vs-migrate backlog), this reports only definitions no migration "
        "produced — the clean production drift signal. Requires --config (or --env); "
        "honours --schemas, --migrations-dir, --ssh (with --scratch-url). Heaviest "
        "drift check (replays the full migration history).",
    ),
]
ScratchUrlOpt = Annotated[
    str | None,
    typer.Option(
        "--scratch-url",
        help="Writable PostgreSQL server on which to build the expected scratch database "
        "for --check-body-views / --check-body-replay (default: the live server from "
        "the config). Required when using --ssh, since the scratch DB cannot be built "
        "on the remote read-only live server.",
    ),
]
CheckAclsOpt = Annotated[
    bool,
    typer.Option(
        "--check-acls",
        "--check-acl-coverage",
        help="Static: verify every `CREATE TABLE` in db/migrations/ has a matching "
        "`GRANT` either in the same migration or in the configured global grant "
        "sweep directory (defaults to db/7_grant). No-op when the config has no "
        "`acls:` block. No database connection required.  "
        "Use --check-acls; --check-acl-coverage is a deprecated alias.",
    ),
]
CheckOwnershipCoverageOpt = Annotated[
    bool,
    typer.Option(
        "--check-ownership-coverage",
        help="Static: verify every `CREATE { TABLE | VIEW | MATERIALIZED VIEW | SEQUENCE }` "
        "in db/migrations/ is paired with a matching `ALTER … OWNER TO <expected_owner>` "
        "in the same file (`own_001`).  Also flags bare `ALTER … OWNER TO` on objects "
        "the migration didn't create (`own_002` — three severity tiers: silent when "
        "guarded + companion `requires_superuser=True`, WARNING when only guarded, "
        "ERROR when bare).  No-op when the config has no `ownership:` block, or when "
        "`ownership.lint_enabled` is false.  Requires the [ast] extra (pglast).",
    ),
]
CheckFunctionUniquenessOpt = Annotated[
    bool,
    typer.Option(
        "--check-function-uniqueness",
        help="Static: verify every `CREATE FUNCTION` / `CREATE PROCEDURE` "
        "in the configured DDL directories has a unique fully-qualified "
        "signature. Two files defining the same `schema.name(args)` "
        "are silently shadowed by `confiture build` — this rule "
        "(`func_001`) catches the duplicate first. No-op when the "
        "config has no `function_coverage:` block, or when "
        "`function_coverage.enabled` is false. Requires the [ast] extra (pglast).",
    ),
]
CheckSecurityDefinerOpt = Annotated[
    bool,
    typer.Option(
        "--check-security-definer",
        help="Flag `SECURITY DEFINER` functions/procedures that do not pin "
        "`search_path` (CVE-2018-1058). Rule `sec_002`. "
        "Without `--against-db`: static DDL scan (no DB, requires [ast]/pglast). "
        "With `--against-db`: live `pg_proc` query (authoritative; works even when "
        "ALTER FUNCTION patched the search_path separately from the CREATE). "
        "No-op when config has no `security_lint:` block or "
        "`security_lint.enabled` is false. Default severity advisory "
        "(warning, exit 0); set `security_lint.severity: error` for exit 1. "
        "See docs/guides/security-definer-lint.md.",
    ),
]
SecdefAgainstDbOpt = Annotated[
    bool,
    typer.Option(
        "--against-db",
        help="Used with `--check-security-definer`: query the live database "
        "(`pg_proc.proconfig`) instead of scanning DDL source files. "
        "Authoritative for migrate-strategy databases where "
        "`ALTER FUNCTION … SET search_path` may have been applied after "
        "the original CREATE.",
    ),
]
EmitRemediationOpt = Annotated[
    Path | None,
    typer.Option(
        "--emit-remediation",
        help="Used with `--check-security-definer`: write a SQL remediation script "
        "containing one `ALTER FUNCTION … SET search_path = …` statement per "
        "flagged callable to the given file path. Does nothing when no violations "
        "are found.",
    ),
]
DdlDirOpt = Annotated[
    list[Path] | None,
    typer.Option(
        "--ddl-dir",
        help="DDL directory to scan for `--check-function-uniqueness` and "
        "`--check-security-definer` (repeatable). "
        "Defaults to `db/schema` if not provided.",
    ),
]
CheckSignatureSchemasOpt = Annotated[
    str,
    typer.Option(
        "--schemas",
        help="Comma-separated list of schemas to inspect for stale overloads "
        "(default: public). Used with --check-signatures.",
    ),
]
ConfigOpt = Annotated[
    Path,
    typer.Option(
        "-c",
        "--config",
        help="Config file path. Use --env as a shortcut for db/environments/{name}.yaml.",
    ),
]
EnvOpt = Annotated[
    str | None,
    typer.Option(
        "--env",
        help="Environment name — shortcut for --config db/environments/{name}.yaml "
        "(e.g. --env production). Cannot be combined with --config.",
    ),
]
SshViaOpt = Annotated[
    str | None,
    typer.Option(
        "--ssh",
        help="Open an SSH tunnel before connecting: user@host or host "
        "(e.g. lionel@printoptim.io).  Used with --check-signatures and "
        "--check-live-drift.  Overrides the ssh_tunnel block in the config file.",
    ),
]
SchemaFileOpt = Annotated[
    Path | None,
    typer.Option(
        "--schema",
        help="Schema SQL file to compare against. "
        "If omitted with --check-signatures, schema is auto-built from DDL files.",
    ),
]
OutputFileOpt = Annotated[
    Path | None, typer.Option("--output", "-o", help="Save output to file (default: stdout)")
]


@cli_boundary
def migrate_validate(
    ctx: typer.Context,
    migrations_dir: MigrationsDirOpt = Path("db/migrations"),
    fix_naming: FixNamingOpt = False,
    idempotent: IdempotentOpt = False,
    list_patterns: ListPatternsOpt = False,
    strict_cor: StrictCorOpt = False,
    fail_on_unanalyzable: FailOnUnanalyzableOpt = False,
    check_drift: CheckDriftOpt = False,
    require_migration: RequireMigrationOpt = False,
    require_migration_bodies: RequireMigrationBodiesOpt = False,
    list_unmigrated_bodies: ListUnmigratedBodiesOpt = False,
    base_ref: BaseRefOpt = "origin/main",
    since: SinceOpt = None,
    staged: StagedOpt = False,
    require_grant_migration: RequireGrantMigrationOpt = False,
    allow_grant_only: AllowGrantOnlyOpt = False,
    dry_run: DryRunOpt = False,
    check_live_drift: CheckLiveDriftOpt = False,
    ignore_column_order: IgnoreColumnOrderOpt = False,
    check_signatures: CheckSignaturesOpt = False,
    check_imports: CheckImportsOpt = False,
    check_body: CheckBodyOpt = False,
    show_diff: ShowDiffOpt = False,
    check_body_views: CheckBodyViewsOpt = False,
    check_body_replay: CheckBodyReplayOpt = False,
    scratch_url: ScratchUrlOpt = None,
    check_acls: CheckAclsOpt = False,
    check_ownership_coverage: CheckOwnershipCoverageOpt = False,
    check_function_uniqueness: CheckFunctionUniquenessOpt = False,
    check_security_definer: CheckSecurityDefinerOpt = False,
    secdef_against_db: SecdefAgainstDbOpt = False,
    emit_remediation: EmitRemediationOpt = None,
    ddl_dir: DdlDirOpt = None,
    check_signature_schemas: CheckSignatureSchemasOpt = "public",
    config: ConfigOpt = Path("confiture.yaml"),
    env: EnvOpt = None,
    ssh_via: SshViaOpt = None,
    schema_file: SchemaFileOpt = None,
    format_output: str = format_option("text", "json", "csv"),
    output_file: OutputFileOpt = None,
) -> None:
    """Validate migration files follow naming and quality conventions.

    PROCESS:
      Checks for orphaned files, validates naming pattern ({NNN}_{name}.sql),
      optionally verifies idempotency, checks for schema drift, and ensures DDL
      changes have corresponding migration files.

      Every check you ask for runs (0.40.0). The exit code is the worst outcome
      across them, so a passing check cannot mask a failing one.

    EXAMPLES:
      confiture migrate validate
        ↳ Check for orphaned files not matching naming pattern

      confiture migrate validate --idempotent
        ↳ Also validate all migrations are idempotent (safe to re-run)

      confiture migrate validate --check-drift --staged
        ↳ Pre-commit: check staged files for schema drift

      confiture migrate validate --require-migration --base-ref origin/main
        ↳ Static: verify DDL changes + no function signature changes (no DB needed)

      confiture migrate validate --check-signatures --env local
        ↳ Live: detect stale function overloads in the local database (schema auto-built)

      confiture migrate validate --check-signatures --env production --schemas public,auth
        ↳ Live: check production DB across multiple schemas

      confiture migrate validate --check-signatures --env production --ssh lionel@printoptim.io
        ↳ Live: reach production DB through an SSH tunnel (no manual ssh -L needed)

      confiture migrate validate --check-imports
        ↳ Static: import-check all Python migration modules (no DB needed)

      confiture migrate validate --check-live-drift --check-signatures --env production --schema schema.sql
        ↳ Live: check both column/table drift AND function overload drift

      confiture migrate validate --list-patterns --format json
        ↳ Print the catalog of every detection pattern (machine-readable, no DB needed)

      confiture migrate validate --check-acls -c db/environments/prod.yaml
        ↳ Static: verify every CREATE TABLE has a matching GRANT (no DB needed)

    FLAG INTERACTIONS:
      --check-signatures takes both a singular --schema and a plural --schemas:
        --schema FILE       Path to a *SQL file* to compare function signatures against.
                            If omitted, schema is auto-built from db/schema/ DDL files.
        --schemas LIST      Comma-separated list of *database schema names* (default: public)
                            to scan in the live DB for stale overloads.
        They're different things — file path vs. DB schema names — and both flags can
        appear in the same invocation.

      Checks compose: pass as many as you like and all of them run, sharing one
      config parse and one database connection. The exit code is the worst
      outcome across them. One exception, and it is loud:
        --list-patterns / --list-unmigrated-bodies  report modes; they always exit
                            0, so there is no result to compose. Combining either
                            with anything else is rejected (exit 5).

      --idempotent composes with the git checks from 0.41.0. It was rejected
      alongside --check-drift / --require-migration / --require-migration-bodies /
      --require-grant-migration in 0.37.0–0.40.0, because the pre-composition
      dispatch ran the git branch and silently skipped idempotency (#181).

    JSON SCHEMA:
      See docs/reference/json-schemas.md for the JSON output schemas:
        - --idempotent: migrate-validate-idempotent.schema.json
        - --list-patterns: migrate-validate-list-patterns.schema.json
        - --check-acls: migrate-validate-check-acl-coverage.schema.json
        - two or more checks: migrate-validate-composed.schema.json (a wrapper
          keyed by check name; one check still emits its own payload verbatim)

    RELATED:
      confiture migrate generate - Create new migration file
      confiture migrate fix      - Auto-fix non-idempotent migrations
      confiture migrate status   - View migration history
    """
    json_mode = is_json(format_output)
    if not list_patterns:
        config = _resolve_config(config, env)

    # The git checks build the expected schema via GitSchemaBuilder(env),
    # so --env must reach them: on projects whose `local` env includes
    # seed data, pointing at a DDL-only env is the difference between a
    # working gate and a silent no-op (#194). --config-only callers keep
    # the historical "local" default.
    opts = ValidateOptions(
        format_output=format_output,
        json_mode=json_mode,
        migrations_dir=migrations_dir,
        config=config,
        git_env=env or "local",
        schema_file=schema_file,
        scratch_url=scratch_url,
        schemas=check_signature_schemas,
        ssh_via=ssh_via,
        ddl_dir=list(ddl_dir) if ddl_dir else [],
        list_patterns=list_patterns,
        list_unmigrated_bodies=list_unmigrated_bodies,
        check_drift=check_drift,
        require_migration=require_migration,
        require_migration_bodies=require_migration_bodies,
        require_grant_migration=require_grant_migration,
        check_acls=check_acls,
        check_ownership_coverage=check_ownership_coverage,
        check_function_uniqueness=check_function_uniqueness,
        check_security_definer=check_security_definer,
        check_imports=check_imports,
        check_live_drift=check_live_drift,
        ignore_column_order=ignore_column_order,
        check_signatures=check_signatures,
        check_body_views=check_body_views,
        check_body_replay=check_body_replay,
        idempotent=idempotent,
        allow_grant_only=allow_grant_only,
        staged=staged,
        check_body=check_body,
        show_diff=show_diff,
        strict_cor=strict_cor,
        fail_on_unanalyzable=fail_on_unanalyzable,
        secdef_against_db=secdef_against_db,
        emit_remediation=emit_remediation,
        fix_naming=fix_naming,
        dry_run=dry_run,
        # #181: --base-ref carries a truthy default ("origin/main"), so the
        # value alone cannot say whether the operator asked for scoping.
        # Gate on the parameter source; without this every unscoped run
        # would silently scope, and a plain --idempotent in a non-git tree
        # would exit 7.
        idempotent_base_ref=(
            (since or base_ref)
            if (param_is_explicit(ctx, "base_ref", "since") and not staged)
            else None
        ),
    )

    validate_flag_dependencies(opts)
    checks = build_registry(opts)
    _reject_exclusive_composition(checks)

    with ValidationContext(
        config_path=config,
        ssh_via=ssh_via,
        effective_base_ref=since or base_ref,
        staged=staged,
    ) as run_ctx:
        outcomes = run_checks(checks, run_ctx)

    payload = compose_payload(outcomes)
    if payload is not None:
        _output_json(payload, output_file, console)

    exit_code = aggregate_exit_code(outcomes)
    if exit_code:
        raise typer.Exit(exit_code)  # success-signal: a check found something


def _reject_exclusive_composition(checks: list[ValidationCheck]) -> None:
    """Reject report modes combined with anything else.

    ``--list-patterns`` and ``--list-unmigrated-bodies`` are *report* modes, not
    validation modes: they dump a catalog or size a backlog and always exit 0,
    so there is no exit code for them to compose into. Silently running one and
    dropping the other is the very defect #187 is about, so this fails loudly
    and names both flags.

    Raises:
        ConfigurationError: an exclusive check was requested alongside another.
    """
    on = [c for c in checks if c.enabled]
    if len(on) < 2:
        return
    for check in on:
        if not check.exclusive:
            continue
        others = ", ".join(c.flag for c in on if c is not check)
        raise ConfigurationError(
            f"{check.flag} cannot be combined with {others}: it is a report mode, "
            "not a validation check, so there is no result to combine.",
            resolution_hint=f"Run `{check.flag}` on its own, then run the other checks.",
        )
