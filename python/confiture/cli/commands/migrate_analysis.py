"""Migration analysis commands: migrate diff, validate, fix, introspect, verify."""

import json
import re
from pathlib import Path
from typing import Any

import typer

from confiture.cli.formatters.common import display_drift_report, display_signature_drift_report
from confiture.cli.helpers import (
    _emit_hint,
    _fix_idempotency,
    _fix_ownership,
    _output_json,
    _resolve_config,
    _validate_idempotency,
    console,
    error_console,
)
from confiture.core._migrator.session import MigratorSession
from confiture.core.connection import create_connection, load_config, open_connection
from confiture.core.differ import SchemaDiffer
from confiture.core.drift import SchemaDriftDetector
from confiture.core.migration_generator import MigrationGenerator
from confiture.core.migrator import Migrator


def migrate_diff(
    old_schema: Path = typer.Argument(..., help="Old schema file"),
    new_schema: Path = typer.Argument(..., help="New schema file"),
    generate: bool = typer.Option(
        False,
        "--generate",
        help="Generate migration from diff (default: off)",
    ),
    name: str = typer.Option(
        None,
        "--name",
        help="Migration name (default: none, required with --generate)",
    ),
    migrations_dir: Path = typer.Option(
        Path("db/migrations"),
        "--migrations-dir",
        help="Migrations directory (default: db/migrations)",
    ),
    format_type: str = typer.Option(
        "text",
        "--format",
        "-f",
        help="Output format: text, json, or csv (default: text)",
    ),
    report_file: Path | None = typer.Option(
        None,
        "--report",
        "-o",
        help="Save report to file (default: stdout)",
    ),
) -> None:
    """Compare two schema files and identify differences.

    PROCESS:
      Compares old and new schema files, shows additions/modifications/removals.
      Optionally generates a migration file from the detected differences.

    EXAMPLES:
      confiture migrate diff schema_old.sql schema_new.sql
        ↳ Show all differences between two schemas

      confiture migrate diff schema_old.sql schema_new.sql --generate --name add_payments
        ↳ Generate migration file from differences

      confiture migrate diff db/generated/schema_local.sql db/schema/production.sql
        ↳ Compare local schema with production target

    RELATED:
      confiture migrate generate - Create migration template
      confiture migrate validate - Check migration integrity
      confiture build             - Build schema from DDL files
    """
    try:
        # Validate format
        if format_type not in ("text", "json", "csv"):
            console.print(f"[red]❌ Invalid format: {format_type}. Use text, json, or csv[/red]")
            raise typer.Exit(1)

        # Validate files exist
        if not old_schema.exists():
            console.print(f"[red]❌ Old schema file not found: {old_schema}[/red]")
            raise typer.Exit(1)

        if not new_schema.exists():
            console.print(f"[red]❌ New schema file not found: {new_schema}[/red]")
            raise typer.Exit(1)

        # Read schemas
        old_sql = old_schema.read_text()
        new_sql = new_schema.read_text()

        # Compare schemas
        differ = SchemaDiffer()
        diff = differ.compare(old_sql, new_sql)

        # Convert changes to SchemaChange objects
        from confiture.cli.formatters.migrate_formatter import format_migrate_diff_result
        from confiture.models.results import MigrateDiffChange, MigrateDiffResult

        changes = [MigrateDiffChange(change.type, str(change)) for change in diff.changes]
        migration_file_name = None

        # Handle migration generation if requested
        if generate:
            if not name:
                console.print("[red]❌ Migration name is required when using --generate[/red]")
                console.print(
                    "Usage: confiture migrate diff old.sql new.sql --generate --name migration_name"
                )
                raise typer.Exit(1)

            # Ensure migrations directory exists
            migrations_dir.mkdir(parents=True, exist_ok=True)

            # Generate migration
            generator = MigrationGenerator(migrations_dir=migrations_dir)
            migration_file = generator.generate(diff, name=name)
            migration_file_name = migration_file.name

        # Create result and format output
        result = MigrateDiffResult(
            success=True,
            has_changes=diff.has_changes(),
            changes=changes,
            migration_generated=generate and migration_file_name is not None,
            migration_file=migration_file_name,
        )

        format_migrate_diff_result(result, format_type, report_file, console)

    except Exception as e:
        from confiture.cli.formatters.migrate_formatter import format_migrate_diff_result
        from confiture.models.results import MigrateDiffResult

        result = MigrateDiffResult(
            success=False,
            has_changes=False,
            error=str(e),
        )
        format_migrate_diff_result(result, format_type, report_file, console)
        raise typer.Exit(1) from e


def _emit_pattern_catalog(format_output: str, output_file: Path | None) -> None:
    """Render the idempotency pattern catalog.

    Read-only: no DB, no config, no migrations directory.

    Args:
        format_output: ``"text"`` for a Rich table, ``"json"`` for the
            machine-readable catalog envelope.
        output_file: Optional path to write JSON output; ignored for text.
    """
    from confiture.core.idempotency.patterns import list_patterns

    entries = list_patterns()

    if format_output == "json":
        # `hints` is pre-allocated per the documented JSON-schema contract
        # (docs/reference/json-schemas/migrate-validate-list-patterns.schema.json).
        # `--list-patterns` is a read-only catalog query with no ambiguous
        # success state, so the list is always empty; the key still
        # appears so consumers can code against a stable shape.
        _output_json(
            {"version": "1", "patterns": entries, "hints": []},
            output_file,
            console,
        )
        return

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


def _display_body_drift_report(report: Any, console: Any) -> None:
    """Print a FunctionBodyDriftReport to the console in human-readable form."""
    if not report.has_drift:
        console.print(
            f"[green]✓[/green] 0 function body drift(s) detected "
            f"({report.functions_checked} checked, "
            f"{report.detection_time_ms:.1f}ms)"
        )
        return

    console.print(
        f"[yellow]⚠[/yellow]  {len(report.body_drifts)} function body "
        f"drift(s) detected ({report.functions_checked} checked)"
    )
    for drift in report.body_drifts:
        console.print(f"\n  [bold]{drift.signature_key}[/bold]")
        console.print(f"    Source hash:   [cyan]{drift.source_hash}[/cyan]")
        console.print(f"    Database hash: [red]{drift.db_hash}[/red]")
        console.print(
            "    Hint: function body differs — run "
            "[bold]fix-signatures --apply[/bold] to re-apply from source"
        )


