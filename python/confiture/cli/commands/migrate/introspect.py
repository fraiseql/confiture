"""`confiture migrate introspect`.

Split out of the monolithic migrate command modules.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer

from confiture.cli.error_json import cli_boundary
from confiture.cli.helpers import _get_tracking_table, console, is_json, open_connection
from confiture.cli.options import format_option
from confiture.core import baseline_detector as _core_baseline_detector
from confiture.core import connection as _core_connection
from confiture.core import migrator as _core_migrator
from confiture.core.migrator import parse_migration_filename
from confiture.exceptions import ConfigurationError


@cli_boundary
def migrate_introspect(
    config: Path = typer.Option(
        Path("db/environments/local.yaml"),
        "--config",
        "-c",
        help="Configuration file (default: db/environments/local.yaml)",
    ),
    snapshots_dir: Path = typer.Option(
        Path("db/schema_history"),
        "--snapshots-dir",
        help="Schema history snapshots directory (default: db/schema_history)",
    ),
    format_output: str = format_option("text", "json"),
) -> None:
    """Detect migration level by comparing live schema to history snapshots.

    PROCESS:
      Introspects the live database schema using pg_catalog, normalises it,
      and compares against stored schema history snapshots. Reports the
      detected migration level without making any changes.

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
            console.print(f"  Snapshots directory: {snapshots_dir}")
            if not snapshots_dir.exists():
                console.print("  [yellow](directory not found — no snapshots available)[/yellow]")
            else:
                snap_count = len(list(snapshots_dir.glob("*.sql")))
                console.print(f"  ({snap_count} snapshot(s) found)")
            console.print(
                f"  {_get_tracking_table(config_data)}: "
                f"{'PRESENT' if tb_present else '[yellow]NOT FOUND[/yellow]'}"
            )

        if not snapshots_dir.exists():
            if format_output == "json":
                print(
                    json.dumps(
                        _introspect_payload(
                            tb_present,
                            detected_version=None,
                            error="snapshots_dir not found",
                        ),
                        indent=2,
                    )
                )
            else:
                console.print("\n[red]❌ Cannot introspect: snapshots directory not found.[/red]")
                console.print(
                    "  Run 'confiture migrate generate' to start building snapshot history."
                )
            raise typer.Exit(1)

        detector = _core_baseline_detector.BaselineDetector(snapshots_dir)

        if format_output == "text":
            console.print("\n  Comparing live schema against snapshots...")

        live_sql = detector.introspect_live_schema(conn)
        detected_version = detector.find_matching_snapshot(live_sql)

    if detected_version:
        # Resolve name from snapshot filename
        detected_name = ""
        for snap_path in snapshots_dir.glob(f"{detected_version}_*.sql"):
            detected_name = parse_migration_filename(snap_path.name)[1]
            break

        if format_output == "json":
            print(
                json.dumps(
                    _introspect_payload(
                        tb_present,
                        detected_version=detected_version,
                        detected_migration_name=detected_name,
                        confidence="exact",
                        recommendation=(f"confiture migrate baseline --through {detected_version}"),
                    ),
                    indent=2,
                )
            )
        else:
            console.print(f"  [green]✓ Match found: {detected_version}_{detected_name}[/green]")
            console.print(f"\n  Detected migration level: [bold]{detected_version}[/bold]")
            if not tb_present:
                console.print("\n  To restore tracking, run:")
                console.print(
                    f"    confiture migrate baseline --through {detected_version} --config {config}"
                )
                console.print("\n  Or apply automatically with:")
                console.print(f"    confiture migrate up --auto-detect-baseline --config {config}")
    else:
        closest = detector.last_closest
        if format_output == "json":
            result: dict = _introspect_payload(tb_present, detected_version=None, confidence="none")
            if closest:
                result["closest_version"] = closest[0]
                result["closest_similarity"] = round(closest[1], 4)
            print(json.dumps(result, indent=2))
        else:
            console.print("  [yellow]✗ No matching snapshot found[/yellow]")
            if closest:
                _cv, _cr = closest
                console.print(f"  [dim]Closest: {_cv} ({_cr:.0%} similar)[/dim]")
            console.print("\n  The live schema does not exactly match any stored snapshot.")
            console.print("  This can happen if the schema was modified outside of confiture.")


def _introspect_payload(ledger_present: bool, **extra: Any) -> dict[str, Any]:
    """Build ``migrate introspect``'s JSON payload (#186).

    ``ledger_present`` is the table-name-agnostic spelling ``migrate verify``
    adopted in 0.37.0. The 0.39.0 deprecated alias ``tb_confiture_present`` —
    which hardcoded the default table name and was therefore wrong for any
    project that configured ``tracking_table`` — was removed in 0.40.0 as
    announced.

    One builder for all three emit sites, so the shape cannot drift between them.
    """
    return {"ledger_present": ledger_present, **extra}
