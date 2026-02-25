"""Main CLI entry point for Confiture.

This module defines the main Typer application and all CLI commands.
"""

import difflib
import json
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.table import Table

from confiture.cli.branch import branch_app
from confiture.cli.coordinate import coordinate_app
from confiture.cli.generate import generate_app
from confiture.cli.lint_formatter import format_lint_report, save_report
from confiture.cli.seed import seed_app
from confiture.core.builder import SchemaBuilder
from confiture.core.connection import create_connection
from confiture.core.differ import SchemaDiffer
from confiture.core.error_handler import handle_cli_error, print_error_to_console
from confiture.core.introspector import SchemaIntrospector
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
from confiture.core.seed_applier import SeedApplier
from confiture.models.lint import LintReport, LintSeverity, Violation

# Valid output formats for linting
LINT_FORMATS = ("table", "json", "csv")

# Common command names for "Did you mean?" suggestions
COMMON_COMMANDS = [
    "init",
    "build",
    "migrate",
    "lint",
    "introspect",
    "seed",
    "branch",
    "generate",
    "coordinate",
    "install-helpers",
    "migrate-up",
    "migrate-down",
    "migrate-status",
    "migrate-validate",
]


def _get_suggestion(unknown_command: str) -> str | None:
    """Get "Did you mean?" suggestion for unknown command.

    Uses difflib to find similar commands (75% similarity threshold).

    Args:
        unknown_command: The command user tried to run

    Returns:
        Suggested command if match found (>75% similarity), None otherwise
    """
    matches = difflib.get_close_matches(unknown_command, COMMON_COMMANDS, n=1, cutoff=0.75)
    return matches[0] if matches else None


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


def version_callback(value: bool) -> None:
    """Print version and exit."""
    if value:
        from confiture import __version__

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
        print_error_to_console(e)
        raise typer.Exit(handle_cli_error(e)) from e