def migrate_validate(
    migrations_dir: Path = typer.Option(
        Path("db/migrations"),
        "--migrations-dir",
        help="Migrations directory (default: db/migrations)",
    ),
    fix_naming: bool = typer.Option(
        False,
        "--fix-naming",
        help="Auto-rename orphaned files to match convention (default: off)",
    ),
    idempotent: bool = typer.Option(
        False,
        "--idempotent",
        help="Validate migrations are idempotent, can re-run (default: off)",
    ),
    list_patterns: bool = typer.Option(
        False,
        "--list-patterns",
        help=(
            "Print machine-readable catalog of detection patterns "
            "(read-only, no DB needed). Use with `--format json` for tooling."
        ),
    ),
    strict_cor: bool = typer.Option(
        False,
        "--strict-cor",
        help=(
            "Treat info-severity CREATE OR REPLACE shape-risk findings as "
            "blocking (exit 1). Off by default — info findings are still "
            "rendered but don't fail the gate."
        ),
    ),
    check_drift: bool = typer.Option(
        False,
        "--check-drift",
        help="Validate schema against git refs for drift (default: off)",
    ),
    require_migration: bool = typer.Option(
        False,
        "--require-migration",
        help=(
            "Ensure DDL changes have migration files (static, no DB required). "
            "Also detects function parameter type changes missing a DROP FUNCTION. "
            "Companion to --check-signatures which detects stale overloads in a live DB."
        ),
    ),
    base_ref: str = typer.Option(
        "origin/main",
        "--base-ref",
        help="Base git reference for comparison (default: origin/main)",
    ),
    since: str | None = typer.Option(
        None,
        "--since",
        help="Shortcut for --base-ref (default: none)",
    ),
    staged: bool = typer.Option(
        False,
        "--staged",
        help="Validate staged files only, pre-commit mode (default: off)",
    ),
    require_grant_migration: bool = typer.Option(
        False,
        "--require-grant-migration",
        help="Fail if staged changes in db/7_grant/ exist without a corresponding migration file (default: off)",
    ),
    allow_grant_only: bool = typer.Option(
        False,
        "--allow-grant-only",
        help="Suppress --require-grant-migration failure for build-only branches (default: off)",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Preview changes without renaming (default: off)",
    ),
    check_live_drift: bool = typer.Option(
        False,
        "--check-live-drift",
        help=(
            "Compare the live database schema against the DDL files. "
            "Requires --config and a database connection."
        ),
    ),
    check_signatures: bool = typer.Option(
        False,
        "--check-signatures",
        help=(
            "Compare function signatures in --schema against the live DB. "
            "Detects stale overloads created by CREATE OR REPLACE with changed param types. "
            "Companion to --require-migration (static pre-commit check, no DB needed). "
            "Requires --config (or --env) and --schema."
        ),
    ),
    check_imports: bool = typer.Option(
        False,
        "--check-imports",
        help=(
            "Import-check pending Python migration modules. "
            "Level 1: catches syntax errors and missing imports. "
            "Level 2: verifies version, name, up(), down() are defined. "
            "No database connection required."
        ),
    ),
    check_body: bool = typer.Option(
        False,
        "--check-body",
        help=(
            "Compare function bodies (prosrc) between source SQL and the live database. "
            "Requires --check-signatures. Opt-in because body comparison is heavier than "
            "signature-only comparison."
        ),
    ),
    check_acls: bool = typer.Option(
        False,
        "--check-acls",
        "--check-acl-coverage",  # back-compat alias (deprecated in 0.12.0)
        help=(
            "Static: verify every `CREATE TABLE` in db/migrations/ has a matching "
            "`GRANT` either in the same migration or in the configured global grant "
            "sweep directory (defaults to db/7_grant). No-op when the config has no "
            "`acls:` block. No database connection required.  "
            "Use --check-acls; --check-acl-coverage is a deprecated alias."
        ),
    ),
    check_ownership_coverage: bool = typer.Option(
        False,
        "--check-ownership-coverage",
        help=(
            "Static: verify every `CREATE { TABLE | VIEW | MATERIALIZED VIEW | SEQUENCE }` "
            "in db/migrations/ is paired with a matching `ALTER … OWNER TO <expected_owner>` "
            "in the same file (`own_001`).  Also flags bare `ALTER … OWNER TO` on objects "
            "the migration didn't create (`own_002` — three severity tiers: silent when "
            "guarded + companion `requires_superuser=True`, WARNING when only guarded, "
            "ERROR when bare).  No-op when the config has no `ownership:` block, or when "
            "`ownership.lint_enabled` is false.  Requires the [ast] extra (pglast)."
        ),
    ),
    check_function_uniqueness: bool = typer.Option(
        False,
        "--check-function-uniqueness",
        help=(
            "Static: verify every `CREATE FUNCTION` / `CREATE PROCEDURE` "
            "in the configured DDL directories has a unique fully-qualified "
            "signature. Two files defining the same `schema.name(args)` "
            "are silently shadowed by `confiture build` — this rule "
            "(`func_001`) catches the duplicate first. No-op when the "
            "config has no `function_coverage:` block, or when "
            "`function_coverage.enabled` is false. Requires the [ast] extra (pglast)."
        ),
    ),
    ddl_dir: list[Path] = typer.Option(
        None,
        "--ddl-dir",
        help=(
            "DDL directory to scan for `--check-function-uniqueness` "
            "(repeatable). Defaults to `db/schema` if not provided."
        ),
    ),
    check_signature_schemas: str = typer.Option(
        "public",
        "--schemas",
        help=(
            "Comma-separated list of schemas to inspect for stale overloads "
            "(default: public). Used with --check-signatures."
        ),
    ),
    config: Path = typer.Option(
        Path("confiture.yaml"),
        "-c",
        "--config",
        help="Config file path. Use --env as a shortcut for db/environments/{name}.yaml.",
    ),
    env: str | None = typer.Option(
        None,
        "--env",
        help=(
            "Environment name — shortcut for --config db/environments/{name}.yaml "
            "(e.g. --env production). Cannot be combined with --config."
        ),
    ),
    ssh_via: str | None = typer.Option(
        None,
        "--ssh",
        help=(
            "Open an SSH tunnel before connecting: user@host or host "
            "(e.g. lionel@printoptim.io).  Used with --check-signatures and "
            "--check-live-drift.  Overrides the ssh_tunnel block in the config file."
        ),
    ),
    schema_file: Path | None = typer.Option(
        None,
        "--schema",
        help=(
            "Schema SQL file to compare against. "
            "If omitted with --check-signatures, schema is auto-built from DDL files."
        ),
    ),
    format_output: str = typer.Option(
        "text",
        "--format",
        "-f",
        help="Output format: text or json (default: text)",
    ),
    output_file: Path | None = typer.Option(
        None,
        "--output",
        "-o",
        help="Save output to file (default: stdout)",
    ),
) -> None:
    """Validate migration files follow naming and quality conventions.

    PROCESS:
      Checks for orphaned files, validates naming pattern ({NNN}_{name}.sql),
      optionally verifies idempotency, checks for schema drift, and ensures DDL
      changes have corresponding migration files.

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

    JSON SCHEMA:
      See docs/reference/json-schemas.md for the JSON output schemas:
        - --idempotent: migrate-validate-idempotent.schema.json
        - --list-patterns: migrate-validate-list-patterns.schema.json
        - --check-acls: migrate-validate-check-acl-coverage.schema.json

    RELATED:
      confiture migrate generate - Create new migration file
      confiture migrate fix      - Auto-fix non-idempotent migrations
      confiture migrate status   - View migration history
    """
    try:
        # Validate output format
        if format_output not in ("text", "json", "csv"):
            console.print(
                f"[red]❌ Invalid format: {format_output}. Use 'text', 'json', or 'csv'[/red]"
            )
            raise typer.Exit(1)

        # --list-patterns is a read-only catalog query. Short-circuit before
        # touching config / migrations directory / DB. Must run before
        # _resolve_config so projects without a confiture.yaml can still
        # introspect the pattern catalog.
        if list_patterns:
            if idempotent:
                error_console.print(
                    "[red]Error:[/red] --list-patterns is mutually exclusive with --idempotent"
                )
                raise typer.Exit(2)
            _emit_pattern_catalog(format_output, output_file)
            return

        # Resolve --env / --config to a single config path
        try:
            config = _resolve_config(config, env)
        except Exception as e:
            if format_output == "json":
                _output_json({"error": str(e)}, output_file, console)
            else:
                error_console.print(f"[red]❌ {e}[/red]")
            raise typer.Exit(2) from e

        # Handle git validation flags
        if check_drift or require_migration or require_grant_migration or staged:
            from confiture.cli.git_validation import (
                validate_git_drift,
                validate_git_flags_in_repo,
                validate_grant_accompaniment,
                validate_migration_accompaniment,
            )

            # Override base_ref with since if provided
            effective_base_ref = since or base_ref

            # Validate we're in a git repo
            try:
                validate_git_flags_in_repo()
            except Exception as e:
                if format_output == "json":
                    result = {"error": str(e)}
                    _output_json(result, output_file, console)
                else:
                    console.print(f"[red]❌ {e}[/red]")
                raise typer.Exit(2) from e

            # Run git drift check
            drift_passed = True
            if check_drift:
                try:
                    drift_result = validate_git_drift(
                        env="local",
                        base_ref=effective_base_ref,
                        target_ref="HEAD" if not staged else "HEAD",
                        console=console,
                        format_output=format_output,
                    )
                    if not drift_result.get("passed"):
                        drift_passed = False
                        if format_output == "json":
                            result = {
                                "status": "failed",
                                "check": "drift",
                                **drift_result,
                            }
                            _output_json(result, output_file, console)
                            raise typer.Exit(1)
                except Exception as e:
                    if format_output == "json":
                        result = {"error": f"Drift check failed: {e}"}
                        _output_json(result, output_file, console)
                    else:
                        console.print(f"[red]❌ Drift check failed: {e}[/red]")
                    raise typer.Exit(1) from e

            # Run migration accompaniment check
            accompaniment_passed = True
            if require_migration:
                try:
                    acc_result = validate_migration_accompaniment(
                        env="local",
                        base_ref=effective_base_ref,
                        target_ref="HEAD" if not staged else "HEAD",
                        console=console,
                        format_output=format_output,
                    )
                    if not acc_result.get("is_valid"):
                        accompaniment_passed = False
                        if format_output == "json":
                            result = {
                                "status": "failed",
                                "check": "accompaniment",
                                **acc_result,
                            }
                            _output_json(result, output_file, console)
                            raise typer.Exit(1)
                except Exception as e:
                    if format_output == "json":
                        result = {"error": f"Accompaniment check failed: {e}"}
                        _output_json(result, output_file, console)
                    else:
                        console.print(f"[red]❌ Accompaniment check failed: {e}[/red]")
                    raise typer.Exit(1) from e

            # Run grant accompaniment check
            grant_passed = True
            if require_grant_migration and not allow_grant_only:
                try:
                    grant_result = validate_grant_accompaniment(
                        base_ref=effective_base_ref,
                        target_ref="HEAD",
                        staged_only=staged,
                        console=console,
                        format_output=format_output,
                        migrations_dir=str(migrations_dir),
                    )
                    if not grant_result.get("is_valid"):
                        grant_passed = False
                        if format_output == "json":
                            result = {
                                "status": "failed",
                                "check": "grant_accompaniment",
                                **grant_result,
                            }
                            _output_json(result, output_file, console)
                            raise typer.Exit(1)
                except typer.Exit:
                    raise
                except Exception as e:
                    if format_output == "json":
                        result = {"error": f"Grant accompaniment check failed: {e}"}
                        _output_json(result, output_file, console)
                    else:
                        console.print(f"[red]❌ Grant accompaniment check failed: {e}[/red]")
                    raise typer.Exit(1) from e

            # Check if all checks passed (for text output)
            if drift_passed and accompaniment_passed and grant_passed:
                if format_output == "json":
                    result = {
                        "status": "passed",
                        "checks": [
                            c
                            for c, flag in [
                                ("drift", check_drift),
                                ("accompaniment", require_migration),
                                ("grant_accompaniment", require_grant_migration),
                            ]
                            if flag
                        ],
                    }
                    _output_json(result, output_file, console)
                else:
                    console.print("[green]✅ All git validation checks passed[/green]")
                return
            else:
                # At least one check failed in text mode
                raise typer.Exit(1)

        # Guard: --check-body requires --check-signatures
        if check_body and not check_signatures:
            error_console.print("[red]Error:[/red] --check-body requires --check-signatures")
            raise typer.Exit(2)

        # Run ACL coverage check on migration files (static, no DB).
        if check_acls:
            from confiture.cli.acl_loader import load_acl_expectations
            from confiture.core.linting.schema_linter import SchemaLinter

            if not config.exists():
                error_console.print(f"[red]❌ Config file not found: {config}[/red]")
                raise typer.Exit(2)

            config_data = load_config(config)
            # No-op when the project hasn't adopted the `acls:` block yet.
            expectations = load_acl_expectations(config_data, config, require=False)

            grant_dir_raw = (
                config_data.get("migration", {}).get("grant_dir")
                if isinstance(config_data, dict)
                else None
            ) or "db/7_grant"
            grant_dir = (config.parent / grant_dir_raw).resolve()

            acl_report = SchemaLinter().lint_migrations(
                migrations_dir=migrations_dir,
                expectations=expectations,
                grant_dir=grant_dir if grant_dir.exists() else None,
            )

            if format_output == "json":
                _output_json(
                    {
                        "check": "acl_coverage",
                        "violations": [
                            {
                                "rule_id": v.rule_id,
                                "severity": v.severity.value,
                                "object_name": v.object_name,
                                "message": v.message,
                                "file_path": v.file_path,
                            }
                            for v in (acl_report.errors + acl_report.warnings + acl_report.info)
                        ],
                        "hints": [],
                    },
                    output_file,
                    console,
                )
            elif acl_report.has_errors:
                console.print(
                    f"[red]❌ ACL coverage check failed: "
                    f"{len(acl_report.errors)} violation(s)[/red]"
                )
                for v in acl_report.errors:
                    # Escape the rule_id brackets so Rich doesn't read them as markup.
                    console.print(f"  [red]✗[/red] \\[{v.rule_id}] {v.object_name}: {v.message}")
            else:
                console.print("[green]✅ All migrations have ACL coverage[/green]")

            if acl_report.has_errors:
                raise typer.Exit(1)
            return

        # Run ownership coverage check on migration files (static, no DB).
        if check_ownership_coverage:
            from confiture.cli.ownership_loader import load_ownership_expectation
            from confiture.core.linting.libraries.ownership import (
                Own001OwnershipCoverage,
                Own002BareAlterOwner,
            )

            if not config.exists():
                error_console.print(f"[red]❌ Config file not found: {config}[/red]")
                raise typer.Exit(2)

            config_data = load_config(config)
            # No-op when the project hasn't adopted the `ownership:` block yet.
            ownership_exp = load_ownership_expectation(config_data, config, require=False)

            ownership_violations = []
            if ownership_exp is not None:
                ownership_violations = Own001OwnershipCoverage(expectation=ownership_exp).check(
                    migrations_dir
                )
                # Issue #137 — own_002 sibling rule: bare `ALTER … OWNER TO`
                # on objects the migration didn't create.
                ownership_violations.extend(
                    Own002BareAlterOwner(expectation=ownership_exp).check(migrations_dir)
                )

            # Errors fail the gate (exit 1); warnings print but don't.
            from confiture.core.linting.schema_linter import RuleSeverity

            has_errors = any(v.severity == RuleSeverity.ERROR for v in ownership_violations)

            if format_output == "json":
                _output_json(
                    {
                        "check": "ownership_coverage",
                        "violations": [
                            {
                                "rule_id": v.rule_id,
                                "severity": v.severity.value,
                                "object_name": v.object_name,
                                "message": v.message,
                                "file_path": v.file_path,
                                "line_number": v.line_number,
                            }
                            for v in ownership_violations
                        ],
                    },
                    output_file,
                    console,
                )
            elif ownership_violations:
                console.print(
                    f"[red]❌ Ownership coverage check failed: "
                    f"{len(ownership_violations)} violation(s)[/red]"
                )
                for v in ownership_violations:
                    # Escape the rule_id brackets so Rich doesn't read them as markup.
                    color = "red" if v.severity == RuleSeverity.ERROR else "yellow"
                    mark = "✗" if v.severity == RuleSeverity.ERROR else "⚠"
                    console.print(
                        f"  [{color}]{mark}[/{color}] \\[{v.rule_id}] {v.object_name}: {v.message}"
                    )
            else:
                console.print("[green]✅ All migrations have ownership coverage[/green]")

            if has_errors:
                raise typer.Exit(1)
            return

        # Run function-uniqueness check on DDL files (static, no DB).
        if check_function_uniqueness:
            from confiture.cli.function_coverage_loader import load_function_coverage
            from confiture.core.linting.libraries.functions import (
                Func001FunctionUniqueness,
            )

            if not config.exists():
                error_console.print(f"[red]❌ Config file not found: {config}[/red]")
                raise typer.Exit(2)

            config_data = load_config(config)
            coverage = load_function_coverage(config_data, config, require=False)

            scan_paths = list(ddl_dir) if ddl_dir else [Path("db/schema")]

            func_violations = []
            if coverage is not None and coverage.enabled:
                func_violations = Func001FunctionUniqueness(coverage=coverage).check(scan_paths)

            if format_output == "json":
                _output_json(
                    {
                        "check": "function_uniqueness",
                        "violations": [
                            {
                                "rule_id": v.rule_id,
                                "severity": v.severity.value,
                                "object_name": v.object_name,
                                "object_type": v.object_type,
                                "message": v.message,
                                "file_path": v.file_path,
                                "line_number": v.line_number,
                            }
                            for v in func_violations
                        ],
                    },
                    output_file,
                    console,
                )
            elif func_violations:
                console.print(
                    f"[red]❌ Function uniqueness check failed: "
                    f"{len(func_violations)} violation(s)[/red]"
                )
                for v in func_violations:
                    console.print(f"  [red]✗[/red] \\[{v.rule_id}] {v.object_name}: {v.message}")
            else:
                console.print("[green]✅ All callables have unique signatures[/green]")

            if func_violations:
                raise typer.Exit(1)
            return

        # Run import check on Python migration modules
        if check_imports:
            from confiture.core.import_checker import ImportChecker

            checker = ImportChecker(migrations_dir)
            import_result = checker.check()

            if format_output == "json":
                _output_json(
                    {"check": "imports", **import_result.to_dict()},
                    output_file,
                    console,
                )
            else:
                if import_result.success:
                    console.print(
                        f"[green]✅ All {import_result.checked} Python migration(s) passed import check[/green]"
                    )
                    if import_result.skipped_sql:
                        console.print(
                            f"  [dim]({import_result.skipped_sql} SQL migration(s) skipped)[/dim]"
                        )
                else:
                    console.print(
                        f"[red]❌ Import check failed: {import_result.failed}/{import_result.checked} file(s) have issues[/red]"
                    )
                    for v in import_result.violations:
                        console.print(
                            f"  [red]✗[/red] [{v.rule}] {Path(v.file_path).name}: {v.message}"
                        )

            if not import_result.success:
                raise typer.Exit(1)
            return

        # Run live drift check
        if check_live_drift:
            live_drift_passed = True
            try:
                if not config.exists():
                    error_console.print(f"[red]❌ Config file not found: {config}[/red]")
                    raise typer.Exit(2)
                if schema_file is None:
                    error_console.print(
                        "[red]❌ --schema is required with --check-live-drift[/red]"
                    )
                    raise typer.Exit(2)
                config_data = load_config(config)
                conn = create_connection(config_data)
                try:
                    detector = SchemaDriftDetector(conn)
                    drift_report = detector.compare_with_schema_file(str(schema_file))
                finally:
                    conn.close()
                if format_output == "json":
                    _output_json(
                        {"check": "live_drift", **drift_report.to_dict()}, output_file, console
                    )
                else:
                    display_drift_report(drift_report, console)
                if drift_report.has_critical_drift:
                    live_drift_passed = False
            except typer.Exit:
                raise
            except Exception as e:
                error_console.print(f"[red]❌ Live drift check failed: {e}[/red]")
                raise typer.Exit(2) from e

            if not live_drift_passed:
                raise typer.Exit(1)
            return

        # Run live function signature drift check
        if check_signatures:
            try:
                if not config.exists():
                    error_console.print(f"[red]❌ Config file not found: {config}[/red]")
                    raise typer.Exit(2)

                config_data = load_config(config)
                schemas = [s.strip() for s in check_signature_schemas.split(",") if s.strip()]

                # Resolve source SQL: explicit --schema file or auto-build from DDL files
                if schema_file is not None:
                    source_sql = schema_file.read_text()
                else:
                    try:
                        from confiture.core.builder import SchemaBuilder  # noqa: PLC0415

                        env_name = (
                            config_data.get("name")
                            if isinstance(config_data, dict)
                            else getattr(config_data, "name", None)
                        )
                        if not env_name:
                            raise ValueError(
                                "Config has no 'name' field — cannot auto-build schema. "
                                "Pass --schema explicitly."
                            )
                        builder = SchemaBuilder(env=env_name)
                        source_sql = builder.build(schema_only=True)
                        if format_output == "text":
                            console.print("[dim]  (schema auto-built from DDL files)[/dim]")
                    except Exception as build_exc:
                        error_console.print(
                            f"[red]❌ --schema not provided and auto-build failed: {build_exc}[/red]\n"
                            "  Either run 'confiture build' first or pass --schema explicitly."
                        )
                        raise typer.Exit(2) from build_exc

                from confiture.core.function_signature_drift import (  # noqa: PLC0415
                    FunctionSignatureDriftDetector,
                )
                from confiture.core.function_signature_parser import (  # noqa: PLC0415
                    FunctionSignatureParser,
                )
                from confiture.core.live_function_catalog import (  # noqa: PLC0415
                    LiveFunctionCatalog,
                )

                source_sigs = FunctionSignatureParser().parse(source_sql)

                # Build effective config: --ssh flag overrides config-file ssh_tunnel
                effective_config: Any = config_data
                if ssh_via:
                    from confiture.config.environment import SshTunnelConfig  # noqa: PLC0415

                    parts = ssh_via.split("@", 1)
                    ssh_host = parts[1] if len(parts) == 2 else parts[0]
                    ssh_user = parts[0] if len(parts) == 2 else None

                    # Wrap config_data with an ssh_tunnel override
                    class _SshOverride:  # noqa: N801
                        """Thin adapter that layers an ssh_tunnel onto config_data."""

                        def __init__(self, base: Any, tunnel: SshTunnelConfig) -> None:
                            self._base = base
                            self.ssh_tunnel = tunnel

                        @property
                        def database_url(self) -> str:
                            if hasattr(self._base, "database_url"):
                                return self._base.database_url  # type: ignore[no-any-return]
                            return self._base.get("database_url", "")

                        def get(self, key: str, default: Any = None) -> Any:  # noqa: ANN401
                            return getattr(self._base, key, None) or (
                                self._base.get(key, default)
                                if isinstance(self._base, dict)
                                else default
                            )

                    effective_config = _SshOverride(
                        config_data,
                        SshTunnelConfig(host=ssh_host, user=ssh_user),
                    )
                    if format_output == "text":
                        console.print(f"[dim]  (connecting via SSH tunnel to {ssh_via})[/dim]")

                with open_connection(effective_config) as conn:
                    live_catalog = LiveFunctionCatalog(conn)
                    live_sigs = live_catalog.get_signatures(schemas=schemas)
                    detector = FunctionSignatureDriftDetector()
                    drift_report = detector.compare(source_sigs, live_sigs, schemas_checked=schemas)

                    body_report = None
                    if check_body:
                        from confiture.core.function_body_drift import (  # noqa: PLC0415
                            FunctionBodyDriftDetector,
                        )

                        source_with_bodies = FunctionSignatureParser().parse_with_bodies(source_sql)
                        source_bodies: dict[str, str | None] = {
                            sig.signature_key(): body for sig, body in source_with_bodies
                        }
                        live_bodies = live_catalog.get_bodies(
                            schemas=schemas,
                            sig_keys=set(source_bodies),
                        )
                        body_report = FunctionBodyDriftDetector().compare(
                            source_bodies, live_bodies
                        )

                if format_output == "json":
                    json_output: dict[str, Any] = {
                        "check": "function_signature_drift",
                        **drift_report.to_dict(),
                    }
                    if body_report is not None:
                        json_output["body_drift"] = {
                            "has_drift": body_report.has_drift,
                            "body_drifts": [
                                {
                                    "schema": d.schema,
                                    "name": d.name,
                                    "signature_key": d.signature_key,
                                    "source_hash": d.source_hash,
                                    "db_hash": d.db_hash,
                                }
                                for d in body_report.body_drifts
                            ],
                            "functions_checked": body_report.functions_checked,
                            "detection_time_ms": body_report.detection_time_ms,
                        }
                    _output_json(json_output, output_file, console)
                else:
                    display_signature_drift_report(drift_report, console)
                    if body_report is not None:
                        _display_body_drift_report(body_report, console)

                has_any_drift = drift_report.has_critical_drift or (
                    body_report is not None and body_report.has_drift
                )
                if has_any_drift:
                    raise typer.Exit(1)
                return
            except typer.Exit:
                raise
            except Exception as e:
                error_console.print(f"[red]❌ Signature drift check failed: {e}[/red]")
                raise typer.Exit(2) from e

        if not migrations_dir.exists():
            if format_output == "json":
                result = {"error": f"Migrations directory not found: {migrations_dir.absolute()}"}
                _output_json(result, output_file, console)
            else:
                console.print(f"[red]❌ Migrations directory not found: {migrations_dir}[/red]")
            raise typer.Exit(1)

        # Handle idempotency validation
        if idempotent:
            _validate_idempotency(migrations_dir, format_output, output_file, strict_cor=strict_cor)
            return

        # Use Migrator to find orphaned files (needs instance for method)
        from unittest.mock import Mock

        from confiture.core.migrator import Migrator, find_duplicate_migration_versions

        mock_conn = Mock()
        migrator = Migrator(connection=mock_conn)

        # Check for duplicate migration versions (hard error)
        duplicate_versions = find_duplicate_migration_versions(migrations_dir)

        # Find orphaned files
        orphaned_files = migrator.find_orphaned_sql_files(migrations_dir)

        if duplicate_versions:
            if format_output == "json":
                result = {
                    "status": "issues_found",
                    "duplicate_versions": {
                        v: [f.name for f in files] for v, files in duplicate_versions.items()
                    },
                }
                if orphaned_files:
                    result["orphaned_files"] = [f.name for f in orphaned_files]
                _output_json(result, output_file, console)
            else:
                console.print("[red]❌ Duplicate migration versions detected[/red]")
                console.print(
                    "[red]Multiple migration files share the same version number:[/red]\n"
                )
                for version, files in sorted(duplicate_versions.items()):
                    console.print(f"  Version {version}:")
                    for f in files:
                        console.print(f"    • {f.name}")
                console.print("\n[yellow]💡 Rename files to use unique version prefixes.[/yellow]")
                console.print(
                    "[yellow]   Use 'confiture migrate generate' to auto-assign the next version.[/yellow]"
                )
            raise typer.Exit(1)

        if not orphaned_files:
            if format_output == "json":
                result = {
                    "status": "ok",
                    "message": "No orphaned migration files found",
                    "fixed": [],
                    "errors": [],
                }
                _output_json(result, output_file, console)
            else:
                console.print("[green]✅ No orphaned migration files found[/green]")
            return

        # If fix_naming is requested, fix the files
        if fix_naming:
            # --dry-run takes precedence
            is_dry_run = dry_run
            result = migrator.fix_orphaned_sql_files(migrations_dir, dry_run=is_dry_run)

            if format_output == "json":
                output_dict: dict[str, Any] = {
                    "status": "fixed" if not is_dry_run else "preview",
                    "fixed": result.get("renamed", []),
                    "errors": result.get("errors", []),
                }
                _output_json(output_dict, output_file, console)
            else:
                # Text output
                if is_dry_run:
                    console.print(
                        "[cyan]📋 DRY-RUN: Would fix the following orphaned files:[/cyan]"
                    )
                else:
                    console.print("[green]✅ Fixed orphaned migration files:[/green]")

                for old_name, new_name in result.get("renamed", []):
                    console.print(f"  • {old_name} → {new_name}")

                if result.get("errors"):
                    console.print("[red]Errors:[/red]")
                    for filename, error_msg in result.get("errors", []):
                        console.print(f"  ❌ {filename}: {error_msg}")

        else:
            # Just report the orphaned files (don't fix)
            if format_output == "json":
                output_dict = {
                    "status": "issues_found",
                    "orphaned_files": [f.name for f in orphaned_files],
                }
                _output_json(output_dict, output_file, console)
            else:
                console.print("[yellow]⚠️  WARNING: Orphaned migration files detected[/yellow]")
                console.print(
                    "[yellow]These SQL files exist but won't be applied by Confiture:[/yellow]"
                )

                for orphaned_file in orphaned_files:
                    suggested_name = f"{orphaned_file.stem}.up.sql"
                    console.print(f"  • {orphaned_file.name} → rename to: {suggested_name}")

                console.print()
                console.print("[cyan]To automatically fix these files, run:[/cyan]")
                console.print("[cyan]  confiture migrate validate --fix-naming[/cyan]")
                console.print()
                console.print("[cyan]Or preview the changes first with:[/cyan]")
                console.print("[cyan]  confiture migrate validate --fix-naming --dry-run[/cyan]")

    except typer.Exit:
        raise
    except Exception as e:
        if format_output == "json":
            result = {"error": str(e)}
            _output_json(result, output_file, console)
        else:
            console.print(f"[red]❌ Error: {e}[/red]")
        raise typer.Exit(1) from e


