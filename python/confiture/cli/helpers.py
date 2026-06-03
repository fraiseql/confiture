"""Shared helpers for Confiture CLI commands."""

import difflib
import json
import os
import re
from pathlib import Path
from typing import Any

from rich.console import Console

from confiture.core.idempotency.python_migration_extractor import (
    is_migration_file as _is_migration_file,
)
from confiture.core.linting.schema_linter import (
    LintReport as LinterReport,
)
from confiture.core.linting.schema_linter import (
    RuleSeverity,
)
from confiture.models.lint import LintReport, LintSeverity, Violation

_VALID_ENV_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_\-]*$")

# Create Rich consoles for stdout and stderr. Use stderr=True (not
# file=sys.stderr) so the stream is resolved dynamically at write time — this
# keeps it correct under pytest's capsys, which swaps sys.stderr per test.
console = Console()
error_console = Console(stderr=True)

_MACHINE_OUTPUT_FORMATS = frozenset({"json", "csv", "yaml"})


def _emit_hint(
    hint: str,
    *,
    hints_list: list[str],
    format_: str,
    error_console: Console | None = None,
) -> None:
    """Emit an advisory "looks unusual" hint via the right channel.

    Hints are dual-channel based on the output format:

    - ``format_ == "text"`` → write to ``error_console`` (stderr).
    - ``format_ in {"json", "csv", "yaml"}`` → append to ``hints_list``
      so it lands in the machine-readable payload under ``"hints": [...]``;
      nothing goes to stderr (agents pipe stdout, not stderr).

    Hints never change the exit code — they are pure agent-experience
    breadcrumbs.

    ``error_console`` defaults to the module-level :data:`error_console`
    looked up at call time, so test fixtures that monkeypatch the
    module-level binding take effect.
    """
    if format_ in _MACHINE_OUTPUT_FORMATS:
        hints_list.append(hint)
        return
    target = error_console or globals()["error_console"]
    target.print(f"[dim]Hint: {hint}[/dim]")


# Common command names for "Did you mean?" suggestions
COMMON_COMMANDS = [
    "init",
    "build",
    "migrate",
    "lint",
    "introspect",
    "seed",
    "branch",
    "generate",
    "coordinate",
    "install-helpers",
    "restore",
    "migrate-up",
    "migrate-down",
    "migrate-status",
    "migrate-validate",
]


def _get_suggestion(unknown_command: str) -> str | None:
    """Get "Did you mean?" suggestion for unknown command.

    Uses difflib to find similar commands (75% similarity threshold).

    Args:
        unknown_command: The command user tried to run

    Returns:
        Suggested command if match found (>75% similarity), None otherwise
    """
    matches = difflib.get_close_matches(unknown_command, COMMON_COMMANDS, n=1, cutoff=0.75)
    return matches[0] if matches else None


def _convert_linter_report(linter_report: LinterReport, schema_name: str = "schema") -> LintReport:
    """Convert a schema_linter.LintReport to models.lint.LintReport.

    Args:
        linter_report: Report from SchemaLinter
        schema_name: Name of schema being linted

    Returns:
        LintReport compatible with format_lint_report
    """
    violations = []

    # Map RuleSeverity to LintSeverity
    severity_map = {
        RuleSeverity.ERROR: LintSeverity.ERROR,
        RuleSeverity.WARNING: LintSeverity.WARNING,
        RuleSeverity.INFO: LintSeverity.INFO,
    }

    # Convert all violations
    for violation in linter_report.errors:
        violations.append(
            Violation(
                rule_name=violation.rule_name,
                severity=severity_map[violation.severity],
                message=violation.message,
                location=violation.object_name,
            )
        )

    for violation in linter_report.warnings:
        violations.append(
            Violation(
                rule_name=violation.rule_name,
                severity=severity_map[violation.severity],
                message=violation.message,
                location=violation.object_name,
            )
        )

    for violation in linter_report.info:
        violations.append(
            Violation(
                rule_name=violation.rule_name,
                severity=severity_map[violation.severity],
                message=violation.message,
                location=violation.object_name,
            )
        )

    return LintReport(
        violations=violations,
        schema_name=schema_name,
        tables_checked=0,  # Not tracked in linter
        columns_checked=0,  # Not tracked in linter
        errors_count=len(linter_report.errors),
        warnings_count=len(linter_report.warnings),
        info_count=len(linter_report.info),
        execution_time_ms=0,  # Not tracked in linter
    )


