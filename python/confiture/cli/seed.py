"""CLI commands for seed data validation.

These commands validate seed files for consistency and correctness.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.table import Table

from confiture.cli.prep_seed_formatter import format_prep_seed_report
from confiture.core.seed_applier import SeedApplier
from confiture.core.seed_validation import SeedFixer, SeedValidator
from confiture.core.seed_validation.prep_seed import (
    OrchestrationConfig,
    PrepSeedOrchestrator,
)

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


def _format_benchmark_output(result: Any) -> None:  # type: ignore[no-untyped-def]
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
    fix: bool,
    dry_run: bool,
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
        console.print(
            "[red]✗ Database URL required for levels 4-5. Use --database-url or --static-only[/red]"
        )
        raise typer.Exit(2)

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
                import sys

                print(json_output, file=sys.stdout)
        else:
            # Use formatter for text and CSV
            format_prep_seed_report(report, format_, output, console)

        # Exit with appropriate code
        if report.has_violations:
            raise typer.Exit(1)
        else:
            raise typer.Exit(0)

    except typer.Exit:
        raise
    except Exception as e:
        console.print(f"[red]✗ Prep-seed validation error: {e}[/red]")
        raise typer.Exit(2) from e


@seed_app.command("validate")
def validate(
    seeds_dir: Path = typer.Option(
        Path("db/seeds"),
        "--seeds-dir",
        help="Directory containing seed files",
    ),
    env: str | None = typer.Option(
        None,
        "--env",
        help="Environment name for multi-env validation",
    ),
    all_envs: bool = typer.Option(
        False,
        "--all",
        help="Validate all environments",
    ),
    mode: str = typer.Option(
        "static",
        "--mode",
        help="Validation mode: static or database",
    ),
    database_url: str | None = typer.Option(
        None,
        "--database-url",
        help="Database URL for database mode validation",
    ),
    format_: str = typer.Option(
        "text",
        "--format",
        help="Output format: text, json, or csv",
    ),
    output: Path | None = typer.Option(
        None,
        "--output",
        help="Output file path (default: stdout)",
    ),
    fix: bool = typer.Option(
        False,
        "--fix",
        help="Automatically fix issues (where possible)",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Show what would be fixed without modifying files",
    ),
    prep_seed: bool = typer.Option(
        False,
        "--prep-seed",
        help="Enable prep-seed pattern validation (UUID->BIGINT transformations)",
    ),
    prep_seed_level: int = typer.Option(
        3,
        "--level",
        "-l",
        help="Prep-seed validation level: 1-5 (1=files, 2=schema, 3=resolvers, 4=runtime, 5=execution)",
        min=1,
        max=5,
    ),
    static_only: bool = typer.Option(
        False,
        "--static-only",
        help="Run only prep-seed Levels 1-3 (no database, pre-commit safe)",
    ),
    full_execution: bool = typer.Option(
        False,
        "--full-execution",
        help="Run all prep-seed levels 1-5 (requires database)",
    ),
    uuid_validation: bool = typer.Option(
        False,
        "--uuid-validation",
        help="Enable seed enumerated UUID pattern validation (Phase 10)",
    ),
) -> None:
    """Validate seed files for data consistency.

    This command checks seed files for common issues like:
    - Double semicolons (;;)
    - DDL statements (CREATE/ALTER/DROP) in seed files
    - Missing ON CONFLICT clauses

    With --prep-seed, validates UUID→BIGINT transformation patterns (5 levels).
    With --uuid-validation, validates seed enumerated UUID patterns (Phase 10).

    Examples:
        # Validate default seed directory
        confiture seed validate

        # Validate specific directory
        confiture seed validate --seeds-dir db/seeds/test

        # Validate with database checks
        confiture seed validate --mode database --database-url postgresql://localhost/mydb

        # Auto-fix issues (add ON CONFLICT clauses)
        confiture seed validate --fix

        # Preview fixes without modifying files
        confiture seed validate --fix --dry-run

        # Output as JSON
        confiture seed validate --format json --output report.json

        # UUID validation (seed enumerated patterns)
        confiture seed validate --uuid-validation

        # Prep-seed validation (pre-commit safe, Levels 1-3)
        confiture seed validate --prep-seed --static-only

        # Prep-seed validation (full, Levels 1-5)
        confiture seed validate --prep-seed --full-execution --database-url postgresql://localhost/test
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
                fix=fix,
                dry_run=dry_run,
            )

        # Handle UUID validation if requested
        if uuid_validation:
            console.print("[blue]ℹ Phase 10: UUID Validation Support[/blue]")
            console.print("  UUID validation is available via Level 1 of prep-seed validation.")
            console.print("  Use: confiture seed validate --prep-seed --static-only")
            raise typer.Exit(0)

        # Determine which directories to validate
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
                console.print(f"[red]✗ Environment seeds not found: {env_seeds}[/red]")
                raise typer.Exit(2)
        else:
            # Validate provided directory
            if seeds_dir.exists():
                dirs_to_validate.append((seeds_dir, "default"))
            else:
                console.print(f"[red]✗ Seeds directory not found: {seeds_dir}[/red]")
                raise typer.Exit(2)

        # Create validator
        validator = SeedValidator()

        # Collect all reports
        all_violations = []
        all_files = []

        for dir_path, _env_name in dirs_to_validate:
            report = validator.validate_directory(dir_path, recursive=True)
            all_violations.extend(report.violations)
            all_files.extend(report.scanned_files)

            # Auto-fix if requested
            if fix:
                fixer = SeedFixer()
                for file_path in report.scanned_files:
                    file_path_obj = Path(file_path)
                    fix_result = fixer.fix_file(file_path_obj, dry_run=dry_run)
                    if fix_result.fixes_applied > 0:
                        if dry_run:
                            console.print(
                                f"[yellow]~ Would fix {fix_result.fixes_applied} issues in {file_path}[/yellow]"
                            )
                        else:
                            console.print(
                                f"[green]✓ Fixed {fix_result.fixes_applied} issues in {file_path}[/green]"
                            )

        # Output report
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
        else:
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

        # Exit with appropriate code
        if all_violations:
            raise typer.Exit(1)
        else:
            raise typer.Exit(0)

    except typer.Exit:
        raise
    except Exception as e:
        console.print(f"[red]✗ Error during validation: {e}[/red]")
        raise typer.Exit(2) from e