def migrate_fix(
    migrations_dir: Path = typer.Option(
        Path("db/migrations"),
        "--migrations-dir",
        help="Migrations directory (default: db/migrations)",
    ),
    idempotent: bool = typer.Option(
        False,
        "--idempotent",
        help="Fix non-idempotent SQL statements (default: off)",
    ),
    ownership: bool = typer.Option(
        False,
        "--ownership",
        help=(
            "Insert missing `ALTER … OWNER TO <expected_owner>` after each "
            "CREATE that lacks one.  Requires an `ownership:` block in the "
            "config and the [ast] extra (pglast)."
        ),
    ),
    config_path: Path = typer.Option(
        Path("confiture.yaml"),
        "-c",
        "--config",
        help="Config file (needed for --ownership; defaults to confiture.yaml)",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help=(
            "With --ownership --apply: rewrite migration files even when "
            "their checksum is already recorded in the local tracking table.  "
            "Use with care — downstream `migrate verify` will report drift."
        ),
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Preview changes without modifying files (default: off)",
    ),
    format_output: str = typer.Option(
        "text",
        "--format",
        "-f",
        help="Output format: text or json (default: text)",
    ),
    output_file: Path | None = typer.Option(
        None,
        "--output",
        "-o",
        help="Save output to file (default: stdout)",
    ),
) -> None:
    """Auto-fix non-idempotent SQL in migrations.

    PROCESS:
      Transforms non-idempotent statements to safe-to-rerun equivalents:
      CREATE TABLE → CREATE TABLE IF NOT EXISTS, CREATE INDEX → CREATE INDEX
      IF NOT EXISTS, DROP TABLE → DROP TABLE IF EXISTS, and more.

    EXAMPLES:
      confiture migrate fix --idempotent --dry-run
        ↳ Preview what would be fixed without modifying files

      confiture migrate fix --idempotent
        ↳ Apply all fixes to migration files

      confiture migrate fix --idempotent --format json --output fixes.json
        ↳ Generate JSON report of all transformations

    JSON SCHEMA:
      See docs/reference/json-schemas.md for the JSON output schema
      (migrate-fix.schema.json).

    RELATED:
      confiture migrate validate - Check migration quality
      confiture migrate up       - Apply migrations
      confiture migrate generate - Create new migration
    """
    try:
        # Validate output format
        if format_output not in ("text", "json"):
            console.print(f"[red]❌ Invalid format: {format_output}. Use 'text' or 'json'[/red]")
            raise typer.Exit(1)

        if not migrations_dir.exists():
            if format_output == "json":
                result: dict[str, Any] = {
                    "error": f"Migrations directory not found: {migrations_dir.absolute()}"
                }
                _output_json(result, output_file, console)
            else:
                console.print(f"[red]❌ Migrations directory not found: {migrations_dir}[/red]")
            raise typer.Exit(1)

        if not idempotent and not ownership:
            console.print(
                "[yellow]⚠️  No fix type specified.  Use --idempotent and/or --ownership.[/yellow]"
            )
            return

        if idempotent:
            _fix_idempotency(migrations_dir, dry_run, format_output, output_file)

        if ownership:
            _fix_ownership(
                migrations_dir=migrations_dir,
                config_path=config_path,
                dry_run=dry_run,
                force=force,
                format_output=format_output,
                output_file=output_file,
            )

    except typer.Exit:
        raise
    except Exception as e:
        if format_output == "json":
            result = {"error": str(e)}
            _output_json(result, output_file, console)
        else:
            console.print(f"[red]❌ Error: {e}[/red]")
        raise typer.Exit(1) from e