def _output_yaml(data: dict[str, Any], output_file: Path | None, console: Console) -> None:
    """Output YAML data to file or console.

    Args:
        data: Data to serialise as YAML.
        output_file: Optional file to write to; if None, writes to stdout.
        console: Console used for status messages (stderr).
    """
    import yaml

    yaml_str = yaml.dump(data, default_flow_style=False, sort_keys=False, allow_unicode=True)
    if output_file:
        output_file.write_text(yaml_str)
        console.print(f"[green]✅ Output written to {output_file}[/green]")
    else:
        print(yaml_str, end="")


_DEFAULT_CONFIG = Path("confiture.yaml")


def _resolve_config(config: Path, env: str | None) -> Path:
    """Resolve --config / --env to a single config Path.

    --env is a shortcut for db/environments/{name}.yaml.
    --config accepts any path (for non-standard layouts).
    Raises ConfigurationError when both are explicitly set.

    Args:
        config: Value of the --config option (may be the default Path("confiture.yaml"))
        env: Value of the --env option (None if not given)

    Returns:
        Resolved config file path

    Examples:
        >>> _resolve_config(Path("confiture.yaml"), "local")
        PosixPath('db/environments/local.yaml')
        >>> _resolve_config(Path("custom.yaml"), None)
        PosixPath('custom.yaml')
    """
    from confiture.exceptions import ConfigurationError  # noqa: PLC0415

    if env and config != _DEFAULT_CONFIG:
        raise ConfigurationError(
            "Cannot use --env and --config together. "
            "Use --env as a shortcut for db/environments/{name}.yaml, "
            "or --config for a custom path."
        )
    if env:
        if not _VALID_ENV_RE.match(env):
            raise ConfigurationError(
                f"Invalid environment name: {env!r}. "
                "Use only letters, digits, hyphens, and underscores."
            )
        return Path("db") / "environments" / f"{env}.yaml"
    return config


# The two recognized DSN env vars, treated *differently* by intent (#152):
#   - CONFITURE_DATABASE_URL: canonical, confiture-specific, set on purpose.
#   - DATABASE_URL: ambient, ubiquitous in CI/deploy; must never silently
#     clobber a config.
_CONFITURE_DSN_ENV = "CONFITURE_DATABASE_URL"
_AMBIENT_DSN_ENV = "DATABASE_URL"
_DATABASE_URL_ENV_VARS = (_CONFITURE_DSN_ENV, _AMBIENT_DSN_ENV)

# Shared --help text for the --no-config flag across the migrate family (#152).
NO_CONFIG_OPTION_HELP = (
    "Suppress config-file discovery entirely; the environment "
    "(CONFITURE_DATABASE_URL, else DATABASE_URL) becomes the sole DSN source. "
    "Use this for runtime-resolved DSNs that must not be exposed in argv."
)

# Shared --help text for the --database-url flag across the migrate family (#140).
DATABASE_URL_OPTION_HELP = (
    "PostgreSQL DSN for the tracking database. Always wins over --config / --env "
    "and the env vars. The canonical CONFITURE_DATABASE_URL beats a *default* "
    "--config but conflicts with an *explicit* one (CONFIG_007); the ambient "
    "DATABASE_URL never overrides a present config. Pass --no-config to make the "
    "environment the sole source. When a DSN is supplied, no YAML is required "
    "(tracking table defaults to tb_confiture). SSH-tunnel configs still require "
    "--config."
)


