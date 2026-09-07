"""``migrate fix --ownership``: apply the ownership expectation to a live database."""

from collections.abc import Callable
from pathlib import Path
from typing import Any

from confiture.cli.error_json import fail
from confiture.cli.helpers import (
    _extract_version,
    _output_json,
    _query_applied_versions,
    console,
    is_json,
)
from confiture.core import connection as _core_connection
from confiture.core.ownership_fixer import OwnershipFixer
from confiture.core.validation.config_loaders import load_ownership_expectation
from confiture.exceptions import ConfigurationError, ValidationError
from confiture.url_redaction import (
    redact_url as redact_url,  # noqa: PLC0414 — explicit re-export (layering)
)


def _partition_refused(
    previews: list[Any], config_data: Any, *, dry_run: bool, force: bool
) -> tuple[list[Any], list[tuple[Path, str]]]:
    """Checksum-drift guard: previews of already-applied versions are refused unless ``--force``.

    Returns:
        ``(applicable, refused)``; under ``dry_run`` nothing is refused because
        nothing is written.
    """
    refused: list[tuple[Path, str]] = []
    if dry_run or not previews:
        return previews, refused
    # Ask the local DB which migration versions are already recorded.
    applied_versions = _query_applied_versions(config_data)
    if not applied_versions:
        return previews, refused
    safe: list[Any] = []
    for preview in previews:
        version = _extract_version(preview.file.name)
        if version and version in applied_versions and not force:
            refused.append((preview.file, "already applied locally"))
        else:
            safe.append(preview)
    return safe, refused


def _render_ownership_fix_text(
    previews: list[Any],
    refused: list[tuple[Path, str]],
    *,
    dry_run: bool,
    force: bool,
    refuse: Callable[[], None],
) -> None:
    """The text report of ``migrate fix --ownership``; ``refuse`` exits when a refusal stands."""
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
            refuse()


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

    if not config_path.exists():
        fail(
            ConfigurationError(f"Config file not found: {config_path}", error_code="CONFIG_004"),
            json_mode=is_json(format_output),
            output_file=output_file,
        )

    config_data = _core_connection.load_config(config_path)
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

    applicable_previews, refused = _partition_refused(
        previews, config_data, dry_run=dry_run, force=force
    )

    modified: list[Path] = []
    if not dry_run:
        for preview in applicable_previews:
            preview.file.write_text(preview.after)
            modified.append(preview.file)

    def _refuse() -> None:

        fail(
            ValidationError(
                f"Refused to rewrite {len(refused)} already-applied migration file(s).",
                context={"refused": [{"file": str(f), "reason": r} for f, r in refused]},
                resolution_hint="Pass --force to rewrite files whose version is already applied.",
            ),
            json_mode=is_json(format_output),
            output_file=output_file,
        )

    if format_output == "json":
        if refused and not force:
            _refuse()
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
        return

    _render_ownership_fix_text(previews, refused, dry_run=dry_run, force=force, refuse=_refuse)
