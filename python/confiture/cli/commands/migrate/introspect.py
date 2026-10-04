"""`confiture migrate introspect`."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import typer

from confiture.cli.error_json import cli_boundary
from confiture.cli.helpers import _get_tracking_table, console, emit, is_json, open_connection
from confiture.cli.options import config_option, format_option
from confiture.core import baseline_detector as _core_baseline_detector
from confiture.core import connection as _core_connection
from confiture.core import migrator as _core_migrator
from confiture.error_codes import FINDINGS
from confiture.exceptions import ConfigurationError


@cli_boundary
def migrate_introspect(
    config: Path = config_option(),
    snapshots_dir: Path = typer.Option(
        Path("db/schema_history"),
        "--snapshots-dir",
        help="Schema history snapshots directory (default: db/schema_history)",
    ),
    format_output: str = format_option("text", "json"),
) -> None:
    """Detect migration level by comparing live schema to history snapshots.

    PROCESS:
      Reads the live database through its catalog and compares it with each
      schema history snapshot, newest first, the way `migrate diff --from db`
      compares a database with a tree. The first snapshot it has no change from
      is its level; otherwise the closest is reported. Makes no changes.

    EXAMPLES:
      confiture migrate introspect
        ↳ Detect migration level using default config and snapshots dir

      confiture migrate introspect --format json
        ↳ Output result as JSON for scripting

      confiture migrate introspect --snapshots-dir path/to/snapshots
        ↳ Use a custom snapshots directory

    RELATED:
      confiture migrate up --auto-detect-baseline   - Apply migrations with auto-baseline
      confiture migrate baseline --through <ver>    - Manually establish baseline
    """

    is_json(format_output)
    if not config.exists():
        raise ConfigurationError(f"Config file not found: {config}", error_code="CONFIG_004")

    config_data = _core_connection.load_config(config)
    with open_connection(config_data) as conn:
        migrator = _core_migrator.Migrator(
            connection=conn, migration_table=_get_tracking_table(config_data)
        )

        tb_present = migrator.tracking_table_exists()

        if format_output == "text":
            console.print("\n[cyan]Introspecting database schema...[/cyan]\n")
            console.print(t"  Snapshots directory: {snapshots_dir}")
            if not snapshots_dir.exists():
                console.print("  [yellow](directory not found — no snapshots available)[/yellow]")
            else:
                snap_count = len(
                    _core_baseline_detector.BaselineDetector(snapshots_dir).snapshot_files()
                )
                console.print(t"  ({snap_count} snapshot(s) found)")
            console.print(
                t"  {_get_tracking_table(config_data)}: "
                t"{'PRESENT' if tb_present else '[yellow]NOT FOUND[/yellow]'}"
            )

        if not snapshots_dir.exists():
            if format_output == "json":
                emit(
                    _introspect_payload(
                        tb_present,
                        detected_version=None,
                        error="snapshots_dir not found",
                    )
                )
            else:
                console.print("\n[red]❌ Cannot introspect: snapshots directory not found.[/red]")
                console.print(
                    "  Run 'confiture migrate generate' to start building snapshot history."
                )
            raise typer.Exit(FINDINGS)

        detector = _core_baseline_detector.BaselineDetector(
            snapshots_dir, tracking_table=_get_tracking_table(config_data)
        )

        if format_output == "text":
            console.print("\n  Comparing live schema against snapshots...")

        found = detector.find_matching_snapshot(conn)

    if found is not None:
        detected_version, detected_name = found.version, found.name

        if format_output == "json":
            emit(
                _introspect_payload(
                    tb_present,
                    detected_version=detected_version,
                    detected_migration_name=detected_name,
                    confidence="exact",
                    recommendation=(f"confiture migrate baseline --through {detected_version}"),
                )
            )
        else:
            console.print(t"  [green]✓ Match found: {detected_version}_{detected_name}[/green]")
            console.print(t"\n  Detected migration level: [bold]{detected_version}[/bold]")
            if not tb_present:
                console.print("\n  To restore tracking, run:")
                console.print(
                    t"    confiture migrate baseline --through {detected_version} --config {config}"
                )
                console.print("\n  Or apply automatically with:")
                console.print(t"    confiture migrate up --auto-detect-baseline --config {config}")
    else:
        closest = detector.last_closest
        if format_output == "json":
            result: dict = _introspect_payload(tb_present, detected_version=None, confidence="none")
            if closest:
                result["closest_version"] = closest[0]
                result["closest_similarity"] = round(closest[1], 4)
            emit(result)
        else:
            console.print("  [yellow]✗ No matching snapshot found[/yellow]")
            if closest:
                _cv, _cr = closest
                console.print(t"  [dim]Closest: {_cv} ({_cr:.0%} similar)[/dim]")
            console.print("\n  The live schema does not exactly match any stored snapshot.")
            console.print("  This can happen if the schema was modified outside of confiture.")


def _introspect_payload(ledger_present: bool, **extra: Any) -> dict[str, Any]:
    """Build ``migrate introspect``'s JSON payload (#186).

    ``ledger_present`` is the table-name-agnostic spelling ``migrate verify``
    also uses: a key that named the default table would be wrong for any
    project that configures ``tracking_table``.

    One builder for all three emit sites, so the shape cannot drift between them.
    """
    return {"ledger_present": ledger_present, **extra}