def resolve_database_url(
    flag: str | None,
    config_path: Path | None,
    *,
    config_explicit: bool = False,
    no_config: bool = False,
    require_intentional_source: bool = False,
) -> str | None:
    """Resolve the tracking-database DSN under the #152 precedence contract.

    Principle: **explicit-and-singular wins; ambiguity fails loud** — the secure
    default for a tool that touches production. Order:

    1. ``--database-url`` flag — always wins (validated).
    2. ``--no-config`` — config discovery is suppressed, the environment is the
       sole source: ``CONFITURE_DATABASE_URL`` preferred over the ambient
       ``DATABASE_URL``; neither set → ``CONFIG_010`` (fail loud).
    3. An **explicit** ``--config``/``--env`` **and** ``CONFITURE_DATABASE_URL``
       both present → ``CONFIG_007`` (fail loud; two explicit sources are never
       silently reconciled — no DSN normalization, no "pick one").
    4. An explicit ``--config``/``--env`` only → defer to the config (``None``);
       an ambient ``DATABASE_URL`` does NOT override an explicit config.
    5. ``CONFITURE_DATABASE_URL`` set while the config is only the **default** →
       the canonical var (it beats a default config — the bug #152 fixes).
    6. A present config file (even the default) → defer to it (``None``); it
       beats the ambient ``DATABASE_URL``.
    7. Otherwise the ambient ``DATABASE_URL`` — unless
       ``require_intentional_source`` (mutating commands), where an ambient-only
       DSN raises ``CONFIG_010`` rather than silently migrating against it.
    8. Nothing resolved → ``None`` (the caller has no source).

    Args:
        flag: ``--database-url`` value (``None`` if not given).
        config_path: The resolved ``--config`` path. Its default is a *present*
            file, so existence alone cannot tell default from explicit — hence
            ``config_explicit``.
        config_explicit: Whether ``--config`` or ``--env`` was set explicitly
            (vs defaulted). The command recovers this via ``config_is_explicit``
            from ``ctx.get_parameter_source`` for the ``config`` and ``env``
            parameters.
        no_config: Whether ``--no-config`` was passed (suppress config discovery).
        require_intentional_source: For mutating commands (``up``/``down``):
            refuse to run against a merely-ambient ``DATABASE_URL``.

    Returns:
        The DSN to use as ``database_url_override``, or ``None`` to defer to the
        config file.

    Raises:
        ConfigurationError: ``CONFIG_003`` (malformed flag DSN), ``CONFIG_007``
            (two explicit sources), or ``CONFIG_010`` (no usable source).
    """
    from confiture.exceptions import ConfigurationError  # noqa: PLC0415

    # (1) An explicit flag always wins.
    if flag:
        if not flag.startswith(("postgresql://", "postgres://")):
            raise ConfigurationError(
                f"Invalid --database-url: must start with postgresql:// or "
                f"postgres://, got: {flag}",
                error_code="CONFIG_003",
                resolution_hint="Use format: postgresql://user:password@host:port/database",
            )
        return flag

    confiture_url = os.environ.get(_CONFITURE_DSN_ENV)
    ambient_url = os.environ.get(_AMBIENT_DSN_ENV)

    # (2) --no-config: the environment is the sole source.
    if no_config:
        if confiture_url:
            return confiture_url
        if ambient_url:
            return ambient_url
        raise ConfigurationError(
            "--no-config was given but no DSN is set in the environment",
            error_code="CONFIG_010",
            resolution_hint=(
                "Set CONFITURE_DATABASE_URL (or DATABASE_URL), or drop --no-config "
                "to use a config file."
            ),
        )

    # (3) Two explicit sources → fail loud, period (present-at-all, not differing).
    if config_explicit and confiture_url:
        raise ConfigurationError(
            "Both an explicit --config/--env and CONFITURE_DATABASE_URL are set",
            error_code="CONFIG_007",
            resolution_hint=(
                "Pass exactly one explicit source: drop --config/--env, unset "
                "CONFITURE_DATABASE_URL, or pass --no-config."
            ),
        )

    # (4) Explicit config (no canonical var) → use it; ambient never overrides it.
    if config_explicit:
        return None

    # config_path is at most the DEFAULT below here.
    # (5) The canonical var beats a default config.
    if confiture_url:
        return confiture_url

    # (6) A present (default) config beats the ambient DATABASE_URL.
    if config_path is not None and config_path.exists():
        return None

    # (7) Ambient DATABASE_URL — refused for mutating commands.
    if ambient_url:
        if require_intentional_source:
            raise ConfigurationError(
                "No intentional DSN source for a mutating command; refusing to run "
                "against an ambient DATABASE_URL",
                error_code="CONFIG_010",
                resolution_hint=(
                    "Pass --database-url, set CONFITURE_DATABASE_URL, or point "
                    "--config at a config file."
                ),
            )
        return ambient_url

    # (8) No source.
    return None


def config_is_explicit(ctx: Any, *params: str) -> bool:
    """Whether ``--config`` or ``--env`` was set explicitly, not defaulted (#152).

    The migrate family defaults ``--config`` to a *present* file
    (``db/environments/local.yaml``), so the resolved ``Path`` cannot tell a
    default from an operator-supplied one. Click's parameter source can — this
    is the linchpin that makes the precedence contract expressible.

    Checks ``config`` and ``env`` by default (a command may carry either —
    ``preflight`` has both). A parameter the command does not declare yields no
    source and is ignored, so passing the full set is always safe. Returns
    ``True`` if *any* checked parameter was set on the command line / via env
    rather than defaulted; ``False`` defensively when no source is available.

    Compares the ``click.core.ParameterSource`` enum by member name rather than
    importing it: ``click`` is only a transitive dependency (via typer), so a
    direct ``import click`` is not guaranteed to resolve. ``ctx`` is already a
    typer/click Context, so no import is needed.
    """
    for param in params or ("config", "env"):
        try:
            source = ctx.get_parameter_source(param)
        except Exception:  # noqa: BLE001 — no/!click ctx → treat as default
            continue
        name = getattr(source, "name", None)
        if name is not None and name not in ("DEFAULT", "DEFAULT_MAP"):
            return True
    return False


