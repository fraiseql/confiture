"""Schema commands: init, build, lint, introspect."""

import json
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Annotated, Any

import psycopg
import typer
from rich.console import Console
from rich.console import Console as _Console
from rich.table import Table

from confiture.cli.error_json import cli_boundary, fail
from confiture.cli.formatters.build_formatter import (
    format_build_result,
    format_pattern_notes,
    format_selection_report,
)
from confiture.cli.helpers import (
    FINDINGS_EXIT_CODE,
    USAGE_EXIT_CODE,
    _convert_linter_report,
    _output_json,
    _output_yaml,
    connect,
    console,
    error_console,
    is_json,
)
from confiture.cli.lint_formatter import format_lint_report, save_report
from confiture.cli.options import format_option
from confiture.config.environment import DEFAULT_STATUS_WORDS, Environment
from confiture.core import builder as _core_builder
from confiture.core import linting as _core_linting
from confiture.core.builder import SchemaBuilder
from confiture.core.connection import load_config as _lc
from confiture.core.error_handler import handle_cli_error, print_error_to_console
from confiture.core.introspection.tables import SchemaIntrospector
from confiture.core.linting import SchemaLinter
from confiture.core.linting.baseline import Baseline, BaselineDiff, identity
from confiture.core.linting.duplicates import duplicate_violations, find_duplicates, inventory_files
from confiture.core.linting.gate import (
    Gate,
    Threshold,
    compute_gate,
    parse_threshold,
    should_fail,
    threshold_from_aliases,
    unrun_reaches,
)
from confiture.core.linting.inventory import label_for
from confiture.core.linting.libraries.generate import TREE_RULE_CODES, tree_violations
from confiture.core.linting.libraries.security_definer import Sec002SecurityDefinerSearchPath
from confiture.core.linting.rule_registry import (
    DEFAULT_SELECTOR,
    LEGACY_CODE_ALIASES,
    LINT_RULES,
    resolve_selection,
)
from confiture.core.linting.schema_linter import (
    LintConfig as LinterConfig,
)
from confiture.core.linting.schema_linter import LintReport as LinterReport
from confiture.core.linting.schema_linter import (
    LintViolation,
)
from confiture.core.linting.schema_linter import (
    RuleSeverity as _RS,
)
from confiture.core.progress import ProgressManager
from confiture.core.schema_artifact import build_schema_artifact, default_artifact_path
from confiture.core.seed.applier import apply_profile_filter
from confiture.core.seed.paths import is_seed_path
from confiture.core.seed.sequencer import apply_seed_files
from confiture.core.unified_linter import UnifiedLinter
from confiture.core.validation.config_loaders import load_security_lint as _lsl
from confiture.exceptions import ConfigurationError, ConfiturError, SchemaError
from confiture.models.lint import LintSeverity
from confiture.models.results import BuildResult, BuildWarning
from confiture.models.unified_lint import UnifiedLintIssue, UnifiedLintResult

# Valid output formats for linting (re-exported so main.py can keep LINT_FORMATS there)
LINT_FORMATS = ("table", "json", "csv")


def _violation_to_unified_issue(v, tool: str, file=None):
    """Convert a LintViolation to a UnifiedLintIssue."""

    return UnifiedLintIssue(
        tool=tool,
        file=file if file is not None else (v.file_path or v.object_name),
        line=v.line_number,
        message=v.message,
        severity=LintSeverity(v.severity.value),
        rule=v.rule_id if tool == "tree" else v.rule_name,
    )


