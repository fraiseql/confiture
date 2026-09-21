"""``confiture build``: concatenate the schema tree into one DDL file, or apply it."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.console import Console

from confiture.cli.error_json import cli_boundary, fail
from confiture.cli.formatters.build_formatter import (
    format_build_result,
    format_selection_report,
)
from confiture.cli.helpers import (
    console,
    error_console,
    is_json,
)
from confiture.cli.options import (
    ProjectDirOpt,
    database_url_option,
    env_option,
    format_option,
    output_option,
)
from confiture.core.builder import SchemaBuilder
from confiture.core.linting.duplicates import duplicate_violations, find_duplicates, inventory_files
from confiture.core.progress import ProgressManager
from confiture.core.schema_artifact import build_schema_artifact, default_artifact_path
from confiture.core.seed.applier import apply_profile_filter
from confiture.core.seed.paths import is_seed_path
from confiture.core.seed.sequencer import apply_seed_files
from confiture.error_codes import FINDINGS
from confiture.exceptions import ConfigurationError, ConfiturError, SchemaError
from confiture.models.results import BuildResult
from confiture.models.warnings import BuildWarning

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
_SEPARATOR_STYLES = ("block_comment", "line_comment", "mysql", "custom")


@cli_boundary
def build(
    env: str = env_option(),
    output: Path | None = output_option(
        help="Output file path (default: db/generated/schema_{env}.sql)"
    ),
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
    database_url: str | None = database_url_option(
        help="Database connection URL (required for --sequential, default: from config)"
    ),
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
        schema, schema_file_count, duplicates, warnings = _run_build(
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
) -> tuple[list[dict[str, Any]], list[BuildWarning]]:
    """Scan the build's files for duplicate definitions when asked (#218).

    ``--warn-duplicates`` reports and builds; ``--fail-on-duplicates`` reports
    and exits 1 before anything is written. A plain build does not scan.

    Returns:
        ``(duplicates, warnings)`` — a file the scan could not parse was not
        checked, which the envelope says rather than only the console (#268).
    """
    if not (warn or fail):
        return [], []

    objects, _schemas, unparseable = inventory_files(sql_files, root=project_dir)
    warnings = [BuildWarning.of("SCHEMA_206", file=r.label) for r in unparseable]
    duplicates = find_duplicates(objects)
    if not duplicates:
        return [], warnings
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
            warnings=warnings,
            duplicates=payload,
            error=f"{len(duplicates)} duplicate definition(s); nothing was built",
        )
        format_build_result(result, "json" if json_mode else "text", report_output, console)
        raise typer.Exit(FINDINGS)  # success-signal: the duplicate gate tripped
    return payload, warnings


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
) -> tuple[str, int, Any, list[BuildWarning]]:
    """Concatenate the schema under a progress bar, after ``duplicate_gate`` saw the files.

    Returns:
        ``(schema, schema_file_count, duplicates, warnings)``; the seed files
        are left to the sequential applier when ``apply_sequential``.
    """
    out.print(f"[cyan]🔨 Building schema for environment: {env}[/cyan]")

    with ProgressManager() as progress:
        sql_files = builder.find_sql_files()
        duplicates, warnings = duplicate_gate(sql_files)
        if apply_sequential:
            schema = builder.build(output_path=output, schema_only=True, progress=progress)
            schema_file_count = len([f for f in sql_files if not builder.is_seed_file(f)])
        else:
            schema = builder.build(output_path=output, progress=progress)
            schema_file_count = len(sql_files)
    out.print(f"[cyan]📄 Found {len(sql_files)} SQL files[/cyan]")
    return schema, schema_file_count, duplicates, warnings


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