def migrate_introspect(
    config: Path = typer.Option(
        Path("db/environments/local.yaml"),
        "--config",
        "-c",
        help="Configuration file (default: db/environments/local.yaml)",
    ),
    snapshots_dir: Path = typer.Option(
        Path("db/schema_history"),
        "--snapshots-dir",
        help="Schema history snapshots directory (default: db/schema_history)",
    ),
    format_output: str = typer.Option(
        "text",
        "--format",
        "-f",
        help="Output format: text or json (default: text)",
    ),
) -> None:
    """Detect migration level by comparing live schema to history snapshots.

    PROCESS:
      Introspects the live database schema using pg_catalog, normalises it,
      and compares against stored schema history snapshots. Reports the
      detected migration level without making any changes.

    EXAMPLES:
      confiture migrate introspect
        ↳ Detect migration level using default config and snapshots dir

      confiture migrate introspect --format json
        ↳ Output result as JSON for scripting

      confiture migrate introspect --snapshots-dir path/to/snapshots
        ↳ Use a custom snapshots directory

    RELATED:
      confiture migrate up --auto-detect-baseline   - Apply migrations with auto-baseline
      confiture migrate baseline --through <ver>    - Manually establish baseline
    """
    from confiture.cli.helpers import _get_tracking_table
    from confiture.core.connection import create_connection, load_config
    from confiture.core.migrator import Migrator

    try:
        if not config.exists():
            console.print(f"[red]❌ Config file not found: {config}[/red]")
            raise typer.Exit(1)

        config_data = load_config(config)
        conn = create_connection(config_data)
        migrator = Migrator(connection=conn, migration_table=_get_tracking_table(config_data))

        tb_present = migrator.tracking_table_exists()

        if format_output == "text":
            console.print("\n[cyan]Introspecting database schema...[/cyan]\n")
            console.print(f"  Snapshots directory: {snapshots_dir}")
            if not snapshots_dir.exists():
                console.print("  [yellow](directory not found — no snapshots available)[/yellow]")
            else:
                snap_count = len(list(snapshots_dir.glob("*.sql")))
                console.print(f"  ({snap_count} snapshot(s) found)")
            console.print(
                f"  tb_confiture: {'PRESENT' if tb_present else '[yellow]NOT FOUND[/yellow]'}"
            )

        if not snapshots_dir.exists():
            if format_output == "json":
                print(
                    json.dumps(
                        {
                            "tb_confiture_present": tb_present,
                            "detected_version": None,
                            "error": "snapshots_dir not found",
                        },
                        indent=2,
                    )
                )
            else:
                console.print("\n[red]❌ Cannot introspect: snapshots directory not found.[/red]")
                console.print(
                    "  Run 'confiture migrate generate' to start building snapshot history."
                )
            conn.close()
            raise typer.Exit(1)

        from confiture.core.baseline_detector import BaselineDetector

        detector = BaselineDetector(snapshots_dir)

        if format_output == "text":
            console.print("\n  Comparing live schema against snapshots...")

        live_sql = detector.introspect_live_schema(conn)
        detected_version = detector.find_matching_snapshot(live_sql)
        conn.close()

        if detected_version:
            # Resolve name from snapshot filename
            detected_name = ""
            for snap_path in snapshots_dir.glob(f"{detected_version}_*.sql"):
                stem = snap_path.stem
                parts = stem.split("_", 1)
                detected_name = parts[1] if len(parts) > 1 else stem
                break

            if format_output == "json":
                print(
                    json.dumps(
                        {
                            "tb_confiture_present": tb_present,
                            "detected_version": detected_version,
                            "detected_migration_name": detected_name,
                            "confidence": "exact",
                            "recommendation": f"confiture migrate baseline --through {detected_version}",
                        },
                        indent=2,
                    )
                )
            else:
                console.print(f"  [green]✓ Match found: {detected_version}_{detected_name}[/green]")
                console.print(f"\n  Detected migration level: [bold]{detected_version}[/bold]")
                if not tb_present:
                    console.print("\n  To restore tracking, run:")
                    console.print(
                        f"    confiture migrate baseline --through {detected_version} --config {config}"
                    )
                    console.print("\n  Or apply automatically with:")
                    console.print(
                        f"    confiture migrate up --auto-detect-baseline --config {config}"
                    )
        else:
            closest = detector.last_closest
            if format_output == "json":
                result: dict = {
                    "tb_confiture_present": tb_present,
                    "detected_version": None,
                    "confidence": "none",
                }
                if closest:
                    result["closest_version"] = closest[0]
                    result["closest_similarity"] = round(closest[1], 4)
                print(json.dumps(result, indent=2))
            else:
                console.print("  [yellow]✗ No matching snapshot found[/yellow]")
                if closest:
                    _cv, _cr = closest
                    console.print(f"  [dim]Closest: {_cv} ({_cr:.0%} similar)[/dim]")
                console.print("\n  The live schema does not exactly match any stored snapshot.")
                console.print("  This can happen if the schema was modified outside of confiture.")

    except typer.Exit:
        raise
    except Exception as e:
        if format_output == "json":
            print(json.dumps({"error": str(e)}, indent=2))
        else:
            console.print(f"[red]❌ Error: {e}[/red]")
        raise typer.Exit(1) from e