@cli_boundary
def init(
    path: Path = typer.Argument(
        Path(),
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

migration:
  # View helper mode for ALTER COLUMN TYPE with dependent views.
  #   auto   — install helper functions on first migrate up (default)
  #   manual — you run `confiture admin install-helpers` yourself
  #   off    — disabled; manage views in your migration SQL
  view_helpers: auto
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

    except typer.Exit:
        raise
    except OSError as e:
        print_error_to_console(e)
        raise typer.Exit(handle_cli_error(e)) from e


EnvOpt = Annotated[str, typer.Option("--env", "-e", help="Environment to build (default: local)")]
OutputOpt = Annotated[
    Path | None,
    typer.Option(
        "--output", "-o", help="Output file path (default: db/generated/schema_{env}.sql)"
    ),
]
ProjectDirOpt = Annotated[
    Path, typer.Option("--project-dir", help="Project directory (default: current directory)")
]
ShowHashOpt = Annotated[
    bool, typer.Option("--show-hash", help="Display schema hash after build (default: off)")
]
SchemaOnlyOpt = Annotated[
    bool, typer.Option("--schema-only", help="Build schema only, exclude seed data (default: off)")
]
ValidateCommentsOpt = Annotated[
    bool | None,
    typer.Option(
        "--validate-comments/--no-validate-comments",
        help="Enable/disable comment validation (default: from config)",
    ),
]
FailOnUnclosedOpt = Annotated[
    bool | None,
    typer.Option(
        "--fail-on-unclosed/--no-fail-on-unclosed",
        help="Fail on unclosed block comments (default: from config)",
    ),
]
FailOnSpilloverOpt = Annotated[
    bool | None,
    typer.Option(
        "--fail-on-spillover/--no-fail-on-spillover",
        help="Fail on comment spillover into next file (default: from config)",
    ),
]
TwoPassOpt = Annotated[
    bool | None,
    typer.Option(
        "--two-pass/--no-two-pass",
        help="Two-pass FK emission: strip REFERENCES from CREATE TABLE, emit ALTER TABLE after (default: from config)",
    ),
]
SeparatorStyleOpt = Annotated[
    str | None,
    typer.Option(
        "--separator-style",
        help="Separator style: block_comment, line_comment, mysql, custom (default: from config)",
    ),
]
SeparatorTemplateOpt = Annotated[
    str | None,
    typer.Option(
        "--separator-template",
        help="Custom separator template with {file_path} placeholder (default: none)",
    ),
]
SequentialOpt = Annotated[
    bool,
    typer.Option("--sequential", help="Apply seed files sequentially after build (default: off)"),
]
DatabaseUrlOpt = Annotated[
    str | None,
    typer.Option(
        "--database-url",
        help="Database connection URL (required for --sequential, default: from config)",
    ),
]
ContinueOnErrorOpt = Annotated[
    bool,
    typer.Option(
        "--continue-on-error",
        help="Continue applying seed files if one fails (only with --sequential)",
    ),
]
WarnDuplicatesOpt = Annotated[
    bool,
    typer.Option(
        "--warn-duplicates",
        help="Report objects defined more than once across the build's files (build_001/build_002), then build",
    ),
]
FailOnDuplicatesOpt = Annotated[
    bool,
    typer.Option(
        "--fail-on-duplicates", help="Report duplicate definitions and exit 1 without building"
    ),
]
ReportOutputOpt = Annotated[
    Path | None,
    typer.Option(
        "--report",
        help="Save structured build report (JSON/CSV) to file (default: stdout). "
        "Distinct from --output/-o, which is the generated *schema* file.",
    ),
]
DumpOpt = Annotated[
    Path | None,
    typer.Option(
        "--dump",
        help="Also emit a content-addressed pg_dump -Fc artifact restorable by "
        "'confiture restore'. Pass a file path, or an existing directory to "
        "auto-name 'schema_{env}.{profile}.{hash}.pgdump' inside it (cache by db/ hash).",
    ),
]
DumpFormatOpt = Annotated[
    str,
    typer.Option(
        "--dump-format",
        help="Artifact format for --dump: custom (-Fc) or directory (-Fd, parallel). "
        "Default: custom.",
    ),
]
ListFilesOpt = Annotated[
    bool,
    typer.Option(
        "--list-files",
        help="Print the files this build would read — with the include_dirs entry, "
        "its order and the pattern that matched each — and build nothing",
    ),
]
SeedProfileOpt = Annotated[
    str | None,
    typer.Option(
        "--seed-profile",
        help="Apply only the named seed profile (seed.profiles.<name>) during "
        "--sequential seed application and --dump. Unknown name → exit 5.",
    ),
]


@cli_boundary
def build(
    env: EnvOpt = "local",
    output: OutputOpt = None,
    project_dir: ProjectDirOpt = Path(),
    show_hash: ShowHashOpt = False,
    schema_only: SchemaOnlyOpt = False,
    validate_comments: ValidateCommentsOpt = None,
    fail_on_unclosed: FailOnUnclosedOpt = None,
    fail_on_spillover: FailOnSpilloverOpt = None,
    two_pass: TwoPassOpt = None,
    separator_style: SeparatorStyleOpt = None,
    separator_template: SeparatorTemplateOpt = None,
    sequential: SequentialOpt = False,
    database_url: DatabaseUrlOpt = None,
    continue_on_error: ContinueOnErrorOpt = False,
    warn_duplicates: WarnDuplicatesOpt = False,
    fail_on_duplicates: FailOnDuplicatesOpt = False,
    format_type: str = format_option("text", "json", "csv"),
    report_output: ReportOutputOpt = None,
    dump: DumpOpt = None,
    dump_format: DumpFormatOpt = "custom",
    seed_profile: SeedProfileOpt = None,
    list_files: ListFilesOpt = False,
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

      confiture build --list-files
        ↳ Print what the build would read — file, entry, order, pattern — and build nothing

    RELATED:
      confiture migrate up      - Apply incremental migrations instead
      confiture seed validate   - Validate seed data separately
      confiture lint            - Check schema against best practices

    OPTIONS:
      CORE: --env, --output
        Essential options for basic usage

      ADVANCED: --show-hash, --schema-only, --two-pass, --separator-style, --separator-template
        Optional parameters for customizing output format

      DIAGNOSTIC: --list-files
        Print the selection instead of building it

      STRUCTURED OUTPUT: --format, --report
        Export results in JSON/CSV format for automation and integration

      SEEDS & VALIDATION: --sequential, --database-url, --continue-on-error,
                         --validate-comments, --fail-on-unclosed, --fail-on-spillover
        For applying seeds after build and controlling validation behavior
    """
    # Progress lines go to stderr in JSON mode: stdout is the payload.
    # Progress lines go to stderr in JSON mode: stdout is the payload.
    out = error_console if is_json(format_type) else console
    json_mode = is_json(format_type)
    try:
        builder = SchemaBuilder(env=env, project_dir=project_dir)
        if list_files:
            format_selection_report(builder.selection_report(), format_type, project_dir, console)
            return
        format_pattern_notes(builder.pattern_diagnostics(), project_dir, out)
        _apply_build_overrides(
            builder,
            out,
            two_pass=two_pass,
            validate_comments=validate_comments,
            fail_on_unclosed=fail_on_unclosed,
            fail_on_spillover=fail_on_spillover,
            separator_style=separator_style,
            separator_template=separator_template,
            json_mode=json_mode,
            report_output=report_output,
        )
        output, seed_profile_obj, apply_sequential = _build_settings(
            builder,
            schema_only=schema_only,
            output=output,
            project_dir=project_dir,
            env=env,
            seed_profile=seed_profile,
            sequential=sequential,
        )
        schema, schema_file_count, duplicates = _run_build(
            builder,
            out,
            env=env,
            output=output,
            apply_sequential=apply_sequential,
            duplicate_gate=lambda files: _duplicate_gate(
                files,
                project_dir=project_dir,
                output=output,
                warn=warn_duplicates,
                fail=fail_on_duplicates,
                out=out,
                json_mode=json_mode,
                report_output=report_output,
            ),
        )

        seed_files_applied = 0
        warnings: list[BuildWarning] = []
        if apply_sequential:
            seed_files_applied, seed_warnings = _apply_seeds_sequentially(
                builder,
                out,
                env=env,
                database_url=database_url,
                continue_on_error=continue_on_error,
                profile=seed_profile_obj,
                json_mode=json_mode,
                report_output=report_output,
            )
            warnings.extend(seed_warnings)

        schema_hash = builder.compute_hash() if show_hash else None
        artifact_path_str: str | None = None
        artifact_hash_str: str | None = None
        if dump is not None:
            if schema_hash is None:
                schema_hash = builder.compute_hash()
            artifact_path_str, artifact_hash_str = _write_dump_artifact(
                builder,
                out,
                dump=dump,
                dump_format=dump_format,
                env=env,
                database_url=database_url,
                schema_hash=schema_hash,
                schema_only=schema_only,
                seed_profile=seed_profile,
                seed_profile_obj=seed_profile_obj,
                json_mode=json_mode,
                report_output=report_output,
            )

        build_result = BuildResult(
            success=True,
            files_processed=schema_file_count,
            schema_size_bytes=len(schema),
            output_path=str(output.absolute()),
            hash=schema_hash,
            execution_time_ms=0,
            seed_files_applied=seed_files_applied,
            artifact_path=artifact_path_str,
            artifact_hash=artifact_hash_str,
            seed_profile=seed_profile,
            warnings=warnings,
            duplicates=duplicates,
        )
        format_build_result(build_result, format_type, report_output, console)
        if format_type == "text":
            out.print("\n💡 Next steps:")
            out.print(f"  • Apply schema: psql -f {output}")
            out.print("  • Or use: confiture migrate up")
    except typer.Exit:
        raise  # an inner fail() already emitted its envelope
    except FileNotFoundError as e:
        # In text mode keep the human-friendly "run init" tip on stderr; the
        # envelope (json mode) carries the actionable hint instead.
        if not json_mode:
            out.print("\n💡 Tip: Run 'confiture init' to create project structure")
        fail(
            SchemaError(
                f"Schema source not found: {e}",
                error_code="SCHEMA_201",
                resolution_hint="Run 'confiture init' to create the project structure.",
            ),
            json_mode=json_mode,
            output_file=report_output,
        )


def _duplicate_gate(
    sql_files: list[Path],
    *,
    project_dir: Path,
    output: Path,
    warn: bool,
    fail: bool,
    out: Console,
    json_mode: bool,
    report_output: Path | None,
) -> list[dict[str, Any]]:
    """Scan the build's files for duplicate definitions when asked (#218).

    ``--warn-duplicates`` reports and builds; ``--fail-on-duplicates`` reports
    and exits 1 before anything is written. A plain build does not scan.
    """
    if not (warn or fail):
        return []

    objects, _schemas, unparseable = inventory_files(sql_files, root=project_dir)
    for label in unparseable:
        out.print(
            f"[yellow]⚠️ {label}: pglast could not parse it — not checked for duplicates[/yellow]"
        )
    duplicates = find_duplicates(objects)
    if not duplicates:
        return []
    if not json_mode:
        out.print("[yellow]Duplicate definitions:[/yellow]")
        for violation in duplicate_violations(duplicates):
            out.print(f"  ⚠️ {violation.rule_id}: {violation.message}")
    payload = [duplicate.to_dict() for duplicate in duplicates]
    if fail:
        result = BuildResult(
            success=False,
            files_processed=len(sql_files),
            schema_size_bytes=0,
            output_path=str(output.absolute()),
            hash=None,
            duplicates=payload,
            error=f"{len(duplicates)} duplicate definition(s); nothing was built",
        )
        format_build_result(result, "json" if json_mode else "text", report_output, console)
        raise typer.Exit(FINDINGS_EXIT_CODE)  # success-signal: the duplicate gate tripped
    return payload


_SEPARATOR_STYLES = ("block_comment", "line_comment", "mysql", "custom")


def _build_settings(
    builder: SchemaBuilder,
    *,
    schema_only: bool,
    output: Path | None,
    project_dir: Path,
    env: str,
    seed_profile: str | None,
    sequential: bool,
) -> tuple[Path, Any, bool]:
    """Trim seeds under ``--schema-only``, default the output path, resolve the seed profile and mode.

    Returns:
        ``(output, seed_profile_obj, apply_sequential)``.
    """
    if schema_only:
        builder.include_dirs = [d for d in builder.include_dirs if not is_seed_path(d)]
        builder.include_configs = [
            cfg for cfg in builder.include_configs if not is_seed_path(cfg["path"])
        ]
        if builder.include_dirs:
            builder.base_dir = builder.find_common_parent(builder.include_dirs)
    if output is None:
        output_dir = project_dir / "db" / "generated"
        output_dir.mkdir(parents=True, exist_ok=True)
        output = output_dir / f"schema_{env}.sql"

    # Resolve a named seed profile from env config (unknown → exit 5).
    seed_profile_obj = None
    if seed_profile is not None:
        seed_profile_obj = builder.env_config.seed.get_profile(seed_profile)
    apply_sequential = sequential or (
        builder.env_config.seed and builder.env_config.seed.execution_mode == "sequential"
    )
    return output, seed_profile_obj, bool(apply_sequential)


def _run_build(
    builder: SchemaBuilder,
    out: Any,
    *,
    env: str,
    output: Path,
    apply_sequential: bool,
    duplicate_gate: Callable[[list[Path]], Any],
) -> tuple[str, int, Any]:
    """Concatenate the schema under a progress bar, after ``duplicate_gate`` saw the files.

    Returns:
        ``(schema, schema_file_count, duplicates)``; the seed files are left
        to the sequential applier when ``apply_sequential``.
    """
    out.print(f"[cyan]🔨 Building schema for environment: {env}[/cyan]")

    with ProgressManager() as progress:
        sql_files = builder.find_sql_files()
        duplicates = duplicate_gate(sql_files)
        if apply_sequential:
            schema = builder.build(output_path=output, schema_only=True, progress=progress)
            schema_file_count = len([f for f in sql_files if not builder.is_seed_file(f)])
        else:
            schema = builder.build(output_path=output, progress=progress)
            schema_file_count = len(sql_files)
    out.print(f"[cyan]📄 Found {len(sql_files)} SQL files[/cyan]")
    return schema, schema_file_count, duplicates


def _apply_build_overrides(
    builder: SchemaBuilder,
    out: Any,
    *,
    two_pass: bool | None,
    validate_comments: bool | None,
    fail_on_unclosed: bool | None,
    fail_on_spillover: bool | None,
    separator_style: str | None,
    separator_template: str | None,
    json_mode: bool,
    report_output: Path | None,
) -> None:
    """CLI flags override the environment's ``build:`` settings; report what changed."""
    cfg = builder.env_config.build
    if validate_comments is not None:
        cfg.validate_comments.enabled = validate_comments
    if fail_on_unclosed is not None:
        cfg.validate_comments.fail_on_unclosed_blocks = fail_on_unclosed
    if fail_on_spillover is not None:
        cfg.validate_comments.fail_on_spillover = fail_on_spillover
    if two_pass is not None:
        cfg.two_pass = two_pass
    if separator_style is not None:
        if separator_style not in _SEPARATOR_STYLES:
            fail(
                ConfigurationError(
                    f"Invalid separator style: {separator_style}",
                    resolution_hint=f"Valid options: {', '.join(_SEPARATOR_STYLES)}",
                ),
                json_mode=json_mode,
                output_file=report_output,
            )
        cfg.separators.style = separator_style
    if separator_template is not None:
        cfg.separators.custom_template = separator_template
    if (
        separator_style == "custom"
        and not separator_template
        and not cfg.separators.custom_template
    ):
        fail(
            ConfigurationError(
                "Custom separator style requires --separator-template",
                resolution_hint="Pass --separator-template with a {file_path} placeholder.",
            ),
            json_mode=json_mode,
            output_file=report_output,
        )
    shown = [
        ("Two-pass FK emission", two_pass),
        ("Comment validation", validate_comments),
        ("Fail on unclosed blocks", fail_on_unclosed),
        ("Fail on spillover", fail_on_spillover),
        ("Separator style", separator_style),
    ]
    if separator_template is not None:
        shown.append(
            (
                "Custom template",
                f"{separator_template[:50]}..."
                if len(separator_template) > 50
                else separator_template,
            )
        )
    applied = [(label, value) for label, value in shown if value is not None]
    if applied:
        out.print("[cyan]📝 Configuration overrides applied:[/cyan]")
        for label, value in applied:
            out.print(f"  • {label}: {value}")


def _apply_seeds_sequentially(
    builder: SchemaBuilder,
    out: Any,
    *,
    env: str,
    database_url: str | None,
    continue_on_error: bool,
    profile: Any,
    json_mode: bool,
    report_output: Path | None,
) -> tuple[int, list[BuildWarning]]:
    """``--sequential``: apply the seed files through the core sequencer.

    Returns:
        ``(applied, warnings)``. What the run has to say about the seeds is
        returned rather than printed, so the envelope carries it and the
        result renders it once (issue #268).
    """

    # The environment's `seed:` block is the default; the flag can only widen it.
    seed_settings = getattr(builder.env_config, "seed", None)
    continue_on_error = continue_on_error or bool(seed_settings and seed_settings.continue_on_error)
    transaction_mode = seed_settings.transaction_mode if seed_settings else "savepoint"
    out.print("\n[cyan]🌱 Applying seed files sequentially...[/cyan]")
    _schema_files, seed_files = builder.categorize_sql_files()
    if not seed_files:
        return 0, [BuildWarning.of("SEED_003", env=env)]
    try:
        result = apply_seed_files(
            database_url or builder.env_config.database_url,
            seed_files[0].parent.parent,
            env=env,
            profile=profile,
            continue_on_error=continue_on_error,
            transaction_mode=transaction_mode,
            console=console,
        )
    except ConfiturError as e:
        fail(e, json_mode=json_mode, output_file=report_output)
    out.print(f"[green]✅ Applied {result.succeeded} seed files[/green]")
    if result.failed == 0:
        return result.succeeded, []
    return result.succeeded, [BuildWarning.of("SEED_002", count=result.failed)]


def _write_dump_artifact(
    builder: SchemaBuilder,
    out: Any,
    *,
    dump: Path,
    dump_format: str,
    env: str,
    database_url: str | None,
    schema_hash: str,
    schema_only: bool,
    seed_profile: str | None,
    seed_profile_obj: Any,
    json_mode: bool,
    report_output: Path | None,
) -> tuple[str, str | None]:
    """``--dump``: a cacheable pg_dump artifact built from an ephemeral database.

    The artifact content always matches the db/ hash that names it.
    """
    if dump_format not in ("custom", "directory"):
        fail(
            ConfigurationError(
                f"Invalid dump format: {dump_format}. Use custom or directory.",
                resolution_hint="Pass --dump-format custom or directory.",
            ),
            json_mode=json_mode,
            output_file=report_output,
        )
    server_url = database_url or builder.env_config.database_url
    if not server_url:
        fail(
            ConfigurationError(
                "--dump requires a database server URL to build the ephemeral dump database.",
                error_code="CONFIG_010",
                resolution_hint="Provide --database-url or set it in the environment config.",
            ),
            json_mode=json_mode,
            output_file=report_output,
        )
    if dump.is_dir() or str(dump).endswith("/"):
        artifact_out = default_artifact_path(
            dump, env, schema_hash, profile=seed_profile, dump_format=dump_format
        )
    else:
        artifact_out = dump
    artifact_schema_sql = builder.build(schema_only=True)
    if schema_only:
        artifact_seed_files: list[Path] | None = None
    else:
        _schema_files, seed_paths = builder.categorize_sql_files()
        if seed_profile_obj is not None:
            seed_paths = apply_profile_filter(seed_paths, seed_profile_obj)
        artifact_seed_files = seed_paths or None
    artifact_result = build_schema_artifact(
        server_url=server_url,
        schema_sql=artifact_schema_sql,
        output_path=artifact_out,
        schema_hash=schema_hash,
        seed_files=artifact_seed_files,
        dump_format=dump_format,
    )
    path_str = str(artifact_result.artifact_path)
    if not json_mode:
        if artifact_result.skipped:
            out.print(f"[cyan]📦 Artifact up-to-date (cache hit): {path_str}[/cyan]")
        else:
            out.print(f"[green]📦 Artifact written: {path_str}[/green]")
    return path_str, artifact_result.artifact_hash


EnvOpt = Annotated[str, typer.Option("--env", "-e", help="Environment to lint (default: local)")]
ProjectDirOpt = Annotated[
    Path, typer.Option("--project-dir", help="Project directory (default: current directory)")
]
OutputOpt = Annotated[
    Path | None,
    typer.Option("--output", "-o", help="Output file path (default: stdout, only with json/csv)"),
]
FailOnOpt = Annotated[
    str | None,
    typer.Option(
        "--fail-on",
        help="Severity at which the run fails: error (default), warning, info "
        "or never. `--fail-on-error` and `--fail-on-warning` are aliases for "
        "the first two; passing both an alias and this exits 2. When no "
        "selected rule can emit at the threshold, the run says so instead of "
        "passing quietly (#247).",
    ),
]
FailOnErrorOpt = Annotated[
    bool,
    typer.Option("--fail-on-error", help="Alias for `--fail-on error` (default: on)"),
]
FailOnWarningOpt = Annotated[
    bool,
    typer.Option(
        "--fail-on-warning", help="Alias for `--fail-on warning` (default: off, stricter)"
    ),
]
SelectOpt = Annotated[
    list[str] | None,
    typer.Option(
        "--select",
        help="Rules or families to run, comma-separated (#150). `default` means "
        "the rules a plain lint runs, so `--select default,replica` is the "
        "defaults plus one family. Omit to run the defaults. "
        "See `--list-rules`.",
    ),
]
IgnoreOpt = Annotated[
    list[str] | None,
    typer.Option(
        "--ignore",
        help="Rules or families to skip, comma-separated. Applied after --select, "
        "so --ignore always wins.",
    ),
]
BaselineOpt = Annotated[
    Path | None,
    typer.Option(
        "--baseline",
        help="Baseline file (#219): fail only on findings it does not know, print only those, rewrite it when findings disappear",
    ),
]
WriteBaselineOpt = Annotated[
    bool,
    typer.Option(
        "--write-baseline", help="Create or reset the --baseline file from the current findings"
    ),
]
ListRulesOpt = Annotated[
    bool,
    typer.Option(
        "--list-rules",
        help="Print the rule catalogue (code, family, severity, default/opt-in) "
        "and exit 0. Honours --format json.",
    ),
]
ReplicaSafeOpt = Annotated[
    bool,
    typer.Option(
        "--replica-safe",
        help="Deprecated alias for `--select default,replica` (#139). Still "
        "supported; new rules register instead of adding a flag.",
    ),
]
MigrationsDirOpt = Annotated[
    Path,
    typer.Option(
        "--migrations-dir",
        help="Migrations directory the migration-tree rules read — replica_001, "
        "own_001, own_002 (default: db/migrations)",
    ),
]
OverridesDirOpt = Annotated[
    Path | None,
    typer.Option(
        "--overrides-dir",
        help="Overrides mirror directory. tree_004 needs it and is skipped without it: "
        "there is no conventional location to guess.",
    ),
]
ServerUrlOpt = Annotated[
    str | None,
    typer.Option(
        "--server-url",
        help="Writable PostgreSQL server the body family builds its scratch "
        "database on. Only the server is used: a throwaway database is created "
        "beside the configured one and dropped again. Defaults to the "
        "environment's own database_url.",
    ),
]
CheckTenantIsolationOpt = Annotated[
    bool,
    typer.Option(
        "--check-tenant-isolation",
        help="Deprecated alias for `--select default,tenant` (tenant_001): flag "
        "function INSERTs missing the FK column a tenant-scoped view requires.",
    ),
]
CheckSecurityDefinerOpt = Annotated[
    bool,
    typer.Option(
        "--check-security-definer",
        help="Deprecated alias for `--select default,security-definer`. Runs "
        "sec_002 over the env's schema DDL: flag SECURITY DEFINER "
        "functions/procedures that do not pin search_path (CVE-2018-1058). "
        "No-op when the config has no `security_lint:` block or "
        "`security_lint.enabled` is false. Default severity is advisory "
        "(warning); set `security_lint.severity: error` to make it a hard gate.",
    ),
]


@cli_boundary
def lint(
    ctx: typer.Context,
    env: EnvOpt = "local",
    project_dir: ProjectDirOpt = Path(),
    format_type: str = format_option("table", "json", "csv"),
    output: OutputOpt = None,
    fail_on: FailOnOpt = None,
    fail_on_error: FailOnErrorOpt = True,
    fail_on_warning: FailOnWarningOpt = False,
    select: SelectOpt = None,
    ignore: IgnoreOpt = None,
    baseline: BaselineOpt = None,
    write_baseline: WriteBaselineOpt = False,
    list_rules: ListRulesOpt = False,
    replica_safe: ReplicaSafeOpt = False,
    migrations_dir: MigrationsDirOpt = Path("db/migrations"),
    overrides_dir: OverridesDirOpt = None,
    server_url: ServerUrlOpt = None,
    check_tenant_isolation: CheckTenantIsolationOpt = False,
    check_security_definer: CheckSecurityDefinerOpt = False,
) -> None:
    """Validate schema against best practices.

    PROCESS:
      Runs the default rule set — naming_001, naming_002, pk_001, doc_001–doc_004,
      build_001, build_002, sec_001, qual_001 — plus whatever `--select` adds.
      `--list-rules` prints the full catalogue with codes and families. Results
      in table, JSON or CSV.

    RULES:
      Select by code or family: `--select pk,naming`, `--select naming_001`,
      `--ignore doc`. `default` means every rule that is on by default, so
      `--select default,replica` is the usual lint plus one opt-in family.
      `--ignore` wins over `--select`; an unknown selector exits 5.

      naming_001, naming_002, pk_001, doc_001–doc_004, build_001, build_002,
      build_003, sec_001, qual_001 — on by default. build_001 is the one that
      emits `error`, so a plain lint fails on a duplicate definition.

      Opt-in, each needing its configuration as well as its selector:
      acl_001 (`acls.lint_enabled: true`), tenant_001, replica_001, sec_002
      (`security_lint.enabled: true`), func_001 (`function_coverage.enabled:
      true`), own_001 / own_002 (an `ownership:` block), qual_002 (relations and
      types created without a schema), doc_005 (a COMMENT that says only what
      the object's own name says), and tree_001–tree_004, the DDL file-tree
      rules — `--select tree`; tree_004 also needs `--overrides-dir`.
      `--list-rules` prints all of it with the configuration each needs.

    EXAMPLES:
      confiture lint
        ↳ Lint local environment, display results as table

      confiture lint --list-rules
        ↳ Print every rule with its code, family and default state

      confiture lint --select pk,naming
        ↳ Run only the primary-key and naming families

      confiture lint --ignore doc
        ↳ The default rules, minus doc_001

      confiture lint --select default,qual_002
        ↳ Also report relations and types created without a schema

      confiture lint --select default,doc_005
        ↳ Also report a COMMENT that says only what the object's name says

      confiture lint --env production
        ↳ Lint production environment

      confiture lint --format json --output report.json
        ↳ Save linting report to JSON file

      confiture lint --fail-on warning
        ↳ Fail the run on warnings as well as errors (--fail-on-warning is an alias)

      confiture lint --fail-on never
        ↳ Report every finding and never fail — the setting the two booleans could not express

    RELATED:
      confiture build       - Build schema from DDL files
      confiture migrate up  - Apply migrations
      confiture schema-to-schema - Compare and sync schemas

    OPTIONS:
      CORE: --env, --format, --output
        What to lint and how to report results

      SEVERITY: --fail-on (error | warning | info | never)
        The one threshold that decides the exit code. --fail-on-error and
        --fail-on-warning are aliases; passing both an alias and --fail-on
        exits 2. A threshold no selected rule can reach is reported, not
        obeyed quietly.
    """
    try:
        if list_rules:
            _emit_rule_catalogue(format_type, output)
            return
        if write_baseline and baseline is None:
            error_console.print("[red]❌ Error: --write-baseline requires --baseline <file>[/red]")
            raise typer.Exit(USAGE_EXIT_CODE)
        threshold = _resolve_threshold(
            ctx, fail_on=fail_on, fail_on_error=fail_on_error, fail_on_warning=fail_on_warning
        )
        # One selection, resolved once (#150). The three per-rule flags are
        # aliases over it rather than branches further down: each adds its
        # family to the defaults, which is exactly what it always did.
        selected = _resolve_lint_rules(
            select=select,
            ignore=ignore,
            replica_safe=replica_safe,
            check_tenant_isolation=check_tenant_isolation,
            check_security_definer=check_security_definer,
        )
        config = _linter_config(selected, threshold, server_url)
        if format_type == "table":
            # The banner is for humans; in json/csv mode stdout is the payload alone.
            console.print(f"[cyan]🔍 Linting schema for environment: {env}[/cyan]")
        linter = SchemaLinter(env=env, project_dir=project_dir, config=config)
        linter_report = linter.lint()
        # LintConfig's switches are coarser than the rule codes — `check_naming`
        # covers naming_001 *and* naming_002 — so `--select naming_001` needs a
        # second pass over the findings.
        _keep_selected_rules(linter_report, selected)
        for violation in _tree_rule_findings(
            selected, env, project_dir, migrations_dir, overrides_dir
        ):
            linter_report.add_violation(violation)
        baseline_diff = _apply_baseline(
            linter_report, baseline=baseline, write=write_baseline, project_dir=project_dir
        )
        gate = compute_gate(
            threshold=threshold,
            selected=selected,
            escalations=_severity_escalations(env, project_dir, selected),
            baseline_active=baseline_diff is not None,
        )
        report = _convert_linter_report(
            linter_report,
            schema_name=env,
            baseline=None if baseline_diff is None else baseline_diff.summary(),
            gate=gate.to_dict(),
        )
        if format_type == "table":
            format_lint_report(report, format_type="table", console=console)
        else:
            fmt = "json" if format_type == "json" else "csv"
            formatted = format_lint_report(report, format_type=fmt, console=console)
            if output:
                save_report(report, output, format_type=fmt)
                console.print(f"[green]✅ Report saved to: {output.absolute()}[/green]")
            else:
                # print(), not console.print(): Rich wraps long lines at the
                # terminal width, which breaks the JSON stream (see _output_json).
                print(formatted)

        _print_gate_notice(gate, format_type)
        if baseline_diff is not None:
            _print_baseline_note(baseline_diff, format_type, wrote=write_baseline)
        found = [v.severity.value for v in report.violations]
        new_since_baseline = baseline_diff is not None and bool(baseline_diff.new)
        # A rule that did not run has established nothing, so it is not a pass:
        # the gate reads the severity its registry entry declares (#245).
        unrun = unrun_reaches([s.code for s in linter_report.skipped], threshold)
        if should_fail(found, threshold) or new_since_baseline or unrun:
            raise typer.Exit(FINDINGS_EXIT_CODE)  # success-signal: lint found violations
    except typer.Exit:
        raise
    except FileNotFoundError as e:
        if not is_json(format_type):
            console.print("\n💡 Tip: Make sure schema files exist in db/schema/")
        fail(e, json_mode=is_json(format_type), output_file=output)
    # Reason: lint's --output is its report path; the boundary cannot know that, so lint routes the envelope itself
    except Exception as e:
        # The one error boundary: an envelope in JSON mode, the Rich rendering otherwise.
        fail(e, json_mode=is_json(format_type), output_file=output)


def _passed_explicitly(ctx: typer.Context, name: str) -> bool:
    """Whether the operator typed this option, rather than inheriting its default.

    Compared by member name: Typer vendors its own click, so the
    ``ParameterSource`` a Typer context returns is not the ``click.core`` one
    and an identity test silently answers "no" for every option.
    """
    source = ctx.get_parameter_source(name)
    return source is not None and source.name == "COMMANDLINE"


def _resolve_threshold(
    ctx: typer.Context,
    *,
    fail_on: str | None,
    fail_on_error: bool,
    fail_on_warning: bool,
) -> Threshold:
    """The one severity that decides this run's exit code.

    ``--fail-on-error`` / ``--fail-on-warning`` are aliases for two of
    ``--fail-on``'s four values, so passing both a threshold and an alias states
    the gate twice — possibly two different ways. That is a usage error, not a
    precedence puzzle to resolve silently.
    """
    given_aliases = [
        flag
        for flag, name in (
            ("--fail-on-error", "fail_on_error"),
            ("--fail-on-warning", "fail_on_warning"),
        )
        if _passed_explicitly(ctx, name)
    ]
    if fail_on is None:
        return threshold_from_aliases(fail_on_error=fail_on_error, fail_on_warning=fail_on_warning)
    if given_aliases:
        error_console.print(
            f"[red]❌ Error: --fail-on and {', '.join(given_aliases)} both set the gate; "
            "pass one[/red]"
        )
        raise typer.Exit(USAGE_EXIT_CODE)
    return parse_threshold(fail_on)


def _print_gate_notice(gate: Gate, format_type: str) -> None:
    """Say, on the summary, when nothing this run selected could have failed it.

    The whole of #247: a pipeline set ``--fail-on-error``, no selected rule
    emitted at ``error``, and four real findings sat behind a green tick for
    months. ``--fail-on never`` is the same fact deliberately chosen, so it is
    stated rather than warned about.
    """
    if format_type != "table" or gate.reachable or gate.reason is None:
        return
    style = "dim" if gate.threshold is Threshold.NEVER else "yellow"
    console.print(f"\n[{style}]{gate.reason}[/{style}]")


def _severity_escalations(env: str, project_dir: Path, selected: frozenset[str]) -> dict[str, str]:
    """Selected rules whose configured severity is above the registry's declaration.

    Reachability that ignored these would tell a project that has escalated
    ``sec_002`` to ``error`` that its ``--fail-on error`` gate cannot fire, one
    sentence before it fires.
    """
    escalations: dict[str, str] = {}
    if "sec_002" in selected:
        cfg = _security_lint_config(env, project_dir)
        if cfg is not None and cfg.severity == "error":
            escalations["sec_002"] = "error"
    if "replica_001" in selected:
        has_replicas, bypass = _replica_policy(env, project_dir)
        if has_replicas and not bypass:
            escalations["replica_001"] = "error"
    return escalations


def _linter_config(
    selected: frozenset[str], threshold: Threshold, server_url: str | None = None
) -> LinterConfig:
    """``LintConfig``'s coarse switches, from the exact set of selected codes.

    Its two ``fail_on_*`` booleans decide nothing — the gate does — so they are
    derived from the threshold rather than carried alongside it.
    """
    return LinterConfig(
        enabled=True,
        fail_on_error=threshold.rank <= Threshold.ERROR.rank,
        fail_on_warning=threshold.rank <= Threshold.WARNING.rank,
        check_naming="naming_001" in selected or "naming_002" in selected,
        check_primary_keys="pk_001" in selected,
        check_documentation=any(code.startswith("doc_") for code in selected),
        check_restatements="doc_005" in selected,
        check_duplicates=any(code in selected for code in ("build_001", "build_002")),
        check_references="build_003" in selected,
        check_security="sec_001" in selected,
        check_tenant_isolation="tenant_001" in selected,
        check_acl_coverage="acl_001" in selected,
        check_qualification="qual_001" in selected,
        check_qualification_relations="qual_002" in selected,
        check_bodies="body_001" in selected,
        check_body_warnings="body_002" in selected,
        server_url=server_url,
    )


def _tree_rule_findings(
    selected: frozenset[str],
    env: str,
    project_dir: Path,
    migrations_dir: Path,
    overrides_dir: Path | None = None,
) -> list[LintViolation]:
    """The rules that read a tree of files rather than the built schema.

    They are findings like any other — same report, same baseline, same gate —
    and they name their files the way the rest of the report does. Every one of
    them is selected by code here rather than through ``LintConfig``'s coarser
    switches, because they run after ``_keep_selected_rules`` has already passed.
    """
    findings: list[LintViolation] = []
    if "replica_001" in selected:
        findings += _replica_findings(env, project_dir, migrations_dir)
    if "sec_002" in selected:
        findings += _security_definer_findings(env, project_dir)
    if "func_001" in selected:
        findings += _function_uniqueness_findings(env, project_dir)
    if selected & {"own_001", "own_002"}:
        findings += _ownership_findings(selected, env, project_dir, migrations_dir)
    if selected & set(TREE_RULE_CODES):
        findings += _ddl_tree_findings(selected, env, project_dir, overrides_dir)
    return [_relative(v, project_dir) for v in findings]


def _under(path: Path | None, project_dir: Path) -> Path | None:
    """A directory an operator named, read relative to ``--project-dir``.

    ``--migrations-dir`` and ``--overrides-dir`` are project-relative like
    ``--baseline`` is; three rules read the first of them and they must all read
    the same directory.
    """
    if path is None or path.is_absolute():
        return path
    return project_dir / path


def _env_ddl_files(env: str, project_dir: Path) -> tuple[list[Path], list[Path]]:
    """``(the files the build reads, the roots it reads them from)``.

    One answer for every rule that walks the DDL tree, so none of them reports a
    file the environment's ``exclude_dirs`` or per-directory ``exclude`` globs
    keep out of the build (LINT-08). A project whose config will not load has no
    build to describe, so it has no tree to lint.
    """
    try:
        builder = _core_builder.SchemaBuilder(env=env, project_dir=project_dir)
        return builder.find_sql_files(), list(builder.include_dirs)
    except (ConfiturError, OSError):
        return [], []


def _ddl_tree_findings(
    selected: frozenset[str], env: str, project_dir: Path, overrides_dir: Path | None
) -> list[LintViolation]:
    """#111: tree_001–tree_004 over the DDL file tree the environment builds."""
    files, roots = _env_ddl_files(env, project_dir)
    # A config that will not load has already left `files` empty, so the
    # fallback here is a spelling of "nothing to report", not a second default.
    lint_settings = _env_block(env, project_dir, "lint")
    return tree_violations(
        files,
        selected=selected,
        schema_dirs=roots,
        overrides_dir=_under(overrides_dir, project_dir),
        status_words=(
            DEFAULT_STATUS_WORDS if lint_settings is None else lint_settings.status_words
        ),
    )


def _function_uniqueness_findings(env: str, project_dir: Path) -> list[LintViolation]:
    """#136: func_001 — one definition per function signature across the DDL tree."""
    # Reason: CLI start-up: the rule is opt-in, so its import is deferred until it is selected
    from confiture.core.linting.libraries.functions import Func001FunctionUniqueness

    coverage = _env_block(env, project_dir, "function_coverage")
    if coverage is None or not coverage.enabled:
        return []
    files, roots = _env_ddl_files(env, project_dir)
    return Func001FunctionUniqueness(coverage=coverage).check(files or roots)


def _ownership_findings(
    selected: frozenset[str], env: str, project_dir: Path, migrations_dir: Path
) -> list[LintViolation]:
    """#124/#137: own_001 and own_002 over the migrations tree."""
    # Reason: CLI start-up: the rules are opt-in, so their import is deferred until one is selected
    from confiture.core.linting.libraries.ownership import (
        Own001OwnershipCoverage,
        Own002BareAlterOwner,
    )

    expectation = _env_block(env, project_dir, "ownership")
    if expectation is None:
        return []
    resolved = _under(migrations_dir, project_dir)
    findings: list[LintViolation] = []
    if "own_001" in selected:
        findings += Own001OwnershipCoverage(expectation=expectation).check(resolved)
    if "own_002" in selected:
        findings += Own002BareAlterOwner(expectation=expectation).check(resolved)
    return findings


def _env_block(env: str, project_dir: Path, attribute: str) -> Any:
    """One optional block of the environment config, or ``None`` when it is absent.

    A rule whose configuration is missing has nothing to report — the same
    contract ``_security_lint_config`` and ``_replica_policy`` keep, and the
    reason each of these rules declares a ``requires_config``.
    """
    try:
        return getattr(Environment.load(env, project_dir=project_dir), attribute)
    except (ConfiturError, OSError):
        return None


def _relative(violation: LintViolation, project_dir: Path) -> LintViolation:
    """A finding names its file the way the rest of the report does."""
    if violation.file_path is None:
        return violation
    return replace(violation, file_path=label_for(Path(violation.file_path), project_dir))


def _replica_findings(env: str, project_dir: Path, migrations_dir: Path) -> list[LintViolation]:
    """#139: replica-aware forward-compatibility lint over the migrations tree.

    A migration-tree check, distinct from the schema lint — but a finding all
    the same, so it joins the report every other rule writes to instead of
    printing itself to the console and deciding its own exit code.
    """
    # Reason: CLI start-up: importing confiture.core.linting.libraries.replica costs ~28 ms at start (importtime, 2026-09-07); deferred until the command runs
    from confiture.core.linting.libraries.replica import Replica001ForwardCompat

    has_replicas, bypass = _replica_policy(env, project_dir)
    return Replica001ForwardCompat(has_replicas=has_replicas, bypass=bypass).check(
        _under(migrations_dir, project_dir)
    )


def _replica_policy(env: str, project_dir: Path) -> tuple[bool, bool]:
    """``(replicas declared, unsafe DDL allowed anyway)`` — what decides replica_001's severity."""
    try:
        _env = Environment.load(env, project_dir=project_dir)
    # Reason: replica config is optional; any failure reading it means 'no replicas'
    except Exception:
        return False, False
    return bool(_env.infrastructure.replicas), _env.migration.allow_unsafe_under_replication


def _security_definer_findings(env: str, project_dir: Path) -> list[LintViolation]:
    """#161: sec_002 — SECURITY DEFINER / search_path over the env's schema DDL.

    Findings join the report, so `lint --format json` carries them and
    `--baseline` can absorb them (LINT-03). They used to print straight to the
    console, which in a machine-output mode meant printing *into* the payload.
    """
    sec_cfg = _security_lint_config(env, project_dir)
    if sec_cfg is None:
        return []
    severity = _RS.ERROR if sec_cfg.severity == "error" else _RS.WARNING
    ddl_paths, roots = _env_ddl_files(env, project_dir)
    return Sec002SecurityDefinerSearchPath(
        apply_to=sec_cfg.apply_to, ignore=sec_cfg.ignore, severity=severity
    ).check(ddl_paths or roots or [Path("db/schema")])


def _security_lint_config(env: str, project_dir: Path) -> Any:
    """The env's ``security_lint:`` block, or ``None`` when absent or disabled."""
    try:
        cfg_path = (project_dir or Path.cwd()) / "db" / "environments" / f"{env}.yaml"
        if not cfg_path.exists():
            return None
        cfg = _lsl(_lc(cfg_path), cfg_path, require=False)
    # Reason: security config is optional; any failure reading it means 'defaults'
    except Exception:
        return None
    return cfg if cfg is not None and cfg.enabled else None


def _apply_baseline(
    linter_report: LinterReport, *, baseline: Path | None, write: bool, project_dir: Path
) -> Any:
    """Keep only the findings the baseline does not know; write or tighten the file (#219).

    Returns the ``BaselineDiff`` (``None`` without ``--baseline``). ``--write-baseline``
    records every current finding and leaves nothing to report; otherwise findings
    the file knows are dropped from the report, identities no longer found are
    removed from the file (D12), and what remains is new.
    """
    if baseline is None:
        return None

    path = baseline if baseline.is_absolute() else project_dir / baseline
    buckets = (linter_report.errors, linter_report.warnings, linter_report.info)
    current = [v for bucket in buckets for v in bucket]
    if write:
        Baseline.from_violations(current).write(path)
        for bucket in buckets:
            bucket[:] = []
        return BaselineDiff(known=len({identity(v) for v in current}))
    known = Baseline.load(path)
    diff = known.diff(current)
    if diff.fixed:
        known.without(diff.fixed).write(path)
    new_identities = {identity(v) for v in diff.new}
    for bucket in buckets:
        bucket[:] = [v for v in bucket if identity(v) in new_identities]
    return diff


def _print_baseline_note(diff: Any, format_type: str, *, wrote: bool) -> None:
    """One human line about the baseline — only when something happened, never in JSON/CSV."""
    if format_type != "table":
        return
    if wrote:
        console.print(f"[green]✅ Baseline written: {diff.known} finding(s) recorded[/green]")
    elif diff.new or diff.fixed:
        console.print(
            f"[cyan]Baseline: {diff.known} known, {len(diff.new)} new, "
            f"{len(diff.fixed)} fixed{' (file tightened)' if diff.fixed else ''}[/cyan]"
        )


def _keep_selected_rules(linter_report: LinterReport, selected: frozenset[str]) -> None:
    """Drop findings whose rule was deselected (#150), in place.

    Only rules the registry knows are filtered. A violation carrying an
    unregistered code — a rule added to the linter without registering it, or a
    consumer's own — is passed through rather than silently swallowed: it could
    not have been selected, and dropping it would turn "I forgot to register my
    rule" into "my rule stopped reporting".
    """

    known = {rule.code for rule in LINT_RULES}
    for bucket in (linter_report.errors, linter_report.warnings, linter_report.info):
        bucket[:] = [v for v in bucket if v.rule_id in selected or v.rule_id not in known]


def _resolve_lint_rules(
    *,
    select: list[str] | None,
    ignore: list[str] | None,
    replica_safe: bool,
    check_tenant_isolation: bool,
    check_security_definer: bool,
) -> frozenset[str]:
    """The rule codes this invocation applies, legacy flags folded in.

    Each legacy flag means "the defaults *plus* this family", which is what it
    did when it was a branch of its own. Expressing them as selectors keeps one
    dispatch path — the point of #150 — and makes them exactly equivalent to the
    ``--select`` form they are documented as aliasing.

    Raises:
        ConfigurationError: An unknown code or family was named.
    """

    aliases = [
        rule_family
        for enabled, rule_family in (
            (replica_safe, "replica"),
            (check_tenant_isolation, "tenant"),
            (check_security_definer, "security-definer"),
        )
        if enabled
    ]
    effective = list(select or [])
    if aliases:
        # A bare legacy flag keeps the default rules; combined with --select it
        # extends whatever that selected, rather than re-adding the defaults.
        effective = (effective or [DEFAULT_SELECTOR]) + aliases
    return resolve_selection(effective or None, ignore or ())


def _emit_rule_catalogue(format_type: str, output: Path | None) -> None:
    """Print the rule registry: `confiture lint --list-rules`.

    A report mode — it never consults the schema and always exits 0, so it works
    in a project that does not lint cleanly (or at all).
    """

    if is_json(format_type):
        _output_json(
            {
                "version": "1",
                "status": "ok",
                "rules": [rule.to_dict() for rule in LINT_RULES],
                "hints": [],
            },
            output,
            console,
        )
        return

    table = Table(title="confiture lint rules", show_lines=False)
    table.add_column("Code", style="cyan")
    table.add_column("Family", style="magenta")
    table.add_column("Severity")
    table.add_column("Default")
    table.add_column("Description")
    for rule in LINT_RULES:
        table.add_row(
            rule.code,
            rule.family,
            rule.severity,
            "on" if rule.default_on else "opt-in",
            rule.title + (f" (needs {rule.requires_config})" if rule.requires_config else ""),
        )
    console.print(table)
    console.print(
        "\n[dim]Select with --select <family|code>[,…]; skip with --ignore. "
        "`default` selects every rule marked on.[/dim]"
    )
    aliases = ", ".join(
        f"{old.upper()} → {new}" for old, new in sorted(LEGACY_CODE_ALIASES.items())
    )
    console.print(f"[dim]Deprecated selectors, accepted for one minor: {aliases}.[/dim]")


def _unified_tree_findings(
    env: str, schema_dir: Path | None, overrides_dir: Path | None
) -> list[LintViolation]:
    """``lint-unified --check tree``'s findings, resolved the way ``lint`` resolves them.

    ``--schema-dir`` names a tree explicitly; without it the environment's own
    include configuration decides, which is what the flag's help has always
    claimed and what ``confiture lint --select tree`` does. Two commands, one
    answer to "which files is this rule about".
    """
    if schema_dir is not None:
        files = sorted(f for f in schema_dir.rglob("*.sql") if f.is_file())
        roots = [schema_dir]
    else:
        files, roots = _env_ddl_files(env, Path())
    return [
        _relative(v, Path())
        for v in tree_violations(files, schema_dirs=roots, overrides_dir=overrides_dir)
    ]


@cli_boundary
def lint_unified(
    files: list[Path] = typer.Argument(
        default=None,
        help="SQL files or directories to lint (default: all schema files)",
    ),
    check: list[str] = typer.Option(
        None,
        "--check",
        "-c",
        help="Which checks to run: safety (squawk), format (sqlfluff), schema (SchemaLinter), tree (tree_001–tree_004 file-numbering). "
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
    schema_dir: Path | None = typer.Option(
        None,
        "--schema-dir",
        help="Root of the DDL file tree for --check tree (default: the directories --env's "
        "include_dirs builds from, minus what it excludes).",
    ),
    overrides_dir: Path | None = typer.Option(
        None,
        "--overrides-dir",
        help="Overrides mirror directory for the tree_004 orphan check (optional).",
    ),
    format_type: str = format_option("table", "json"),
    fail_on_error: bool = typer.Option(
        True,
        "--fail-on-error",
        help="Exit with code 1 if errors found (default: on)",
    ),
) -> None:
    """Run unified SQL lint checks (Squawk, SQLFluff, SchemaLinter, and/or tree numbering).

    EXAMPLES:
      confiture lint-unified db/migrations/
        Lint all SQL files in migrations directory with all available tools.

      confiture lint-unified --check safety
        Run only Squawk safety checks.

      confiture lint-unified --check schema --env local
        Run only SchemaLinter checks on the local environment.

      confiture lint-unified --check tree --schema-dir db/schema/
        Check DDL file-tree numbering rules (tree_001–tree_004): duplicate prefixes,
        verb suffixes, sequence gaps, and orphaned overrides. Without --schema-dir
        the tree is the one --env builds from.

      confiture lint-unified --git-diff
        Lint only SQL files changed in the current git diff.
    """

    checks = list(check) if check else None

    # Handle schema checks separately (uses SchemaLinter)
    run_schema = checks is None or "schema" in (checks or [])
    run_tree = checks is None or "tree" in (checks or [])
    run_tool_checks = checks is None or any(c in (checks or []) for c in ("safety", "format"))

    all_issues: list = []

    if run_tool_checks:
        linter = UnifiedLinter()
        result = linter.run(files=list(files) if files else None, checks=checks, git_diff=git_diff)
        all_issues.extend(result.issues)

    if run_schema:
        schema_config = LinterConfig(enabled=True, fail_on_error=fail_on_error)
        schema_linter = _core_linting.SchemaLinter(env=env, config=schema_config)
        try:
            linter_report = schema_linter.lint()
            all_issues.extend(
                _violation_to_unified_issue(v, "schema", file=env)
                for v in linter_report.errors + linter_report.warnings + linter_report.info
            )
        # Reason: lint-unified skips a linter that fails for any reason and says so
        except Exception as e:
            console.print(f"[yellow]Schema lint skipped: {e}[/yellow]")

    if run_tree:
        try:
            all_issues.extend(
                _violation_to_unified_issue(v, "tree")
                for v in _unified_tree_findings(env, schema_dir, overrides_dir)
            )
        # Reason: lint-unified skips a linter that fails for any reason and says so
        except Exception as e:
            console.print(f"[yellow]Tree lint skipped: {e}[/yellow]")

    unified_result = UnifiedLintResult(issues=all_issues)

    if format_type == "json":
        print(json.dumps(unified_result.to_dict(), indent=2))
    elif not unified_result.issues:
        console.print("[green]No issues found.[/green]")
    else:
        for tool, tool_issues in unified_result.by_tool.items():
            console.print(f"\n[bold]{tool}[/bold] ({len(tool_issues)} issue(s)):")
            for issue in tool_issues:
                sev = issue.severity.value.upper()
                loc = f"{issue.file}:{issue.line}" if issue.line else issue.file
                rule = f" [{issue.rule}]" if issue.rule else ""
                # markup=False: every field is data. Rich reads `[tree_001]` as a
                # style tag and prints nothing where the rule id should be — the
                # uppercase codes only survived because they are not style names.
                console.print(f"  [{sev}]{rule} {loc}: {issue.message}", markup=False)

    if fail_on_error and unified_result.has_errors:
        raise typer.Exit(FINDINGS_EXIT_CODE)  # success-signal: lint found errors


@cli_boundary
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
    format_type: str = format_option("json", "yaml"),
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
    _console = _Console(stderr=True)

    # introspect emits json or yaml; the unified error envelope is JSON, so we
    # route failures through fail() in JSON mode only when the requested format
    # is json (yaml failures fall back to the human path).
    json_mode = is_json(format_type)

    try:
        conn = connect(db)
    except (ConfiturError, psycopg.Error) as e:
        fail(
            ConfigurationError(
                f"Connection failed: {e}",
                error_code="CONFIG_006",
            ),
            json_mode=json_mode,
            output_file=output,
        )

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
