"""Drift command: compare live database schema against expected DDL."""

import json
from pathlib import Path

import typer

from confiture.cli.acl_loader import load_acl_expectations
from confiture.cli.formatters.common import display_drift_report
from confiture.cli.helpers import console, error_console
from confiture.cli.ownership_loader import load_ownership_expectation
from confiture.config.environment import AclExpectation, OwnershipExpectation
from confiture.core.connection import create_connection, load_config
from confiture.core.drift import (
    AclDriftDetector,
    DriftReport,
    DriftSeverity,
    DriftType,
    OwnershipDriftDetector,
    SchemaDriftDetector,
)
from confiture.exceptions import ConfigurationError


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
    check_ownership: bool = typer.Option(
        False,
        "--check-ownership",
        help="Also compare live `pg_class.relowner` against the `ownership:` block",
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

    JSON SCHEMA:
      See docs/reference/json-schemas.md for the JSON output schemas:
        - default: drift.schema.json
        - with --check-acls: drift-check-acls.schema.json (same shape;
          missing_grant / extra_grant items may appear in drift_items)

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

        if schema is None and not check_acls and not check_ownership:
            error_console.print(
                "[red]❌ --schema is required (or use --check-acls / --check-ownership). "
                "Provide a schema SQL file to compare against.[/red]"
            )
            raise typer.Exit(2)

        config_data = load_config(config)

        # Load ACL + ownership expectations up-front so config errors fail
        # before we even open a database connection.
        expectations: list[AclExpectation] = []
        if check_acls:
            expectations = load_acl_expectations(config_data, config, require=True)

        ownership_expectation: OwnershipExpectation | None = None
        if check_ownership:
            ownership_expectation = load_ownership_expectation(config_data, config, require=True)

        conn = create_connection(config_data)

        try:
            structural_report: DriftReport | None = None
            if schema is not None:
                structural_report = SchemaDriftDetector(conn).compare_with_schema_file(str(schema))

            drift_report: DriftReport | None = structural_report
            if check_acls:
                acl_report = AclDriftDetector(conn).check(expectations)
                if drift_report is None:
                    drift_report = acl_report
                else:
                    drift_report.drift_items.extend(acl_report.drift_items)

            if check_ownership:
                assert ownership_expectation is not None  # require=True above
                own_report = OwnershipDriftDetector(conn).check(ownership_expectation)
                if drift_report is None:
                    drift_report = own_report
                else:
                    drift_report.drift_items.extend(own_report.drift_items)

            assert drift_report is not None  # guarded by the schema/--check-* check above
        finally:
            conn.close()

        if warn_only:
            _demote_missing_grant_warnings(drift_report)

        if format_output == "json":
            payload = drift_report.to_dict()
            # `hints` is pre-allocated per the documented JSON-schema contract
            # (docs/reference/json-schemas/drift.schema.json). Currently
            # always empty; the contract guarantees the key exists so
            # agents can read `payload["hints"]` without a defensive get().
            payload["hints"] = []
            print(json.dumps(payload, indent=2, default=str))
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