def migrate_verify(
    migrations_dir: Path = typer.Option(
        Path("db/migrations"),
        "--migrations-dir",
        help="Migrations directory (default: db/migrations)",
    ),
    config: Path | None = typer.Option(
        None,
        "--config",
        "-c",
        help="Configuration file path",
    ),
    version: str | None = typer.Option(
        None,
        "--version",
        help="Verify a single migration version (default: verify all applied)",
    ),
    format_output: str = typer.Option(
        "text",
        "--format",
        "-f",
        help="Output format: text or json (default: text)",
    ),
    output_file: Path | None = typer.Option(
        None,
        "--output",
        "-o",
        help="Save output to file (default: stdout)",
    ),
) -> None:
    """Verify applied migrations using .verify.sql sidecar files.

    Each .verify.sql file contains a SELECT query that returns a truthy value
    when the migration was applied correctly. Queries run inside SAVEPOINT
    (read-only, no side effects).

    EXAMPLES:
      confiture migrate verify -c db/environments/local.yaml
        -> Verify all applied migrations that have .verify.sql files

      confiture migrate verify --version 003 -c db/environments/local.yaml
        -> Verify a single migration

      confiture migrate verify --format json -c db/environments/local.yaml
        -> Output as JSON for CI/CD pipelines

    RELATED:
      confiture migrate status  - View migration history
      confiture migrate up      - Apply pending migrations
    """
    from confiture.cli.formatters.migrate_formatter import format_verify_results
    from confiture.cli.helpers import _get_tracking_table
    from confiture.core.connection import create_connection, load_config
    from confiture.core.migration_verifier import MigrationVerifier
    from confiture.core.migrator import Migrator
    from confiture.models.results import VerifyAllResult

    try:
        if not config or not config.exists():
            error_console.print("[red]Config file required for migrate verify[/red]")
            raise typer.Exit(1)

        config_data = load_config(str(config))
        tracking_table = _get_tracking_table(config_data)

        conn = create_connection(config_data)
        try:
            migrator = Migrator(connection=conn, migration_table=tracking_table)
            applied_versions = migrator.get_applied_versions()

            verifier = MigrationVerifier(connection=conn, migrations_dir=migrations_dir)
            results = verifier.verify_all(applied_versions, target_version=version)

            verify_result = VerifyAllResult(
                results=results,
                verified_count=sum(1 for r in results if r.status == "verified"),
                failed_count=sum(1 for r in results if r.status == "failed"),
                skipped_count=sum(1 for r in results if r.status == "no_file"),
                total_applied=len(applied_versions),
            )

            if format_output == "json":
                _output_json(verify_result.to_dict(), output_file, console)
            else:
                format_verify_results(verify_result, console)

            if verify_result.failed_count > 0:
                raise typer.Exit(1)

        finally:
            conn.close()

    except typer.Exit:
        raise
    except Exception as e:
        error_console.print(f"[red]Verify failed: {e}[/red]")
        raise typer.Exit(1) from e


# ---------------------------------------------------------------------------
# Helpers for fix-signatures
# ---------------------------------------------------------------------------

_FUNC_HEADER_RE = re.compile(
    r"CREATE\s+(?:OR\s+REPLACE\s+)?(?:FUNCTION|PROCEDURE)\s+",
    re.IGNORECASE,
)


def _extract_function_source(sql: str, schema: str, name: str) -> str | None:
    """Return the full CREATE [OR REPLACE] FUNCTION statement for (schema, name).

    Splits *sql* into individual statements with sqlparse, then returns the
    first one whose header matches ``[schema.]name(``.  Returns ``None`` when
    no matching statement is found.
    """
    import sqlparse  # noqa: PLC0415

    # Pattern matches both qualified (schema.name) and unqualified (name) forms
    header_re = re.compile(
        r"CREATE\s+(?:OR\s+REPLACE\s+)?(?:FUNCTION|PROCEDURE)\s+"
        rf"(?:{re.escape(schema)}\.)?{re.escape(name)}\s*\(",
        re.IGNORECASE,
    )
    for stmt in sqlparse.split(sql):
        stripped = stmt.strip()
        if stripped and header_re.search(stripped):
            return stripped
    return None


# ---------------------------------------------------------------------------
# migrate fix-signatures command
# ---------------------------------------------------------------------------


