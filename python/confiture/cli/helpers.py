"""Shared helpers for Confiture CLI commands."""

import difflib
import json
import re
import sys
from pathlib import Path
from typing import Any

from rich.console import Console

from confiture.core.linting.schema_linter import (
    LintReport as LinterReport,
)
from confiture.core.linting.schema_linter import (
    RuleSeverity,
)
from confiture.models.lint import LintReport, LintSeverity, Violation

_VALID_ENV_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_\-]*$")

# Create Rich consoles for stdout and stderr
console = Console()
error_console = Console(file=sys.stderr)

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


def _get_tracking_table(config_data: Any) -> str:
    """Safely extract migration tracking table name from any config format.

    Handles Environment objects (from mocks / validated config), raw dicts
    from load_config() (old YAML format without database_url), and MagicMock
    objects used in tests.
    """
    if hasattr(config_data, "migration") and hasattr(config_data.migration, "tracking_table"):
        return config_data.migration.tracking_table  # type: ignore[no-any-return]
    if isinstance(config_data, dict):
        migration_cfg = config_data.get("migration") or {}
        if isinstance(migration_cfg, dict):
            return migration_cfg.get("tracking_table", "tb_confiture")
    return "tb_confiture"


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


def _validate_idempotency(
    migrations_dir: Path,
    format_output: str,
    output_file: Path | None,
) -> None:
    """Validate idempotency of SQL migration files.

    Args:
        migrations_dir: Directory containing migration files
        format_output: Output format (text or json)
        output_file: Optional file to save output to
    """
    import typer

    from confiture.core.idempotency import IdempotencyValidator

    validator = IdempotencyValidator()

    # Find all SQL migration files
    sql_files = list(migrations_dir.glob("*.up.sql"))
    sql_files.sort()

    if not sql_files:
        if format_output == "json":
            result: dict[str, Any] = {
                "status": "ok",
                "message": "No migration files found",
                "violations": [],
            }
            _output_json(result, output_file, console)
        else:
            console.print("[green]✅ No migration files found to validate[/green]")
        return

    # Validate all files
    combined_report = validator.validate_directory(migrations_dir, pattern="*.up.sql")

    if format_output == "json":
        result = combined_report.to_dict()
        result["status"] = "issues_found" if combined_report.has_violations else "ok"
        _output_json(result, output_file, console)
        if combined_report.has_violations:
            raise typer.Exit(1)
    else:
        if not combined_report.has_violations:
            console.print("[green]✅ All migrations are idempotent[/green]")
            console.print(f"   Scanned {combined_report.files_scanned} file(s)")
            return

        # Display violations
        console.print(
            f"[red]❌ Found {combined_report.violation_count} idempotency violation(s)[/red]\n"
        )

        # Group violations by file
        violations_by_file: dict[str, list[Any]] = {}
        for violation in combined_report.violations:
            file_path = violation.file_path
            if file_path not in violations_by_file:
                violations_by_file[file_path] = []
            violations_by_file[file_path].append(violation)

        for file_path, violations in violations_by_file.items():
            file_name = Path(file_path).name
            console.print(f"[yellow]{file_name}[/yellow]")
            for v in violations:
                console.print(f"  Line {v.line_number}: {v.pattern.value}")
                console.print(
                    f"    [dim]{v.sql_snippet[:60]}...[/dim]"
                    if len(v.sql_snippet) > 60
                    else f"    [dim]{v.sql_snippet}[/dim]"
                )
                console.print(f"    💡 {v.suggestion}")
            console.print()

        console.print("[cyan]To auto-fix these issues, run:[/cyan]")
        console.print(
            f"[cyan]  confiture migrate fix --idempotent --migrations-dir {migrations_dir}[/cyan]"
        )

        raise typer.Exit(1)


def _fix_idempotency(
    migrations_dir: Path,
    dry_run: bool,
    format_output: str,
    output_file: Path | None,
) -> None:
    """Fix idempotency issues in SQL migration files.

    Args:
        migrations_dir: Directory containing migration files
        dry_run: If True, preview changes without modifying files
        format_output: Output format (text or json)
        output_file: Optional file to save output to
    """
    from confiture.core.idempotency import IdempotencyFixer

    fixer = IdempotencyFixer()

    # Find all SQL migration files
    sql_files = list(migrations_dir.glob("*.up.sql"))
    sql_files.sort()

    if not sql_files:
        if format_output == "json":
            result: dict[str, Any] = {
                "status": "ok",
                "message": "No migration files found",
                "files": [],
            }
            _output_json(result, output_file, console)
        else:
            console.print("[green]✅ No migration files found to fix[/green]")
        return

    # Process each file
    files_changed: list[dict[str, Any]] = []

    for sql_file in sql_files:
        original_content = sql_file.read_text()
        fixed_content = fixer.fix(original_content)

        if fixed_content != original_content:
            # Get list of changes for reporting
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

    # Output results
    if format_output == "json":
        result = {
            "status": "fixed" if not dry_run and files_changed else "preview" if dry_run else "ok",
            "files": files_changed,
            "total_files_changed": len(files_changed),
        }
        _output_json(result, output_file, console)
    else:
        if not files_changed:
            console.print("[green]✅ All migrations are already idempotent[/green]")
            return

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

        if dry_run:
            console.print(f"[cyan]Would fix {len(files_changed)} file(s)[/cyan]")
            console.print("[cyan]Run without --dry-run to apply changes[/cyan]")
        else:
            console.print(f"[green]Fixed {len(files_changed)} file(s)[/green]")