def has_intentional_dsn_source(ctx: Any, flag: str | None, no_config: bool) -> bool:
    """Whether an *intentional* DSN source is present (#152, for ``status``).

    True for a ``--database-url`` flag, ``--no-config``, an explicit
    ``--config``/``--env``, or the canonical ``CONFITURE_DATABASE_URL``. A
    merely-ambient ``DATABASE_URL`` does NOT count — ``migrate status`` stays in
    its no-connect "status-unknown" state (exit 0) rather than auto-connecting
    to whatever ``DATABASE_URL`` happens to be in the environment.
    """
    return (
        bool(flag)
        or no_config
        or config_is_explicit(ctx)
        or bool(os.environ.get(_CONFITURE_DSN_ENV))
    )


def is_json(fmt: str | None) -> bool:
    """Whether a command's --format value selects JSON output (#145).

    Commands use varied format param names (``format_output`` / ``output_format``
    / ``format_type``) with different allowed sets; this collapses them to the
    single boolean the error boundary needs.
    """
    return bool(fmt) and fmt.lower() == "json"


def _get_tracking_table(config_data: Any) -> str:
    """Safely extract migration tracking table name from any config format.

    Handles Environment objects (from mocks / validated config), raw dicts
    from load_config() (old YAML format without database_url), and MagicMock
    objects used in tests.

    Always returns a ``str``: a non-string candidate (e.g. a bare ``MagicMock``
    config in tests) falls back to the default rather than leaking a non-string
    into callers that build SQL identifiers from it (#152).
    """
    candidate: Any = "tb_confiture"
    if hasattr(config_data, "migration") and hasattr(config_data.migration, "tracking_table"):
        candidate = config_data.migration.tracking_table
    elif isinstance(config_data, dict):
        migration_cfg = config_data.get("migration") or {}
        if isinstance(migration_cfg, dict):
            candidate = migration_cfg.get("tracking_table", "tb_confiture")
    return candidate if isinstance(candidate, str) else "tb_confiture"


def _output_json(data: dict[str, Any], output_file: Path | None, console: Console) -> None:
    """Output JSON data to file or console.

    Args:
        data: Data to output as JSON
        output_file: Optional file to write to
        console: Console for output
    """
    json_str = json.dumps(data, indent=2)
    if output_file:
        output_file.write_text(json_str)
        console.print(f"[green]✅ Output written to {output_file}[/green]")
    else:
        # Use print() instead of console.print() to avoid Rich wrapping long lines
        print(json_str)


def _find_orphaned_sql_files(migrations_dir: Path) -> list[Path]:
    """Find .sql files that don't match the expected naming pattern.

    Args:
        migrations_dir: Directory to search for migrations

    Returns:
        List of orphaned .sql file paths
    """
    if not migrations_dir.exists():
        return []

    # Find all .sql files
    all_sql_files = set(migrations_dir.glob("*.sql"))

    # Find all properly named migration files
    expected_files = set(migrations_dir.glob("*.up.sql")) | set(migrations_dir.glob("*.down.sql"))

    # Orphaned files are SQL files that don't match the expected pattern
    orphaned = all_sql_files - expected_files
    return sorted(orphaned, key=lambda f: f.name)


def _print_duplicate_versions_warning(
    duplicate_versions: dict[str, list[Path]], console: Console
) -> None:
    """Print a warning about duplicate migration versions.

    Args:
        duplicate_versions: Dict mapping version to list of conflicting files
        console: Console for output
    """
    console.print("\n[yellow]⚠️  WARNING: Duplicate migration versions detected[/yellow]")
    console.print("[yellow]Multiple migration files share the same version number:[/yellow]")

    for version, files in sorted(duplicate_versions.items()):
        console.print(f"\n  Version {version}:")
        for f in files:
            console.print(f"    • {f.name}")

    console.print("\n[yellow]💡 Rename files to use unique version prefixes.[/yellow]")
    console.print(
        "[yellow]   Use 'confiture migrate generate' to auto-assign the next version.[/yellow]"
    )


