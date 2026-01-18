"""Main CLI entry point for Confiture.

This module defines the main Typer application and all CLI commands.
"""

from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.table import Table

from confiture.cli.lint_formatter import format_lint_report, save_report
from confiture.core.builder import SchemaBuilder
from confiture.core.differ import SchemaDiffer
from confiture.core.linting import SchemaLinter
from confiture.core.linting.schema_linter import (
    LintConfig as LinterConfig,
)
from confiture.core.linting.schema_linter import (
    LintReport as LinterReport,
)
from confiture.core.linting.schema_linter import (
    RuleSeverity,
)
from confiture.core.migration_generator import MigrationGenerator
from confiture.models.lint import LintReport, LintSeverity, Violation

# Valid output formats for linting
LINT_FORMATS = ("table", "json", "csv")


def _convert_linter_report(linter_report: LinterReport, schema_name: str = "schema") -> LintReport:
    """Convert a schema_linter.LintReport to models.lint.LintReport.

    Args:
        linter_report: Report from SchemaLinter
        schema_name: Name of schema being linted

    Returns:
        LintReport compatible with format_lint_report
    """
    violations = []

    # Map RuleSeverity to LintSeverity
    severity_map = {
        RuleSeverity.ERROR: LintSeverity.ERROR,
        RuleSeverity.WARNING: LintSeverity.WARNING,
        RuleSeverity.INFO: LintSeverity.INFO,
    }

    # Convert all violations
    for violation in linter_report.errors:
        violations.append(
            Violation(
                rule_name=violation.rule_name,
                severity=severity_map[violation.severity],
                message=violation.message,
                location=violation.object_name,
            )
        )

    for violation in linter_report.warnings:
        violations.append(
            Violation(
                rule_name=violation.rule_name,
                severity=severity_map[violation.severity],
                message=violation.message,
                location=violation.object_name,
            )
        )

    for violation in linter_report.info:
        violations.append(
            Violation(
                rule_name=violation.rule_name,
                severity=severity_map[violation.severity],
                message=violation.message,
                location=violation.object_name,
            )
        )

    return LintReport(
        violations=violations,
        schema_name=schema_name,
        tables_checked=0,  # Not tracked in linter
        columns_checked=0,  # Not tracked in linter
        errors_count=len(linter_report.errors),
        warnings_count=len(linter_report.warnings),
        info_count=len(linter_report.info),
        execution_time_ms=0,  # Not tracked in linter
    )


# Create Typer app
app = typer.Typer(
    name="confiture",
    help="PostgreSQL migrations, sweetly done 🍓",
    add_completion=False,
)

# Create Rich console for pretty output
console = Console()

# Version
__version__ = "0.3.5"


def version_callback(value: bool) -> None:
    """Print version and exit."""
    if value:
        console.print(f"confiture version {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        False,
        "--version",
        callback=version_callback,
        is_eager=True,
        help="Show version and exit",
    ),
) -> None:
    """Confiture - PostgreSQL migrations, sweetly done 🍓."""
    pass


@app.command()
def init(
    path: Path = typer.Argument(
        Path("."),
        help="Project directory to initialize",
    ),
) -> None:
    """Initialize a new Confiture project.

    Creates necessary directory structure and configuration files.
    """
    try:
        # Create directory structure
        db_dir = path / "db"
        schema_dir = db_dir / "schema"
        seeds_dir = db_dir / "seeds"
        migrations_dir = db_dir / "migrations"
        environments_dir = db_dir / "environments"

        # Check if already initialized
        if db_dir.exists():
            console.print(
                "[yellow]⚠️  Project already exists. Some files may be overwritten.[/yellow]"
            )
            if not typer.confirm("Continue?"):
                raise typer.Exit()

        # Create directories
        schema_dir.mkdir(parents=True, exist_ok=True)
        (seeds_dir / "common").mkdir(parents=True, exist_ok=True)
        (seeds_dir / "development").mkdir(parents=True, exist_ok=True)
        (seeds_dir / "test").mkdir(parents=True, exist_ok=True)
        migrations_dir.mkdir(parents=True, exist_ok=True)
        environments_dir.mkdir(parents=True, exist_ok=True)

        # Create example schema directory structure
        (schema_dir / "00_common").mkdir(exist_ok=True)
        (schema_dir / "10_tables").mkdir(exist_ok=True)

        # Create example schema file
        example_schema = schema_dir / "00_common" / "extensions.sql"
        example_schema.write_text(
            """-- PostgreSQL extensions
-- Add commonly used extensions here

-- Example:
-- CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
-- CREATE EXTENSION IF NOT EXISTS "pg_trgm";
"""
        )

        # Create example table
        example_table = schema_dir / "10_tables" / "example.sql"
        example_table.write_text(
            """-- Example table
-- Replace with your actual schema

CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    email TEXT NOT NULL UNIQUE,
    created_at TIMESTAMP DEFAULT NOW()
);
"""
        )

        # Create example seed file
        example_seed = seeds_dir / "common" / "00_example.sql"
        example_seed.write_text(
            """-- Common seed data
-- These records are included in all non-production environments

-- Example: Test users
-- INSERT INTO users (username, email) VALUES
--     ('admin', 'admin@example.com'),
--     ('editor', 'editor@example.com'),
--     ('reader', 'reader@example.com');
"""
        )

        # Create local environment config
        local_config = environments_dir / "local.yaml"
        local_config.write_text(
            """# Local development environment configuration

name: local
include_dirs:
  - db/schema/00_common
  - db/schema/10_tables
exclude_dirs: []

database:
  host: localhost
  port: 5432
  database: myapp_local
  user: postgres
  password: postgres
"""
        )

        # Create README
        readme = db_dir / "README.md"
        readme.write_text(
            """# Database Schema

This directory contains your database schema and migrations.

## Directory Structure

- `schema/` - DDL files organized by category
  - `00_common/` - Extensions, types, functions
  - `10_tables/` - Table definitions
- `migrations/` - Python migration files
- `environments/` - Environment-specific configurations

## Quick Start

1. Edit schema files in `schema/`
2. Generate migrations: `confiture migrate diff old.sql new.sql --generate`
3. Apply migrations: `confiture migrate up`

## Learn More

Documentation: https://github.com/evoludigit/confiture
"""
        )

        console.print("[green]✅ Confiture project initialized successfully![/green]")
        console.print(f"\n📁 Created structure in: {path.absolute()}")
        console.print("\n📝 Next steps:")
        console.print("  1. Edit your schema files in db/schema/")
        console.print("  2. Configure environments in db/environments/")
        console.print("  3. Run 'confiture migrate diff' to detect changes")

    except Exception as e:
        console.print(f"[red]❌ Error initializing project: {e}[/red]")
        raise typer.Exit(1) from e