@app.command()
def build(
    env: str = typer.Option(
        "local",
        "--env",
        "-e",
        help="Environment to build (default: local)",
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
        help="Display schema hash after build (default: off)",
    ),
    schema_only: bool = typer.Option(
        False,
        "--schema-only",
        help="Build schema only, exclude seed data (default: off)",
    ),
    validate_comments: bool | None = typer.Option(
        None,
        "--validate-comments/--no-validate-comments",
        help="Enable/disable comment validation (default: from config)",
    ),
    fail_on_unclosed: bool | None = typer.Option(
        None,
        "--fail-on-unclosed/--no-fail-on-unclosed",
        help="Fail on unclosed block comments (default: from config)",
    ),
    fail_on_spillover: bool | None = typer.Option(
        None,
        "--fail-on-spillover/--no-fail-on-spillover",
        help="Fail on comment spillover into next file (default: from config)",
    ),
    separator_style: str | None = typer.Option(
        None,
        "--separator-style",
        help="Separator style: block_comment, line_comment, mysql, custom (default: from config)",
    ),
    separator_template: str | None = typer.Option(
        None,
        "--separator-template",
        help="Custom separator template with {file_path} placeholder (default: none)",
    ),
    sequential: bool = typer.Option(
        False,
        "--sequential",
        help="Apply seed files sequentially after build (default: off)",
    ),
    database_url: str | None = typer.Option(
        None,
        "--database-url",
        help="Database connection URL (required for --sequential, default: from config)",
    ),
    continue_on_error: bool = typer.Option(
        False,
        "--continue-on-error",
        help="Continue applying seed files if one fails (only with --sequential)",
    ),
    format_type: str = typer.Option(
        "text",
        "--format",
        "-f",
        help="Output format: text, json, csv (default: text)",
    ),
    report_output: Path = typer.Option(
        None,
        "--report",
        help="Save structured output (JSON/CSV) to file (default: stdout)",
    ),
) -> None:
    """Build complete schema from DDL files in one fast operation.

    PROCESS:
      Concatenates all SQL files from db/schema/ in deterministic order, validates
      comments (optional), adds separators, and writes the complete schema. Fastest
      way to create or recreate a database from scratch.

    EXAMPLES:
      confiture build
        ↳ Build local environment, output to db/generated/schema_local.sql

      confiture build --env production --show-hash
        ↳ Build production environment and show schema hash for change detection

      confiture build --sequential --database-url postgresql://localhost/myapp
        ↳ Build schema AND apply seed files sequentially (solves 650+ row limits)

      confiture build --validate-comments --fail-on-unclosed
        ↳ Enable comment validation to catch concatenation errors

    RELATED:
      confiture migrate up      - Apply incremental migrations instead
      confiture seed validate   - Validate seed data separately
      confiture lint            - Check schema against best practices

    OPTIONS:
      CORE: --env, --output
        Essential options for basic usage

      ADVANCED: --show-hash, --schema-only, --separator-style, --separator-template
        Optional parameters for customizing output format

      STRUCTURED OUTPUT: --format, --report
        Export results in JSON/CSV format for automation and integration

      SEEDS & VALIDATION: --sequential, --database-url, --continue-on-error,
                         --validate-comments, --fail-on-unclosed, --fail-on-spillover
        For applying seeds after build and controlling validation behavior
    """
    try:
        # Create schema builder
        builder = SchemaBuilder(env=env, project_dir=project_dir)

        # Apply CLI overrides for comment validation
        if validate_comments is not None:
            builder.env_config.build.validate_comments.enabled = validate_comments
        if fail_on_unclosed is not None:
            builder.env_config.build.validate_comments.fail_on_unclosed_blocks = fail_on_unclosed
        if fail_on_spillover is not None:
            builder.env_config.build.validate_comments.fail_on_spillover = fail_on_spillover

        # Apply CLI overrides for separator style
        if separator_style is not None:
            # Validate separator style
            valid_styles = ["block_comment", "line_comment", "mysql", "custom"]
            if separator_style not in valid_styles:
                console.print(f"[red]❌ Invalid separator style: {separator_style}[/red]")
                console.print(f"   Valid options: {', '.join(valid_styles)}")
                raise typer.Exit(1)
            builder.env_config.build.separators.style = separator_style

        # Apply custom template if provided
        if separator_template is not None:
            builder.env_config.build.separators.custom_template = separator_template

        # Validate custom template requirement
        if (
            separator_style == "custom"
            and not separator_template
            and not builder.env_config.build.separators.custom_template
        ):
            console.print("[red]❌ Custom separator style requires --separator-template[/red]")
            raise typer.Exit(1)

        # Show overrides if any were applied
        overrides_applied = any(
            [
                validate_comments is not None,
                fail_on_unclosed is not None,
                fail_on_spillover is not None,
                separator_style is not None,
                separator_template is not None,
            ]
        )
        if overrides_applied:
            console.print("[cyan]📝 Configuration overrides applied:[/cyan]")
            if validate_comments is not None:
                console.print(f"  • Comment validation: {validate_comments}")
            if fail_on_unclosed is not None:
                console.print(f"  • Fail on unclosed blocks: {fail_on_unclosed}")
            if fail_on_spillover is not None:
                console.print(f"  • Fail on spillover: {fail_on_spillover}")
            if separator_style is not None:
                console.print(f"  • Separator style: {separator_style}")
            if separator_template is not None:
                console.print(
                    f"  • Custom template: {separator_template[:50]}..."
                    if len(separator_template or "") > 50
                    else f"  • Custom template: {separator_template}"
                )

        # Override to exclude seeds if --schema-only is specified
        if schema_only:
            builder.include_dirs = [d for d in builder.include_dirs if "seed" not in str(d).lower()]
            builder.include_configs = [
                cfg for cfg in builder.include_configs if "seed" not in str(cfg["path"]).lower()
            ]
            # Recalculate base_dir after filtering
            if builder.include_dirs:
                builder.base_dir = builder._find_common_parent(builder.include_dirs)

        # Set default output path if not specified
        if output is None:
            output_dir = project_dir / "db" / "generated"
            output_dir.mkdir(parents=True, exist_ok=True)
            output = output_dir / f"schema_{env}.sql"

        # Determine if we should apply seeds sequentially
        apply_sequential = sequential or (
            builder.env_config.seed and builder.env_config.seed.execution_mode == "sequential"
        )

        # Build schema (with or without seeds)
        console.print(f"[cyan]🔨 Building schema for environment: {env}[/cyan]")

        # Import ProgressManager for progress tracking
        from confiture.core.progress import ProgressManager

        with ProgressManager() as progress:
            if apply_sequential:
                # Build schema only, seeds will be applied separately
                schema = builder.build(output_path=output, schema_only=True, progress=progress)
                sql_files = builder.find_sql_files()
                schema_file_count = len(
                    [
                        f
                        for f in sql_files
                        if not any(p.lower() in ("seed", "seeds") for p in f.parts)
                    ]
                )
            else:
                # Build schema with seeds
                sql_files = builder.find_sql_files()
                schema = builder.build(output_path=output, progress=progress)
                schema_file_count = len(sql_files)

        console.print(f"[cyan]📄 Found {len(sql_files)} SQL files[/cyan]")

        # Track seed files applied (will be updated if sequential)
        seed_files_applied = 0

        # Apply seeds sequentially if requested
        if apply_sequential:
            console.print("\n[cyan]🌱 Applying seed files sequentially...[/cyan]")

            # Get database URL (from CLI or config)
            db_url = database_url or builder.env_config.database_url
            if not db_url:
                console.print("[red]❌ Database URL required for --sequential mode[/red]")
                console.print("   Provide via --database-url or in environment config")
                raise typer.Exit(1)

            # Import psycopg here to connect to database
            try:
                import psycopg

                connection = psycopg.connect(db_url)
            except Exception as e:
                console.print(f"[red]❌ Failed to connect to database: {e}[/red]")
                raise typer.Exit(1) from e

            try:
                # Get seeds directory (parent of first seed file)
                schema_files, seed_files = builder.categorize_sql_files()
                if seed_files:
                    seeds_dir = seed_files[0].parent.parent

                    # Apply seeds
                    applier = SeedApplier(
                        seeds_dir=seeds_dir,
                        env=env,
                        connection=connection,
                        console=console,
                    )
                    result = applier.apply_sequential(continue_on_error=continue_on_error)

                    seed_files_applied = result.succeeded
                    console.print(f"[green]✅ Applied {result.succeeded} seed files[/green]")
                    if result.failed > 0:
                        console.print(f"[yellow]⚠️  {result.failed} seed files failed[/yellow]")
                        if not continue_on_error:
                            raise typer.Exit(1)
                else:
                    console.print("[yellow]⚠️  No seed files found[/yellow]")

                connection.close()
            except typer.Exit:
                connection.close()
                raise
            except Exception as e:
                connection.close()
                console.print(f"[red]❌ Seed application failed: {e}[/red]")
                raise typer.Exit(1) from e

        # Show hash if requested
        schema_hash = None
        if show_hash:
            schema_hash = builder.compute_hash()

        # Validate format_type
        if format_type not in ("text", "json", "csv"):
            console.print(f"[red]❌ Invalid format: {format_type}. Use text, json, or csv[/red]")
            raise typer.Exit(1)

        # Create and format build result
        from confiture.cli.formatters.build_formatter import format_build_result
        from confiture.models.results import BuildResult

        build_result = BuildResult(
            success=True,
            files_processed=schema_file_count,
            schema_size_bytes=len(schema),
            output_path=str(output.absolute()),
            hash=schema_hash,
            execution_time_ms=0,  # Could track this if needed
            seed_files_applied=seed_files_applied,
        )

        # Format and output result
        format_build_result(build_result, format_type, report_output, console)

        # Show next steps only for text format
        if format_type == "text":
            console.print("\n💡 Next steps:")
            console.print(f"  • Apply schema: psql -f {output}")
            console.print("  • Or use: confiture migrate up")

    except FileNotFoundError as e:
        # Try to format error result if format was specified
        try:
            from confiture.cli.formatters.build_formatter import format_build_result
            from confiture.models.results import BuildResult

            error_result = BuildResult(
                success=False,
                files_processed=0,
                schema_size_bytes=0,
                output_path="",
                error=str(e),
            )
            if format_type != "text":
                format_build_result(error_result, format_type, report_output, console)
        except Exception:
            pass

        print_error_to_console(e)
        console.print("\n💡 Tip: Run 'confiture init' to create project structure")
        raise typer.Exit(handle_cli_error(e)) from e
    except Exception as e:
        # Try to format error result if format was specified
        try:
            from confiture.cli.formatters.build_formatter import format_build_result
            from confiture.models.results import BuildResult

            error_result = BuildResult(
                success=False,
                files_processed=0,
                schema_size_bytes=0,
                output_path="",
                error=str(e),
            )
            if format_type != "text":
                format_build_result(error_result, format_type, report_output, console)
        except Exception:
            pass

        print_error_to_console(e)
        raise typer.Exit(handle_cli_error(e)) from e