def migrate_fix_signatures(
    config: Path = typer.Option(
        Path("confiture.yaml"),
        "-c",
        "--config",
        help="Config file path. Use --env as a shortcut for db/environments/{name}.yaml.",
    ),
    env: str | None = typer.Option(
        None,
        "--env",
        help="Environment name — shortcut for --config db/environments/{name}.yaml.",
    ),
    schema_file: Path | None = typer.Option(
        None,
        "--schema",
        help=(
            "Schema SQL file containing the authoritative function definitions. "
            "If omitted, schema is auto-built from DDL files."
        ),
    ),
    check_signature_schemas: str = typer.Option(
        "public",
        "--schemas",
        help="Comma-separated list of schemas to inspect (default: public).",
    ),
    ssh_via: str | None = typer.Option(
        None,
        "--ssh",
        help=(
            "Open an SSH tunnel before connecting: user@host or host. "
            "Overrides the ssh_tunnel block in the config file."
        ),
    ),
    apply: bool = typer.Option(
        False,
        "--apply",
        help=(
            "Execute the fixes in a single transaction. "
            "Default is dry-run: print the SQL and exit without changing the DB."
        ),
    ),
    format_output: str = typer.Option(
        "text",
        "--format",
        "-f",
        help="Output format: text or json (default: text).",
    ),
    output_file: Path | None = typer.Option(
        None,
        "--output",
        "-o",
        help="Save output to file (default: stdout).",
    ),
    check_body: bool = typer.Option(
        False,
        "--check-body",
        help=(
            "Also detect and fix function body drift (same signature, different body). "
            "Runs CREATE OR REPLACE from source for each drifted function — no DROP needed."
        ),
    ),
) -> None:
    """Fix stale function overloads: DROP old signature + re-apply source definition.

    PROCESS:
      1. Parse function signatures from --schema (or auto-built DDL).
      2. Introspect live database signatures.
      3. Detect stale overloads (present in DB but not in source).
      4. For each stale overload, generate DROP FUNCTION + CREATE OR REPLACE.
      5. Dry-run (default): print the combined SQL.
         With --apply: execute all fixes in a single transaction.

    EXAMPLES:
      confiture migrate fix-signatures --env local
        ↳ Dry-run: show DROP + CREATE SQL for any stale overloads

      confiture migrate fix-signatures --env production --apply
        ↳ Apply fixes atomically in one transaction

      confiture migrate fix-signatures --env production --ssh lionel@prod-db --apply
        ↳ Apply via SSH tunnel
    """
    try:
        config = _resolve_config(config, env)

        if not config.exists():
            error_console.print(f"[red]❌ Config file not found: {config}[/red]")
            raise typer.Exit(2)

        config_data = load_config(config)
        schemas = [s.strip() for s in check_signature_schemas.split(",") if s.strip()]

        # --- Resolve source SQL ---
        if schema_file is not None:
            source_sql = schema_file.read_text()
        else:
            try:
                from confiture.core.builder import SchemaBuilder  # noqa: PLC0415

                env_name = (
                    config_data.get("name")
                    if isinstance(config_data, dict)
                    else getattr(config_data, "name", None)
                )
                if not env_name:
                    raise ValueError(
                        "Config has no 'name' field — cannot auto-build schema. "
                        "Pass --schema explicitly."
                    )
                builder = SchemaBuilder(env=env_name)
                source_sql = builder.build(schema_only=True)
                if format_output == "text":
                    console.print("[dim]  (schema auto-built from DDL files)[/dim]")
            except Exception as build_exc:
                error_console.print(
                    f"[red]❌ --schema not provided and auto-build failed: {build_exc}[/red]\n"
                    "  Either run 'confiture build' first or pass --schema explicitly."
                )
                raise typer.Exit(2) from build_exc

        from confiture.core.function_signature_drift import (  # noqa: PLC0415
            FunctionSignatureDriftDetector,
        )
        from confiture.core.function_signature_parser import (  # noqa: PLC0415
            FunctionSignatureParser,
        )
        from confiture.core.live_function_catalog import (  # noqa: PLC0415
            LiveFunctionCatalog,
        )

        source_sigs = FunctionSignatureParser().parse(source_sql)

        # --- SSH tunnel override ---
        effective_config: Any = config_data
        if ssh_via:
            from confiture.config.environment import SshTunnelConfig  # noqa: PLC0415

            parts = ssh_via.split("@", 1)
            ssh_host = parts[1] if len(parts) == 2 else parts[0]
            ssh_user = parts[0] if len(parts) == 2 else None

            class _SshOverride:  # noqa: N801
                def __init__(self, base: Any, tunnel: SshTunnelConfig) -> None:
                    self._base = base
                    self.ssh_tunnel = tunnel

                @property
                def database_url(self) -> str:
                    if hasattr(self._base, "database_url"):
                        return self._base.database_url  # type: ignore[no-any-return]
                    return self._base.get("database_url", "")

                def get(self, key: str, default: Any = None) -> Any:  # noqa: ANN401
                    return getattr(self._base, key, None) or (
                        self._base.get(key, default) if isinstance(self._base, dict) else default
                    )

            effective_config = _SshOverride(
                config_data,
                SshTunnelConfig(host=ssh_host, user=ssh_user),
            )
            if format_output == "text":
                console.print(f"[dim]  (connecting via SSH tunnel to {ssh_via})[/dim]")

        # Pre-initialize body vars so they're accessible outside the with block (post-apply output)
        source_bodies: dict[str, str | None] = {}
        body_fix_blocks: list[dict[str, Any]] = []
        body_missing_source: list[str] = []
        body_report_after: Any = None  # FunctionBodyDriftReport | None

        # --- Detect drift ---
        with open_connection(effective_config) as conn:
            live_catalog = LiveFunctionCatalog(conn)
            live_sigs = live_catalog.get_signatures(schemas=schemas)
            drift_report = FunctionSignatureDriftDetector().compare(
                source_sigs, live_sigs, schemas_checked=schemas
            )

            if not drift_report.has_drift and not check_body:
                if format_output == "json":
                    _output_json(
                        {
                            "status": "clean",
                            "message": drift_report.summary(),
                            "fixes_applied": 0,
                        },
                        output_file,
                        console,
                    )
                else:
                    console.print(f"[green]✅ {drift_report.summary()}[/green]")
                return
            # when check_body and no sig drift: fall through to body detection

            # --- Build fix SQL for each stale overload ---
            fix_blocks: list[dict[str, Any]] = []
            missing_source: list[str] = []

            for overload in drift_report.stale_overloads:
                create_sql = _extract_function_source(source_sql, overload.schema, overload.name)
                if create_sql is None:
                    missing_source.append(overload.stale_signature)
                    continue
                fix_blocks.append(
                    {
                        "stale_signature": overload.stale_signature,
                        "drop_sql": overload.drop_sql,
                        "create_sql": create_sql,
                    }
                )

            if missing_source and format_output == "text":
                console.print(
                    "[yellow]⚠ Source definition not found for the following overloads "
                    "(skipped — would leave function undefined):[/yellow]"
                )
                for sig in missing_source:
                    console.print(f"[yellow]    {sig}[/yellow]")

            if not fix_blocks and not check_body:
                error_console.print(
                    "[red]❌ No fixable overloads found "
                    "(source definitions missing for all stale overloads).[/red]"
                )
                raise typer.Exit(1)
            # when check_body: no sig fixes available but body detection may still proceed

            # --- Body drift detection ---
            body_report: Any = None
            if check_body:
                from confiture.core.function_body_drift import (  # noqa: PLC0415
                    FunctionBodyDriftDetector,
                )

                source_bodies = {
                    sig.signature_key(): body
                    for sig, body in FunctionSignatureParser().parse_with_bodies(source_sql)
                }
                live_bodies = live_catalog.get_bodies(schemas=schemas, sig_keys=set(source_bodies))
                body_report = FunctionBodyDriftDetector().compare(source_bodies, live_bodies)

                if body_report.has_drift:
                    stale_fn_keys = {b["stale_signature"].split("(")[0] for b in fix_blocks}
                    for drift in body_report.body_drifts:
                        if f"{drift.schema}.{drift.name}" in stale_fn_keys:
                            continue  # DROP + CREATE in fix_blocks already applies correct body
                        create_sql = _extract_function_source(source_sql, drift.schema, drift.name)
                        if create_sql is None:
                            body_missing_source.append(drift.signature_key)
                            continue
                        body_fix_blocks.append(
                            {"signature_key": drift.signature_key, "create_sql": create_sql}
                        )

            # Combined exit: no sig fixes and no body fixes
            if not fix_blocks and not body_fix_blocks:
                if format_output == "json":
                    _output_json(
                        {
                            "status": "clean",
                            "message": "No signature or body drift detected.",
                            "fixes_applied": 0,
                            **({"body_drift_fixes_planned": 0} if check_body else {}),
                        },
                        output_file,
                        console,
                    )
                else:
                    console.print("[green]✅ No signature or body drift detected.[/green]")
                return

            combined_sql = "\n\n".join(f"{b['drop_sql']}\n{b['create_sql']}" for b in fix_blocks)

            # --- Dry-run ---
            if not apply:
                if format_output == "json":
                    _output_json(
                        {
                            "status": "dry_run",
                            "fixes_planned": len(fix_blocks),
                            "missing_source": missing_source,
                            "sql": combined_sql,
                            "blocks": fix_blocks,
                            **(
                                {
                                    "body_drift_fixes_planned": len(body_fix_blocks),
                                    "body_drift_blocks": body_fix_blocks,
                                    "body_drift_missing_source": body_missing_source,
                                }
                                if check_body
                                else {}
                            ),
                        },
                        output_file,
                        console,
                    )
                else:
                    if fix_blocks:
                        console.print(
                            f"[bold]Dry-run: {len(fix_blocks)} fix(es) planned "
                            f"(pass --apply to execute):[/bold]"
                        )
                        console.print()
                        console.print(combined_sql)
                    if body_fix_blocks:
                        console.print(
                            f"[bold]Dry-run: {len(body_fix_blocks)} body drift fix(es) planned"
                            " (pass --apply to execute):[/bold]"
                        )
                        for block in body_fix_blocks:
                            console.print()
                            console.print(block["create_sql"])
                return

            # --- Apply in a single transaction ---
            conn.autocommit = False
            try:
                with conn.cursor() as cur:
                    for block in fix_blocks:
                        cur.execute(block["drop_sql"])
                        cur.execute(block["create_sql"])
                    for block in body_fix_blocks:
                        cur.execute(block["create_sql"])
                conn.commit()
            except Exception as apply_exc:
                conn.rollback()
                error_console.print(f"[red]❌ Fix failed (rolled back): {apply_exc}[/red]")
                raise typer.Exit(1) from apply_exc

            # --- Re-check to confirm zero drift ---
            live_sigs_after = LiveFunctionCatalog(conn).get_signatures(schemas=schemas)
            report_after = FunctionSignatureDriftDetector().compare(
                source_sigs, live_sigs_after, schemas_checked=schemas
            )

            if check_body and source_bodies:
                from confiture.core.function_body_drift import (  # noqa: PLC0415
                    FunctionBodyDriftDetector,
                )

                live_bodies_after = LiveFunctionCatalog(conn).get_bodies(
                    schemas=schemas, sig_keys=set(source_bodies)
                )
                body_report_after = FunctionBodyDriftDetector().compare(
                    source_bodies, live_bodies_after
                )

        applied = [b["stale_signature"] for b in fix_blocks]
        body_applied = [b["signature_key"] for b in body_fix_blocks]
        has_residual = report_after.has_drift or (
            body_report_after is not None and body_report_after.has_drift
        )

        if format_output == "json":
            _output_json(
                {
                    "status": "applied" if not has_residual else "partial",
                    "fixes_applied": len(fix_blocks),
                    "applied": applied,
                    "missing_source": missing_source,
                    "remaining_drift": report_after.has_drift,
                    "remaining_stale": [o.stale_signature for o in report_after.stale_overloads],
                    **(
                        {
                            "body_drift_fixes_applied": len(body_fix_blocks),
                            "body_drift_applied": body_applied,
                            "body_drift_missing_source": body_missing_source,
                            "remaining_body_drift": (
                                body_report_after.has_drift if body_report_after else False
                            ),
                        }
                        if check_body
                        else {}
                    ),
                },
                output_file,
                console,
            )
        else:
            if fix_blocks:
                console.print(f"[green]✅ Applied {len(fix_blocks)} signature fix(es):[/green]")
                for sig in applied:
                    console.print(f"[green]    {sig}[/green]")
            if body_fix_blocks:
                console.print(
                    f"[green]✅ Applied {len(body_fix_blocks)} body drift fix(es):[/green]"
                )
                for sig in body_applied:
                    console.print(f"[green]    {sig}[/green]")
            if has_residual:
                console.print(
                    "[yellow]⚠ Residual drift detected after apply — "
                    "run --check-signatures --check-body to investigate.[/yellow]"
                )
            else:
                console.print("[green]✅ Zero drift confirmed after apply.[/green]")

        if has_residual:
            raise typer.Exit(1)

    except typer.Exit:
        raise
    except Exception as e:
        error_console.print(f"[red]❌ fix-signatures failed: {e}[/red]")
        raise typer.Exit(2) from e