def _print_orphaned_files_warning(orphaned_files: list[Path], console: Console) -> None:
    """Print a warning about orphaned migration files.

    Args:
        orphaned_files: List of orphaned migration file paths
        console: Console for output
    """
    console.print("\n[yellow]⚠️  WARNING: Orphaned migration files detected[/yellow]")
    console.print("[yellow]These SQL files exist but won't be applied by Confiture:[/yellow]")

    for orphaned_file in orphaned_files:
        # Suggest the rename
        suggested_name = f"{orphaned_file.stem}.up.sql"
        console.print(f"  • {orphaned_file.name} → rename to: {suggested_name}")

    console.print(
        "\n[yellow]Confiture only recognizes migration files with these patterns:[/yellow]"
    )
    console.print("[yellow]  • {NNN}_{name}.up.sql   (forward migrations)[/yellow]")
    console.print("[yellow]  • {NNN}_{name}.down.sql (rollback migrations)[/yellow]")
    console.print("[yellow]  • {NNN}_{name}.py       (Python class migrations)[/yellow]")
    console.print("[yellow]Learn more: https://github.com/evoludigit/confiture/issues/13[/yellow]")


def _collect_idempotency_report(
    sql_files: list[Path],
    py_files: list[Path],
    validator: Any,
    project_root: Path | None = None,
) -> Any:
    """Run the idempotency validator against .sql files and Python migrations.

    Returns a merged :class:`IdempotencyReport`. Python-origin violations
    carry the ``source_line`` of the originating ``self.execute()`` call;
    extractor warnings ride on the report's ``warnings`` list.

    ``project_root`` is forwarded to the extractor for ``execute_file``
    path-boundary checking; passing ``None`` lets the extractor auto-detect
    the root (the nearest ancestor with ``pyproject.toml``, ``.git``, or
    ``db/``).
    """
    from confiture.core.idempotency.models import IdempotencyReport
    from confiture.core.idempotency.python_migration_extractor import (
        extract_sql_from_python_migration,
    )

    combined = IdempotencyReport()

    for sql_path in sorted(sql_files):
        if not sql_path.is_file():
            continue
        file_report = validator.validate_file(sql_path)
        for scanned in file_report.scanned_files:
            combined.add_file_scanned(scanned)
        for violation in file_report.violations:
            combined.add_violation(violation)

    for py_path in sorted(py_files):
        extraction = extract_sql_from_python_migration(py_path, project_root=project_root)
        combined.add_file_scanned(str(py_path))
        combined.warnings.extend(extraction.warnings)
        for snippet in extraction.snippets:
            snippet_report = validator.validate_sql(snippet.sql, file_path=str(py_path))
            for violation in snippet_report.violations:
                violation.source_line = snippet.source_line
                combined.add_violation(violation)

    combined.scanned_files.sort()
    return combined


def _idempotent_backend_banner(format_output: str) -> dict[str, str]:
    """Report which idempotency backend is active.

    Text mode prints a one-line banner to ``console`` (stdout) — it's a
    status line, not an error. JSON / CSV / YAML modes print *nothing*:
    the backend is reported via ``payload["meta"]["backend"]`` so that
    pipe-able output stays valid.

    Returns:
        A ``meta`` dict the caller folds into its JSON payload. Always
        contains ``{"backend": "ast" | "regex"}``.
    """
    from confiture.core.idempotency.patterns import is_pglast_available

    backend = "ast" if is_pglast_available() else "regex"
    if format_output == "text":
        if backend == "ast":
            console.print("[green]✓ AST backend (pglast)[/green]")
        else:
            # Escape the [ast] brackets so Rich doesn't read them as markup.
            console.print(
                "[yellow]⚠ Regex fallback — install with "
                '`pip install "fraiseql-confiture\\[ast]"` '
                "for AST-backed detection[/yellow]"
            )
    return {"backend": backend}


