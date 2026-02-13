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
        help="Directory containing seed files (default: db/seeds)",
    ),
    env: str | None = typer.Option(
        None,
        "--env",
        help="Environment name for multi-env validation (default: none)",
    ),
    all_envs: bool = typer.Option(
        False,
        "--all",
        help="Validate all environments (default: off)",
    ),
    mode: str = typer.Option(
        "static",
        "--mode",
        help="Validation mode: static or database (default: static)",
    ),
    database_url: str | None = typer.Option(
        None,
        "--database-url",
        help="Database URL for database mode validation (default: none)",
    ),
    format_: str = typer.Option(
        "text",
        "--format",
        help="Output format: text, json, csv (default: text)",
    ),
    output: Path | None = typer.Option(
        None,
        "--output",
        help="Output file path (default: stdout)",
    ),
    fix: bool = typer.Option(
        False,
        "--fix",
        help="Automatically fix issues where possible (default: off)",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Show what would be fixed without modifying (default: off)",
    ),
    prep_seed: bool = typer.Option(
        False,
        "--prep-seed",
        help="Enable prep-seed pattern validation (default: off)",
    ),
    prep_seed_level: int = typer.Option(
        3,
        "--level",
        "-l",
        help="Prep-seed validation level 1-5 (default: 3)",
        min=1,
        max=5,
    ),
    static_only: bool = typer.Option(
        False,
        "--static-only",
        help="Run only Levels 1-3, no database (default: off)",
    ),
    full_execution: bool = typer.Option(
        False,
        "--full-execution",
        help="Run all levels 1-5, requires database (default: off)",
    ),
    uuid_validation: bool = typer.Option(
        False,
        "--uuid-validation",
        help="Enable seed enumerated UUID pattern validation (default: off)",
    ),
) -> None:
    """Validate seed files for data consistency and quality.

    PROCESS:
      Checks for common issues (double semicolons, DDL statements, missing ON
      CONFLICT). Optionally validates UUID patterns and prep-seed transformations
      (5 validation levels). Supports auto-fix for common issues.

    EXAMPLES:
      confiture seed validate
        ↳ Validate default seed directory, static mode (no database needed)

      confiture seed validate --mode database --database-url postgresql://localhost/mydb
        ↳ Validate with database checks for schema compatibility

      confiture seed validate --fix --dry-run
        ↳ Preview what would be fixed (e.g., add ON CONFLICT clauses)

      confiture seed validate --prep-seed --static-only
        ↳ Pre-commit safe: validate UUID transformations Levels 1-3

      confiture seed validate --prep-seed --full-execution --database-url postgresql://localhost/test
        ↳ Full validation: all 5 levels including runtime execution

    RELATED:
      confiture seed apply     - Load seeds into database
      confiture seed convert   - Transform INSERT to COPY format
      confiture seed benchmark - Compare VALUES vs COPY performance
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
        help="Directory containing seed files (default: db/seeds)",
    ),
    env: str = typer.Option(
        DEFAULT_ENV,
        "--env",
        help="Environment name for database URL lookup (default: local)",
    ),
    sequential: bool = typer.Option(
        False,
        "--sequential",
        help="Apply files sequentially, solves parser limits (default: off)",
    ),
    continue_on_error: bool = typer.Option(
        False,
        "--continue-on-error",
        help="Continue if file fails, for --sequential only (default: off)",
    ),
    database_url: str | None = typer.Option(
        None,
        "--database-url",
        help="Database URL, overrides environment config (default: from config)",
    ),
    copy_format: bool = typer.Option(
        False,
        "--copy-format",
        help="Convert INSERT to COPY format for faster loading (default: off)",
    ),
    copy_threshold: int = typer.Option(
        DEFAULT_COPY_THRESHOLD,
        "--copy-threshold",
        help=f"Row threshold for auto COPY selection (default: {DEFAULT_COPY_THRESHOLD})",
    ),
    benchmark: bool = typer.Option(
        False,
        "--benchmark",
        help="Show VALUES vs COPY performance comparison (default: off)",
    ),
) -> None:
    """Load seed data into the database.

    PROCESS:
      Concatenates seed files (default) or applies sequentially with savepoint
      isolation. Sequential mode solves PostgreSQL parser limits for large files
      (650+ rows). Supports COPY format for 10x faster loading.

    EXAMPLES:
      confiture seed apply --env local --sequential
        ↳ Apply seed files sequentially to local database

      confiture seed apply --sequential --copy-format
        ↳ Use faster COPY format (auto-converts INSERT statements)

      confiture seed apply --sequential --continue-on-error --env production
        ↳ Skip failed files, continue with remaining seeds

      confiture seed apply --sequential --benchmark
        ↳ Show VALUES vs COPY performance comparison

    RELATED:
      confiture seed validate - Check seed data quality
      confiture seed convert  - Transform INSERT to COPY format
      confiture build         - Build schema, optionally apply seeds
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
        help="Input file with INSERT statements (required)",
    ),
    output_file: Path | None = typer.Option(
        None,
        "--output",
        help="Output file for COPY format (default: stdout)",
    ),
) -> None:
    """Transform INSERT statements to COPY format (10x faster).

    PROCESS:
      Reads SQL files with INSERT statements and converts to PostgreSQL COPY
      format for dramatically faster bulk loading (typically 10x speed improvement).

    EXAMPLES:
      confiture seed convert --input seeds.sql
        ↳ Convert and display COPY format to stdout

      confiture seed convert --input seeds.sql --output seeds_copy.sql
        ↳ Convert and save to file

      confiture seed convert --input db/seeds/users.sql --output db/seeds/users_copy.sql
        ↳ Convert multiple files in bulk

    RELATED:
      confiture seed apply     - Load seeds with optional COPY format
      confiture seed validate  - Check seed data quality
      confiture seed benchmark - Compare VALUES vs COPY performance
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
        help="Directory containing seed files (default: db/seeds)",
    ),
) -> None:
    """Compare VALUES vs COPY format performance.

    PROCESS:
      Analyzes seed files and benchmarks loading performance in both formats.
      Shows estimated speedup, time savings, and per-table metrics to help
      optimize seed data loading strategy.

    EXAMPLES:
      confiture seed benchmark
        ↳ Benchmark default seed directory, show performance comparison

      confiture seed benchmark --seeds-dir db/seeds/test
        ↳ Benchmark specific seed directory

      confiture seed apply --benchmark --sequential
        ↳ See benchmark while applying seeds with --sequential flag

    RELATED:
      confiture seed apply   - Load seeds with --copy-format flag
      confiture seed convert - Transform INSERT to COPY format
      confiture seed validate - Check seed data quality
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