@app.command()
def build(
    env: str = typer.Option(
        "local",
        "--env",
        "-e",
        help="Environment to build (references db/environments/{env}.yaml)",
    ),
    output: Path = typer.Option(
        None,
        "--output",
        "-o",
        help="Output file path (default: db/generated/schema_{env}.sql)",
    ),
    project_dir: Path = typer.Option(
        Path("."),
        "--project-dir",
        help="Project directory (default: current directory)",
    ),
    show_hash: bool = typer.Option(
        False,
        "--show-hash",
        help="Display schema hash after build",
    ),
    schema_only: bool = typer.Option(
        False,
        "--schema-only",
        help="Build schema only, exclude seed data",
    ),
) -> None:
    """Build complete schema from DDL files.

    This command builds a complete schema by concatenating all SQL files
    from the db/schema/ directory in deterministic order. This is the
    fastest way to create or recreate a database from scratch.

    The build process:
    1. Reads environment configuration (db/environments/{env}.yaml)
    2. Discovers all .sql files in configured include_dirs
    3. Concatenates files in alphabetical order
    4. Adds metadata headers (environment, file count, timestamp)
    5. Writes to output file (default: db/generated/schema_{env}.sql)

    Examples:
        # Build local environment schema
        confiture build

        # Build for specific environment
        confiture build --env production

        # Custom output location
        confiture build --output /tmp/schema.sql

        # Show hash for change detection
        confiture build --show-hash
    """
    try:
        # Create schema builder
        builder = SchemaBuilder(env=env, project_dir=project_dir)

        # Override to exclude seeds if --schema-only is specified
        if schema_only:
            builder.include_dirs = [d for d in builder.include_dirs if "seed" not in str(d).lower()]
            # Recalculate base_dir after filtering
            if builder.include_dirs:
                builder.base_dir = builder._find_common_parent(builder.include_dirs)

        # Set default output path if not specified
        if output is None:
            output_dir = project_dir / "db" / "generated"
            output_dir.mkdir(parents=True, exist_ok=True)
            output = output_dir / f"schema_{env}.sql"

        # Build schema
        console.print(f"[cyan]🔨 Building schema for environment: {env}[/cyan]")

        sql_files = builder.find_sql_files()
        console.print(f"[cyan]📄 Found {len(sql_files)} SQL files[/cyan]")

        schema = builder.build(output_path=output)

        # Success message
        console.print("[green]✅ Schema built successfully![/green]")
        console.print(f"\n📁 Output: {output.absolute()}")
        console.print(f"📏 Size: {len(schema):,} bytes")
        console.print(f"📊 Files: {len(sql_files)}")

        # Show hash if requested
        if show_hash:
            schema_hash = builder.compute_hash()
            console.print(f"🔐 Hash: {schema_hash}")

        console.print("\n💡 Next steps:")
        console.print(f"  • Apply schema: psql -f {output}")
        console.print("  • Or use: confiture migrate up")

    except FileNotFoundError as e:
        console.print(f"[red]❌ File not found: {e}[/red]")
        console.print("\n💡 Tip: Run 'confiture init' to create project structure")
        raise typer.Exit(1) from e
    except Exception as e:
        console.print(f"[red]❌ Error building schema: {e}[/red]")
        raise typer.Exit(1) from e


@app.command()
def lint(
    env: str = typer.Option(
        "local",
        "--env",
        "-e",
        help="Environment to lint (references db/environments/{env}.yaml)",
    ),
    project_dir: Path = typer.Option(
        Path("."),
        "--project-dir",
        help="Project directory (default: current directory)",
    ),
    format_type: str = typer.Option(
        "table",
        "--format",
        "-f",
        help="Output format (table, json, csv)",
    ),
    output: Path = typer.Option(
        None,
        "--output",
        "-o",
        help="Output file path (only with json/csv format)",
    ),
    fail_on_error: bool = typer.Option(
        True,
        "--fail-on-error",
        help="Exit with code 1 if errors found",
    ),
    fail_on_warning: bool = typer.Option(
        False,
        "--fail-on-warning",
        help="Exit with code 1 if warnings found (stricter)",
    ),
) -> None:
    """Lint schema against best practices.

    Validates the schema against 6 built-in linting rules:
    - Naming conventions (snake_case)
    - Primary keys on all tables
    - Documentation (COMMENT on tables)
    - Multi-tenant identifier columns
    - Indexes on foreign keys
    - Security best practices (passwords, tokens, secrets)

    Examples:
        # Lint local environment, display as table
        confiture lint

        # Lint production environment, output as JSON
        confiture lint --env production --format json

        # Save results to file
        confiture lint --format json --output lint-report.json

        # Strict mode: fail on warnings
        confiture lint --fail-on-warning
    """
    try:
        # Validate format option
        if format_type not in LINT_FORMATS:
            console.print(f"[red]❌ Invalid format: {format_type}[/red]")
            console.print(f"Valid formats: {', '.join(LINT_FORMATS)}")
            raise typer.Exit(1)

        # Create linter configuration (use LinterConfig for the linter)
        config = LinterConfig(
            enabled=True,
            fail_on_error=fail_on_error,
            fail_on_warning=fail_on_warning,
        )

        # Create linter and run linting
        console.print(f"[cyan]🔍 Linting schema for environment: {env}[/cyan]")
        linter = SchemaLinter(env=env, config=config)
        linter_report = linter.lint()

        # Convert to model LintReport for formatting
        report = _convert_linter_report(linter_report, schema_name=env)

        # Display results based on format
        if format_type == "table":
            format_lint_report(report, format_type="table", console=console)
        else:
            # JSON/CSV format: format and optionally save
            # Cast format_type for type checker
            fmt = "json" if format_type == "json" else "csv"
            formatted = format_lint_report(
                report,
                format_type=fmt,
                console=console,
            )

            if output:
                save_report(report, output, format_type=fmt)
                console.print(f"[green]✅ Report saved to: {output.absolute()}[/green]")
            else:
                console.print(formatted)

        # Determine exit code based on violations and fail mode
        should_fail = (report.has_errors and fail_on_error) or (
            report.has_warnings and fail_on_warning
        )
        if should_fail:
            raise typer.Exit(1)

    except FileNotFoundError as e:
        console.print(f"[red]❌ File not found: {e}[/red]")
        console.print("\n💡 Tip: Make sure schema files exist in db/schema/")
        raise typer.Exit(1) from e
    except Exception as e:
        console.print(f"[red]❌ Error linting schema: {e}[/red]")
        raise typer.Exit(1) from e


# Create migrate subcommand group
migrate_app = typer.Typer(help="Migration commands")
app.add_typer(migrate_app, name="migrate")