def _validate_idempotency(
    migrations_dir: Path,
    format_output: str,
    output_file: Path | None,
    *,
    strict_cor: bool = False,
) -> None:
    """Validate idempotency of SQL and Python migration files.

    Args:
        migrations_dir: Directory containing migration files
        format_output: Output format (text or json)
        output_file: Optional file to save output to
        strict_cor: If True, info-severity CREATE OR REPLACE findings flip
            the exit code to 1 (default False — info findings render but
            don't fail the gate).
    """
    import typer

    from confiture.core.idempotency import IdempotencyValidator

    validator = IdempotencyValidator()

    # Backend banner (text) + meta accumulator (json) — printed before
    # file enumeration so users see which detector is running.
    meta = _idempotent_backend_banner(format_output)

    sql_files = sorted(migrations_dir.glob("*.up.sql"))
    py_files = sorted(p for p in migrations_dir.glob("*.py") if _is_migration_file(p))

    if not sql_files and not py_files:
        # Quiet-success ambiguity: "no migrations" can mean the user
        # intentionally validated an empty directory, but more often
        # they pointed --migrations-dir at the wrong path. Emit a hint
        # to make the success state legible to agents.
        zero_files_hints: list[str] = []
        _emit_hint(
            f"Migration directory `{migrations_dir}` exists but contains no files. "
            "Did you mean to pass --migrations-dir <other>?",
            hints_list=zero_files_hints,
            format_=format_output,
        )
        if format_output == "json":
            result: dict[str, Any] = {
                "status": "ok",
                "message": "No migration files found",
                "violations": [],
                "meta": meta,
                "hints": zero_files_hints,
            }
            _output_json(result, output_file, console)
        else:
            console.print("[green]✅ No migration files found to validate[/green]")
        return

    combined_report = _collect_idempotency_report(sql_files, py_files, validator)
    fail = combined_report.has_violations if strict_cor else combined_report.has_blocking_violations

    if format_output == "json":
        result = combined_report.to_dict()
        result["status"] = "issues_found" if fail else "ok"
        result["meta"] = meta
        result["hints"] = []
        _output_json(result, output_file, console)
        if fail:
            raise typer.Exit(1)
        return

    blocking = [v for v in combined_report.violations if v.severity == "error"]
    info = [v for v in combined_report.violations if v.severity == "info"]

    if not blocking and not info:
        console.print("[green]✅ All migrations are idempotent[/green]")
        console.print(f"   Scanned {combined_report.files_scanned} file(s)")
        _render_extractor_warnings(combined_report)
        return

    if blocking:
        console.print(f"[red]❌ Found {len(blocking)} idempotency violation(s)[/red]\n")
        _render_violations_by_file(blocking)

    if info:
        if not blocking:
            console.print("[green]✅ All migrations are idempotent[/green]")
            console.print(f"   Scanned {combined_report.files_scanned} file(s)")
        console.print(
            f"\n[yellow]ℹ️  {len(info)} heuristic note(s) "
            "(informational, do not fail the gate)[/yellow]\n"
        )
        _render_violations_by_file(info)
        if not strict_cor:
            console.print("[dim]Pass --strict-cor to treat these as blocking.[/dim]\n")

    _render_extractor_warnings(combined_report)

    if blocking:
        console.print("[cyan]To auto-fix .sql files, run:[/cyan]")
        console.print(
            f"[cyan]  confiture migrate fix --idempotent --migrations-dir {migrations_dir}[/cyan]"
        )
        console.print("[cyan]For .py migrations, edit them manually.[/cyan]")

    if fail:
        raise typer.Exit(1)


def _render_violations_by_file(violations: list[Any]) -> None:
    """Render violations grouped by file (shared by error + info sections)."""
    by_file: dict[str, list[Any]] = {}
    for violation in violations:
        by_file.setdefault(violation.file_path, []).append(violation)
    for file_path, group in by_file.items():
        file_name = Path(file_path).name
        console.print(f"[yellow]{file_name}[/yellow]")
        for v in group:
            location = (
                f"Line {v.source_line} (SQL line {v.line_number})"
                if v.source_line is not None
                else f"Line {v.line_number}"
            )
            console.print(f"  {location}: {v.pattern.value}")
            console.print(
                f"    [dim]{v.sql_snippet[:60]}...[/dim]"
                if len(v.sql_snippet) > 60
                else f"    [dim]{v.sql_snippet}[/dim]"
            )
            console.print(f"    💡 {v.suggestion}")
        console.print()


def _render_extractor_warnings(report: Any) -> None:
    """Render extractor warnings (dynamic SQL the validator couldn't reach)."""
    if not report.has_warnings:
        return
    console.print(
        f"[yellow]⚠️  {len(report.warnings)} dynamic SQL call(s) "
        "could not be statically analyzed:[/yellow]"
    )
    for warn in report.warnings:
        source = Path(str(warn.source_file)).name
        console.print(f"  {source}:{warn.source_line} — {warn.kind.value}")
        console.print(f"    [dim]{warn.message}[/dim]")
    console.print("    [dim]These calls were skipped. Idempotency cannot be guaranteed.[/dim]")
    console.print()


