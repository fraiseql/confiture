"""``confiture seed convert`` and ``seed benchmark``: the COPY-format tools."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

import typer
from rich.table import Table

from confiture.cli.error_json import cli_boundary, fail
from confiture.cli.helpers import console
from confiture.cli.options import output_option
from confiture.core.seed.insert_to_copy_converter import InsertToCopyConverter
from confiture.core.seed.performance_benchmark import PerformanceBenchmark
from confiture.error_codes import FINDINGS, SUCCESS
from confiture.exceptions import ConfigurationError, ConfiturError, SeedError

#: Where the seed files are, unless a command is told otherwise.
DEFAULT_SEEDS_DIR = Path("db/seeds")


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


@cli_boundary
def convert(
    input_file: Path = typer.Option(
        ...,
        "--input",
        help="Input file with INSERT statements (required)",
    ),
    output_file: Path | None = output_option(help="Output file for COPY format (default: stdout)"),
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
                raise typer.Exit(SUCCESS)

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

            raise typer.Exit(SUCCESS)

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
            raise typer.Exit(FINDINGS)

        # Output result
        if output_file:
            output_file.write_text(result.copy_format)
            console.print("[green]✓ Converted to COPY format[/green]")
            console.print(f"  Input: {input_file}")
            console.print(f"  Output: {output_file}")
            console.print(f"  Rows: {result.rows_converted}")
        else:
            sys.stdout.write(result.copy_format or "")

        raise typer.Exit(SUCCESS)

    except typer.Exit:
        raise
    except ConfiturError as e:
        fail(e, json_mode=False)
    # Reason: text-only command: the message names the operation that failed, whatever failed
    except Exception as e:
        fail(SeedError(f"Conversion failed: {e!s}"), json_mode=False)


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
            raise typer.Exit(SUCCESS)

        # Run benchmark
        benchmark_runner = PerformanceBenchmark()
        result = asyncio.run(benchmark_runner.compare(seed_data))

        # Display results using helper
        _format_benchmark_output(result)
        raise typer.Exit(SUCCESS)  # success-signal: benchmark complete

    except typer.Exit:
        raise
    # Reason: text-only command: the message names the operation that failed, whatever failed
    except Exception as e:
        fail(SeedError(f"Benchmark failed: {e}"), json_mode=False)