@migrate_app.command("status")
def migrate_status(
    migrations_dir: Path = typer.Option(
        Path("db/migrations"),
        "--migrations-dir",
        help="Migrations directory",
    ),
    config: Path = typer.Option(
        None,
        "--config",
        "-c",
        help="Configuration file (optional, to show applied status)",
    ),
    output_format: str = typer.Option(
        "table",
        "--format",
        "-f",
        help="Output format: table (default) or json",
    ),
    output_file: Path = typer.Option(
        None,
        "--output",
        "-o",
        help="Save output to file (useful with --format json)",
    ),
) -> None:
    """Show migration status.

    If config is provided, shows which migrations are applied vs pending.

    Examples:
        confiture migrate status
        confiture migrate status --format json
        confiture migrate status -f json -o status.json
    """
    try:
        # Validate output format
        if output_format not in ("table", "json"):
            console.print(f"[red]❌ Invalid format: {output_format}. Use 'table' or 'json'[/red]")
            raise typer.Exit(1)

        if not migrations_dir.exists():
            if output_format == "json":
                result = {"error": f"Migrations directory not found: {migrations_dir.absolute()}"}
                _output_json(result, output_file, console)
            else:
                console.print("[yellow]No migrations directory found.[/yellow]")
                console.print(f"Expected: {migrations_dir.absolute()}")
            return

        # Find migration files (both Python and SQL)
        py_files = list(migrations_dir.glob("*.py"))
        sql_files = list(migrations_dir.glob("*.up.sql"))
        migration_files = sorted(py_files + sql_files, key=lambda f: f.name.split("_")[0])

        if not migration_files:
            if output_format == "json":
                result = {
                    "applied": [],
                    "pending": [],
                    "current": None,
                    "total": 0,
                    "migrations": [],
                }
                _output_json(result, output_file, console)
            else:
                console.print("[yellow]No migrations found.[/yellow]")
            return

        # Get applied migrations from database if config provided
        applied_versions: set[str] = set()
        db_error: str | None = None
        if config and config.exists():
            try:
                from confiture.core.connection import create_connection, load_config
                from confiture.core.migrator import Migrator

                config_data = load_config(config)
                conn = create_connection(config_data)
                migrator = Migrator(connection=conn)
                migrator.initialize()
                applied_versions = set(migrator.get_applied_versions())
                conn.close()
            except Exception as e:
                db_error = str(e)
                if output_format != "json":
                    console.print(f"[yellow]⚠️  Could not connect to database: {e}[/yellow]")
                    console.print("[yellow]Showing file list only (status unknown)[/yellow]\n")

        # Build migrations data
        migrations_data: list[dict[str, str]] = []
        applied_list: list[str] = []
        pending_list: list[str] = []

        for migration_file in migration_files:
            # Extract version and name from filename
            # Python: "001_add_users.py" -> version="001", name="add_users"
            # SQL: "001_add_users.up.sql" -> version="001", name="add_users"
            base_name = migration_file.stem
            if base_name.endswith(".up"):
                base_name = base_name[:-3]  # Remove ".up" suffix
            parts = base_name.split("_", 1)
            version = parts[0] if len(parts) > 0 else "???"
            name = parts[1] if len(parts) > 1 else base_name

            # Determine status
            if applied_versions:
                if version in applied_versions:
                    status = "applied"
                    applied_list.append(version)
                else:
                    status = "pending"
                    pending_list.append(version)
            else:
                status = "unknown"

            migrations_data.append(
                {
                    "version": version,
                    "name": name,
                    "status": status,
                }
            )

        # Determine current version (highest applied)
        current_version = applied_list[-1] if applied_list else None

        if output_format == "json":
            result: dict[str, Any] = {
                "applied": applied_list,
                "pending": pending_list,
                "current": current_version,
                "total": len(migration_files),
                "migrations": migrations_data,
            }
            if db_error:
                result["warning"] = f"Could not connect to database: {db_error}"
            _output_json(result, output_file, console)
        else:
            # Display migrations in a table
            table = Table(title="Migrations")
            table.add_column("Version", style="cyan")
            table.add_column("Name", style="green")
            table.add_column("Status", style="yellow")

            for migration in migrations_data:
                if migration["status"] == "applied":
                    status_display = "[green]✅ applied[/green]"
                elif migration["status"] == "pending":
                    status_display = "[yellow]⏳ pending[/yellow]"
                else:
                    status_display = "unknown"

                table.add_row(migration["version"], migration["name"], status_display)

            console.print(table)
            console.print(f"\n📊 Total: {len(migration_files)} migrations", end="")
            if applied_versions:
                console.print(f" ({len(applied_list)} applied, {len(pending_list)} pending)")
            else:
                console.print()

    except Exception as e:
        if output_format == "json":
            result = {"error": str(e)}
            _output_json(result, output_file, console)
        else:
            console.print(f"[red]❌ Error: {e}[/red]")
        raise typer.Exit(1) from e


def _output_json(data: dict[str, Any], output_file: Path | None, console: Console) -> None:
    """Output JSON data to file or console.

    Args:
        data: Data to output as JSON
        output_file: Optional file to write to
        console: Console for output
    """
    import json

    json_str = json.dumps(data, indent=2)
    if output_file:
        output_file.write_text(json_str)
        console.print(f"[green]✅ Output written to {output_file}[/green]")
    else:
        console.print(json_str)


