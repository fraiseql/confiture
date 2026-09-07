"""Drift command: compare live database schema against expected DDL."""

import json
from dataclasses import dataclass
from pathlib import Path

import typer

from confiture.cli.error_json import cli_boundary, fail
from confiture.cli.formatters.common import display_drift_report
from confiture.cli.helpers import console, is_json, open_connection
from confiture.cli.options import format_option
from confiture.config.environment import AclExpectation, OwnershipExpectation
from confiture.core.connection import load_config
from confiture.core.drift import (
    AclDriftDetector,
    DriftReport,
    DriftSeverity,
    DriftType,
    OwnershipDriftDetector,
    SchemaDriftDetector,
    drift_config_from,
)
from confiture.core.validation.config_loaders import (
    load_acl_expectations,
    load_ownership_expectation,
)
from confiture.exceptions import ConfigurationError, SchemaError


@dataclass(frozen=True)
class _DriftRequest:
    """What one ``confiture drift`` run compares."""

    schema: Path | None
    default_schema: str
    ignore_column_order: bool
    check_acls: bool
    check_ownership: bool
    warn_only: bool
    fail_on_warning: bool


def _run_drift(
    config: Path, request: _DriftRequest, *, format_output: str, json_mode: bool
) -> None:
    """Load the expectations, compare, render, and exit 1 on drift."""
    if not config.exists():
        fail(
            ConfigurationError(
                f"Config file not found: {config}",
                error_code="CONFIG_004",
                resolution_hint="Check the path passed to --config.",
            ),
            json_mode=json_mode,
        )

    if request.schema is None and not request.check_acls and not request.check_ownership:
        fail(
            ConfigurationError(
                "--schema is required (or use --check-acls / --check-ownership). "
                "Provide a schema SQL file to compare against.",
            ),
            json_mode=json_mode,
        )

    config_data = load_config(config)

    # Load ACL + ownership expectations up-front so config errors fail
    # before we even open a database connection.
    expectations: list[AclExpectation] = []
    if request.check_acls:
        expectations = load_acl_expectations(config_data, config, require=True)

    ownership_expectation: OwnershipExpectation | None = None
    if request.check_ownership:
        ownership_expectation = load_ownership_expectation(config_data, config, require=True)

    with open_connection(config_data) as conn:
        drift_report: DriftReport | None = None
        if request.schema is not None:
            drift_cfg = drift_config_from(config_data)
            drift_report = SchemaDriftDetector(
                conn,
                ignore_column_order=request.ignore_column_order or drift_cfg.ignore_column_order,
                column_order_severity=drift_cfg.column_order_severity,
            ).compare_with_schema_file(str(request.schema), default_schema=request.default_schema)
        if request.check_acls:
            drift_report = _merge(drift_report, AclDriftDetector(conn).check(expectations))
        if request.check_ownership:
            assert ownership_expectation is not None  # require=True above
            drift_report = _merge(
                drift_report, OwnershipDriftDetector(conn).check(ownership_expectation)
            )
        assert drift_report is not None  # guarded by the schema/--check-* check above

    if request.warn_only:
        _demote_missing_grant_warnings(drift_report)

    _render_drift(drift_report, format_output)

    if drift_report.has_critical_drift:
        raise typer.Exit(1)  # success-signal: drift detected

    if request.fail_on_warning and drift_report.has_drift:
        raise typer.Exit(1)  # success-signal: drift detected (warnings)


def _merge(report: DriftReport | None, other: DriftReport) -> DriftReport:
    """``other``'s items folded into ``report``; ``other`` itself when there is none yet."""
    if report is None:
        return other
    report.drift_items.extend(other.drift_items)
    return report


def _render_drift(drift_report: DriftReport, format_output: str) -> None:
    if format_output == "json":
        payload = drift_report.to_dict()
        # `hints` is pre-allocated per the documented JSON-schema contract
        # — see docs/reference/json-schemas/drift.schema.json. Currently
        # always empty; the contract guarantees the key exists so
        # agents can read `payload["hints"]` without a defensive get().
        payload["hints"] = []
        print(json.dumps(payload, indent=2, default=str))
    else:
        display_drift_report(drift_report, console)


def _demote_missing_grant_warnings(report: DriftReport) -> None:
    """Demote MISSING_GRANT items from CRITICAL to WARNING in place."""
    for item in report.drift_items:
        if item.drift_type == DriftType.MISSING_GRANT:
            item.severity = DriftSeverity.WARNING


@cli_boundary
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
    default_schema: str = typer.Option(
        "public",
        "--default-schema",
        help="Schema an unqualified CREATE TABLE in --schema belongs to (#227)",
    ),
    ignore_column_order: bool = typer.Option(
        False,
        "--ignore-column-order",
        help="Do not report column_order_mismatch (#226); also drift.ignore_column_order in the config",
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
    format_output: str = format_option("table", "json"),
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
      3 - Database connection failed
      4 - Schema file not found, or unparseable (declares tables but parsed zero)
      5 - Invalid configuration (missing --schema, bad --format, config errors)

    JSON SCHEMA:
      See docs/reference/json-schemas.md for the JSON output schemas:
        - default: drift.schema.json
        - with --check-acls: drift-check-acls.schema.json (same shape;
          missing_grant / extra_grant items may appear in drift_items)

    RELATED:
      confiture migrate validate --check-live-drift - Validate within migrate workflow
      confiture migrate diff                        - Compare two schema files
    """
    json_mode = is_json(format_output)
    request = _DriftRequest(
        schema=schema,
        default_schema=default_schema,
        ignore_column_order=ignore_column_order,
        check_acls=check_acls,
        check_ownership=check_ownership,
        warn_only=warn_only,
        fail_on_warning=fail_on_warning,
    )
    try:
        _run_drift(config, request, format_output=format_output, json_mode=json_mode)
    except typer.Exit:
        raise
    except ConfigurationError as e:
        fail(e, json_mode=json_mode)
    except FileNotFoundError as e:
        fail(
            SchemaError(str(e), error_code="SCHEMA_201"),
            json_mode=json_mode,
        )
    except SchemaError as e:
        # e.g. SCHEMA_202: the --schema file declares tables but parsed to zero
        # (issue #175) — surface with its own code/exit, not as a config error.
        fail(e, json_mode=json_mode)
    # Reason: configuration or connection failure of any kind → the CONFIG_006 envelope
    except Exception as e:
        fail(
            ConfigurationError(
                f"Connection or configuration error: {e}",
                error_code="CONFIG_006",
            ),
            json_mode=json_mode,
        )