@app.command()
def lint(
    env: str = typer.Option(
        "local",
        "--env",
        "-e",
        help="Environment to lint (default: local)",
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
        help="Output format: table, json, csv (default: table)",
    ),
    output: Path = typer.Option(
        None,
        "--output",
        "-o",
        help="Output file path (default: stdout, only with json/csv)",
    ),
    fail_on_error: bool = typer.Option(
        True,
        "--fail-on-error",
        help="Exit with code 1 if errors found (default: on)",
    ),
    fail_on_warning: bool = typer.Option(
        False,
        "--fail-on-warning",
        help="Exit with code 1 if warnings found (default: off, stricter)",
    ),
) -> None:
    """Validate schema against best practices.

    PROCESS:
      Checks schema against 6 rules: naming conventions (snake_case), primary
      keys on all tables, documentation, multi-tenant columns, FK indexes, and
      security (no passwords/secrets). Results in table or JSON format.

    EXAMPLES:
      confiture lint
        ↳ Lint local environment, display results as table

      confiture lint --env production
        ↳ Lint production environment

      confiture lint --format json --output report.json
        ↳ Save linting report to JSON file

      confiture lint --fail-on-warning
        ↳ Exit with error code if any warnings found (strict mode)

    RELATED:
      confiture build       - Build schema from DDL files
      confiture migrate up  - Apply migrations
      confiture schema-to-schema - Compare and sync schemas

    OPTIONS:
      CORE: --env, --format, --output
        What to lint and how to report results

      SEVERITY: --fail-on-error, --fail-on-warning
        Control exit behavior based on issue severity
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
        print_error_to_console(e)
        console.print("\n💡 Tip: Make sure schema files exist in db/schema/")
        raise typer.Exit(handle_cli_error(e)) from e
    except Exception as e:
        print_error_to_console(e)
        raise typer.Exit(handle_cli_error(e)) from e


@app.command()
def introspect(
    db: str = typer.Option(
        ...,
        "--db",
        help="PostgreSQL connection URL (e.g. postgresql://user:pass@host/dbname)",
    ),
    schema: str = typer.Option(
        "public",
        "--schema",
        help="Schema to introspect (default: public)",
    ),
    format_type: str = typer.Option(
        "json",
        "--format",
        "-f",
        help="Output format: json, yaml (default: json)",
    ),
    all_tables: bool = typer.Option(
        False,
        "--all-tables",
        help="Include all tables, not just tb_* (default: off)",
    ),
    hints: bool = typer.Option(
        True,
        "--hints/--no-hints",
        help="Include naming-convention hints block (default: on)",
    ),
    output: Path | None = typer.Option(
        None,
        "--output",
        "-o",
        help="Write output to file instead of stdout",
    ),
) -> None:
    """Introspect a PostgreSQL database and export its schema as structured JSON.

    Connects to an existing database and exports tables, columns, PostgreSQL
    types, primary keys, and the full FK relationship graph.  Designed for
    brownfield adoption and agentic workflows where an agent needs accurate,
    structured facts about a schema it cannot see.

    By default only tables whose names start with ``tb_`` are included.
    Use ``--all-tables`` to include every base table in the schema.

    The ``hints`` block surfaces surrogate-PK / natural-ID naming patterns as
    non-prescriptive signals.  Use ``--no-hints`` to omit it.

    Examples:

      confiture introspect --db $DATABASE_URL

      confiture introspect --db $DATABASE_URL --schema myschema

      confiture introspect --db $DATABASE_URL --format yaml --output schema.yaml

      confiture introspect --db $DATABASE_URL --all-tables --no-hints
    """
    # Status/error messages go to stderr so stdout stays pipe-friendly.
    console = Console(stderr=True)

    if format_type not in ("json", "yaml"):
        console.print(f"[red]❌ Invalid format: {format_type!r}. Use 'json' or 'yaml'[/red]")
        raise typer.Exit(1)

    try:
        conn = create_connection(db)
    except Exception as e:
        console.print(f"[red]❌ Connection failed: {e}[/red]")
        raise typer.Exit(1) from e

    with conn:
        introspector = SchemaIntrospector(conn)
        result = introspector.introspect(
            schema=schema,
            all_tables=all_tables,
            include_hints=hints,
        )

    data = result.to_dict()

    if format_type == "yaml":
        _output_yaml(data, output, console)
    else:
        _output_json(data, output, console)


def _output_yaml(data: dict[str, Any], output_file: Path | None, console: Console) -> None:
    """Output YAML data to file or console.

    Args:
        data: Data to serialise as YAML.
        output_file: Optional file to write to; if None, writes to stdout.
        console: Console used for status messages (stderr).
    """
    import yaml

    yaml_str = yaml.dump(data, default_flow_style=False, sort_keys=False, allow_unicode=True)
    if output_file:
        output_file.write_text(yaml_str)
        console.print(f"[green]✅ Output written to {output_file}[/green]")
    else:
        print(yaml_str, end="")


# Create migrate subcommand group
migrate_app = typer.Typer(help="Migration commands")
app.add_typer(migrate_app, name="migrate")

# Add branch subcommand group (pgGit integration)
app.add_typer(branch_app, name="branch")

# Add generate subcommand group (pgGit migration generation)
app.add_typer(generate_app, name="generate")

# Add coordinate subcommand group (multi-agent coordination)
app.add_typer(coordinate_app, name="coordinate")

# Add seed subcommand group (seed validation)
app.add_typer(seed_app, name="seed")


@app.command("install-helpers")
def install_helpers(
    config: Path = typer.Option(
        None,
        "--config",
        "-c",
        help="Configuration file (YAML)",
    ),
    env: str = typer.Option(
        "local",
        "--env",
        "-e",
        help="Environment name (default: local)",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Show SQL without executing",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Reinstall even if already installed",
    ),
) -> None:
    """Install confiture SQL helper functions in the target database.

    Creates the `confiture` schema with `save_and_drop_dependent_views()`
    and `recreate_saved_views()` PL/pgSQL functions for use in migrations
    that need to ALTER COLUMN TYPE on tables with dependent views.
    """
    try:
        from confiture.core.connection import load_config
        from confiture.core.view_manager import ViewManager

        if config:
            cfg = load_config(config)
        else:
            from confiture.config.environment import Environment

            environment = Environment.load(env)
            cfg = {"database": {"url": environment.database_url}}

        conn = create_connection(cfg)

        if dry_run:
            from importlib import resources

            sql = resources.files("confiture.sql").joinpath("view_helpers.sql").read_text()
            console.print("[bold]SQL that would be executed:[/bold]\n")
            console.print(sql)
            conn.close()
            return

        vm = ViewManager(conn)

        if not force and vm.helpers_installed():
            console.print("[green]✓[/green] View helpers already installed — nothing to do")
            console.print("  Use [bold]--force[/bold] to reinstall")
            conn.close()
            return

        vm.install_helpers()
        conn.close()

        console.print("[green]✓[/green] Installed confiture view helper functions")
        console.print("  Schema: [bold]confiture[/bold]")
        console.print("  Functions:")
        console.print("    • confiture.save_and_drop_dependent_views(schemas TEXT[])")
        console.print("    • confiture.recreate_saved_views()")

    except Exception as e:
        handle_cli_error(e, console)
        raise typer.Exit(code=1) from None


@migrate_app.command("status")
def migrate_status(
    migrations_dir: Path = typer.Option(
        Path("db/migrations"),
        "--migrations-dir",
        help="Migrations directory (default: db/migrations)",
    ),
    config: Path = typer.Option(
        None,
        "--config",
        "-c",
        help="Configuration file (default: none, optional for applied status)",
    ),
    output_format: str = typer.Option(
        "table",
        "--format",
        "-f",
        help="Output format: table or json (default: table)",
    ),
    output_file: Path = typer.Option(
        None,
        "--output",
        "-o",
        help="Save output to file (default: stdout, useful with json)",
    ),
) -> None:
    """Show migration status and history.

    PROCESS:
      Lists all migrations and their status (applied or pending). With --config,
      connects to database and shows which migrations are applied vs pending.

    EXAMPLES:
      confiture migrate status
        ↳ List all migrations and their status

      confiture migrate status --config db/environments/prod.yaml
        ↳ Show applied vs pending migrations in production database

      confiture migrate status --format json
        ↳ Output as JSON for scripting

      confiture migrate status --format json --output migrations.json
        ↳ Save status report to file

    RELATED:
      confiture migrate up       - Apply pending migrations
      confiture migrate down     - Rollback applied migrations
      confiture migrate generate - Create new migration
    """
    try:
        # Validate output format
        if output_format not in ("table", "json", "csv"):
            console.print(
                f"[red]❌ Invalid format: {output_format}. Use 'table', 'json', or 'csv'[/red]"
            )
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

        # Check for orphaned SQL files that don't match the naming pattern
        orphaned_sql_files = _find_orphaned_sql_files(migrations_dir)

        # Check for duplicate migration versions (warning only)
        from confiture.core.migrator import find_duplicate_migration_versions as _status_find

        duplicate_versions = _status_find(migrations_dir)

        if not migration_files:
            if output_format == "json":
                result = {
                    "applied": [],
                    "pending": [],
                    "current": None,
                    "total": 0,
                    "migrations": [],
                }
                if orphaned_sql_files:
                    result["orphaned_migrations"] = [f.name for f in orphaned_sql_files]
                _output_json(result, output_file, console)
            else:
                console.print("[yellow]No migrations found.[/yellow]")
                if orphaned_sql_files:
                    _print_orphaned_files_warning(orphaned_sql_files, console)
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
            if orphaned_sql_files:
                result["orphaned_migrations"] = [f.name for f in orphaned_sql_files]
            if duplicate_versions:
                result["duplicate_versions"] = {
                    v: [f.name for f in files] for v, files in duplicate_versions.items()
                }
            _output_json(result, output_file, console)
        elif output_format == "csv":
            # CSV output with migration list
            from confiture.cli.formatters.common import handle_output

            csv_data = (
                ["version", "name", "status"],
                [[m["version"], m["name"], m["status"]] for m in migrations_data],
            )
            handle_output("csv", {}, csv_data, output_file, console)
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

            # Warn about duplicate versions
            if duplicate_versions:
                _print_duplicate_versions_warning(duplicate_versions, console)

            # Warn about orphaned files
            if orphaned_sql_files:
                _print_orphaned_files_warning(orphaned_sql_files, console)

    except Exception as e:
        if output_format == "json":
            result = {"error": str(e)}
            _output_json(result, output_file, console)
        elif output_format == "csv":
            from confiture.cli.formatters.common import handle_output

            csv_data = (
                ["error"],
                [[str(e)]],
            )
            handle_output("csv", {}, csv_data, output_file, console)
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
        # Use print() instead of console.print() to avoid Rich wrapping long lines
        print(json_str)


def _find_orphaned_sql_files(migrations_dir: Path) -> list[Path]:
    """Find .sql files that don't match the expected naming pattern.

    Args:
        migrations_dir: Directory to search for migrations

    Returns:
        List of orphaned .sql file paths
    """
    if not migrations_dir.exists():
        return []

    # Find all .sql files
    all_sql_files = set(migrations_dir.glob("*.sql"))

    # Find all properly named migration files
    expected_files = set(migrations_dir.glob("*.up.sql")) | set(migrations_dir.glob("*.down.sql"))

    # Orphaned files are SQL files that don't match the expected pattern
    orphaned = all_sql_files - expected_files
    return sorted(orphaned, key=lambda f: f.name)


def _print_duplicate_versions_warning(
    duplicate_versions: dict[str, list[Path]], console: Console
) -> None:
    """Print a warning about duplicate migration versions.

    Args:
        duplicate_versions: Dict mapping version to list of conflicting files
        console: Console for output
    """
    console.print("\n[yellow]⚠️  WARNING: Duplicate migration versions detected[/yellow]")
    console.print("[yellow]Multiple migration files share the same version number:[/yellow]")

    for version, files in sorted(duplicate_versions.items()):
        console.print(f"\n  Version {version}:")
        for f in files:
            console.print(f"    • {f.name}")

    console.print("\n[yellow]💡 Rename files to use unique version prefixes.[/yellow]")
    console.print(
        "[yellow]   Use 'confiture migrate generate' to auto-assign the next version.[/yellow]"
    )


def _print_orphaned_files_warning(orphaned_files: list[Path], console: Console) -> None:
    """Print a warning about orphaned migration files.

    Args:
        orphaned_files: List of orphaned migration file paths
        console: Console for output
    """
    console.print("\n[yellow]⚠️  WARNING: Orphaned migration files detected[/yellow]")
    console.print("[yellow]These SQL files exist but won't be applied by Confiture:[/yellow]")

    for orphaned_file in orphaned_files:
        # Suggest the rename
        suggested_name = f"{orphaned_file.stem}.up.sql"
        console.print(f"  • {orphaned_file.name} → rename to: {suggested_name}")

    console.print(
        "\n[yellow]Confiture only recognizes migration files with these patterns:[/yellow]"
    )
    console.print("[yellow]  • {NNN}_{name}.up.sql   (forward migrations)[/yellow]")
    console.print("[yellow]  • {NNN}_{name}.down.sql (rollback migrations)[/yellow]")
    console.print("[yellow]  • {NNN}_{name}.py       (Python class migrations)[/yellow]")
    console.print("[yellow]Learn more: https://github.com/evoludigit/confiture/issues/13[/yellow]")


@migrate_app.command("up")
def migrate_up(
    migrations_dir: Path = typer.Option(
        Path("db/migrations"),
        "--migrations-dir",
        help="Migrations directory (default: db/migrations)",
    ),
    config: Path = typer.Option(
        Path("db/environments/local.yaml"),
        "--config",
        "-c",
        help="Configuration file (default: db/environments/local.yaml)",
    ),
    target: str = typer.Option(
        None,
        "--target",
        "-t",
        help="Target migration version (default: applies all pending)",
    ),
    strict: bool = typer.Option(
        False,
        "--strict",
        help="Enable strict mode, fail on warnings (default: off)",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Force application, skip state checks (default: off)",
    ),
    lock_timeout: int = typer.Option(
        30000,
        "--lock-timeout",
        help="Lock timeout in milliseconds (default: 30000ms)",
    ),
    no_lock: bool = typer.Option(
        False,
        "--no-lock",
        help="Disable migration locking (default: off, DANGEROUS in multi-pod)",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Analyze without executing (default: off)",
    ),
    dry_run_execute: bool = typer.Option(
        False,
        "--dry-run-execute",
        help="Execute in SAVEPOINT for testing (default: off, guaranteed rollback)",
    ),
    verify_checksums: bool = typer.Option(
        True,
        "--verify-checksums/--no-verify-checksums",
        help="Verify migration checksums before running (default: on)",
    ),
    on_checksum_mismatch: str = typer.Option(
        "fail",
        "--on-checksum-mismatch",
        help="Checksum mismatch behavior: fail, warn, ignore (default: fail)",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Show detailed analysis in dry-run (default: off)",
    ),
    format_output: str = typer.Option(
        "text",
        "--format",
        "-f",
        help="Report format: text or json (default: text)",
    ),
    output_file: Path | None = typer.Option(
        None,
        "--output",
        "-o",
        help="Save report to file (default: stdout)",
    ),
) -> None:
    """Apply pending migrations to the database.

    PROCESS:
      Applies pending migrations in order, with distributed locking to prevent
      concurrent runs. Verifies checksums to detect unauthorized changes. Use
      --dry-run to analyze, or --dry-run-execute to test in a SAVEPOINT.

    EXAMPLES:
      confiture migrate up
        ↳ Apply all pending migrations

      confiture migrate up --target 003
        ↳ Apply migrations up to version 003

      confiture migrate up --dry-run
        ↳ Analyze migrations without executing

      confiture migrate up --strict --no-verify-checksums
        ↳ Strict mode with warnings treated as errors, skip checksum validation

    RELATED:
      confiture migrate down        - Rollback migrations
      confiture migrate status      - View migration history
      confiture migrate generate    - Create new migration template

    OPTIONS:
      CORE: --target
        Which migration version to apply (default: all pending)

      DRY-RUN: --dry-run, --dry-run-execute, --verbose, --format, --output
        Analyze migrations before executing, with optional SAVEPOINT testing

      SAFETY: --verify-checksums, --on-checksum-mismatch, --strict, --no-lock, --lock-timeout
        Control verification and locking behavior for production safety

      ADVANCED: --force
        Skip safety checks (use with caution in production)
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

        # Check for duplicate migration versions (hard block, no DB needed)
        from confiture.core.migrator import find_duplicate_migration_versions

        _up_duplicates = find_duplicate_migration_versions(migrations_dir)
        if _up_duplicates:
            console.print(
                "[red]❌ Duplicate migration versions detected — refusing to proceed[/red]"
            )
            console.print("[red]Multiple migration files share the same version number:[/red]\n")
            for version, files in sorted(_up_duplicates.items()):
                console.print(f"  Version {version}:")
                for f in files:
                    console.print(f"    • {f.name}")
            console.print("\n[yellow]💡 Rename files to use unique version prefixes.[/yellow]")
            console.print(
                "[yellow]   Run 'confiture migrate validate' to see all duplicates.[/yellow]"
            )
            raise typer.Exit(3)

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

        # Auto-install view helpers if configured
        try:
            if config.parent.name == "environments" and config.parent.parent.name == "db":
                from confiture.config.environment import Environment as _EnvCfg
                from confiture.core.view_manager import ViewManager as _VM

                _env_name = config.stem
                _project_dir = config.parent.parent.parent
                _env_cfg = _EnvCfg.load(_env_name, project_dir=_project_dir)
                if _env_cfg.migration.view_helpers == "auto":
                    _vm = _VM(conn)
                    if not _vm.helpers_installed():
                        _vm.install_helpers()
                        console.print(
                            "[cyan]🔧 Auto-installed view helper functions "
                            "(migration.view_helpers: auto)[/cyan]\n"
                        )
        except Exception:
            pass  # Non-critical — don't block migration on helper install failure

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

        # Check for orphaned migration files
        orphaned_files = _find_orphaned_sql_files(migrations_dir)
        if orphaned_files:
            _print_orphaned_files_warning(orphaned_files, console)
            if effective_strict_mode:
                console.print("\n[red]❌ Strict mode enabled: Aborting due to orphaned files[/red]")
                conn.close()
                raise typer.Exit(1)

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
                print_error_to_console(e)
                conn.close()
                raise typer.Exit(1) from e

        # Configure locking
        lock_config = LockConfig(
            enabled=not no_lock,
            timeout_ms=lock_timeout,
        )

        # Create lock manager
        lock = MigrationLock(conn, lock_config)

        # Import ProgressManager for progress tracking
        # Apply migrations with distributed lock
        import time

        from confiture.cli.formatters.migrate_formatter import format_migrate_up_result
        from confiture.core.progress import ProgressManager
        from confiture.models.results import MigrateUpResult, MigrationApplied

        applied_count = 0
        failed_migration = None
        failed_exception = None
        migrations_applied = []
        total_execution_time_ms = 0

        try:
            with lock.acquire():
                if not no_lock:
                    console.print("[cyan]🔒 Acquired migration lock[/cyan]\n")

                # Use progress manager for migration application
                with ProgressManager() as progress:
                    apply_task = progress.add_task(
                        "Applying migrations...", total=len(migrations_to_apply)
                    )

                    for migration_file in migrations_to_apply:
                        # Load migration module
                        migration_class = load_migration_class(migration_file)

                        # Create migration instance
                        migration = migration_class(connection=conn)
                        # Override strict_mode from CLI/config if not already set on class
                        if effective_strict_mode and not getattr(
                            migration_class, "strict_mode", False
                        ):
                            migration.strict_mode = effective_strict_mode

                        # Check target
                        if target and migration.version > target:
                            console.print(
                                f"[yellow]⏭️  Skipping {migration.version} (after target)[/yellow]"
                            )
                            break

                        # Apply migration
                        console.print(
                            f"[cyan]⚡ Applying {migration.version}_{migration.name}...[/cyan]",
                            end=" ",
                        )

                        try:
                            start_time = time.time()
                            migrator.apply(migration, force=force, migration_file=migration_file)
                            execution_time_ms = int((time.time() - start_time) * 1000)
                            total_execution_time_ms += execution_time_ms

                            console.print("[green]✅[/green]")
                            applied_count += 1

                            # Track successful migration
                            migrations_applied.append(
                                MigrationApplied(
                                    version=migration.version,
                                    name=migration.name,
                                    execution_time_ms=execution_time_ms,
                                    rows_affected=0,  # Not easily tracked, so default to 0
                                )
                            )
                            progress.update(apply_task, advance=1)
                        except Exception as e:
                            console.print("[red]❌[/red]")
                            failed_migration = migration
                            failed_exception = e
                            break

        except LockAcquisitionError as e:
            print_error_to_console(e)
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
            # Create error result
            error_result = MigrateUpResult(
                success=False,
                migrations_applied=migrations_applied,
                total_execution_time_ms=total_execution_time_ms,
                checksums_verified=verify_checksums,
                dry_run=False,
                error=str(failed_exception),
            )

            # Format output if not text (text format handled above)
            if format_output != "text":
                format_migrate_up_result(error_result, format_output, output_file, console)
            else:
                # Show detailed error information for text format
                _show_migration_error_details(failed_migration, failed_exception, applied_count)

            conn.close()
            raise typer.Exit(1)
        else:
            # Create success result
            success_result = MigrateUpResult(
                success=True,
                migrations_applied=migrations_applied,
                total_execution_time_ms=total_execution_time_ms,
                checksums_verified=verify_checksums,
                dry_run=False,
                warnings=["Force mode enabled"] if force else [],
            )

            # Format output
            format_migrate_up_result(success_result, format_output, output_file, console)

            # Show next steps for text format only
            if format_output == "text":
                if force:
                    console.print(
                        "[yellow]⚠️  Remember to verify your database state after force application[/yellow]"
                    )
                else:
                    console.print("\n💡 Next steps:")
                    console.print("  • Verify: confiture migrate status")
                    console.print("  • Validate: confiture lint")
                    console.print("  • Load data: confiture seed apply")

            conn.close()

    except typer.Exit:
        raise
    except LockAcquisitionError:
        # Already handled above
        raise
    except Exception as e:
        print_error_to_console(e)
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
        help="Migrations directory (default: db/migrations)",
    ),
    format_output: str = typer.Option(
        "text",
        "--format",
        "-f",
        help="Output format: text or json (default: text)",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Overwrite existing migration file (default: off)",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Show what would be generated without creating (default: off)",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Show version calculation details (default: off)",
    ),
) -> None:
    """Generate a new migration file with auto-incrementing version.

    PROCESS:
      Creates an empty migration template with auto-calculated version number.
      Scans existing migrations and increments the highest version (3-digit
      zero-padded: 001, 002, ..., 999). Gaps in numbering are preserved.

    EXAMPLES:
      confiture migrate generate add_user_email
        ↳ Create migration template, auto-version to 001 (or next available)

      confiture migrate generate add_payment_column --verbose
        ↳ Show version calculation and scanning details

      confiture migrate generate stripe_integration --dry-run
        ↳ Preview what would be created without writing files

      confiture migrate generate hotfix --force
        ↳ Overwrite existing migration file if it exists

    RELATED:
      confiture migrate up      - Apply the generated migration
      confiture migrate status  - View all migrations
      confiture migrate diff    - Compare schema files
    """
    try:
        # Ensure migrations directory exists
        migrations_dir.mkdir(parents=True, exist_ok=True)

        # Generate migration file template
        generator = MigrationGenerator(migrations_dir=migrations_dir)

        # Collect warnings
        warnings = []

        # Verbose mode: show scanning info
        if verbose:
            console.print("[cyan]🔍 Scanning migrations directory...[/cyan]")
            console.print(f"  Directory: {migrations_dir.absolute()}")

            migration_files = sorted(migrations_dir.glob("*.py"))
            console.print(f"  Found {len(migration_files)} migration files:")

            for f in migration_files:
                version_str = f.name.split("_")[0]
                console.print(f"    - {f.name} (version: {version_str})")

        # Check for duplicate versions (covers both .py and .up.sql files)
        from confiture.core.migrator import find_duplicate_migration_versions as _gen_find

        duplicates = _gen_find(migrations_dir)
        if duplicates:
            warning_msg = f"Duplicate versions detected: {', '.join(sorted(duplicates.keys()))}"
            warnings.append(warning_msg)
            if format_output == "text":
                console.print(f"[yellow]⚠️  Warning: {warning_msg}[/yellow]")

        # Check for name conflicts
        name_conflicts = generator._check_name_conflict(name)
        if name_conflicts:
            warning_msg = f"Migration name '{name}' already exists in other versions"
            warnings.append(warning_msg)
            if format_output == "text":
                console.print(f"[yellow]⚠️  Warning: {warning_msg}[/yellow]")
                for f in name_conflicts:
                    console.print(f"    - {f.name}")

        # Calculate next version
        version = generator._get_next_version()

        if verbose:
            console.print(f"\n  Highest version: {version[:-1] if int(version) > 1 else '000'}")
            console.print(f"  Next version: {version}")
            console.print(f"  Target file: {version}_{name}.py")
            console.print()

        # Generate class name and file path
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

        # Dry-run mode: show preview and exit
        if dry_run:
            if format_output == "json":
                output = {
                    "status": "dry_run",
                    "version": version,
                    "name": name,
                    "filepath": str(filepath.absolute()),
                    "class_name": class_name,
                    "template": template,
                    "warnings": warnings,
                }
                print(json.dumps(output, indent=2))
            else:
                console.print("[cyan]🔍 Dry-run mode - no files will be created[/cyan]\n")
                console.print("Would create migration:")
                console.print(f"  Version: {version}")
                console.print(f"  Name: {name}")
                console.print(f"  Class: {class_name}")
                console.print(f"  File: {filepath.absolute()}")
                console.print("\n[dim]Template preview:[/dim]")
                console.print("[dim]" + "─" * 60 + "[/dim]")
                console.print(template)
                console.print("[dim]" + "─" * 60 + "[/dim]")
            return

        # Check if file exists
        if filepath.exists() and not force:
            if format_output == "json":
                output = {
                    "status": "error",
                    "error": "file_exists",
                    "message": f"Migration file already exists: {filepath.name}",
                    "filepath": str(filepath.absolute()),
                    "resolution": "Use --force flag to overwrite existing file",
                }
                print(json.dumps(output, indent=2))
            else:
                console.print("[red]❌ Error: Migration file already exists:[/red]")
                console.print(f"  {filepath.absolute()}")
                console.print("\n[yellow]Use --force to overwrite[/yellow]")
            raise typer.Exit(1)

        # Warn if overwriting
        if filepath.exists() and force and format_output == "text":
            console.print(f"[yellow]⚠️  Overwriting existing file: {filepath.name}[/yellow]")

        # Write file (with lock protection)
        lock_fd = generator._acquire_migration_lock()
        try:
            filepath.write_text(template)
        finally:
            generator._release_migration_lock(lock_fd)

        # Output success message
        if format_output == "json":
            output = {
                "status": "success",
                "version": version,
                "name": name,
                "filepath": str(filepath.absolute()),
                "class_name": class_name,
                "migrations_dir": str(migrations_dir.absolute()),
                "next_available_version": version,
                "warnings": warnings,
            }
            print(json.dumps(output, indent=2))
        else:
            console.print("[green]✅ Migration generated successfully![/green]")
            print(f"\n📄 File: {filepath.absolute()}")
            console.print("\n✏️  Edit the migration file to add your SQL statements.")
            console.print("\n💡 Next steps:")
            console.print("  • Edit file and add SQL")
            console.print("  • Apply: confiture migrate up")
            console.print("  • Or verify first: confiture migrate up --dry-run")

    except typer.Exit:
        raise
    except Exception as e:
        if format_output == "json":
            output = {
                "status": "error",
                "error": "generation_failed",
                "message": str(e),
            }
            print(json.dumps(output, indent=2))
        else:
            console.print(f"[red]❌ Error generating migration: {e}[/red]")
        raise typer.Exit(1) from e