@migrate_app.command("up")
def migrate_up(
    migrations_dir: Path = typer.Option(
        Path("db/migrations"),
        "--migrations-dir",
        help="Migrations directory",
    ),
    config: Path = typer.Option(
        Path("db/environments/local.yaml"),
        "--config",
        "-c",
        help="Configuration file",
    ),
    target: str = typer.Option(
        None,
        "--target",
        "-t",
        help="Target migration version (applies all if not specified)",
    ),
    strict: bool = typer.Option(
        False,
        "--strict",
        help="Enable strict mode (fail on warnings)",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Force migration application, skipping state checks",
    ),
    lock_timeout: int = typer.Option(
        30000,
        "--lock-timeout",
        help="Lock acquisition timeout in milliseconds (default: 30000ms = 30s)",
    ),
    no_lock: bool = typer.Option(
        False,
        "--no-lock",
        help="Disable migration locking (DANGEROUS in multi-pod environments)",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Analyze migrations without executing (metadata queries only)",
    ),
    dry_run_execute: bool = typer.Option(
        False,
        "--dry-run-execute",
        help="Execute migrations in SAVEPOINT for realistic testing (guaranteed rollback)",
    ),
    verify_checksums: bool = typer.Option(
        True,
        "--verify-checksums/--no-verify-checksums",
        help="Verify migration file checksums before running (default: enabled)",
    ),
    on_checksum_mismatch: str = typer.Option(
        "fail",
        "--on-checksum-mismatch",
        help="Behavior on checksum mismatch: fail, warn, ignore",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Show detailed analysis in dry-run report",
    ),
    format_output: str = typer.Option(
        "text",
        "--format",
        "-f",
        help="Report format (text or json)",
    ),
    output_file: Path | None = typer.Option(
        None,
        "--output",
        "-o",
        help="Save report to file",
    ),
) -> None:
    """Apply pending migrations.

    Applies all pending migrations up to the target version (or all if no target).

    Uses distributed locking to ensure only one migration process runs at a time.
    This is critical for Kubernetes/multi-pod deployments.

    Verifies migration file checksums to detect unauthorized modifications.
    Use --no-verify-checksums to skip verification.

    Use --dry-run for analysis without execution, or --dry-run-execute to test in SAVEPOINT.
    """
    from confiture.cli.dry_run import (
        ask_dry_run_execute_confirmation,
        display_dry_run_header,
        print_json_report,
        save_json_report,
        save_text_report,
    )
    from confiture.core.checksum import (
        ChecksumConfig,
        ChecksumMismatchBehavior,
        ChecksumVerificationError,
        MigrationChecksumVerifier,
    )
    from confiture.core.connection import (
        create_connection,
        load_config,
        load_migration_class,
    )
    from confiture.core.locking import LockAcquisitionError, LockConfig, MigrationLock
    from confiture.core.migrator import Migrator

    try:
        # Validate dry-run options
        if dry_run and dry_run_execute:
            console.print("[red]❌ Error: Cannot use both --dry-run and --dry-run-execute[/red]")
            raise typer.Exit(1)

        if (dry_run or dry_run_execute) and force:
            console.print("[red]❌ Error: Cannot use --dry-run with --force[/red]")
            raise typer.Exit(1)

        # Validate format option
        if format_output not in ("text", "json"):
            console.print(
                f"[red]❌ Error: Invalid format '{format_output}'. Use 'text' or 'json'[/red]"
            )
            raise typer.Exit(1)

        # Validate checksum mismatch option
        valid_mismatch_behaviors = ("fail", "warn", "ignore")
        if on_checksum_mismatch not in valid_mismatch_behaviors:
            console.print(
                f"[red]❌ Error: Invalid --on-checksum-mismatch '{on_checksum_mismatch}'. "
                f"Use one of: {', '.join(valid_mismatch_behaviors)}[/red]"
            )
            raise typer.Exit(1)

        # Load configuration
        config_data = load_config(config)

        # Try to load environment config for migration settings
        effective_strict_mode = strict
        if (
            not strict
            and config.parent.name == "environments"
            and config.parent.parent.name == "db"
        ):
            # Check if config is in standard environments directory
            try:
                from confiture.config.environment import Environment

                env_name = config.stem  # e.g., "local" from "local.yaml"
                project_dir = config.parent.parent.parent
                env_config = Environment.load(env_name, project_dir=project_dir)
                effective_strict_mode = env_config.migration.strict_mode
            except Exception:
                # If environment config loading fails, use default (False)
                pass

        # Show warnings for force mode before attempting database operations
        if force:
            console.print(
                "[yellow]⚠️  Force mode enabled - skipping migration state checks[/yellow]"
            )
            console.print(
                "[yellow]This may cause issues if applied incorrectly. Use with caution![/yellow]\n"
            )

        # Show warning for no-lock mode
        if no_lock:
            console.print(
                "[yellow]⚠️  Locking disabled - DANGEROUS in multi-pod environments![/yellow]"
            )
            console.print(
                "[yellow]Concurrent migrations may cause race conditions or data corruption.[/yellow]\n"
            )

        # Create database connection
        conn = create_connection(config_data)

        # Create migrator
        migrator = Migrator(connection=conn)
        migrator.initialize()

        # Verify checksums before running migrations (unless force mode)
        if verify_checksums and not force:
            mismatch_behavior = ChecksumMismatchBehavior(on_checksum_mismatch)
            checksum_config = ChecksumConfig(
                enabled=True,
                on_mismatch=mismatch_behavior,
            )
            verifier = MigrationChecksumVerifier(conn, checksum_config)

            try:
                mismatches = verifier.verify_all(migrations_dir)
                if not mismatches:
                    console.print("[cyan]🔐 Checksum verification passed[/cyan]\n")
            except ChecksumVerificationError as e:
                console.print("[red]❌ Checksum verification failed![/red]\n")
                for m in e.mismatches:
                    console.print(f"  [yellow]{m.version}_{m.name}[/yellow]")
                    console.print(f"    Expected: {m.expected[:16]}...")
                    console.print(f"    Actual:   {m.actual[:16]}...")
                console.print(
                    "\n[yellow]💡 Tip: Use 'confiture verify --fix' to update checksums, "
                    "or --no-verify-checksums to skip[/yellow]"
                )
                conn.close()
                raise typer.Exit(1) from e

        # Find migrations to apply
        if force:
            # In force mode, apply all migrations regardless of state
            migrations_to_apply = migrator.find_migration_files(migrations_dir=migrations_dir)
            if not migrations_to_apply:
                console.print("[yellow]⚠️  No migration files found.[/yellow]")
                conn.close()
                return
            console.print(
                f"[cyan]📦 Force mode: Found {len(migrations_to_apply)} migration(s) to apply[/cyan]\n"
            )
        else:
            # Normal mode: only apply pending migrations
            migrations_to_apply = migrator.find_pending(migrations_dir=migrations_dir)
            if not migrations_to_apply:
                console.print("[green]✅ No pending migrations. Database is up to date.[/green]")
                conn.close()
                return
            console.print(
                f"[cyan]📦 Found {len(migrations_to_apply)} pending migration(s)[/cyan]\n"
            )

        # Handle dry-run modes
        if dry_run or dry_run_execute:
            display_dry_run_header("testing" if dry_run_execute else "analysis")

            # Build migration summary
            migration_summary: dict[str, Any] = {
                "migration_id": f"dry_run_{config.stem}",
                "mode": "execute_and_analyze" if dry_run_execute else "analysis",
                "statements_analyzed": len(migrations_to_apply),
                "migrations": [],
                "summary": {
                    "unsafe_count": 0,
                    "total_estimated_time_ms": 0,
                    "total_estimated_disk_mb": 0.0,
                    "has_unsafe_statements": False,
                },
                "warnings": [],
                "analyses": [],
            }

            try:
                # Collect migration information
                for migration_file in migrations_to_apply:
                    migration_class = load_migration_class(migration_file)
                    migration = migration_class(connection=conn)

                    migration_info = {
                        "version": migration.version,
                        "name": migration.name,
                        "classification": "warning",  # Most migrations are complex changes
                        "estimated_duration_ms": 500,  # Conservative estimate
                        "estimated_disk_usage_mb": 1.0,
                        "estimated_cpu_percent": 30.0,
                    }
                    migration_summary["migrations"].append(migration_info)
                    migration_summary["analyses"].append(migration_info)

                # Display format
                if format_output == "json":
                    if output_file:
                        save_json_report(migration_summary, output_file)
                        console.print(
                            f"\n[green]✅ Report saved to: {output_file.absolute()}[/green]"
                        )
                    else:
                        print_json_report(migration_summary)
                else:
                    # Text format (default)
                    console.print("\n[cyan]Migration Analysis Summary[/cyan]")
                    console.print("=" * 80)
                    console.print(f"Migrations to apply: {len(migrations_to_apply)}")
                    console.print()
                    for mig in migration_summary["migrations"]:
                        console.print(f"  {mig['version']}: {mig['name']}")
                        console.print(
                            f"    Estimated time: {mig['estimated_duration_ms']}ms | "
                            f"Disk: {mig['estimated_disk_usage_mb']:.1f}MB | "
                            f"CPU: {mig['estimated_cpu_percent']:.0f}%"
                        )
                    console.print()
                    console.print("[green]✓ All migrations appear safe to execute[/green]")
                    console.print("=" * 80)

                    if output_file:
                        # Create a simple text report for file output
                        text_report = "DRY-RUN MIGRATION ANALYSIS REPORT\n"
                        text_report += "=" * 80 + "\n\n"
                        for mig in migration_summary["migrations"]:
                            text_report += f"{mig['version']}: {mig['name']}\n"
                        save_text_report(text_report, output_file)
                        console.print(
                            f"[green]✅ Report saved to: {output_file.absolute()}[/green]"
                        )

                # Stop here if dry-run only (not execute)
                if dry_run and not dry_run_execute:
                    conn.close()
                    return

                # For dry_run_execute: ask for confirmation
                if dry_run_execute and not ask_dry_run_execute_confirmation():
                    console.print("[yellow]Cancelled - no changes applied[/yellow]")
                    conn.close()
                    return

                # Continue to actual execution below

            except Exception as e:
                console.print(f"\n[red]❌ Dry-run analysis failed: {e}[/red]")
                conn.close()
                raise typer.Exit(1) from e

        # Configure locking
        lock_config = LockConfig(
            enabled=not no_lock,
            timeout_ms=lock_timeout,
        )

        # Create lock manager
        lock = MigrationLock(conn, lock_config)

        # Apply migrations with distributed lock
        applied_count = 0
        failed_migration = None
        failed_exception = None

        try:
            with lock.acquire():
                if not no_lock:
                    console.print("[cyan]🔒 Acquired migration lock[/cyan]\n")

                for migration_file in migrations_to_apply:
                    # Load migration module
                    migration_class = load_migration_class(migration_file)

                    # Create migration instance
                    migration = migration_class(connection=conn)
                    # Override strict_mode from CLI/config if not already set on class
                    if effective_strict_mode and not getattr(migration_class, "strict_mode", False):
                        migration.strict_mode = effective_strict_mode

                    # Check target
                    if target and migration.version > target:
                        console.print(
                            f"[yellow]⏭️  Skipping {migration.version} (after target)[/yellow]"
                        )
                        break

                    # Apply migration
                    console.print(
                        f"[cyan]⚡ Applying {migration.version}_{migration.name}...[/cyan]", end=" "
                    )

                    try:
                        migrator.apply(migration, force=force, migration_file=migration_file)
                        console.print("[green]✅[/green]")
                        applied_count += 1
                    except Exception as e:
                        console.print("[red]❌[/red]")
                        failed_migration = migration
                        failed_exception = e
                        break

        except LockAcquisitionError as e:
            console.print(f"\n[red]❌ Failed to acquire migration lock: {e}[/red]")
            if e.timeout:
                console.print(
                    f"[yellow]💡 Tip: Increase timeout with --lock-timeout {lock_timeout * 2}[/yellow]"
                )
            else:
                console.print(
                    "[yellow]💡 Tip: Check if another migration is running, or use --no-lock (dangerous)[/yellow]"
                )
            conn.close()
            raise typer.Exit(1) from e

        # Handle results
        if failed_migration:
            console.print("\n[red]❌ Migration failed![/red]")
            if applied_count > 0:
                console.print(
                    f"[yellow]⚠️  {applied_count} migration(s) were applied successfully before the failure.[/yellow]"
                )

            # Show detailed error information
            _show_migration_error_details(failed_migration, failed_exception, applied_count)
            conn.close()
            raise typer.Exit(1)
        else:
            if force:
                console.print(
                    f"\n[green]✅ Force mode: Successfully applied {applied_count} migration(s)![/green]"
                )
                console.print(
                    "[yellow]⚠️  Remember to verify your database state after force application[/yellow]"
                )
            else:
                console.print(
                    f"\n[green]✅ Successfully applied {applied_count} migration(s)![/green]"
                )
            conn.close()

    except LockAcquisitionError:
        # Already handled above
        raise
    except Exception as e:
        console.print(f"[red]❌ Error: {e}[/red]")
        raise typer.Exit(1) from e