@seed_app.command("apply")
def apply(
    seeds_dir: Path = typer.Option(
        DEFAULT_SEEDS_DIR,
        "--seeds-dir",
        help="Directory containing seed files",
    ),
    env: str = typer.Option(
        DEFAULT_ENV,
        "--env",
        help="Environment name (for context and database URL lookup)",
    ),
    sequential: bool = typer.Option(
        False,
        "--sequential",
        help="Apply files sequentially instead of concatenating (solves parser limits)",
    ),
    continue_on_error: bool = typer.Option(
        False,
        "--continue-on-error",
        help="Continue applying remaining files if one fails",
    ),
    database_url: str | None = typer.Option(
        None,
        "--database-url",
        help="Database URL (if not loading from environment config)",
    ),
    copy_format: bool = typer.Option(
        False,
        "--copy-format",
        help="Convert INSERT statements to COPY format for faster loading",
    ),
    copy_threshold: int = typer.Option(
        DEFAULT_COPY_THRESHOLD,
        "--copy-threshold",
        help=f"Row threshold for automatic COPY format selection (default: {DEFAULT_COPY_THRESHOLD})",
    ),
    benchmark: bool = typer.Option(
        False,
        "--benchmark",
        help="Show performance comparison (VALUES vs COPY format)",
    ),
) -> None:
    """Apply seed files to database.

    By default, seed files are concatenated into a single SQL stream.
    Use --sequential to apply each file independently within a savepoint,
    which solves PostgreSQL parser limits for large files (650+ rows).

    Examples:
        # Concatenate mode (default)
        confiture seed apply --env local

        # Sequential mode (for large seed files)
        confiture seed apply --env local --sequential

        # Continue on error (skip failed files)
        confiture seed apply --env local --sequential --continue-on-error

        # Use explicit database URL
        confiture seed apply --sequential --database-url postgresql://localhost/mydb
    """
    try:
        if not sequential:
            console.print("[yellow]ℹ Use --sequential for files with 500+ rows[/yellow]")
            console.print("[yellow]  confiture seed apply --sequential --env {env}[/yellow]")
            raise typer.Exit(0)

        # Verify seeds directory exists
        if not seeds_dir.exists():
            console.print(f"[red]✗ Seeds directory not found: {seeds_dir}[/red]")
            raise typer.Exit(2)

        # Get database connection
        if database_url:
            # Use provided URL directly
            from confiture.core.connection import create_connection

            try:
                connection = create_connection(database_url)
            except Exception as e:
                console.print(f"[red]✗ Failed to connect to database: {e}[/red]")
                raise typer.Exit(2) from e
        else:
            # Load from environment config
            try:
                from confiture.config.environment import Environment

                env_config = Environment.load(env)
                from confiture.core.connection import create_connection

                connection = create_connection(env_config.database_url)
            except Exception as e:
                console.print(f"[red]✗ Failed to load environment {env}: {e}[/red]")
                raise typer.Exit(2) from e

        # Apply seeds sequentially
        try:
            applier = SeedApplier(
                seeds_dir=seeds_dir,
                env=env,
                connection=connection,
                console=console,
            )
            result = applier.apply_sequential(continue_on_error=continue_on_error)

            # Exit with error if files failed and not continuing
            if result.failed > 0 and not continue_on_error:
                raise typer.Exit(1)

            # Close connection
            connection.close()

            console.print("[green]✓ Seed application complete[/green]")
            raise typer.Exit(0)

        except Exception as e:
            console.print(f"[red]✗ Seed application failed: {e}[/red]")
            raise typer.Exit(2) from e

    except typer.Exit:
        raise
    except Exception as e:
        console.print(f"[red]✗ Error: {e}[/red]")
        raise typer.Exit(2) from e