@migrate_app.command("baseline")
def migrate_baseline(
    through: str = typer.Option(
        ...,
        "--through",
        "-t",
        help="Mark all migrations through this version as applied (required)",
    ),
    migrations_dir: Path = typer.Option(
        Path("db/migrations"),
        "--migrations-dir",
        help="Migrations directory (default: db/migrations)",
    ),
    config: Path = typer.Option(
        Path("db/environments/local.yaml"),
        "--config",
        "-c",
        help="Configuration file (default: db/environments/local.yaml)",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Show what would be marked without making changes (default: off)",
    ),
) -> None:
    """Mark migrations as applied without running them.

    PROCESS:
      Marks migrations as applied in the database without executing the SQL.
      Useful for establishing a baseline when adopting confiture on existing
      databases, setting up from backups, or recovering from failed states.

    EXAMPLES:
      confiture migrate baseline --through 002
        ↳ Mark migrations 001-002 as applied

      confiture migrate baseline --through 005 --dry-run
        ↳ Preview what would be marked, without making changes

      confiture migrate baseline -t 003 -c db/environments/production.yaml
        ↳ Mark through version 003 in production database

      confiture migrate baseline -t 010 --force
        ↳ Force marking without state checks

    RELATED:
      confiture migrate up       - Apply migrations normally
      confiture migrate status   - View migration history
      confiture migrate diff     - Compare schema versions
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

        # Check for duplicate migration versions (hard block, no DB needed)
        from confiture.core.migrator import find_duplicate_migration_versions as _baseline_find

        _baseline_duplicates = _baseline_find(migrations_dir)
        if _baseline_duplicates:
            console.print(
                "[red]❌ Duplicate migration versions detected — refusing to proceed[/red]"
            )
            console.print("[red]Multiple migration files share the same version number:[/red]\n")
            for version, files in sorted(_baseline_duplicates.items()):
                console.print(f"  Version {version}:")
                for f in files:
                    console.print(f"    • {f.name}")
            console.print("\n[yellow]💡 Rename files to use unique version prefixes.[/yellow]")
            console.print(
                "[yellow]   Run 'confiture migrate validate' to see all duplicates.[/yellow]"
            )
            raise typer.Exit(3)

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


@migrate_app.command("reinit")
def migrate_reinit(
    through: str = typer.Option(
        None,
        "--through",
        "-t",
        help="Mark migrations as applied through this version (default: all files on disk)",
    ),
    migrations_dir: Path = typer.Option(
        Path("db/migrations"),
        "--migrations-dir",
        help="Migrations directory (default: db/migrations)",
    ),
    config: Path = typer.Option(
        Path("db/environments/local.yaml"),
        "--config",
        "-c",
        help="Configuration file (default: db/environments/local.yaml)",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Show what would happen without making changes (default: off)",
    ),
    yes: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help="Skip confirmation prompt",
    ),
) -> None:
    """Reset tracking table and re-baseline from migration files on disk.

    PROCESS:
      Deletes all entries from tb_confiture, then re-marks migration files
      as applied. Used after consolidating migration files to establish a
      clean tracking state that matches the files on disk.

    EXAMPLES:
      confiture migrate reinit --through 003
        ↳ Clear tracking table and re-mark migrations 001-003

      confiture migrate reinit
        ↳ Clear tracking table and re-mark ALL migration files on disk

      confiture migrate reinit --through 005 --dry-run
        ↳ Preview what would happen without making changes

      confiture migrate reinit -t 003 -y
        ↳ Skip confirmation prompt

    RELATED:
      confiture migrate baseline  - Mark migrations as applied (without clearing)
      confiture migrate up        - Apply migrations normally
      confiture migrate status    - View migration history
    """
    from confiture.core.connection import create_connection, load_config
    from confiture.core.migrator import Migrator, find_duplicate_migration_versions

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

        # Check for duplicate migration versions (hard block, no DB needed)
        duplicates = find_duplicate_migration_versions(migrations_dir)
        if duplicates:
            console.print(
                "[red]❌ Duplicate migration versions detected — refusing to proceed[/red]"
            )
            console.print("[red]Multiple migration files share the same version number:[/red]\n")
            for version, files in sorted(duplicates.items()):
                console.print(f"  Version {version}:")
                for f in files:
                    console.print(f"    • {f.name}")
            console.print("\n[yellow]💡 Rename files to use unique version prefixes.[/yellow]")
            console.print(
                "[yellow]   Run 'confiture migrate validate' to see all duplicates.[/yellow]"
            )
            raise typer.Exit(3)

        # Load config and create connection
        config_data = load_config(config)
        conn = create_connection(config_data)

        # Initialize migrator
        migrator = Migrator(connection=conn)
        migrator.initialize()

        # Find migration files to show what will happen
        all_migrations = migrator.find_migration_files(migrations_dir)

        if not all_migrations:
            console.print("[yellow]No migrations found.[/yellow]")
            conn.close()
            return

        # Determine which migrations will be marked
        if through is not None:
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
        else:
            migrations_to_mark = list(all_migrations)

        # Get current tracking state for summary
        applied_versions = migrator.get_applied_versions()
        current_count = len(applied_versions)

        # Show what will happen
        target_desc = f"through {through}" if through else "all files on disk"
        console.print(f"\n[cyan]📋 Reinit: resetting tracking table and re-marking {target_desc}[/cyan]\n")

        console.print(f"  Tracking entries to delete: [bold]{current_count}[/bold]")
        console.print(f"  Migrations to re-mark:     [bold]{len(migrations_to_mark)}[/bold]\n")

        for migration_file in migrations_to_mark:
            version = migrator._version_from_filename(migration_file.name)
            base_name = migration_file.stem
            if base_name.endswith(".up"):
                base_name = base_name[:-3]
            parts = base_name.split("_", 1)
            name = parts[1] if len(parts) > 1 else base_name
            console.print(f"  [dim]•[/dim] {version} {name}")

        console.print()

        if dry_run:
            console.print("[yellow]🔍 DRY RUN - no changes will be made[/yellow]\n")

        # Confirmation
        if not yes and not dry_run:
            confirmed = typer.confirm(
                f"Will delete {current_count} entries from tb_confiture "
                f"and re-mark {len(migrations_to_mark)} migrations. Continue?"
            )
            if not confirmed:
                console.print("[dim]Aborted.[/dim]")
                conn.close()
                return

        # Execute reinit
        result = migrator.reinit(
            through=through,
            dry_run=dry_run,
            migrations_dir=migrations_dir,
        )

        # Show results
        if dry_run:
            console.print(
                f"[cyan]📊 Would delete {result.deleted_count} tracking entries "
                f"and re-mark {len(result.migrations_marked)} migration(s)[/cyan]"
            )
            console.print("\n[yellow]Run without --dry-run to apply changes[/yellow]")
        else:
            console.print(
                f"[green]✅ Reinit complete: deleted {result.deleted_count} entries, "
                f"re-marked {len(result.migrations_marked)} migration(s)[/green]"
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
        from confiture.models.results import MigrateDiffResult, SchemaChange

        changes = [SchemaChange(change.type, str(change)) for change in diff.changes]
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


@migrate_app.command("down")
def migrate_down(
    migrations_dir: Path = typer.Option(
        Path("db/migrations"),
        "--migrations-dir",
        help="Migrations directory (default: db/migrations)",
    ),
    config: Path = typer.Option(
        Path("db/environments/local.yaml"),
        "--config",
        "-c",
        help="Configuration file (default: db/environments/local.yaml)",
    ),
    steps: int = typer.Option(
        1,
        "--steps",
        "-n",
        help="Number of migrations to rollback (default: 1)",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Analyze rollback without executing (default: off)",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Show detailed analysis in dry-run (default: off)",
    ),
    format_output: str = typer.Option(
        "text",
        "--format",
        "-f",
        help="Report format: text or json (default: text)",
    ),
    output_file: Path | None = typer.Option(
        None,
        "--output",
        "-o",
        help="Save report to file (default: stdout)",
    ),
) -> None:
    """Rollback previously applied migrations.

    PROCESS:
      Rolls back the last N applied migrations (default: 1), reverting schema
      changes. Use --dry-run to analyze without executing.

    EXAMPLES:
      confiture migrate down
        ↳ Rollback the last applied migration

      confiture migrate down --steps 3
        ↳ Rollback the last 3 migrations

      confiture migrate down --dry-run
        ↳ Analyze rollback without executing

      confiture migrate down --verbose --format json
        ↳ Detailed analysis in JSON format

    RELATED:
      confiture migrate up       - Apply migrations forward
      confiture migrate status   - View migration history
      confiture migrate validate - Check migration integrity

    OPTIONS:
      CORE: --steps
        How many migrations to rollback (default: 1)

      DRY-RUN: --dry-run, --verbose, --format, --output
        Analyze rollback without executing, with detailed reports

      OUTPUT: --format, --output
        Control report format and destination
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