def _fix_idempotency(
    migrations_dir: Path,
    dry_run: bool,
    format_output: str,
    output_file: Path | None,
) -> None:
    """Fix idempotency issues in SQL migration files.

    Python migrations are never rewritten — unparsing the AST would lose
    comments and formatting. Any violations in ``.py`` files are surfaced
    under ``manual_fix_required`` so users know to edit them by hand.

    Args:
        migrations_dir: Directory containing migration files
        dry_run: If True, preview changes without modifying files
        format_output: Output format (text or json)
        output_file: Optional file to save output to
    """
    from confiture.core.idempotency import IdempotencyFixer, IdempotencyValidator

    fixer = IdempotencyFixer()
    validator = IdempotencyValidator()

    sql_files = sorted(migrations_dir.glob("*.up.sql"))
    py_files = sorted(p for p in migrations_dir.glob("*.py") if _is_migration_file(p))

    if not sql_files and not py_files:
        if format_output == "json":
            result: dict[str, Any] = {
                "status": "ok",
                "message": "No migration files found",
                "files": [],
                "hints": [],
            }
            _output_json(result, output_file, console)
        else:
            console.print("[green]✅ No migration files found to fix[/green]")
        return

    files_changed: list[dict[str, Any]] = []

    for sql_file in sql_files:
        original_content = sql_file.read_text()
        fixed_content = fixer.fix(original_content)

        if fixed_content != original_content:
            changes = fixer.dry_run(original_content)
            file_info: dict[str, Any] = {
                "file": sql_file.name,
                "changes": [
                    {
                        "pattern": c.pattern.value,
                        "original": c.original[:50] + "..." if len(c.original) > 50 else c.original,
                        "suggested_fix": c.suggested_fix[:50] + "..."
                        if len(c.suggested_fix) > 50
                        else c.suggested_fix,
                        "line": c.line_number,
                    }
                    for c in changes
                ],
            }
            files_changed.append(file_info)
            if not dry_run:
                sql_file.write_text(fixed_content)

    # Surface .py violations without rewriting the source.
    manual_report = _collect_idempotency_report([], py_files, validator)
    py_violations_by_file: dict[str, list[Any]] = {}
    for violation in manual_report.violations:
        py_violations_by_file.setdefault(violation.file_path, []).append(violation)
    manual_fix_required = sorted(py_violations_by_file.keys())

    if format_output == "json":
        status = (
            "fixed"
            if not dry_run and (files_changed or manual_fix_required)
            else "preview"
            if dry_run
            else "ok"
        )
        result = {
            "status": status,
            "files": files_changed,
            "total_files_changed": len(files_changed),
            "manual_fix_required": manual_fix_required,
            "hints": [],
        }
        if manual_report.has_warnings:
            result["warnings"] = manual_report.to_dict()["warnings"]
        _output_json(result, output_file, console)
        return

    if not files_changed and not manual_fix_required:
        console.print("[green]✅ All migrations are already idempotent[/green]")
        _render_extractor_warnings(manual_report)
        return

    if files_changed:
        if dry_run:
            console.print("[cyan]📋 DRY-RUN: Would apply the following fixes:[/cyan]\n")
        else:
            console.print("[green]✅ Applied idempotency fixes:[/green]\n")

        for file_info in files_changed:
            console.print(f"[yellow]{file_info['file']}[/yellow]")
            for change in file_info["changes"]:
                console.print(f"  Line {change['line']}: {change['pattern']}")
                console.print(f"    - {change['original']}")
                console.print(f"    + {change['suggested_fix']}")
            console.print()

    if manual_fix_required:
        console.print(
            "[yellow]Python migrations cannot be auto-fixed; "
            "please edit the following files manually:[/yellow]"
        )
        for file_path in manual_fix_required:
            file_name = Path(file_path).name
            console.print(f"[yellow]  • {file_name}[/yellow]")
            for v in py_violations_by_file[file_path]:
                location = (
                    f"line {v.source_line}"
                    if v.source_line is not None
                    else f"line {v.line_number}"
                )
                console.print(f"    {location}: {v.pattern.value} — 💡 {v.suggestion}")
        console.print()

    _render_extractor_warnings(manual_report)

    if files_changed and dry_run:
        console.print(f"[cyan]Would fix {len(files_changed)} file(s)[/cyan]")
        console.print("[cyan]Run without --dry-run to apply changes[/cyan]")
    elif files_changed:
        console.print(f"[green]Fixed {len(files_changed)} file(s)[/green]")


