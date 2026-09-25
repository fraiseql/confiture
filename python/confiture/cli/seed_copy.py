"""``confiture seed convert``: the COPY-format tool."""

from __future__ import annotations

import sys
from pathlib import Path

import typer
from rich.table import Table

from confiture.cli.error_json import cli_boundary, fail
from confiture.cli.helpers import console
from confiture.cli.markup import verbatim
from confiture.cli.options import output_option
from confiture.core.builder import files_under
from confiture.core.seed.insert_to_copy_converter import InsertToCopyConverter
from confiture.error_codes import FINDINGS, SUCCESS
from confiture.exceptions import ConfigurationError, ConfiturError, SeedError

#: Where the seed files are, unless a command is told otherwise.
DEFAULT_SEEDS_DIR = Path("db/seeds")


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
        help="Process every .sql file under the directory, recursively (requires --output)",
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

        if batch:
            _convert_directory(converter, input_file, output_file)
            raise typer.Exit(SUCCESS)

        # Single file mode
        sql_content = input_file.read_text()
        result = converter.try_convert(sql_content, file_path=str(input_file))

        # Handle conversion result
        if not result.success:
            console.print(f"[yellow]⚠ Cannot convert {verbatim(input_file)}[/yellow]")
            console.print(f"  Reason: {verbatim(result.reason)}")
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
            console.print(f"  Input: {verbatim(input_file)}")
            console.print(f"  Output: {verbatim(output_file)}")
            console.print(f"  Rows: {verbatim(result.rows_converted)}")
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


def _convert_directory(
    converter: InsertToCopyConverter, input_dir: Path, output_dir: Path | None
) -> None:
    """``--batch``: convert every ``*.sql`` under *input_dir* into *output_dir*, path for path."""
    if not input_dir.is_dir():
        raise ConfigurationError("For --batch mode, input must be a directory.")
    if not output_dir:
        raise ConfigurationError("For --batch mode, --output is required.")

    output_dir.mkdir(parents=True, exist_ok=True)
    sql_files = files_under(input_dir)
    if not sql_files:
        console.print(f"[yellow]⚠ No .sql files found in {verbatim(input_dir)}[/yellow]")
        return

    console.print(f"[bold]Processing {len(sql_files)} files...[/bold]\n")
    files_content = {str(f.relative_to(input_dir)): f.read_text() for f in sql_files}
    report = converter.convert_batch(files_content)

    table = Table(title="Conversion Results")
    table.add_column("File", style="cyan")
    table.add_column("Status", style="green")
    table.add_column("Rows/Reason", style="yellow")
    for result in report.results:
        if result.success:
            table.add_row(
                result.file_path, "[green]✓ Converted[/green]", str(result.rows_converted)
            )
            out_path = output_dir / result.file_path
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(result.copy_format)
        else:
            table.add_row(result.file_path, "[yellow]⚠ Skipped[/yellow]", result.reason)

    console.print(table)
    console.print("\n[bold]Summary:[/bold]")
    console.print(f"  Total: {verbatim(report.total_files)} files")
    console.print(f"  [green]Converted: {verbatim(report.successful)}[/green]")
    console.print(f"  [yellow]Skipped: {verbatim(report.failed)}[/yellow]")
    console.print(f"  Success rate: {report.success_rate:.1f}%")
    if report.successful > 0:
        console.print(f"\n[green]✓ Results saved to: {verbatim(output_dir)}[/green]")