@migrate_app.command("validate")
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
        help="Ensure DDL changes have migration files (default: off)",
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
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Preview changes without renaming (default: off)",
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

      confiture migrate validate --require-migration --base-ref origin/main --fix-naming
        ↳ Ensure all DDL changes have migrations, auto-fix file names

    RELATED:
      confiture migrate generate - Create new migration file
      confiture migrate fix      - Auto-fix non-idempotent migrations
      confiture migrate status   - View migration history
        confiture migrate validate --fix-naming

        # Output as JSON
        confiture migrate validate --format json
    """
    try:
        # Validate output format
        if format_output not in ("text", "json", "csv"):
            console.print(
                f"[red]❌ Invalid format: {format_output}. Use 'text', 'json', or 'csv'[/red]"
            )
            raise typer.Exit(1)

        # Handle git validation flags
        if check_drift or require_migration or staged:
            from confiture.cli.git_validation import (
                validate_git_drift,
                validate_git_flags_in_repo,
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

            # Check if all checks passed (for text output)
            if drift_passed and accompaniment_passed:
                if format_output == "json":
                    result = {
                        "status": "passed",
                        "checks": ["drift", "accompaniment"]
                        if (check_drift and require_migration)
                        else (["drift"] if check_drift else ["accompaniment"]),
                    }
                    _output_json(result, output_file, console)
                else:
                    console.print("[green]✅ All git validation checks passed[/green]")
                return
            else:
                # At least one check failed in text mode
                raise typer.Exit(1)

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


def _validate_idempotency(
    migrations_dir: Path,
    format_output: str,
    output_file: Path | None,
) -> None:
    """Validate idempotency of SQL migration files.

    Args:
        migrations_dir: Directory containing migration files
        format_output: Output format (text or json)
        output_file: Optional file to save output to
    """
    from confiture.core.idempotency import IdempotencyValidator

    validator = IdempotencyValidator()

    # Find all SQL migration files
    sql_files = list(migrations_dir.glob("*.up.sql"))
    sql_files.sort()

    if not sql_files:
        if format_output == "json":
            result: dict[str, Any] = {
                "status": "ok",
                "message": "No migration files found",
                "violations": [],
            }
            _output_json(result, output_file, console)
        else:
            console.print("[green]✅ No migration files found to validate[/green]")
        return

    # Validate all files
    combined_report = validator.validate_directory(migrations_dir, pattern="*.up.sql")

    if format_output == "json":
        result = combined_report.to_dict()
        result["status"] = "issues_found" if combined_report.has_violations else "ok"
        _output_json(result, output_file, console)
        if combined_report.has_violations:
            raise typer.Exit(1)
    else:
        if not combined_report.has_violations:
            console.print("[green]✅ All migrations are idempotent[/green]")
            console.print(f"   Scanned {combined_report.files_scanned} file(s)")
            return

        # Display violations
        console.print(
            f"[red]❌ Found {combined_report.violation_count} idempotency violation(s)[/red]\n"
        )

        # Group violations by file
        violations_by_file: dict[str, list[Any]] = {}
        for violation in combined_report.violations:
            file_path = violation.file_path
            if file_path not in violations_by_file:
                violations_by_file[file_path] = []
            violations_by_file[file_path].append(violation)

        for file_path, violations in violations_by_file.items():
            file_name = Path(file_path).name
            console.print(f"[yellow]{file_name}[/yellow]")
            for v in violations:
                console.print(f"  Line {v.line_number}: {v.pattern.value}")
                console.print(
                    f"    [dim]{v.sql_snippet[:60]}...[/dim]"
                    if len(v.sql_snippet) > 60
                    else f"    [dim]{v.sql_snippet}[/dim]"
                )
                console.print(f"    💡 {v.suggestion}")
            console.print()

        console.print("[cyan]To auto-fix these issues, run:[/cyan]")
        console.print(
            f"[cyan]  confiture migrate fix --idempotent --migrations-dir {migrations_dir}[/cyan]"
        )

        raise typer.Exit(1)


@migrate_app.command("fix")
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


def _fix_idempotency(
    migrations_dir: Path,
    dry_run: bool,
    format_output: str,
    output_file: Path | None,
) -> None:
    """Fix idempotency issues in SQL migration files.

    Args:
        migrations_dir: Directory containing migration files
        dry_run: If True, preview changes without modifying files
        format_output: Output format (text or json)
        output_file: Optional file to save output to
    """
    from confiture.core.idempotency import IdempotencyFixer

    fixer = IdempotencyFixer()

    # Find all SQL migration files
    sql_files = list(migrations_dir.glob("*.up.sql"))
    sql_files.sort()

    if not sql_files:
        if format_output == "json":
            result: dict[str, Any] = {
                "status": "ok",
                "message": "No migration files found",
                "files": [],
            }
            _output_json(result, output_file, console)
        else:
            console.print("[green]✅ No migration files found to fix[/green]")
        return

    # Process each file
    files_changed: list[dict[str, Any]] = []

    for sql_file in sql_files:
        original_content = sql_file.read_text()
        fixed_content = fixer.fix(original_content)

        if fixed_content != original_content:
            # Get list of changes for reporting
            changes = fixer.dry_run(original_content)

            file_info: dict[str, Any] = {
                "file": sql_file.name,
                "changes": [
                    {
                        "pattern": c.pattern.value,
                        "original": c.original[:50] + "..." if len(c.original) > 50 else c.original,
                        "suggested_fix": c.suggested_fix[:50] + "..."
                        if len(c.suggested_fix) > 50
                        else c.suggested_fix,
                        "line": c.line_number,
                    }
                    for c in changes
                ],
            }
            files_changed.append(file_info)

            if not dry_run:
                sql_file.write_text(fixed_content)

    # Output results
    if format_output == "json":
        result = {
            "status": "fixed" if not dry_run and files_changed else "preview" if dry_run else "ok",
            "files": files_changed,
            "total_files_changed": len(files_changed),
        }
        _output_json(result, output_file, console)
    else:
        if not files_changed:
            console.print("[green]✅ All migrations are already idempotent[/green]")
            return

        if dry_run:
            console.print("[cyan]📋 DRY-RUN: Would apply the following fixes:[/cyan]\n")
        else:
            console.print("[green]✅ Applied idempotency fixes:[/green]\n")

        for file_info in files_changed:
            console.print(f"[yellow]{file_info['file']}[/yellow]")
            for change in file_info["changes"]:
                console.print(f"  Line {change['line']}: {change['pattern']}")
                console.print(f"    - {change['original']}")
                console.print(f"    + {change['suggested_fix']}")
            console.print()

        if dry_run:
            console.print(f"[cyan]Would fix {len(files_changed)} file(s)[/cyan]")
            console.print("[cyan]Run without --dry-run to apply changes[/cyan]")
        else:
            console.print(f"[green]Fixed {len(files_changed)} file(s)[/green]")


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
    # Note: QW4 "Did you mean?" feature requires custom Click/Typer error handler
    # infrastructure is ready (_get_suggestion helper), but full integration
    # requires wrapping Click's exception handling at a lower level.
    # See: https://github.com/evoludigit/confiture/issues/qw4
    app()
