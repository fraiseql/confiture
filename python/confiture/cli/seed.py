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
from confiture.core.error_handler import print_error_to_console
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
        print_error_to_console(e)
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
      CORE: --seeds-dir, --mode, --format, --output
        What to validate, how to validate, and how to report

      PREP-SEED: --prep-seed, --level, --static-only, --full-execution
        Enable prep-seed pattern validation with 5 validation levels

      AUTO-FIX: --fix, --dry-run
        Automatically fix detected issues (with dry-run preview)

      ADVANCED: --env, --all-envs, --database-url, --uuid-validation
        Multi-environment validation and advanced pattern checking
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
            console.print("[blue]ℹ UUID Validation Support[/blue]")
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
                console.print("\n💡 Next steps:")
                console.print("  • Load data: confiture seed apply")
                console.print("  • Show performance: confiture seed benchmark")
                console.print("  • Convert format: confiture seed convert")

        # Exit with appropriate code
        if all_violations:
            raise typer.Exit(1)
        else:
            raise typer.Exit(0)

    except typer.Exit:
        raise
    except Exception as e:
        print_error_to_console(e)
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
        help="Apply files sequentially, solves 650+ row parser limits",
    ),
    continue_on_error: bool = typer.Option(
        False,
        "--continue-on-error",
        help="Continue if file fails (--sequential only, useful for CI/CD)",
    ),
    database_url: str | None = typer.Option(
        None,
        "--database-url",
        help="Database URL (overrides environment config)",
    ),
    copy_format: bool = typer.Option(
        False,
        "--copy-format",
        help="Use COPY format (2-10x faster for large datasets)",
    ),
    copy_threshold: int = typer.Option(
        DEFAULT_COPY_THRESHOLD,
        "--copy-threshold",
        help=f"Row threshold for auto COPY (default: {DEFAULT_COPY_THRESHOLD}, use >1000 rows)",
    ),
    benchmark: bool = typer.Option(
        False,
        "--benchmark",
        help="Show VALUES vs COPY performance comparison",
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
        help="Save structured output (JSON/CSV) to file",
    ),
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
      • Use --benchmark to see improvement

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

      PERFORMANCE: --copy-format, --copy-threshold, --benchmark
        Format selection (2-10x faster for >50K rows)

      OUTPUT: --format, --report
        Structured results (JSON/CSV for automation)
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
            # Import ProgressManager for progress tracking
            from confiture.core.progress import ProgressManager

            applier = SeedApplier(
                seeds_dir=seeds_dir,
                env=env,
                connection=connection,
                console=console,
            )

            # Use progress manager for seed application
            with ProgressManager() as progress:
                result = applier.apply_sequential(
                    continue_on_error=continue_on_error,
                    progress=progress,
                )

            # Format output
            from confiture.cli.formatters.seed_formatter import format_apply_result

            format_apply_result(result, format_type, report_output, console)

            # Close connection
            connection.close()

            # Exit with error if files failed and not continuing
            if result.failed > 0 and not continue_on_error:
                raise typer.Exit(1)

            raise typer.Exit(0)

        except Exception as e:
            console.print(f"[red]✗ Seed application failed: {e}[/red]")
            raise typer.Exit(2) from e

    except typer.Exit:
        raise
    except Exception as e:
        print_error_to_console(e)
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
        from confiture.core.seed.insert_to_copy_converter import InsertToCopyConverter

        if not input_file.exists():
            console.print(f"[red]✗ Input file/directory not found: {input_file}[/red]")
            raise typer.Exit(2)

        converter = InsertToCopyConverter()

        # Batch mode: process all files in directory
        if batch:
            if not input_file.is_dir():
                console.print("[red]✗ For --batch mode, input must be a directory[/red]")
                raise typer.Exit(2)

            if not output_file:
                console.print("[red]✗ For --batch mode, --output is required[/red]")
                raise typer.Exit(2)

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
            import sys

            sys.stdout.write(result.copy_format or "")

        raise typer.Exit(0)

    except typer.Exit:
        raise
    except Exception as e:
        from rich.text import Text

        console.print(Text(f"Conversion failed: {e!s}", style="red"))
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


@seed_app.command("generate")
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
    format_type: str = typer.Option(
        "text", "--format", "-f", help="Output format: text, json (default: text)"
    ),
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
    from confiture.core.seed_bridge import SeedBridge, SeedGenerationConfig

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
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1) from e

    if format_type == "json":
        import json

        console.print(json.dumps(result.to_dict(), indent=2))
    else:
        if result.success:
            console.print(f"[green]Seed stub generated: {result.output_path}[/green]")
            console.print(
                f"[dim]{result.column_count} column(s), {result.row_count} stub row(s).[/dim]"
            )
        else:
            console.print(f"[red]Error: {result.error}[/red]")
            raise typer.Exit(1)
