"""CLI commands for seed data validation.

These commands validate seed files for consistency and correctness.
"""

from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from confiture.cli.prep_seed_formatter import format_prep_seed_report
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
            "[red]✗ Database URL required for levels 4-5. "
            "Use --database-url or --static-only[/red]"
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
) -> None:
    """Validate seed files for data consistency.

    This command checks seed files for common issues like:
    - Double semicolons (;;)
    - DDL statements (CREATE/ALTER/DROP) in seed files
    - Missing ON CONFLICT clauses

    With --prep-seed, validates UUID→BIGINT transformation patterns (5 levels).

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

                for violation in sorted(
                    all_violations, key=lambda v: (v.file_path, v.line_number)
                ):
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
