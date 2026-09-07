"""CLI commands for seed data validation.

These commands validate seed files for consistency and correctness.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Annotated, Any

import psycopg
import typer
from rich.console import Console
from rich.table import Table

from confiture.cli.error_json import cli_boundary, fail
from confiture.cli.formatters.seed_formatter import format_apply_result
from confiture.cli.helpers import connect, is_json
from confiture.cli.options import format_option
from confiture.cli.prep_seed_formatter import format_prep_seed_report
from confiture.config.environment import Environment
from confiture.core.progress import ProgressManager
from confiture.core.seed.applier import SeedApplier
from confiture.core.seed.bridge import SeedBridge, SeedGenerationConfig
from confiture.core.seed.insert_to_copy_converter import InsertToCopyConverter
from confiture.core.seed.performance_benchmark import PerformanceBenchmark
from confiture.core.seed.validation import SeedFixer, SeedValidator
from confiture.core.seed.validation.prep_seed import (
    OrchestrationConfig,
    PrepSeedOrchestrator,
)
from confiture.exceptions import ConfigurationError, ConfiturError, SeedError

# Create Rich console for pretty output
console = Console()

# Create seed subcommand group
seed_app = typer.Typer(
    help="Seed data validation and management",
    no_args_is_help=True,
)


# Shared option definitions for better reusability
DEFAULT_SEEDS_DIR = Path("db/seeds")
DEFAULT_COPY_THRESHOLD = 1000
DEFAULT_ENV = "local"


def _format_benchmark_output(result: Any) -> None:
    """Format and display benchmark results.

    Args:
        result: BenchmarkResult object with performance metrics
    """
    console.print("\n[bold]COPY Format Performance Benchmark[/bold]")
    console.print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    console.print(f"Total rows: {result.total_rows}")
    console.print(f"\n[yellow]VALUES format:[/yellow] {result.values_time_ms:.2f}ms")
    console.print(f"[cyan]COPY format:  [/cyan] {result.copy_time_ms:.2f}ms")
    console.print(f"[green]Speedup:      [/green] {result.speedup_factor:.1f}x faster")
    console.print(f"[green]Time saved:   [/green] {result.time_saved_ms:.2f}ms")

    if result.table_metrics:
        console.print("\n[bold]Per-Table Metrics:[/bold]")
        for table, metrics in result.table_metrics.items():
            console.print(f"  {table}: {metrics['rows']} rows")
            console.print(
                f"    VALUES: {metrics['values_time_ms']:.2f}ms, "
                f"COPY: {metrics['copy_time_ms']:.2f}ms"
            )

    console.print(f"\n[green]✓ Benchmark complete: {result.get_summary()}[/green]")


def _validate_prep_seed(
    seeds_dir: Path,
    schema_dir: Path,
    level: int,
    static_only: bool,
    full_execution: bool,
    database_url: str | None,
    format_: str,
    output: Path | None,
) -> None:
    """Handle prep-seed pattern validation."""
    # Determine max level to run
    if full_execution:
        max_level = 5
    elif static_only:
        max_level = 3
    else:
        max_level = level

    # Validate database_url requirement
    if max_level >= 4 and not database_url:
        fail(
            ConfigurationError(
                "Database URL required for levels 4-5. Use --database-url or --static-only.",
                error_code="CONFIG_010",
            ),
            json_mode=is_json(format_),
            output_file=output,
        )

    # Create orchestrator config
    config = OrchestrationConfig(
        max_level=max_level,
        seeds_dir=seeds_dir,
        schema_dir=schema_dir,
        database_url=database_url,
        stop_on_critical=True,
        show_progress=True,
    )

    # Run orchestrator
    try:
        orchestrator = PrepSeedOrchestrator(config)
        report = orchestrator.run()

        # For JSON format, bypass Rich console to avoid color codes
        if format_ == "json":
            report_dict = report.to_dict()
            json_output = json.dumps(report_dict, indent=2)

            if output:
                output.write_text(json_output)
                console.print(f"[green]✓ Report saved to {output}[/green]")
            else:
                # Use print() directly to avoid Rich color codes

                print(json_output, file=sys.stdout)
        else:
            # Use formatter for text and CSV
            format_prep_seed_report(report, format_, output, console)

        # Exit with appropriate code
        if report.has_violations:
            raise typer.Exit(1)  # success-signal: validation found violations
        else:
            raise typer.Exit(0)  # success-signal: clean

    except typer.Exit:
        raise
    # Reason: seed validate's --output is its report path; the boundary cannot know that, so it routes the envelope itself
    except Exception as e:
        fail(e, json_mode=is_json(format_), output_file=output)


SeedsDirOpt = Annotated[
    Path, typer.Option("--seeds-dir", help="Directory containing seed files (default: db/seeds)")
]
EnvOpt = Annotated[
    str | None,
    typer.Option("--env", help="Environment name for multi-env validation (default: none)"),
]
AllEnvsOpt = Annotated[bool, typer.Option("--all", help="Validate all environments (default: off)")]
DatabaseUrlOpt = Annotated[
    str | None,
    typer.Option(
        "--database-url", help="Database URL for database mode validation (default: none)"
    ),
]
OutputOpt = Annotated[
    Path | None, typer.Option("--output", help="Output file path (default: stdout)")
]
FixOpt = Annotated[
    bool, typer.Option("--fix", help="Automatically fix issues where possible (default: off)")
]
DryRunOpt = Annotated[
    bool,
    typer.Option("--dry-run", help="Show what would be fixed without modifying (default: off)"),
]
PrepSeedOpt = Annotated[
    bool, typer.Option("--prep-seed", help="Enable prep-seed pattern validation (default: off)")
]
PrepSeedLevelOpt = Annotated[
    int,
    typer.Option("--level", "-l", help="Prep-seed validation level 1-5 (default: 3)", min=1, max=5),
]
StaticOnlyOpt = Annotated[
    bool, typer.Option("--static-only", help="Run only Levels 1-3, no database (default: off)")
]
FullExecutionOpt = Annotated[
    bool,
    typer.Option("--full-execution", help="Run all levels 1-5, requires database (default: off)"),
]


def _seed_dirs_to_validate(
    seeds_dir: Path, *, env: str | None, all_envs: bool, json_mode: bool, output: Path | None
) -> list[tuple[Path, str]]:
    """The ``(directory, environment)`` pairs ``seed validate`` scans; exit 5 when none exists."""
    dirs_to_validate: list[tuple[Path, str]] = []
    if all_envs:
        # Validate all environment seed directories
        env_dir = Path("db/environments")
        if env_dir.exists():
            for env_file in env_dir.glob("*.yaml"):
                env_name = env_file.stem
                env_seeds = Path("db/seeds") / env_name
                if env_seeds.exists():
                    dirs_to_validate.append((env_seeds, env_name))
    elif env:
        # Validate specific environment
        env_seeds = Path("db/seeds") / env
        if env_seeds.exists():
            dirs_to_validate.append((env_seeds, env))
        else:
            fail(
                ConfigurationError(
                    f"Environment seeds not found: {env_seeds}",
                    error_code="CONFIG_004",
                ),
                json_mode=json_mode,
                output_file=output,
            )
    # Validate provided directory
    elif seeds_dir.exists():
        dirs_to_validate.append((seeds_dir, "default"))
    else:
        fail(
            ConfigurationError(
                f"Seeds directory not found: {seeds_dir}",
                error_code="CONFIG_004",
            ),
            json_mode=json_mode,
            output_file=output,
        )
    return dirs_to_validate


def _fix_seed_files(scanned_files: list[str], *, dry_run: bool) -> None:
    """``--fix``: rewrite each scanned file, or say what would change under ``--dry-run``."""
    fixer = SeedFixer()
    for file_path in scanned_files:
        fix_result = fixer.fix_file(Path(file_path), dry_run=dry_run)
        if fix_result.fixes_applied > 0:
            if dry_run:
                console.print(
                    f"[yellow]~ Would fix {fix_result.fixes_applied} issues in {file_path}[/yellow]"
                )
            else:
                console.print(
                    f"[green]✓ Fixed {fix_result.fixes_applied} issues in {file_path}[/green]"
                )


def _render_seed_validation(
    all_violations: list[Any], all_files: list[str], *, format_: str, output: Path | None
) -> None:
    """The validation report: JSON (to ``output`` when given) or the text table."""
    if format_ == "json":
        report_dict = {
            "violations": [v.to_dict() for v in all_violations],
            "violation_count": len(all_violations),
            "files_scanned": len(all_files),
            "has_violations": len(all_violations) > 0,
        }
        json_output = json.dumps(report_dict, indent=2)

        if output:
            output.write_text(json_output)
            console.print(f"[green]✓ Report saved to {output}[/green]")
        else:
            console.print(json_output)
        return

    # Text format (default)
    console.print("\nSeed Validation Report")
    console.print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    console.print(f"Files scanned: {len(all_files)}")
    console.print(f"Violations found: {len(all_violations)}")

    if all_violations:
        console.print("\n[red]Issues found:[/red]")
        table = Table(show_header=True, header_style="bold")
        table.add_column("File", style="cyan")
        table.add_column("Line", style="magenta")
        table.add_column("Issue", style="yellow")
        table.add_column("Suggestion", style="green")

        for violation in sorted(all_violations, key=lambda v: (v.file_path, v.line_number)):
            table.add_row(
                violation.file_path,
                str(violation.line_number),
                violation.pattern.name,
                violation.suggestion,
            )

        console.print(table)
    else:
        console.print("[green]✓ All seed files are valid![/green]")
        console.print("\n💡 Next steps:")
        console.print("  • Load data: confiture seed apply")
        console.print("  • Show performance: confiture seed benchmark")
        console.print("  • Convert format: confiture seed convert")


@seed_app.command("validate")
@cli_boundary
def validate(
    seeds_dir: SeedsDirOpt = Path("db/seeds"),
    env: EnvOpt = None,
    all_envs: AllEnvsOpt = False,
    database_url: DatabaseUrlOpt = None,
    format_: str = format_option("text", "json", "csv"),
    output: OutputOpt = None,
    fix: FixOpt = False,
    dry_run: DryRunOpt = False,
    prep_seed: PrepSeedOpt = False,
    prep_seed_level: PrepSeedLevelOpt = 3,
    static_only: StaticOnlyOpt = False,
    full_execution: FullExecutionOpt = False,
) -> None:
    """Validate seed files for data consistency and quality.

    PROCESS:
      Checks for common issues (double semicolons, DDL statements, missing ON
      CONFLICT). Optionally validates prep-seed transformations (5 validation
      levels). Supports auto-fix for common issues.

    EXAMPLES:
      confiture seed validate
        ↳ Validate default seed directory (no database needed)

      confiture seed validate --prep-seed --database-url postgresql://localhost/mydb
        ↳ Validate with database checks for schema compatibility

      confiture seed validate --fix --dry-run
        ↳ Preview what would be fixed (e.g., add ON CONFLICT clauses)

      confiture seed validate --prep-seed --static-only
        ↳ Pre-commit safe: validate UUID transformations Levels 1-3

      confiture seed validate --prep-seed --full-execution --database-url postgresql://localhost/test
        ↳ Full validation: all 5 levels including runtime execution

    RELATED COMMANDS:
      confiture seed apply     - Load seeds into database
      confiture seed convert   - Transform INSERT to COPY format
      confiture seed benchmark - Compare VALUES vs COPY performance
      confiture build          - Build schema with optional validation

    DOCUMENTATION:
      📖 Seed Validation: docs/guides/seed-validation.md
      📖 COPY Format: docs/guides/copy-format-loading.md
      📖 Decision Tree: docs/guides/seed-loading-decision-tree.md

    OPTIONS:
      CORE: --seeds-dir, --format, --output
        What to validate, how to validate, and how to report

      PREP-SEED: --prep-seed, --level, --static-only, --full-execution
        Enable prep-seed pattern validation with 5 validation levels

      AUTO-FIX: --fix, --dry-run
        Automatically fix detected issues (with dry-run preview)

      ADVANCED: --env, --all-envs, --database-url
        Multi-environment validation
    """
    try:
        # Handle prep-seed validation if requested
        if prep_seed:
            return _validate_prep_seed(
                seeds_dir=seeds_dir,
                schema_dir=Path("db/schema"),
                level=prep_seed_level,
                static_only=static_only,
                full_execution=full_execution,
                database_url=database_url,
                format_=format_,
                output=output,
            )

        dirs_to_validate = _seed_dirs_to_validate(
            seeds_dir, env=env, all_envs=all_envs, json_mode=is_json(format_), output=output
        )

        validator = SeedValidator()
        all_violations: list[Any] = []
        all_files: list[str] = []
        for dir_path, _env_name in dirs_to_validate:
            report = validator.validate_directory(dir_path, recursive=True)
            all_violations.extend(report.violations)
            all_files.extend(report.scanned_files)
            if fix:
                _fix_seed_files(report.scanned_files, dry_run=dry_run)

        _render_seed_validation(all_violations, all_files, format_=format_, output=output)

        # Exit with appropriate code
        if all_violations:
            raise typer.Exit(1)  # success-signal: validation found violations
        else:
            raise typer.Exit(0)  # success-signal: clean

    except typer.Exit:
        raise
    # Reason: seed validate's --output is its report path; the boundary cannot know that, so it routes the envelope itself
    except Exception as e:
        fail(e, json_mode=is_json(format_), output_file=output)


ApplyEnvOpt = Annotated[
    str, typer.Option("--env", help="Environment name for database URL lookup (default: local)")
]
SequentialOpt = Annotated[
    bool,
    typer.Option("--sequential", help="Apply files sequentially, solves 650+ row parser limits"),
]
ContinueOnErrorOpt = Annotated[
    bool,
    typer.Option(
        "--continue-on-error", help="Continue if file fails (--sequential only, useful for CI/CD)"
    ),
]
ApplyDatabaseUrlOpt = Annotated[
    str | None, typer.Option("--database-url", help="Database URL (overrides environment config)")
]
CopyFormatOpt = Annotated[
    bool, typer.Option("--copy-format", help="Use COPY format (2-10x faster for large datasets)")
]
CopyThresholdOpt = Annotated[
    int,
    typer.Option(
        "--copy-threshold",
        help=f"Row threshold for auto COPY (default: {DEFAULT_COPY_THRESHOLD}, use >1000 rows)",
    ),
]
ReportOutputOpt = Annotated[
    Path | None,
    typer.Option(
        "--output",
        "-o",
        "--report",
        help="Save structured output (JSON/CSV) to file. --report is a "
        "back-compat alias for --output/-o (DOCS-M2).",
    ),
]
ProfileOpt = Annotated[
    str | None,
    typer.Option(
        "--profile", help="Apply only the named seed profile (seed.profiles.<name> in env config)."
    ),
]


@seed_app.command("apply")
@cli_boundary
def apply(
    seeds_dir: SeedsDirOpt = DEFAULT_SEEDS_DIR,
    env: ApplyEnvOpt = DEFAULT_ENV,
    sequential: SequentialOpt = False,
    continue_on_error: ContinueOnErrorOpt = False,
    database_url: ApplyDatabaseUrlOpt = None,
    copy_format: CopyFormatOpt = False,
    copy_threshold: CopyThresholdOpt = DEFAULT_COPY_THRESHOLD,
    format_type: str = format_option("text", "json", "csv"),
    report_output: ReportOutputOpt = None,
    profile: ProfileOpt = None,
) -> None:
    """Load seed data into the database.

    PROCESS:
      Applies seed files with optional sequential execution and COPY format.
      Sequential mode solves PostgreSQL's 650+ row parser limit. COPY format
      provides 2-10x faster loading for large datasets.

    COMMON USAGE:

      📌 Development (small seeds < 5K rows):
        confiture seed apply --env local --sequential

      ⚡ Testing (large seeds > 50K rows):
        confiture seed apply --sequential --copy-format --env test

      🚀 CI/CD (maximum speed):
        confiture seed apply --sequential --copy-format --continue-on-error

    PERFORMANCE TIPS:
      • Use --sequential if any file has 650+ rows
      • Use --copy-format if total rows > 50,000
      • Use `confiture seed benchmark` to compare VALUES vs COPY

    RELATED COMMANDS:
      confiture seed validate   - Check seed data quality
      confiture seed convert    - Transform INSERT to COPY format
      confiture seed benchmark  - Compare VALUES vs COPY performance
      confiture build           - Build schema, optionally apply seeds

    DOCUMENTATION:
      📖 COPY Format Guide: docs/guides/copy-format-loading.md
      📖 Decision Tree: docs/guides/seed-loading-decision-tree.md
      📖 Examples: docs/guides/copy-format-examples.md

    OPTIONS:
      EXECUTION: --sequential, --continue-on-error
        Mode and error handling (sequential for 650+ rows)

      DATABASE: --env, --database-url
        Connection parameters (URL overrides environment)

      PERFORMANCE: --copy-format, --copy-threshold
        Format selection (2-10x faster for >50K rows)

      OUTPUT: --format, --report
        Structured results (JSON/CSV for automation)
    """
    if not sequential:
        console.print("[yellow]ℹ Use --sequential for files with 500+ rows[/yellow]")
        console.print("[yellow]  confiture seed apply --sequential --env {env}[/yellow]")
        raise typer.Exit(0)  # success-signal: advisory, nothing applied

    # Verify seeds directory exists
    if not seeds_dir.exists():
        fail(
            ConfigurationError(
                f"Seeds directory not found: {seeds_dir}",
                error_code="CONFIG_004",
            ),
            json_mode=is_json(format_type),
            output_file=report_output,
        )

    # Resolve a named seed profile (before connecting): unknown → exit 5.
    seed_profile = None
    if profile is not None:
        seed_profile = Environment.load(env).seed.get_profile(profile)

    seed_settings = None
    # Get database connection
    if database_url:
        # Use provided URL directly

        try:
            connection = connect(database_url)
        except (ConfiturError, psycopg.Error) as e:
            fail(
                ConfigurationError(
                    f"Failed to connect to database: {e}",
                    error_code="CONFIG_006",
                ),
                json_mode=is_json(format_type),
                output_file=report_output,
            )
    else:
        # Load from environment config
        try:
            env_config = Environment.load(env)
            seed_settings = env_config.seed

            connection = connect(env_config.database_url)
        except (ConfiturError, psycopg.Error, OSError) as e:
            fail(
                ConfigurationError(
                    f"Failed to load environment {env}: {e}",
                    error_code="CONFIG_006",
                ),
                json_mode=is_json(format_type),
                output_file=report_output,
            )

    # Apply seeds sequentially
    try:
        # Import ProgressManager for progress tracking

        applier = SeedApplier(
            seeds_dir=seeds_dir,
            env=env,
            connection=connection,
            console=console,
            copy_format=copy_format,
            copy_threshold=copy_threshold,
        )

        # Use progress manager for seed application
        with ProgressManager() as progress:
            continue_on_error = continue_on_error or bool(
                seed_settings and seed_settings.continue_on_error
            )
            result = applier.apply_sequential(
                continue_on_error=continue_on_error,
                progress=progress,
                profile=seed_profile,
                transaction_mode=seed_settings.transaction_mode if seed_settings else "savepoint",
            )
        result.seed_profile = profile

        # Format output

        format_apply_result(result, format_type, report_output, console)

        # Close connection
        connection.close()

        # Exit with error if files failed and not continuing
        if result.failed > 0 and not continue_on_error:
            raise typer.Exit(1)  # success-signal: some seed files failed

        raise typer.Exit(0)  # success-signal: all applied

    except typer.Exit:
        connection.close()
        raise
    # Reason: seed application runs user SQL; any failure is a SeedError with context, connection closed
    except Exception as e:
        connection.close()
        fail(
            SeedError(f"Seed application failed: {e}"),
            json_mode=is_json(format_type),
            output_file=report_output,
        )


@seed_app.command("convert")
@cli_boundary
def convert(
    input_file: Path = typer.Option(
        ...,
        "--input",
        help="Input file with INSERT statements (required)",
    ),
    output_file: Path | None = typer.Option(
        None,
        "--output",
        help="Output file for COPY format (default: stdout)",
    ),
    batch: bool = typer.Option(
        False,
        "--batch",
        help="Process all .sql files in directory (requires --output)",
    ),
) -> None:
    """Transform INSERT statements to COPY format (2-10x faster).

    PROCESS:
      Converts PostgreSQL INSERT statements to native COPY format for
      dramatically faster bulk loading. Gracefully skips unconvertible
      patterns (functions, subqueries) with clear error messages.

    COMMON USAGE:

      📌 Single file conversion:
        confiture seed convert --input seeds.sql --output seeds_copy.sql

      📁 Batch directory conversion:
        confiture seed convert --input db/seeds --batch --output db/seeds_copy

      🔍 Preview conversion (stdout):
        confiture seed convert --input seeds.sql | head -20

    HOW IT WORKS:
      ✓ Parses INSERT statements using SQLglot AST parser
      ✓ Validates data compatibility with COPY format
      ✓ Converts to tab-delimited COPY format with proper escaping
      ✓ Gracefully skips unconvertible patterns

    SPEED IMPROVEMENT:
      • 2x faster: Small datasets (5K rows)
      • 5x faster: Medium datasets (50K rows)
      • 10x faster: Large datasets (500K+ rows)

    RELATED COMMANDS:
      confiture seed apply     - Load seeds with COPY format
      confiture seed validate  - Check seed data quality
      confiture seed benchmark - Show performance comparison

    DOCUMENTATION:
      📖 COPY Format Guide: docs/guides/copy-format-loading.md
      📖 Decision Tree: docs/guides/seed-loading-decision-tree.md
      📖 Examples: docs/guides/copy-format-examples.md

    EXAMPLES:

      Convert single file to COPY format:
        $ confiture seed convert --input db/seeds/users.sql --output db/seeds/users_copy.sql
        ✓ Converted to COPY format
          Input: db/seeds/users.sql
          Output: db/seeds/users_copy.sql
          Rows: 1,234

      Batch convert directory:
        $ confiture seed convert --input db/seeds --batch --output db/seeds_copy
        Processing 4 files...
        users.sql       ✓ Converted     1,234 rows
        posts.sql       ✓ Converted     5,678 rows
        complex.sql     ⚠ Skipped       Has CTEs
        Summary: 2/3 files converted (67%)

    OPTIONS:
      INPUT: --input (required)
        Single file or directory path

      OUTPUT: --output
        Destination file/directory (required for --batch)

      MODE: --batch
        Process all .sql files in input directory
    """
    try:
        # These guards raise ConfiturError (not fail() directly) so the type
        # checker narrows output_file past the --output requirement; the outer
        # handler routes them through fail() with their own registry codes.
        if not input_file.exists():
            raise ConfigurationError(
                f"Input file/directory not found: {input_file}",
                error_code="CONFIG_004",
            )

        converter = InsertToCopyConverter()

        # Batch mode: process all files in directory
        if batch:
            if not input_file.is_dir():
                raise ConfigurationError("For --batch mode, input must be a directory.")

            if not output_file:
                raise ConfigurationError("For --batch mode, --output is required.")

            # Create output directory if it doesn't exist
            output_file.mkdir(parents=True, exist_ok=True)

            # Find all .sql files
            sql_files = sorted(input_file.glob("*.sql"))
            if not sql_files:
                console.print(f"[yellow]⚠ No .sql files found in {input_file}[/yellow]")
                raise typer.Exit(0)

            console.print(f"[bold]Processing {len(sql_files)} files...[/bold]\n")

            # Process each file
            files_content = {str(f.relative_to(input_file)): f.read_text() for f in sql_files}
            report = converter.convert_batch(files_content)

            # Display results
            table = Table(title="Conversion Results")
            table.add_column("File", style="cyan")
            table.add_column("Status", style="green")
            table.add_column("Rows/Reason", style="yellow")

            for result in report.results:
                if result.success:
                    table.add_row(
                        result.file_path,
                        "[green]✓ Converted[/green]",
                        str(result.rows_converted),
                    )
                    # Write converted file
                    out_path = output_file / result.file_path
                    out_path.parent.mkdir(parents=True, exist_ok=True)
                    out_path.write_text(result.copy_format)
                else:
                    table.add_row(
                        result.file_path,
                        "[yellow]⚠ Skipped[/yellow]",
                        result.reason,
                    )

            console.print(table)
            console.print("\n[bold]Summary:[/bold]")
            console.print(f"  Total: {report.total_files} files")
            console.print(f"  [green]Converted: {report.successful}[/green]")
            console.print(f"  [yellow]Skipped: {report.failed}[/yellow]")
            console.print(f"  Success rate: {report.success_rate:.1f}%")

            if report.successful > 0:
                console.print(f"\n[green]✓ Results saved to: {output_file}[/green]")

            raise typer.Exit(0)

        # Single file mode
        sql_content = input_file.read_text()
        result = converter.try_convert(sql_content, file_path=str(input_file))

        # Handle conversion result
        if not result.success:
            console.print(f"[yellow]⚠ Cannot convert {input_file}[/yellow]")
            console.print(f"  Reason: {result.reason}")
            console.print(
                "\n[dim]Tip: This INSERT statement uses SQL features that\n"
                "cannot be converted to COPY format. You can still use\n"
                "the original INSERT format for this file.[/dim]"
            )
            raise typer.Exit(1)

        # Output result
        if output_file:
            output_file.write_text(result.copy_format)
            console.print("[green]✓ Converted to COPY format[/green]")
            console.print(f"  Input: {input_file}")
            console.print(f"  Output: {output_file}")
            console.print(f"  Rows: {result.rows_converted}")
        else:
            sys.stdout.write(result.copy_format or "")

        raise typer.Exit(0)

    except typer.Exit:
        raise
    except ConfiturError as e:
        fail(e, json_mode=False)
    # Reason: text-only command: the message names the operation that failed, whatever failed
    except Exception as e:
        fail(SeedError(f"Conversion failed: {e!s}"), json_mode=False)


@seed_app.command("benchmark")
@cli_boundary
def benchmark(
    seeds_dir: Path = typer.Option(
        DEFAULT_SEEDS_DIR,
        "--seeds-dir",
        help="Directory containing seed files (default: db/seeds)",
    ),
) -> None:
    """Compare VALUES vs COPY format performance.

    PROCESS:
      Analyzes seed files and benchmarks loading performance in both formats.
      Shows estimated speedup, time savings, and per-table metrics to help
      optimize seed data loading strategy.

    WHEN TO USE:
      ✓ Deciding between VALUES and COPY format
      ✓ Estimating time savings from conversion
      ✓ Analyzing per-table performance
      ✓ Optimizing CI/CD pipeline speed

    EXAMPLE OUTPUT:
      COPY Format Performance Benchmark
      ════════════════════════════════════
      Total rows: 120,000

      VALUES format:  12.5s
      COPY format:    1.3s
      Speedup:        9.6x faster
      Time saved:     11.2s

      Per-Table Metrics:
        users (2,000 rows):      0.08s → 0.01s (8.0x)
        products (15,000 rows):  0.45s → 0.04s (11.2x)
        orders (103,000 rows):   11.97s → 1.26s (9.5x)

    NEXT STEPS:
      If speedup >= 5x:
        confiture seed apply --sequential --copy-format

      If speedup < 5x:
        confiture seed apply --sequential
        (VALUES format is fast enough)

    RELATED COMMANDS:
      confiture seed apply   - Load seeds with --copy-format
      confiture seed convert - Transform INSERT to COPY format
      confiture build        - Build schema with optional seed apply

    DOCUMENTATION:
      📖 COPY Format Guide: docs/guides/copy-format-loading.md
      📖 Decision Tree: docs/guides/seed-loading-decision-tree.md
      📖 Examples: docs/guides/copy-format-examples.md

    USAGE:
      Basic benchmark:
        $ confiture seed benchmark

      Specific directory:
        $ confiture seed benchmark --seeds-dir db/seeds/test

      With apply (simultaneous benchmark):
        $ confiture seed apply --sequential --benchmark
    """
    try:
        if not seeds_dir.exists():
            fail(
                ConfigurationError(
                    f"Seeds directory not found: {seeds_dir}",
                    error_code="CONFIG_004",
                ),
                json_mode=False,
            )

        # Collect seed data
        seed_data: dict[str, list[dict]] = {}

        for seed_file in sorted(seeds_dir.glob("*.sql")):
            console.print(f"[blue]Analyzing {seed_file.name}...[/blue]")
            # Basic parsing - just count lines as a proxy for row count
            content = seed_file.read_text()
            line_count = len(content.split("\n"))
            seed_data[seed_file.stem] = [{"row": i} for i in range(line_count)]

        if not seed_data:
            console.print("[yellow]No seed files found[/yellow]")
            raise typer.Exit(0)

        # Run benchmark
        benchmark_runner = PerformanceBenchmark()
        result = asyncio.run(benchmark_runner.compare(seed_data))

        # Display results using helper
        _format_benchmark_output(result)
        raise typer.Exit(0)  # success-signal: benchmark complete

    except typer.Exit:
        raise
    # Reason: text-only command: the message names the operation that failed, whatever failed
    except Exception as e:
        fail(SeedError(f"Benchmark failed: {e}"), json_mode=False)


@seed_app.command("generate")
@cli_boundary
def seed_generate(
    table: str = typer.Argument(..., help="Table name to generate seed data for"),
    database_url: str = typer.Option(..., "--database-url", "-d", help="PostgreSQL connection URL"),
    schema: str = typer.Option("public", "--schema", "-s", help="Schema name (default: public)"),
    env: str = typer.Option("development", "--env", "-e", help="Seed environment directory"),
    output_dir: Path = typer.Option(
        Path("db/seeds"), "--output-dir", "-o", help="Seeds output directory (default: db/seeds)"
    ),
    row_count: int = typer.Option(10, "--rows", "-n", help="Number of stub rows (default: 10)"),
    overwrite: bool = typer.Option(
        False, "--overwrite", help="Overwrite existing seed file (default: off)"
    ),
    format_type: str = format_option("text", "json"),
) -> None:
    """Generate a seed SQL stub for a PostgreSQL table.

    Connects to the database, introspects the table's column structure,
    and writes a commented-out INSERT template to db/seeds/<env>/<table>.sql.

    EXAMPLES:
      confiture seed generate users --database-url $DATABASE_URL
        ↳ Generate seed stub for the users table

      confiture seed generate bookings -d $DATABASE_URL --rows 5 --env test
        ↳ Generate 5-row stub for bookings in the test environment
    """

    config = SeedGenerationConfig(
        table=table,
        schema=schema,
        row_count=row_count,
        output_dir=output_dir,
        env=env,
        overwrite=overwrite,
    )

    bridge = SeedBridge(database_url)

    try:
        result = bridge.generate(config)
    # Reason: seed generation reaches the database and the file system; any failure is a SeedError
    except Exception as e:
        fail(
            SeedError(f"Seed generation failed: {e}"),
            json_mode=is_json(format_type),
        )

    if format_type == "json":
        console.print(json.dumps(result.to_dict(), indent=2))
    elif result.success:
        console.print(f"[green]Seed stub generated: {result.output_path}[/green]")
        console.print(
            f"[dim]{result.column_count} column(s), {result.row_count} stub row(s).[/dim]"
        )
    else:
        console.print(f"[red]Error: {result.error}[/red]")
        raise typer.Exit(1)