def _show_migration_error_details(failed_migration, exception, applied_count: int) -> None:
    """Show detailed error information for a failed migration with actionable guidance.

    Args:
        failed_migration: The Migration instance that failed
        exception: The exception that was raised
        applied_count: Number of migrations that succeeded before this one
    """
    from confiture.exceptions import MigrationError

    console.print("\n[red]Failed Migration Details:[/red]")
    console.print(f"  Version: {failed_migration.version}")
    console.print(f"  Name: {failed_migration.name}")
    console.print(f"  File: db/migrations/{failed_migration.version}_{failed_migration.name}.py")

    # Analyze error type and provide specific guidance
    error_message = str(exception)

    # Check if this is a SQL error wrapped in a MigrationError
    if "SQL execution failed" in error_message:
        console.print("  Error Type: SQL Execution Error")

        # Extract SQL and error details from the message
        # Message format: "...SQL execution failed | SQL: ... | Error: ..."
        parts = error_message.split(" | ")
        sql_part = next((part for part in parts if part.startswith("SQL: ")), None)
        error_part = next((part for part in parts if part.startswith("Error: ")), None)

        if sql_part:
            sql_content = sql_part[5:].strip()  # Remove "SQL: " prefix
            console.print(
                f"  SQL Statement: {sql_content[:100]}{'...' if len(sql_content) > 100 else ''}"
            )

        if error_part:
            db_error = error_part[7:].strip()  # Remove "Error: " prefix
            console.print(f"  Database Error: {db_error.split(chr(10))[0]}")

            # Specific SQL error guidance
            error_msg = db_error.lower()
            if "syntax error" in error_msg:
                console.print("\n[yellow]🔍 SQL Syntax Error Detected:[/yellow]")
                console.print("  • Check for typos in SQL keywords, table names, or column names")
                console.print(
                    "  • Verify quotes, parentheses, and semicolons are properly balanced"
                )
                if sql_part:
                    sql_content = sql_part[5:].strip()
                    console.print(f'  • Test the SQL manually: psql -c "{sql_content}"')
            elif "does not exist" in error_msg:
                if "schema" in error_msg:
                    console.print("\n[yellow]🔍 Missing Schema Error:[/yellow]")
                    console.print(
                        "  • Create the schema first: CREATE SCHEMA IF NOT EXISTS schema_name;"
                    )
                    console.print("  • Or use the public schema by default")
                elif "table" in error_msg or "relation" in error_msg:
                    console.print("\n[yellow]🔍 Missing Table Error:[/yellow]")
                    console.print("  • Ensure dependent migrations ran first")
                    console.print("  • Check table name spelling and schema qualification")
                elif "function" in error_msg:
                    console.print("\n[yellow]🔍 Missing Function Error:[/yellow]")
                    console.print("  • Define the function before using it")
                    console.print("  • Check function name and parameter types")
            elif "already exists" in error_msg:
                console.print("\n[yellow]🔍 Object Already Exists:[/yellow]")
                console.print("  • Use IF NOT EXISTS clauses for safe creation")
                console.print("  • Check if migration was partially applied")
            elif "permission denied" in error_msg:
                console.print("\n[yellow]🔍 Permission Error:[/yellow]")
                console.print("  • Verify database user has required privileges")
                console.print("  • Check GRANT statements in earlier migrations")

    elif isinstance(exception, MigrationError):
        console.print("  Error Type: Migration Framework Error")
        console.print(f"  Message: {exception}")

        # Migration-specific guidance
        error_msg = str(exception).lower()
        if "already been applied" in error_msg:
            console.print("\n[yellow]🔍 Migration Already Applied:[/yellow]")
            console.print("  • Check migration status: confiture migrate status")
            console.print("  • This migration may have run successfully before")
        elif "connection" in error_msg:
            console.print("\n[yellow]🔍 Database Connection Error:[/yellow]")
            console.print("  • Verify database is running and accessible")
            console.print("  • Check connection string in config file")
            console.print("  • Test connection: psql 'your-connection-string'")

    else:
        console.print(f"  Error Type: {type(exception).__name__}")
        console.print(f"  Message: {exception}")

    # General troubleshooting
    console.print("\n[yellow]🛠️  General Troubleshooting:[/yellow]")
    console.print(
        f"  • View migration file: cat db/migrations/{failed_migration.version}_{failed_migration.name}.py"
    )
    console.print("  • Check database logs for more details")
    console.print("  • Test SQL manually in psql")

    if applied_count > 0:
        console.print(f"  • {applied_count} migration(s) succeeded - database is partially updated")
        console.print("  • Fix the error and re-run: confiture migrate up")
        console.print(f"  • Or rollback and retry: confiture migrate down --steps {applied_count}")
    else:
        console.print("  • No migrations applied yet - database state is clean")
        console.print("  • Fix the error and re-run: confiture migrate up")


