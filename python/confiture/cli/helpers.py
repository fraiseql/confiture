"""Shared helpers for Confiture CLI commands."""

import difflib
import json
import re
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Any

import psycopg
from psycopg import sql as pgsql
from rich.console import Console

from confiture.core.connection import create_connection
from confiture.core.connection import open_connection as _core_open_connection
from confiture.core.ledger import table_identifier, validate_table_name
from confiture.core.linting.schema_linter import (
    LintReport as LinterReport,
)
from confiture.core.linting.schema_linter import (
    RuleSeverity,
)
from confiture.core.url_redaction import redact_url as redact_url  # re-export (layering)
from confiture.exceptions import ConfigurationError
from confiture.models.lint import LintReport, LintSeverity, Violation

_VALID_ENV_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_\-]*$")

# Create Rich consoles for stdout and stderr. Use stderr=True (not
# file=sys.stderr) so the stream is resolved dynamically at write time — this
# keeps it correct under pytest's capsys, which swaps sys.stderr per test.
console = Console()
error_console = Console(stderr=True)

_MACHINE_OUTPUT_FORMATS = frozenset({"json", "csv", "yaml"})


def open_connection(config: Any) -> AbstractContextManager["psycopg.Connection[Any]"]:
    """The CLI's one connection seam.

    Every command opens its database connection here, so a test replaces
    ``confiture.cli.helpers.create_connection`` once and every command sees the
    double; core's own factory is never patched (guard test).
    """
    return _core_open_connection(config, factory=create_connection)


def connect(config: Any) -> "psycopg.Connection[Any]":
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
                rule_id=violation.rule_id,
                rule_name=violation.rule_name,
                severity=severity_map[violation.severity],
                message=violation.message,
                location=violation.object_name,
            )
        )

    for violation in linter_report.warnings:
        violations.append(
            Violation(
                rule_id=violation.rule_id,
                rule_name=violation.rule_name,
                severity=severity_map[violation.severity],
                message=violation.message,
                location=violation.object_name,
            )
        )

    for violation in linter_report.info:
        violations.append(
            Violation(
                rule_id=violation.rule_id,
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


"""Exit code for a run that failed only because it could not read a call.

Under ``--fail-on-unanalyzable`` an unverified call fails the gate. It signals
the existing findings class (1) rather than a new integer: the documented exit
table is frozen at 0–8 and shared with the fraisier adapters, so a distinct
"completed, N unverified" code is a contract change on both sides. It is
parked, not refused (#213) — and when it lands, this constant and the
schema note are the only two places that change.
"""


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
    # Validated before the connection exists: a bad name is a configuration
    # error to surface, not a query failure to swallow.
    table = _get_tracking_table(config_data)

    try:
        with open_connection(config_data) as conn, conn.cursor() as cur:
            cur.execute(pgsql.SQL("SELECT version FROM {}").format(table_identifier(table)))
            return {row[0] for row in cur.fetchall()}
    except Exception:  # noqa: BLE001 — best-effort: no DB or no table means no guard, not a failure
        return set()
