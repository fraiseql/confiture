"""Migration analysis commands: migrate diff, validate, fix, introspect, verify."""

import json
from pathlib import Path
from typing import Any

import typer

from confiture.cli.formatters.common import display_drift_report, display_signature_drift_report
from confiture.cli.helpers import (
    _fix_idempotency,
    _output_json,
    _resolve_config,
    _validate_idempotency,
    console,
    error_console,
)
from confiture.core.connection import create_connection, load_config, open_connection
from confiture.core.differ import SchemaDiffer
from confiture.core.drift import SchemaDriftDetector
from confiture.core.migration_generator import MigrationGenerator


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

      confiture migrate validate --check-live-drift --check-signatures --env production --schema schema.sql
        ↳ Live: check both column/table drift AND function overload drift

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

                if format_output == "json":
                    _output_json(
                        {"check": "function_signature_drift", **drift_report.to_dict()},
                        output_file,
                        console,
                    )
                else:
                    display_signature_drift_report(drift_report, console)

                if drift_report.has_critical_drift:
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
            _validate_idempotency(migrations_dir, format_output, output_file)
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

        if not idempotent:
            console.print(
                "[yellow]⚠️  No fix type specified. Use --idempotent to fix idempotency issues.[/yellow]"
            )
            return

        _fix_idempotency(migrations_dir, dry_run, format_output, output_file)

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