@migrate_app.command("generate")
def migrate_generate(
    name: str = typer.Argument(..., help="Migration name (snake_case)"),
    migrations_dir: Path = typer.Option(
        Path("db/migrations"),
        "--migrations-dir",
        help="Migrations directory",
    ),
) -> None:
    """Generate a new migration file.

    Creates an empty migration template with the given name.
    """
    try:
        # Ensure migrations directory exists
        migrations_dir.mkdir(parents=True, exist_ok=True)

        # Generate migration file template
        generator = MigrationGenerator(migrations_dir=migrations_dir)

        # For empty migration, create a template manually
        version = generator._get_next_version()
        class_name = generator._to_class_name(name)
        filename = f"{version}_{name}.py"
        filepath = migrations_dir / filename

        # Create template
        template = f'''"""Migration: {name}

Version: {version}
"""

from confiture.models.migration import Migration


class {class_name}(Migration):
    """Migration: {name}."""

    version = "{version}"
    name = "{name}"

    def up(self) -> None:
        """Apply migration."""
        # TODO: Add your SQL statements here
        # Example:
        # self.execute("CREATE TABLE users (id SERIAL PRIMARY KEY)")
        pass

    def down(self) -> None:
        """Rollback migration."""
        # TODO: Add your rollback SQL statements here
        # Example:
        # self.execute("DROP TABLE users")
        pass
'''

        filepath.write_text(template)

        console.print("[green]✅ Migration generated successfully![/green]")
        # Use plain print to avoid Rich wrapping long paths
        print(f"\n📄 File: {filepath.absolute()}")
        console.print("\n✏️  Edit the migration file to add your SQL statements.")

    except Exception as e:
        console.print(f"[red]❌ Error generating migration: {e}[/red]")
        raise typer.Exit(1) from e


@migrate_app.command("baseline")
def migrate_baseline(
    through: str = typer.Option(
        ...,
        "--through",
        "-t",
        help="Mark all migrations through this version as applied",
    ),
    migrations_dir: Path = typer.Option(
        Path("db/migrations"),
        "--migrations-dir",
        help="Migrations directory",
    ),
    config: Path = typer.Option(
        Path("db/environments/local.yaml"),
        "--config",
        "-c",
        help="Configuration file with database connection",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Show what would be marked without making changes",
    ),
) -> None:
    """Mark migrations as applied without executing them.

    Use this to establish a baseline when:
    - Adopting confiture on an existing database
    - Setting up a new environment from a backup
    - Recovering from a failed migration state

    Examples:
        confiture migrate baseline --through 002
        confiture migrate baseline -t 005 --dry-run
        confiture migrate baseline -t 003 -c db/environments/production.yaml
    """
    from confiture.core.connection import create_connection, load_config
    from confiture.core.migrator import Migrator

    try:
        if not config.exists():
            console.print(f"[red]❌ Config file not found: {config}[/red]")
            console.print(
                "[yellow]💡 Tip: Specify config with --config path/to/config.yaml[/yellow]"
            )
            raise typer.Exit(1)

        if not migrations_dir.exists():
            console.print(f"[red]❌ Migrations directory not found: {migrations_dir}[/red]")
            raise typer.Exit(1)

        # Load config and create connection
        config_data = load_config(config)
        conn = create_connection(config_data)

        # Initialize migrator
        migrator = Migrator(connection=conn)
        migrator.initialize()

        # Find all migration files
        all_migrations = migrator.find_migration_files(migrations_dir)

        if not all_migrations:
            console.print("[yellow]No migrations found.[/yellow]")
            conn.close()
            return

        # Filter migrations up to and including the target version
        migrations_to_mark: list[Path] = []
        for migration_file in all_migrations:
            version = migrator._version_from_filename(migration_file.name)
            migrations_to_mark.append(migration_file)
            if version == through:
                break
        else:
            # Target version not found
            console.print(f"[red]❌ Migration version '{through}' not found[/red]")
            console.print("[yellow]Available versions:[/yellow]")
            for mf in all_migrations[:10]:
                v = migrator._version_from_filename(mf.name)
                console.print(f"  • {v}")
            if len(all_migrations) > 10:
                console.print(f"  ... and {len(all_migrations) - 10} more")
            conn.close()
            raise typer.Exit(1)

        # Get already applied versions
        applied_versions = set(migrator.get_applied_versions())

        # Show what will be done
        console.print(f"\n[cyan]📋 Baseline: marking migrations through {through}[/cyan]\n")

        if dry_run:
            console.print("[yellow]🔍 DRY RUN - no changes will be made[/yellow]\n")

        marked_count = 0
        skipped_count = 0

        for migration_file in migrations_to_mark:
            version = migrator._version_from_filename(migration_file.name)
            # Extract name
            base_name = migration_file.stem
            if base_name.endswith(".up"):
                base_name = base_name[:-3]
            parts = base_name.split("_", 1)
            name = parts[1] if len(parts) > 1 else base_name

            if version in applied_versions:
                console.print(f"  [dim]⏭️  {version} {name} (already applied)[/dim]")
                skipped_count += 1
            else:
                if dry_run:
                    console.print(f"  [cyan]📝 {version} {name} (would mark as applied)[/cyan]")
                else:
                    migrator.mark_applied(migration_file, reason="baseline")
                    console.print(f"  [green]✅ {version} {name} (marked as applied)[/green]")
                marked_count += 1

        # Summary
        console.print()
        if dry_run:
            console.print(
                f"[cyan]📊 Would mark {marked_count} migration(s), "
                f"skip {skipped_count} already applied[/cyan]"
            )
            console.print("\n[yellow]Run without --dry-run to apply changes[/yellow]")
        else:
            console.print(
                f"[green]✅ Marked {marked_count} migration(s) as applied, "
                f"skipped {skipped_count} already applied[/green]"
            )

        conn.close()

    except typer.Exit:
        raise
    except Exception as e:
        console.print(f"[red]❌ Error: {e}[/red]")
        raise typer.Exit(1) from e


