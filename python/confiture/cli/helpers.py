"""Shared helpers for Confiture CLI commands."""

import json
import re
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Any

import yaml
from rich.console import Console

try:
    # typer vendors click from 0.2x on; `click.get_current_context()` is then a
    # different module's and returns None inside a command body.
    from typer._click.globals import get_current_context as _current_context
except ImportError:
    from click import get_current_context as _current_context

from confiture.cli.markup import verbatim
from confiture.core.connection import DatabaseError, create_connection
from confiture.core.connection import open_connection as _core_open_connection
from confiture.core.ledger import recorded_versions, validate_table_name
from confiture.core.linting.schema_linter import (
    LintReport as LinterReport,
)
from confiture.core.linting.schema_linter import (
    LintViolation,
    RuleSeverity,
)
from confiture.core.parser_info import parser_stamp
from confiture.exceptions import ConfigurationError, ConfiturError
from confiture.models.lint import LintReport, LintSeverity, Violation
from confiture.url_redaction import (
    redact_url as redact_url,  # noqa: PLC0414 — explicit re-export (layering)
)

_VALID_ENV_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_\-]*$")

# Create Rich consoles for stdout and stderr. Use stderr=True (not
# file=sys.stderr) so the stream is resolved dynamically at write time — this
# keeps it correct under pytest's capsys, which swaps sys.stderr per test.
console = Console()
error_console = Console(stderr=True)

_MACHINE_OUTPUT_FORMATS = frozenset({"json", "csv", "yaml"})


def open_connection(config: Any) -> AbstractContextManager[Any]:
    """The CLI's one connection seam.

    Every command opens its database connection here, so a test replaces
    ``confiture.cli.helpers.create_connection`` once and every command sees the
    double; core's own factory is never patched (guard test).
    """
    return _core_open_connection(config, factory=create_connection)


def connect(config: Any) -> Any:
    """Open a connection the caller owns (and closes) — same seam as :func:`open_connection`."""
    return create_connection(config)


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
    target.print(f"[dim]Hint: {verbatim(hint)}[/dim]")


# Common command names for "Did you mean?" suggestions
COMMON_COMMANDS = [
    "init",
    "build",
    "migrate",
    "lint",
    "introspect",
    "seed",
    "generate",
    "install-helpers",
    "restore",
    "migrate-up",
    "migrate-down",
    "migrate-status",
    "migrate-validate",
]


#: The linter's severities, in the order ``models.lint`` names them.
_SEVERITIES: dict[RuleSeverity, LintSeverity] = {
    RuleSeverity.ERROR: LintSeverity.ERROR,
    RuleSeverity.WARNING: LintSeverity.WARNING,
    RuleSeverity.INFO: LintSeverity.INFO,
}


def _to_violation(violation: LintViolation) -> Violation:
    """The one place a linter violation becomes a reportable one.

    Every call site converts here, under one test: copying the fields at each
    site instead is how ``file_path`` and ``line_number`` go missing from a
    ``lint --format json`` payload.
    """
    return Violation(
        rule_id=violation.rule_id,
        rule_name=violation.rule_name,
        severity=_SEVERITIES[violation.severity],
        message=violation.message,
        location=violation.object_name,
        suggested_fix=violation.suggested_fix,
        file=violation.file_path,
        line=violation.line_number,
        finding_class=violation.finding_class,
    )


def _convert_linter_report(
    linter_report: LinterReport,
    schema_name: str = "schema",
    baseline: dict[str, Any] | None = None,
    gate: dict[str, Any] | None = None,
) -> LintReport:
    """Convert a schema_linter.LintReport to models.lint.LintReport.

    Args:
        linter_report: Report from SchemaLinter
        schema_name: Name of schema being linted
        baseline: The ``--baseline`` comparison summary, when one ran.
        gate: What decides this run's exit code, and whether it can be reached.

    Returns:
        LintReport compatible with format_lint_report
    """
    return LintReport(
        violations=[
            _to_violation(violation)
            for bucket in (linter_report.errors, linter_report.warnings, linter_report.info)
            for violation in bucket
        ],
        schema_name=schema_name,
        tables_checked=linter_report.tables_checked,
        columns_checked=linter_report.columns_checked,
        errors_count=len(linter_report.errors),
        warnings_count=len(linter_report.warnings),
        info_count=len(linter_report.info),
        execution_time_ms=0,  # Not tracked in linter
        baseline=baseline,
        gate=gate,
        skipped=[status.to_dict() for status in linter_report.skipped],
        degraded=[status.to_dict() for status in linter_report.degraded],
        documentation=linter_report.documentation,
    )


