"""Schema commands: init, build, lint, introspect."""

from pathlib import Path

import typer

from confiture.cli.helpers import (
    _convert_linter_report,
    _output_json,
    _output_yaml,
    console,
)
from confiture.cli.lint_formatter import format_lint_report, save_report
from confiture.core.builder import SchemaBuilder
from confiture.core.connection import create_connection
from confiture.core.error_handler import handle_cli_error, print_error_to_console
from confiture.core.introspector import SchemaIntrospector
from confiture.core.linting import SchemaLinter
from confiture.core.linting.schema_linter import LintConfig as LinterConfig
from confiture.core.seed_applier import SeedApplier

# Valid output formats for linting (re-exported so main.py can keep LINT_FORMATS there)
LINT_FORMATS = ("table", "json", "csv")


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


def lint_unified(
    files: list[Path] = typer.Argument(
        default=None,
        help="SQL files or directories to lint (default: all schema files)",
    ),
    check: list[str] = typer.Option(
        None,
        "--check",
        "-c",
        help="Which checks to run: safety (squawk), format (sqlfluff), schema (SchemaLinter). "
        "Default: all.",
    ),
    git_diff: bool = typer.Option(
        False,
        "--git-diff",
        help="Only lint files changed in the current git diff (default: off)",
    ),
    env: str = typer.Option(
        "local",
        "--env",
        "-e",
        help="Environment for schema lint (default: local)",
    ),
    format_type: str = typer.Option(
        "table",
        "--format",
        "-f",
        help="Output format: table, json (default: table)",
    ),
    fail_on_error: bool = typer.Option(
        True,
        "--fail-on-error",
        help="Exit with code 1 if errors found (default: on)",
    ),
) -> None:
    """Run unified SQL lint checks (Squawk, SQLFluff, and/or SchemaLinter).

    EXAMPLES:
      confiture lint-unified db/migrations/
        Lint all SQL files in migrations directory with all available tools.

      confiture lint-unified --check safety
        Run only Squawk safety checks.

      confiture lint-unified --check schema --env local
        Run only SchemaLinter checks on the local environment.

      confiture lint-unified --git-diff
        Lint only SQL files changed in the current git diff.
    """
    from confiture.core.unified_linter import UnifiedLinter

    checks = list(check) if check else None

    # Handle schema checks separately (uses SchemaLinter)
    run_schema = checks is None or "schema" in (checks or [])
    run_tool_checks = checks is None or any(c in (checks or []) for c in ("safety", "format"))

    all_issues: list = []

    if run_tool_checks:
        linter = UnifiedLinter()
        result = linter.run(files=list(files) if files else None, checks=checks, git_diff=git_diff)
        all_issues.extend(result.issues)

    if run_schema:
        from confiture.core.linting import SchemaLinter
        from confiture.core.linting.schema_linter import LintConfig as LinterConfig
        from confiture.models.unified_lint import UnifiedLintIssue

        schema_config = LinterConfig(enabled=True, fail_on_error=fail_on_error)
        schema_linter = SchemaLinter(env=env, config=schema_config)
        try:
            linter_report = schema_linter.lint()
            for v in linter_report.errors + linter_report.warnings + linter_report.info:
                all_issues.append(
                    UnifiedLintIssue(
                        tool="schema",
                        file=env,
                        line=None,
                        message=v.message,
                        severity=v.severity,
                        rule=v.rule_name,
                    )
                )
        except Exception as e:
            console.print(f"[yellow]Schema lint skipped: {e}[/yellow]")

    from confiture.models.unified_lint import UnifiedLintResult

    unified_result = UnifiedLintResult(issues=all_issues)

    if format_type == "json":
        import json

        console.print(json.dumps(unified_result.to_dict(), indent=2))
    else:
        if not unified_result.issues:
            console.print("[green]No issues found.[/green]")
        else:
            for tool, tool_issues in unified_result.by_tool.items():
                console.print(f"\n[bold]{tool}[/bold] ({len(tool_issues)} issue(s)):")
                for issue in tool_issues:
                    sev = issue.severity.value.upper()
                    loc = f"{issue.file}:{issue.line}" if issue.line else issue.file
                    rule = f" [{issue.rule}]" if issue.rule else ""
                    console.print(f"  [{sev}]{rule} {loc}: {issue.message}")

    if fail_on_error and unified_result.has_errors:
        raise typer.Exit(1)


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
    from rich.console import Console as _Console

    # Status/error messages go to stderr so stdout stays pipe-friendly.
    _console = _Console(stderr=True)

    if format_type not in ("json", "yaml"):
        _console.print(f"[red]❌ Invalid format: {format_type!r}. Use 'json' or 'yaml'[/red]")
        raise typer.Exit(1)

    try:
        conn = create_connection(db)
    except Exception as e:
        _console.print(f"[red]❌ Connection failed: {e}[/red]")
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
        _output_yaml(data, output, _console)
    else:
        _output_json(data, output, _console)