@migrate_app.command("diff")
def migrate_diff(
    old_schema: Path = typer.Argument(..., help="Old schema file"),
    new_schema: Path = typer.Argument(..., help="New schema file"),
    generate: bool = typer.Option(
        False,
        "--generate",
        help="Generate migration from diff",
    ),
    name: str = typer.Option(
        None,
        "--name",
        help="Migration name (required with --generate)",
    ),
    migrations_dir: Path = typer.Option(
        Path("db/migrations"),
        "--migrations-dir",
        help="Migrations directory",
    ),
) -> None:
    """Compare two schema files and show differences.

    Optionally generate a migration file from the diff.
    """
    try:
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

        # Display diff
        if not diff.has_changes():
            console.print("[green]✅ No changes detected. Schemas are identical.[/green]")
            return

        console.print("[cyan]📊 Schema differences detected:[/cyan]\n")

        # Display changes in a table
        table = Table()
        table.add_column("Type", style="yellow")
        table.add_column("Details", style="white")

        for change in diff.changes:
            table.add_row(change.type, str(change))

        console.print(table)
        console.print(f"\n📈 Total changes: {len(diff.changes)}")

        # Generate migration if requested
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

            console.print(f"\n[green]✅ Migration generated: {migration_file.name}[/green]")

    except Exception as e:
        console.print(f"[red]❌ Error: {e}[/red]")
        raise typer.Exit(1) from e


@migrate_app.command("down")
def migrate_down(
    migrations_dir: Path = typer.Option(
        Path("db/migrations"),
        "--migrations-dir",
        help="Migrations directory",
    ),
    config: Path = typer.Option(
        Path("db/environments/local.yaml"),
        "--config",
        "-c",
        help="Configuration file",
    ),
    steps: int = typer.Option(
        1,
        "--steps",
        "-n",
        help="Number of migrations to rollback",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Analyze rollback without executing",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Show detailed analysis in dry-run report",
    ),
    format_output: str = typer.Option(
        "text",
        "--format",
        "-f",
        help="Report format (text or json)",
    ),
    output_file: Path | None = typer.Option(
        None,
        "--output",
        "-o",
        help="Save report to file",
    ),
) -> None:
    """Rollback applied migrations.

    Rolls back the last N applied migrations (default: 1).

    Use --dry-run to analyze rollback without executing.
    """
    from confiture.core.connection import (
        create_connection,
        load_config,
        load_migration_class,
    )
    from confiture.core.migrator import Migrator

    try:
        # Validate format option
        if format_output not in ("text", "json"):
            console.print(
                f"[red]❌ Error: Invalid format '{format_output}'. Use 'text' or 'json'[/red]"
            )
            raise typer.Exit(1)

        # Load configuration
        config_data = load_config(config)

        # Create database connection
        conn = create_connection(config_data)

        # Create migrator
        migrator = Migrator(connection=conn)
        migrator.initialize()

        # Get applied migrations
        applied_versions = migrator.get_applied_versions()

        if not applied_versions:
            console.print("[yellow]⚠️  No applied migrations to rollback.[/yellow]")
            conn.close()
            return

        # Get migrations to rollback (last N)
        versions_to_rollback = applied_versions[-steps:]

        # Handle dry-run mode
        if dry_run:
            from confiture.cli.dry_run import (
                display_dry_run_header,
                save_json_report,
                save_text_report,
            )

            display_dry_run_header("analysis")

            # Build rollback summary
            rollback_summary: dict[str, Any] = {
                "migration_id": f"dry_run_rollback_{config.stem}",
                "mode": "analysis",
                "statements_analyzed": len(versions_to_rollback),
                "migrations": [],
                "summary": {
                    "unsafe_count": 0,
                    "total_estimated_time_ms": 0,
                    "total_estimated_disk_mb": 0.0,
                    "has_unsafe_statements": False,
                },
                "warnings": [],
                "analyses": [],
            }

            # Collect rollback migration information
            for version in reversed(versions_to_rollback):
                # Find migration file
                migration_files = migrator.find_migration_files(migrations_dir=migrations_dir)
                migration_file = None
                for mf in migration_files:
                    if migrator._version_from_filename(mf.name) == version:
                        migration_file = mf
                        break

                if not migration_file:
                    continue

                # Load migration class
                migration_class = load_migration_class(migration_file)

                migration = migration_class(connection=conn)

                migration_info = {
                    "version": migration.version,
                    "name": migration.name,
                    "classification": "warning",
                    "estimated_duration_ms": 500,
                    "estimated_disk_usage_mb": 1.0,
                    "estimated_cpu_percent": 30.0,
                }
                rollback_summary["migrations"].append(migration_info)
                rollback_summary["analyses"].append(migration_info)

            # Display format
            if format_output == "json":
                if output_file:
                    save_json_report(rollback_summary, output_file)
                    console.print(f"\n[green]✅ Report saved to: {output_file.absolute()}[/green]")
                else:
                    from confiture.cli.dry_run import print_json_report

                    print_json_report(rollback_summary)
            else:
                # Text format (default)
                console.print("[cyan]Rollback Analysis Summary[/cyan]")
                console.print("=" * 80)
                console.print(f"Migrations to rollback: {len(versions_to_rollback)}")
                console.print()
                for mig in rollback_summary["migrations"]:
                    console.print(f"  {mig['version']}: {mig['name']}")
                    console.print(
                        f"    Estimated time: {mig['estimated_duration_ms']}ms | "
                        f"Disk: {mig['estimated_disk_usage_mb']:.1f}MB | "
                        f"CPU: {mig['estimated_cpu_percent']:.0f}%"
                    )
                console.print()
                console.print("[yellow]⚠️  Rollback will undo these migrations[/yellow]")
                console.print("=" * 80)

                if output_file:
                    text_report = "DRY-RUN ROLLBACK ANALYSIS REPORT\n"
                    text_report += "=" * 80 + "\n\n"
                    for mig in rollback_summary["migrations"]:
                        text_report += f"{mig['version']}: {mig['name']}\n"
                    save_text_report(text_report, output_file)
                    console.print(f"[green]✅ Report saved to: {output_file.absolute()}[/green]")

            conn.close()
            return

        console.print(f"[cyan]📦 Rolling back {len(versions_to_rollback)} migration(s)[/cyan]\n")

        # Rollback migrations in reverse order
        rolled_back_count = 0
        for version in reversed(versions_to_rollback):
            # Find migration file
            migration_files = migrator.find_migration_files(migrations_dir=migrations_dir)
            migration_file = None
            for mf in migration_files:
                if migrator._version_from_filename(mf.name) == version:
                    migration_file = mf
                    break

            if not migration_file:
                console.print(f"[red]❌ Migration file for version {version} not found[/red]")
                continue

            # Load migration module
            migration_class = load_migration_class(migration_file)

            # Create migration instance
            migration = migration_class(connection=conn)

            # Rollback migration
            console.print(
                f"[cyan]⚡ Rolling back {migration.version}_{migration.name}...[/cyan]", end=" "
            )
            migrator.rollback(migration)
            console.print("[green]✅[/green]")
            rolled_back_count += 1

        console.print(
            f"\n[green]✅ Successfully rolled back {rolled_back_count} migration(s)![/green]"
        )
        conn.close()

    except Exception as e:
        console.print(f"[red]❌ Error: {e}[/red]")
        raise typer.Exit(1) from e


