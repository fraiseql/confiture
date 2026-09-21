"""CLI commands for seed data validation.

These commands validate seed files for consistency and correctness.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

import typer
from rich.console import Console
from rich.table import Table

from confiture.cli.error_json import cli_boundary, fail
from confiture.cli.formatters.seed_formatter import format_apply_result
from confiture.cli.helpers import connect, emit, is_json
from confiture.cli.options import database_url_option, env_option, format_option, output_option
from confiture.cli.prep_seed_formatter import format_prep_seed_report
from confiture.cli.seed_copy import DEFAULT_SEEDS_DIR, benchmark, convert
from confiture.config.environment import Environment
from confiture.core.connection import DatabaseError
from confiture.core.progress import ProgressManager
from confiture.core.seed.applier import SeedApplier
from confiture.core.seed.bridge import SeedBridge, SeedGenerationConfig
from confiture.core.seed.validation import SeedFixer, SeedValidator
from confiture.core.seed.validation.prep_seed import (
    OrchestrationConfig,
    PrepSeedOrchestrator,
)
from confiture.error_codes import FAILURE, FINDINGS, SUCCESS
from confiture.exceptions import ConfigurationError, ConfiturError, SeedError

# Create Rich console for pretty output
console = Console()

# Create seed subcommand group
seed_app = typer.Typer(
    help="Seed data validation and management",
    no_args_is_help=True,
)


# Shared option definitions for better reusability
DEFAULT_COPY_THRESHOLD = 1000
DEFAULT_ENV = "local"


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

        if format_ == "json":
            emit(report.to_dict(), output, console)
        else:
            # Use formatter for text and CSV
            format_prep_seed_report(report, format_, output, console)

        # Exit with appropriate code
        if report.has_violations:
            raise typer.Exit(FINDINGS)  # success-signal: validation found violations
        else:
            raise typer.Exit(SUCCESS)  # success-signal: clean

    except typer.Exit:
        raise
    # Reason: seed validate's --output is its report path; the boundary cannot know that, so it routes the envelope itself
    except Exception as e:
        fail(e, json_mode=is_json(format_), output_file=output)


SeedsDirOpt = Annotated[
    Path, typer.Option("--seeds-dir", help="Directory containing seed files (default: db/seeds)")
]
AllEnvsOpt = Annotated[bool, typer.Option("--all", help="Validate all environments (default: off)")]
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
        emit(report_dict, output, console)
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
    env: str | None = env_option(None),
    all_envs: AllEnvsOpt = False,
    database_url: str | None = database_url_option(
        help="Database URL for database mode validation (default: none)"
    ),
    format_: str = format_option("text", "json", "csv"),
    output: Path | None = output_option(),
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
            raise typer.Exit(FINDINGS)  # success-signal: validation found violations
        else:
            raise typer.Exit(SUCCESS)  # success-signal: clean

    except typer.Exit:
        raise
    # Reason: seed validate's --output is its report path; the boundary cannot know that, so it routes the envelope itself
    except Exception as e:
        fail(e, json_mode=is_json(format_), output_file=output)


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
    env: str = env_option(DEFAULT_ENV),
    sequential: SequentialOpt = False,
    continue_on_error: ContinueOnErrorOpt = False,
    database_url: str | None = database_url_option(
        help="Database URL (overrides environment config)"
    ),
    copy_format: CopyFormatOpt = False,
    copy_threshold: CopyThresholdOpt = DEFAULT_COPY_THRESHOLD,
    format_type: str = format_option("text", "json", "csv"),
    report_output: Path | None = output_option(
        None,
        "--report",
        help="Save structured output (JSON/CSV) to file. --report is a "
        "back-compat alias for --output/-o (DOCS-M2).",
    ),
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
        raise typer.Exit(SUCCESS)  # success-signal: advisory, nothing applied

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
        except (ConfiturError, DatabaseError) as e:
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
        except (ConfiturError, DatabaseError, OSError) as e:
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
            raise typer.Exit(FINDINGS)  # success-signal: some seed files failed

        raise typer.Exit(SUCCESS)  # success-signal: all applied

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


seed_app.command("convert")(convert)
seed_app.command("benchmark")(benchmark)


@seed_app.command("generate")
@cli_boundary
def seed_generate(
    table: str = typer.Argument(..., help="Table name to generate seed data for"),
    database_url: str = database_url_option(...),
    schema: str = typer.Option("public", "--schema", "-s", help="Schema name (default: public)"),
    seed_env: str = typer.Option(
        "development",
        "--seed-env",
        help="Seed directory under db/seeds/ to write into (default: development)",
    ),
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

      confiture seed generate bookings -d $DATABASE_URL --rows 5 --seed-env test
        ↳ Generate 5-row stub for bookings in the test environment
    """

    config = SeedGenerationConfig(
        table=table,
        schema=schema,
        row_count=row_count,
        output_dir=output_dir,
        env=seed_env,
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
        emit(result.to_dict())
    elif result.success:
        console.print(f"[green]Seed stub generated: {result.output_path}[/green]")
        console.print(
            f"[dim]{result.column_count} column(s), {result.row_count} stub row(s).[/dim]"
        )
    else:
        console.print(f"[red]Error: {result.error}[/red]")
    if not result.success:
        # The result carries the failure in either format; the exit says so in both.
        raise typer.Exit(FAILURE)