def _preflight_version_from_filename(filename: str) -> str:
    """Extract version prefix from a migration filename."""
    for suffix in (".up.sql", ".py"):
        if filename.endswith(suffix):
            filename = filename[: -len(suffix)]
            break
    return filename.split("_")[0]


def _target_tracking_table_is_empty(session: MigratorSession) -> bool:
    """Return True when the preflight target's ``tb_confiture`` is empty / missing.

    A best-effort probe: any database error (table missing, permission
    denied, connection drop) is treated as "looks empty" — the worst
    case is emitting an extra hint, which is advisory anyway.
    """
    import contextlib

    conn = getattr(session, "_conn", None)
    if conn is None:
        return False
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM tb_confiture LIMIT 1")
            row = cur.fetchone()
        # Roll back any aborted transaction state so run_against starts clean.
        with contextlib.suppress(Exception):
            conn.rollback()
        return row is None
    except Exception:  # noqa: BLE001 — best-effort: missing table / perm denied
        with contextlib.suppress(Exception):
            conn.rollback()
        return True


def _resolve_preflight_pending(
    migrations_dir: Path,
    *,
    config_path: Path | None,
    env_name: str | None,
    since: str | None,
) -> list[Path]:
    """Return migration files to test in a preflight --against run.

    Priority order:
    1. --config / --env: connect to configured DB, return pending files.
    2. --since: all local files with version >= since (no DB required).
    3. Neither: all local migration files.
    """
    if config_path is not None or env_name is not None:
        from confiture.cli.helpers import _get_tracking_table, _resolve_config  # noqa: PLC0415

        resolved = _resolve_config(config_path or Path("confiture.yaml"), env_name)
        config_data = load_config(resolved)
        conn = create_connection(config_data)
        try:
            migrator = Migrator(
                connection=conn,
                migration_table=_get_tracking_table(config_data),
            )
            return migrator.find_pending(migrations_dir=migrations_dir)
        finally:
            conn.close()

    all_files: list[Path] = sorted(
        list(migrations_dir.glob("*.up.sql"))
        + [f for f in migrations_dir.glob("*.py") if not f.name.startswith("_")],
        key=lambda f: _preflight_version_from_filename(f.name),
    )

    if since is not None:
        return [f for f in all_files if _preflight_version_from_filename(f.name) >= since]

    return all_files


def _display_against_result(
    result: Any,
    format_type: str,
    cons: Any,
) -> None:
    """Render --against execution results to the console."""
    from confiture.models.results import PreflightAgainstResult  # noqa: PLC0415

    if format_type == "json":
        return

    safe_url = PreflightAgainstResult._redact_url(result.against_url)
    cons.print(
        f"\nExecution check: {len(result.migrations)} migration(s) against [dim]{safe_url}[/dim]"
    )

    for m in result.migrations:
        if m.skipped:
            cons.print(f"  [yellow]⤳[/yellow]  {m.version}  {m.name:<40}  [dim](skipped)[/dim]")
            if m.skipped_reason:
                cons.print(f"       [dim]{m.skipped_reason}[/dim]")
        elif m.success:
            cons.print(
                f"  [green]✓[/green]  {m.version}  {m.name:<40}  "
                f"({m.execution_time_ms / 1000:.2f}s)"
            )
        else:
            cons.print(f"  [red]✗[/red]  {m.version}  {m.name:<40}")
            if m.error:
                first_line = m.error.splitlines()[0][:120]
                cons.print(f"       [red]Error:[/red] {first_line}")

    cons.print()
    if result.all_passed:
        if result.has_skipped:
            cons.print(
                f"  [green]✓[/green] All {len(result.migrations)} migration(s) passed "
                f"({len(result.skipped_migrations)} skipped)."
            )
        else:
            cons.print(f"  [green]✓[/green] All {len(result.migrations)} migration(s) passed.")
    else:
        cons.print(
            f"  [red]✗[/red] {len(result.failures)} of "
            f"{len(result.migrations)} migration(s) would fail."
        )
    if result.db_consumed:
        cons.print("  [yellow]⚠[/yellow]  Preflight DB consumed — reprovision before next run.")
    else:
        cons.print("  [dim](Rolled back — preflight DB unchanged)[/dim]")


def _run_dependent_check(
    *,
    mode: str,
    pending_files: list[Path],
    migrations_dir: Path,
    against_url: str,
) -> Any:
    """Resolve pending migrations' CoR targets and run the pg_depend check.

    On any error (pglast missing, connection failure, query failure) returns
    a skipped report with a clear reason rather than raising — the caller
    decides how to surface that. ``mode`` is ``"fail"`` (severity=error) or
    ``"warn"`` (severity=info).
    """
    from confiture.models.preflight import DependentAnalysisReport

    try:
        from confiture.core.cor_extractor import find_cor_targets_in_file
    except ImportError:
        error_console.print(
            "[red]❌ Dependent check requires pglast. "
            "Install with: pip install fraiseql-confiture[ast][/red]"
        )
        return DependentAnalysisReport(
            entries=[], status="skipped", skip_reason="pglast_not_installed"
        )

    targets: list[Any] = []
    for migration_file in pending_files:
        targets.extend(find_cor_targets_in_file(migration_file, project_root=migrations_dir))

    if not targets:
        return DependentAnalysisReport(entries=[], status="ok")

    import psycopg

    from confiture.core.dependent_objects import DependentObjectsChecker

    severity = "info" if mode == "warn" else "error"
    try:
        with psycopg.connect(against_url) as conn:
            return DependentObjectsChecker(severity=severity).check(targets, conn)
    except psycopg.Error as e:
        error_console.print(f"[red]❌ Dependent check connection failed: {e}[/red]")
        return DependentAnalysisReport(
            entries=[], status="skipped", skip_reason="connection_failed"
        )


def _display_dependent_analysis(report: Any, cons: Any) -> None:
    """Render the dependent-objects analysis section."""
    cons.print()
    if report.status == "skipped":
        cons.print(
            f"[yellow]⚠️  Dependent analysis skipped[/yellow] [dim]({report.skip_reason})[/dim]"
        )
        return

    if not report.entries:
        cons.print("[green]✓[/green] No CREATE OR REPLACE targets in pending migrations.")
        return

    blocking = report.has_blocking()
    if blocking:
        cons.print("[red]Dependent analysis — live dependents found:[/red]")
    elif any(e.dependents for e in report.entries):
        cons.print("[yellow]Dependent analysis — live dependents (informational):[/yellow]")
    else:
        cons.print("[green]✓[/green] No dependents found for replaced objects.")
        return

    for entry in report.entries:
        if not entry.dependents:
            continue
        sev = entry.severity
        marker = "[red]✗[/red]" if sev == "error" else "[yellow]ℹ[/yellow]"
        cons.print(
            f"  {marker} {entry.target.kind} [cyan]{entry.target.qualified}[/cyan] "
            f"is being replaced; {len(entry.dependents)} dependent(s):"
        )
        for dep in entry.dependents:
            cols = (
                f"  [dim](references: {', '.join(dep.referenced_columns)})[/dim]"
                if dep.referenced_columns
                else ""
            )
            cons.print(f"      - {dep.kind} [cyan]{dep.schema}.{dep.name}[/cyan]{cols}")