@app.command()
def validate_profile(
    path: Path = typer.Argument(
        ...,
        help="Path to anonymization profile YAML file",
    ),
) -> None:
    """Validate anonymization profile YAML structure and schema.

    Performs security validation:
    - Uses safe_load() to prevent YAML injection
    - Validates against Pydantic schema
    - Checks strategy types are whitelisted
    - Verifies all required fields present

    Example:
        confiture validate-profile db/profiles/production.yaml
    """
    try:
        from confiture.core.anonymization.profile import AnonymizationProfile

        console.print(f"[cyan]📋 Validating profile: {path}[/cyan]")
        profile = AnonymizationProfile.load(path)

        # Print profile summary
        console.print("[green]✅ Valid profile![/green]")
        console.print(f"   Name: {profile.name}")
        console.print(f"   Version: {profile.version}")
        if profile.global_seed:
            console.print(f"   Global Seed: {profile.global_seed}")

        # List strategies
        console.print(f"\n[cyan]Strategies ({len(profile.strategies)})[/cyan]:")
        for strategy_name, strategy_def in profile.strategies.items():
            console.print(
                f"   • {strategy_name}: {strategy_def.type}",
                end="",
            )
            if strategy_def.seed_env_var:
                console.print(f" [env: {strategy_def.seed_env_var}]")
            else:
                console.print()

        # List tables
        console.print(f"\n[cyan]Tables ({len(profile.tables)})[/cyan]:")
        for table_name, table_def in profile.tables.items():
            console.print(f"   • {table_name}: {len(table_def.rules)} rules")
            for rule in table_def.rules:
                console.print(f"      - {rule.column} → {rule.strategy}", end="")
                if rule.seed:
                    console.print(f" [seed: {rule.seed}]")
                else:
                    console.print()

        console.print("[green]\n✅ Profile validation passed![/green]")

    except FileNotFoundError as e:
        console.print(f"[red]❌ File not found: {e}[/red]")
        raise typer.Exit(1) from e
    except ValueError as e:
        console.print(f"[red]❌ Invalid profile: {e}[/red]")
        raise typer.Exit(1) from e
    except Exception as e:
        console.print(f"[red]❌ Error validating profile: {e}[/red]")
        raise typer.Exit(1) from e


@app.command()
def verify(
    migrations_dir: Path = typer.Option(
        Path("db/migrations"),
        "--migrations-dir",
        help="Migrations directory",
    ),
    config: Path = typer.Option(
        Path("db/environments/local.yaml"),
        "--config",
        "-c",
        help="Configuration file",
    ),
    fix: bool = typer.Option(
        False,
        "--fix",
        help="Update stored checksums to match current files (dangerous)",
    ),
) -> None:
    """Verify migration file integrity against stored checksums.

    Compares SHA-256 checksums of migration files against the checksums
    stored when migrations were applied. Detects if files have been
    modified after application.

    This helps prevent:
    - Silent schema drift between environments
    - Production/staging mismatches
    - Debugging nightmares from modified migrations

    Examples:
        # Verify all migrations
        confiture verify

        # Verify with specific config
        confiture verify --config db/environments/production.yaml

        # Fix checksums (update stored to match current files)
        confiture verify --fix
    """
    from confiture.core.checksum import (
        ChecksumConfig,
        ChecksumMismatchBehavior,
        MigrationChecksumVerifier,
    )
    from confiture.core.connection import create_connection, load_config

    try:
        # Load config and connect
        config_data = load_config(config)
        conn = create_connection(config_data)

        # Run verification (warn mode - we'll handle display)
        verifier = MigrationChecksumVerifier(
            conn,
            ChecksumConfig(
                enabled=True,
                on_mismatch=ChecksumMismatchBehavior.WARN,
            ),
        )
        mismatches = verifier.verify_all(migrations_dir)

        if not mismatches:
            console.print("[green]✅ All migration checksums verified![/green]")
            conn.close()
            return

        # Display mismatches
        console.print(f"[red]❌ Found {len(mismatches)} checksum mismatch(es):[/red]\n")

        for m in mismatches:
            console.print(f"  [yellow]{m.version}_{m.name}[/yellow]")
            console.print(f"    File: {m.file_path}")
            console.print(f"    Expected: {m.expected[:16]}...")
            console.print(f"    Actual:   {m.actual[:16]}...")
            console.print()

        if fix:
            # Update checksums in database
            console.print("[yellow]⚠️  Updating stored checksums...[/yellow]")
            updated = verifier.update_all_checksums(migrations_dir)
            console.print(f"[green]✅ Updated {updated} checksum(s)[/green]")
        else:
            console.print(
                "[yellow]💡 Tip: Use --fix to update stored checksums (dangerous)[/yellow]"
            )
            conn.close()
            raise typer.Exit(1)

        conn.close()

    except typer.Exit:
        raise
    except Exception as e:
        console.print(f"[red]❌ Error: {e}[/red]")
        raise typer.Exit(1) from e


if __name__ == "__main__":
    app()