@seed_app.command("convert")
def convert(
    input_file: Path = typer.Option(
        ...,
        "--input",
        help="Input file with INSERT statements",
    ),
    output_file: Path | None = typer.Option(
        None,
        "--output",
        help="Output file for COPY format (default: stdout)",
    ),
) -> None:
    """Convert INSERT statements to COPY format.

    This command reads SQL files with INSERT statements and converts them
    to PostgreSQL COPY format for faster bulk loading.

    Examples:
        # Convert INSERT to COPY and display
        confiture seed convert --input seeds.sql

        # Convert and save to file
        confiture seed convert --input seeds.sql --output seeds_copy.sql
    """
    try:
        if not input_file.exists():
            console.print(f"[red]✗ Input file not found: {input_file}[/red]")
            raise typer.Exit(2)

        from confiture.core.seed.insert_to_copy_converter import InsertToCopyConverter

        # Read input file
        sql_content = input_file.read_text()

        # Convert to COPY format
        converter = InsertToCopyConverter()
        copy_format = converter.convert(sql_content)

        # Output result
        if output_file:
            output_file.write_text(copy_format)
            console.print("[green]✓ Converted to COPY format[/green]")
            console.print(f"  Input: {input_file}")
            console.print(f"  Output: {output_file}")
        else:
            console.print(copy_format)

        raise typer.Exit(0)

    except typer.Exit:
        raise
    except Exception as e:
        console.print(f"[red]✗ Conversion failed: {e}[/red]")
        raise typer.Exit(2) from e


@seed_app.command("benchmark")
def benchmark(
    seeds_dir: Path = typer.Option(
        DEFAULT_SEEDS_DIR,
        "--seeds-dir",
        help="Directory containing seed files",
    ),
) -> None:
    """Benchmark COPY vs VALUES performance.

    This command analyzes seed files and shows the performance difference
    between VALUES and COPY format for loading the data.

    Examples:
        # Benchmark default seed directory
        confiture seed benchmark

        # Benchmark specific directory
        confiture seed benchmark --seeds-dir db/seeds/test
    """
    try:
        import asyncio

        from confiture.core.seed.performance_benchmark import PerformanceBenchmark

        if not seeds_dir.exists():
            console.print(f"[red]✗ Seeds directory not found: {seeds_dir}[/red]")
            raise typer.Exit(2)

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
        raise typer.Exit(0)

    except typer.Exit:
        raise
    except Exception as e:
        console.print(f"[red]✗ Benchmark failed: {e}[/red]")
        raise typer.Exit(2) from e