def migrate_preflight(
    migrations_dir: Path = typer.Option(
        Path("db/migrations"),
        "--migrations-dir",
        help="Migrations directory (default: db/migrations)",
    ),
    format_type: str = typer.Option(
        "table",
        "--format",
        "-f",
        help="Output format: table or json (default: table)",
    ),
    against: str | None = typer.Option(
        None,
        "--against",
        help=(
            "PostgreSQL URL of the preflight database to test migrations against. "
            "Typically seeded from pg_dump --schema-only. "
            "Migrations are executed inside a transaction that is always rolled back."
        ),
    ),
    config: Path | None = typer.Option(
        None,
        "--config",
        "-c",
        help=(
            "Config file for pending-migration detection. "
            "Connects to the configured database to read the tracking table."
        ),
    ),
    env: str | None = typer.Option(
        None,
        "--env",
        help="Environment shortcut — db/environments/{name}.yaml (e.g. --env production).",
    ),
    since: str | None = typer.Option(
        None,
        "--since",
        help=(
            "Test migrations with version >= SINCE (e.g. --since 20260428000000). "
            "Inclusive. Alternative to --config when no second DB connection is available."
        ),
    ),
    allow_non_transactional: bool = typer.Option(
        False,
        "--allow-non-transactional",
        help=(
            "Run non-transactional migrations (CREATE INDEX CONCURRENTLY, etc.) "
            "outside the rollback SAVEPOINT in autocommit mode. "
            "The preflight DB will be permanently modified (db_consumed=True). "
            "By default such migrations are skipped."
        ),
    ),
    check_dependents: str = typer.Option(
        "off",
        "--check-dependents",
        help=(
            "Enumerate live dependents of CREATE OR REPLACE targets via "
            "pg_depend on the --against preflight DB. "
            "'off' (default), 'fail' (exit 1 on dependents found), or "
            "'warn' (render dependents as informational, exit code unchanged). "
            "Requires the [ast] extra (pglast)."
        ),
    ),
) -> None:
    """Check if pending migrations are safe to deploy.

    Verifies reversibility (.down.sql exists), detects non-transactional
    statements (CREATE INDEX CONCURRENTLY, etc.), checks for duplicate
    versions, and verifies checksums of applied migrations.

    MODES:
      Default mode — static analysis only. No --against, no DB connection.
        Scans local migration files and reports per-file reversibility +
        transactionality. Cannot detect "is this migration already
        applied?" because there's no source of truth to compare against.

      Explicit source mode — --against <url> [+ --config OR --env OR --since]
        Replays pending migrations inside a SAVEPOINT against a preflight
        DB and reports per-migration success/failure. Source of "pending"
        is determined by the flag combination:
          • --against alone        → all local files
          • --against + --config   → pending files (read tb_confiture from
                                     the --config DB, not from --against)
          • --against + --env      → same, using db/environments/{env}.yaml
          • --against + --since V  → all files with version >= V (no DB
                                     needed for pending detection)

    EXAMPLES:
      confiture migrate preflight
        ↳ Check all migration files in db/migrations

      confiture migrate preflight --format json
        ↳ Output structured JSON for CI/CD integration

      confiture migrate preflight --migrations-dir custom/migrations
        ↳ Check migrations in a custom directory

      confiture migrate preflight --against postgresql://localhost/myapp_preflight
        ↳ Test all local migrations against a schema-only preflight DB

      confiture migrate preflight --against postgresql://localhost/myapp_preflight --env production
        ↳ Test only pending migrations (detected from production tracking table)

      confiture migrate preflight --against postgresql://localhost/myapp_preflight --since 20260428000000
        ↳ Test migrations at or after version 20260428000000 (inclusive)

      confiture migrate preflight --against postgresql://localhost/myapp_preflight --allow-non-transactional
        ↳ Also run non-transactional migrations in autocommit mode (preflight DB consumed)

      confiture migrate preflight --against postgresql://localhost/myapp_preflight --format json
        ↳ Output static + execution results as JSON

    EXIT CODES:
      0 — all migrations safe to deploy (skipped non-transactional migrations are neutral)
      1 — one or more issues detected or execution failures
      2 — config or connection error

    JSON SCHEMA:
      See docs/reference/json-schemas.md for the JSON output schemas:
        - default: migrate-preflight.schema.json
        - with --against: migrate-preflight-against.schema.json
    """
    from rich.table import Table

    from confiture.core.preflight import run_preflight

    if check_dependents not in {"off", "fail", "warn"}:
        error_console.print(
            f"[red]❌ Invalid --check-dependents value: {check_dependents!r}. "
            "Must be one of 'off', 'fail', 'warn'.[/red]"
        )
        raise typer.Exit(2)

    result = run_preflight(migrations_dir)

    if against is None:
        # Backward-compatible path: flat output, no --against execution.
        dependent_skip_payload: dict[str, Any] | None = None
        if check_dependents != "off":
            dependent_skip_payload = {
                "status": "skipped",
                "entries": [],
                "has_blocking": False,
                "skip_reason": "no_preflight_db",
            }

        if format_type == "json":
            payload = result.to_dict()
            if dependent_skip_payload is not None:
                payload["dependent_analysis"] = dependent_skip_payload
            payload["hints"] = []
            _output_json(payload, None, console)
            if not result.safe_to_deploy:
                raise typer.Exit(1)
            return

        table = Table(title="Pre-flight Check")
        table.add_column("Version", style="cyan")
        table.add_column("Name")
        table.add_column("Reversible", justify="center")
        table.add_column("Transactional", justify="center")

        for m in result.migrations:
            rev = "[green]✓[/green]" if m.reversible else "[red]✗[/red]"
            if m.fully_transactional:
                txn = "[green]✓[/green]"
            else:
                txn = "[red]✗[/red] " + "; ".join(m.non_transactional_statements)
            table.add_row(m.version, m.name, rev, txn)

        console.print(table)
        console.print(f"\nSummary: {len(result.migrations)} migrations checked")

        if result.irreversible:
            console.print(
                f"  [red]✗[/red] {len(result.irreversible)} irreversible (missing .down.sql)"
            )
        else:
            console.print("  [green]✓[/green] All reversible")

        if result.non_transactional:
            total_stmts = sum(len(m.non_transactional_statements) for m in result.non_transactional)
            console.print(f"  [red]✗[/red] {total_stmts} non-transactional statements")
        else:
            console.print("  [green]✓[/green] All transactional")

        if result.has_duplicates:
            console.print(f"  [red]✗[/red] {len(result.duplicate_versions)} duplicate version(s)")
        else:
            console.print("  [green]✓[/green] No duplicate versions")

        if result.checksum_verified:
            if result.has_checksum_mismatches:
                console.print(
                    f"  [red]✗[/red] {len(result.checksum_mismatches)} checksum mismatch(es)"
                )
            else:
                console.print("  [green]✓[/green] Checksums verified")

        if result.safe_to_deploy:
            console.print("  [green]→ Safe to deploy[/green]")
        else:
            console.print("  [red]→ Not safe to deploy with rollback guarantee[/red]")
            raise typer.Exit(1)

        if check_dependents != "off":
            console.print(
                "[yellow]⚠️  Dependent check skipped: no preflight DB configured. "
                "Pass --against <url> to enable.[/yellow]"
            )
        return

    # --against path: static analysis + exhaustive execution against preflight DB.
    try:
        pending_files = _resolve_preflight_pending(
            migrations_dir=migrations_dir,
            config_path=config,
            env_name=env,
            since=since,
        )
    except Exception as e:
        error_console.print(f"[red]❌ Failed to resolve pending migrations: {e}[/red]")
        raise typer.Exit(2) from e

    target_tracking_empty = False
    try:
        session = MigratorSession(
            config=None,
            migrations_dir=migrations_dir,
            database_url_override=against,
            migration_table_override="tb_confiture",
        )
        with session:
            # Snapshot whether the target's tracking table is empty BEFORE
            # the SAVEPOINT-bounded run_against — used to emit a
            # quiet-success hint when the target looks like a restored
            # backup with the tracking table stripped.
            target_tracking_empty = _target_tracking_table_is_empty(session)
            against_result = session.run_against(
                pending_files,
                against_url=against,
                allow_non_transactional=allow_non_transactional,
            )
    except Exception as e:
        error_console.print(f"[red]❌ Connection to --against URL failed: {e}[/red]")
        raise typer.Exit(2) from e

    dependent_report = None
    if check_dependents != "off":
        dependent_report = _run_dependent_check(
            mode=check_dependents,
            pending_files=pending_files,
            migrations_dir=migrations_dir,
            against_url=against,
        )

    preflight_hints: list[str] = []
    if target_tracking_empty and pending_files:
        _emit_hint(
            "`tb_confiture` on the target is empty. If --against points at a "
            "restored backup, was the tracking table dropped during "
            "anonymization?",
            hints_list=preflight_hints,
            format_=format_type,
        )

    if format_type == "json":
        payload: dict[str, Any] = {
            "static": result.to_dict(),
            "against": against_result.to_dict(),
            "hints": preflight_hints,
        }
        if dependent_report is not None:
            payload["dependent_analysis"] = dependent_report.to_dict()
        _output_json(payload, None, console)
    else:
        _display_against_result(against_result, format_type, console)
        if dependent_report is not None:
            _display_dependent_analysis(dependent_report, console)

    if not against_result.all_passed:
        raise typer.Exit(1)
    if dependent_report is not None and dependent_report.has_blocking():
        raise typer.Exit(1)
