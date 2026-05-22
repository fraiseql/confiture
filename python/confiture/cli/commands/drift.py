"""Drift command: compare live database schema against expected DDL."""

import json
from pathlib import Path
from typing import Any

import typer
from pydantic import ValidationError

from confiture.cli.formatters.common import display_drift_report
from confiture.cli.helpers import console, error_console
from confiture.config._env_vars import expand_env_vars
from confiture.config.environment import AclExpectation
from confiture.core.connection import create_connection, load_config
from confiture.core.drift import (
    AclDriftDetector,
    DriftReport,
    DriftSeverity,
    DriftType,
    SchemaDriftDetector,
)
from confiture.exceptions import ConfigurationError


def _load_acl_expectations(
    config_data: dict[str, Any], config_path: Path
) -> list[AclExpectation]:
    """Pull ``acls:`` from the raw config dict, expand env vars, validate.

    Mirrors the load-time expansion done by ``Environment.load`` so the
    ``confiture drift --config confiture.yaml`` path supports ``${VAR}``
    the same way other consumers do.
    """
    raw = config_data.get("acls")
    if not raw:
        error_console.print(
            f"[red]❌ --check-acls requires an `acls:` block in {config_path}[/red]"
        )
        raise typer.Exit(2)

    expanded = expand_env_vars(raw, context="acls")
    try:
        return [AclExpectation.model_validate(item) for item in expanded]
    except ValidationError as exc:
        error_console.print(f"[red]❌ Invalid acls: block in {config_path}: {exc}[/red]")
        raise typer.Exit(2) from exc


def _demote_missing_grant_warnings(report: DriftReport) -> None:
    """Demote MISSING_GRANT items from CRITICAL to WARNING in place."""
    for item in report.drift_items:
        if item.drift_type == DriftType.MISSING_GRANT:
            item.severity = DriftSeverity.WARNING


def drift(
    config: Path = typer.Option(
        Path("confiture.yaml"),
        "--config",
        "-c",
        help="Configuration file (default: confiture.yaml)",
    ),
    schema: Path | None = typer.Option(
        None,
        "--schema",
        help="Schema SQL file to compare against (optional when --check-acls is set)",
    ),
    check_acls: bool = typer.Option(
        False,
        "--check-acls",
        help="Also compare live grants against the `acls:` block in the config",
    ),
    warn_only: bool = typer.Option(
        False,
        "--warn-only",
        help="Demote MISSING_GRANT items from critical to warning (progressive rollout)",
    ),
    format_output: str = typer.Option(
        "table",
        "--format",
        "-f",
        help="Output format: table or json (default: table)",
    ),
    fail_on_warning: bool = typer.Option(
        False,
        "--fail-on-warning",
        help="Exit with code 1 on warnings as well as critical drift (default: off)",
    ),
) -> None:
    """Compare live database schema against expected DDL for drift.

    PROCESS:
      Connects to the database, introspects the live schema, and compares it
      against the provided schema SQL file. Reports missing/extra tables and
      columns, type mismatches, and index differences. With --check-acls,
      also compares live ``pg_class.relacl`` against the configured grants.

    EXAMPLES:
      confiture drift --config confiture.yaml --schema db/generated/schema.sql
        ↳ Check live database for schema drift against a generated schema file

      confiture drift --config confiture.yaml --schema db/schema.sql --format json
        ↳ Output drift report as JSON for CI/CD pipelines

      confiture drift --config confiture.yaml --schema db/schema.sql --fail-on-warning
        ↳ Exit 1 on any drift (including warnings)

      confiture drift --config confiture.yaml --check-acls
        ↳ Check ACL coverage only (no structural diff)

      confiture drift --config confiture.yaml --check-acls --warn-only
        ↳ Soft-launch — missing grants surface as warnings, not failures

    EXIT CODES:
      0 - No drift detected
      1 - Drift detected (critical, or warning when --fail-on-warning)
      2 - Connection or configuration error

    RELATED:
      confiture migrate validate --check-live-drift - Validate within migrate workflow
      confiture migrate diff                        - Compare two schema files
    """
    try:
        if format_output not in ("table", "json"):
            error_console.print(
                f"[red]❌ Invalid format: {format_output}. Use 'table' or 'json'[/red]"
            )
            raise typer.Exit(1)

        if not config.exists():
            error_console.print(f"[red]❌ Config file not found: {config}[/red]")
            raise typer.Exit(2)

        if schema is None and not check_acls:
            error_console.print(
                "[red]❌ --schema is required (or use --check-acls). "
                "Provide a schema SQL file to compare against.[/red]"
            )
            raise typer.Exit(2)

        config_data = load_config(config)

        # Load ACL expectations up-front so config errors fail before we
        # even open a database connection.
        expectations: list[AclExpectation] = []
        if check_acls:
            expectations = _load_acl_expectations(config_data, config)

        conn = create_connection(config_data)

        try:
            if schema is not None:
                detector = SchemaDriftDetector(conn)
                drift_report = detector.compare_with_schema_file(str(schema))
            else:
                # ACL-only run: build a minimal report shell so downstream
                # formatters / exit-code logic still see a DriftReport.
                drift_report = DriftReport(
                    database_name="",
                    expected_schema_source=f"acls:{config}",
                )
                with conn.cursor() as cur:
                    cur.execute("SELECT current_database()")
                    row = cur.fetchone()
                    drift_report.database_name = row[0] if row else "unknown"

            if check_acls:
                acl_items = AclDriftDetector(conn).check(expectations)
                drift_report.drift_items.extend(acl_items)
        finally:
            conn.close()

        if warn_only:
            _demote_missing_grant_warnings(drift_report)

        if format_output == "json":
            print(json.dumps(drift_report.to_dict(), indent=2, default=str))
        else:
            display_drift_report(drift_report, console)

        if drift_report.has_critical_drift:
            raise typer.Exit(1)

        if fail_on_warning and drift_report.has_drift:
            raise typer.Exit(1)

    except typer.Exit:
        raise
    except ConfigurationError as e:
        error_console.print(f"[red]❌ {e}[/red]")
        raise typer.Exit(2) from e
    except FileNotFoundError as e:
        error_console.print(f"[red]❌ {e}[/red]")
        raise typer.Exit(2) from e
    except Exception as e:
        error_console.print(f"[red]❌ Connection or configuration error: {e}[/red]")
        raise typer.Exit(2) from e