def _output_yaml(data: dict[str, Any], output_file: Path | None, console: Console) -> None:
    """Output YAML data to file or console.

    Args:
        data: Data to serialise as YAML.
        output_file: Optional file to write to; if None, writes to stdout.
        console: Console used for status messages (stderr).
    """

    yaml_str = yaml.dump(data, default_flow_style=False, sort_keys=False, allow_unicode=True)
    if output_file:
        output_file.write_text(yaml_str)
        console.print(f"[green]✅ Output written to {verbatim(output_file)}[/green]")
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
    from load_config(), and MagicMock objects used in tests.

    Always returns a ``str``: a non-string candidate (e.g. a bare ``MagicMock``
    config in tests) falls back to the default rather than leaking a non-string
    into callers that build SQL identifiers from it (#152).

    Raises:
        ConfigurationError: ``tracking_table`` is not a plain, optionally
            schema-qualified identifier (``CONFIG_008``).  The same rule
            ``Migrator.__init__`` applies is applied here, before any connection
            is opened, so no command carries an unvalidated name into a query.
    """
    candidate: Any = "tb_confiture"
    if hasattr(config_data, "migration") and hasattr(config_data.migration, "tracking_table"):
        candidate = config_data.migration.tracking_table
    elif isinstance(config_data, dict):
        migration_cfg = config_data.get("migration") or {}
        if isinstance(migration_cfg, dict):
            candidate = migration_cfg.get("tracking_table", "tb_confiture")
    table = candidate if isinstance(candidate, str) else "tb_confiture"
    try:
        return validate_table_name(table)
    except ValueError as e:
        raise ConfigurationError(
            f"Invalid migration.tracking_table: {e}",
            error_code="CONFIG_008",
            context={"tracking_table": table},
            resolution_hint=(
                "Set migration.tracking_table to a plain identifier — letters, "
                "digits and underscores, optionally schema-qualified "
                "(e.g. 'public.tb_confiture')."
            ),
        ) from e


def _command_path() -> str | None:
    """The running command's path — ``migrate up`` — from the Click context, if one is live."""
    context = _current_context(silent=True)
    names: list[str] = []
    while context is not None and context.parent is not None:
        names.append(str(context.info_name))
        context = context.parent
    return " ".join(reversed(names)) or None


def emit(data: dict[str, Any], output_file: Path | None = None, out: Console | None = None) -> None:
    """The one writer of a command's machine output: its payload, in the envelope.

    The envelope is three keys: ``ok`` — ``true`` when the command produced its
    report, ``false`` in the error envelope (the report's own fields, ``success`` or
    ``is_valid``, say what it found) — ``command`` (``migrate up``) and ``parser``
    (what parsed the SQL). Each is added only when the payload does not carry it,
    after every key it does: nothing is renamed, nested or reordered, so a consumer
    that reads a payload without the envelope reads it unchanged with it.

    With *output_file* the JSON goes to the file and one human line to stdout — the
    split the fraisier adapter depends on, reading clean JSON from ``--output`` while
    progress goes to stdout. Without it the JSON goes to stdout through ``print``,
    never Rich, which would re-wrap and colour it.
    """
    payload = dict(data)
    payload.setdefault("ok", True)
    command = _command_path()
    if command is not None:
        payload.setdefault("command", command)
    payload.setdefault("parser", parser_stamp())
    text = json.dumps(payload, indent=2, default=str)
    if output_file:
        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_text(text)
        (out or console).print(f"[green]✅ Output written to {verbatim(output_file)}[/green]")
    else:
        print(text)


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
        console.print(f"\n  Version {verbatim(version)}:")
        for f in files:
            console.print(f"    • {verbatim(f.name)}")

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
        console.print(f"  • {verbatim(orphaned_file.name)} → rename to: {verbatim(suggested_name)}")

    console.print(
        "\n[yellow]Confiture only recognizes migration files with these patterns:[/yellow]"
    )
    console.print("[yellow]  • {NNN}_{name}.up.sql   (forward migrations)[/yellow]")
    console.print("[yellow]  • {NNN}_{name}.down.sql (rollback migrations)[/yellow]")
    console.print("[yellow]  • {NNN}_{name}.py       (Python class migrations)[/yellow]")
    console.print("[yellow]Learn more: https://github.com/evoludigit/confiture/issues/13[/yellow]")


def _extract_version(filename: str) -> str | None:
    """Pull the leading version token out of a migration filename.

    Confiture migration files are named ``<version>_<name>.up.sql`` where
    ``<version>`` is either ``NNN`` or a ``YYYYMMDDHHMMSS`` timestamp.
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
    # Validated before the connection exists: a bad name is a configuration
    # error to surface, not a query failure to swallow.
    table = _get_tracking_table(config_data)

    try:
        with open_connection(config_data) as conn:
            return recorded_versions(conn, table)
    except (ConfiturError, DatabaseError):
        return set()