def _fix_ownership(
    migrations_dir: Path,
    config_path: Path,
    dry_run: bool,
    force: bool,
    format_output: str,
    output_file: Path | None,
) -> None:
    """Insert missing ``ALTER … OWNER TO`` statements in migration files (issue #124).

    Loads ``ownership:`` from *config_path* and uses
    :class:`~confiture.core.ownership_fixer.OwnershipFixer` to rewrite
    files in place.  In ``--apply`` mode (i.e. not ``--dry-run``), the
    helper first probes the local tracking table — any file whose
    version is already recorded gets refused unless ``--force`` is also
    set.

    No-op when:
    - ``ownership:`` block is absent from *config_path*
    - ``ownership.lint_enabled`` is False
    - pglast (the [ast] extra) is not installed
    """
    from confiture.core.connection import load_config
    from confiture.core.ownership_fixer import OwnershipFixer
    from confiture.core.validation.config_loaders import load_ownership_expectation

    if not config_path.exists():
        error_console.print(f"[red]❌ Config file not found: {config_path}[/red]")
        raise SystemExit(2)

    config_data = load_config(config_path)
    expectation = load_ownership_expectation(config_data, config_path, require=False)
    if expectation is None:
        if format_output == "json":
            _output_json(
                {"status": "skipped", "reason": "no ownership: block in config"},
                output_file,
                console,
            )
        else:
            console.print(
                "[yellow]⚠️  --ownership: config has no `ownership:` block — nothing to fix.[/yellow]"
            )
        return

    fixer = OwnershipFixer(expectation=expectation)
    previews = fixer.preview(migrations_dir)

    refused: list[tuple[Path, str]] = []
    applicable_previews = previews
    if not dry_run and previews:
        # Checksum-drift guard: ask the local DB which migration versions
        # are already recorded.  Refuse to rewrite those unless --force.
        applied_versions = _query_applied_versions(config_data)
        if applied_versions:
            safe: list = []
            for preview in previews:
                version = _extract_version(preview.file.name)
                if version and version in applied_versions and not force:
                    refused.append((preview.file, "already applied locally"))
                else:
                    safe.append(preview)
            applicable_previews = safe

    modified: list[Path] = []
    if not dry_run:
        for preview in applicable_previews:
            preview.file.write_text(preview.after)
            modified.append(preview.file)

    if format_output == "json":
        _output_json(
            {
                "status": "preview" if dry_run else "fixed",
                "previews": [
                    {
                        "file": str(p.file),
                        "before": p.before,
                        "after": p.after,
                    }
                    for p in previews
                ],
                "modified": [str(p) for p in modified],
                "refused": [{"file": str(f), "reason": r} for f, r in refused],
            },
            output_file,
            console,
        )
        if refused and not force:
            raise SystemExit(2)
        return

    if not previews:
        console.print("[green]✅ All migrations have ownership coverage[/green]")
        return

    label = "Would insert" if dry_run else "Inserted"
    console.print(f"[green]{label} `ALTER … OWNER TO` in:[/green]")
    for preview in previews:
        console.print(f"  [green]✓[/green] {preview.file.name}")

    if refused:
        console.print(
            f"\n[red]Refused {len(refused)} file(s) "
            f"(already applied — pass --force to rewrite anyway):[/red]"
        )
        for file_path, reason in refused:
            console.print(f"  [red]✗[/red] {file_path.name}: {reason}")
        if not force:
            raise SystemExit(2)


def _extract_version(filename: str) -> str | None:
    """Pull the leading version token out of a migration filename.

    Confiture migration files are named ``<version>_<name>.up.sql`` where
    ``<version>`` is either ``NNN`` (legacy) or ``YYYYMMDDHHMMSS`` (post-0.6.0).
    Both forms parse as a leading run of digits.
    """
    m = re.match(r"^(\d+)", filename)
    return m.group(1) if m else None


def _query_applied_versions(config_data: dict[str, Any]) -> set[str]:
    """Return the set of migration versions present in the local tracking table.

    Returns an empty set on any failure (no DB, no table, no rows) so
    the fixer can fall through to the "rewrite everything" path —
    a checksum guard that can't open a connection is no guard at all,
    so we'd rather degrade gracefully than block the fix.
    """
    from confiture.core.connection import create_connection

    try:
        conn = create_connection(config_data)
    except Exception:
        return set()

    table = _get_tracking_table(config_data)
    try:
        with conn.cursor() as cur:
            # Schema-qualified identifier needs splitting + quoting.
            schema, _, name = table.partition(".")
            if not name:
                schema, name = "public", table
            cur.execute(
                f'SELECT version FROM "{schema}"."{name}"'  # noqa: S608 — names quoted, no user input
            )
            return {row[0] for row in cur.fetchall()}
    except Exception:
        return set()
    finally:
        conn.close()
