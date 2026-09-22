"""`confiture migrate fix-signatures`."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any

import typer

from confiture.cli.error_json import cli_boundary, fail
from confiture.cli.helpers import (
    _resolve_config,
    console,
    emit,
    error_console,
    is_json,
    open_connection,
)
from confiture.cli.options import (
    CONFITURE_YAML,
    CheckSignatureSchemasOpt,
    config_option,
    env_option,
    format_option,
    mode_option,
    output_option,
)
from confiture.config.environment import SshTunnelConfig
from confiture.core import builder as _core_builder
from confiture.core.connection import DatabaseError, load_config
from confiture.core.function_body_drift import FunctionBodyDriftDetector, paired
from confiture.core.function_signature_drift import (
    Definitions,
    FunctionSignatureDriftDetector,
    by_function,
    declared_routines,
    definition_of,
    live_routines,
    matching,
    printed_signature,
    replacing_definitions,
    schemas_to_scan,
)
from confiture.error_codes import FINDINGS, USAGE, exit_code_of
from confiture.exceptions import ConfigurationError, ConfiturError

if TYPE_CHECKING:
    from confiture.core.schema_model import Routine


SchemaFileOpt = Annotated[
    Path | None,
    typer.Option(
        "--schema",
        help="Schema SQL file containing the authoritative function definitions. "
        "If omitted, schema is auto-built from DDL files.",
    ),
]
SshViaOpt = Annotated[
    str | None,
    typer.Option(
        "--ssh",
        help="Open an SSH tunnel before connecting: user@host or host. "
        "Overrides the ssh_tunnel block in the config file.",
    ),
]
CheckBodyOpt = Annotated[
    bool,
    typer.Option(
        "--check-body",
        help="Also detect and fix function body drift (same signature, different body). "
        "Runs CREATE OR REPLACE from source for each drifted function — no DROP needed.",
    ),
]


@cli_boundary
def migrate_fix_signatures(
    config: Path = config_option(CONFITURE_YAML),
    env: str | None = env_option(None),
    schema_file: SchemaFileOpt = None,
    check_signature_schemas: CheckSignatureSchemasOpt = None,
    ssh_via: SshViaOpt = None,
    mode: str = mode_option(
        "plan",
        "apply",
        help="plan: print the DROP + CREATE SQL and change nothing; "
        "apply: execute every fix in one transaction",
    ),
    format_output: str = format_option("text", "json"),
    output_file: Path | None = output_option(),
    check_body: CheckBodyOpt = False,
) -> None:
    """Fix stale function overloads: DROP old signature + re-apply source definition.

    PROCESS:
      1. Parse function signatures from --schema (or auto-built DDL).
      2. Introspect live database signatures.
      3. Detect stale overloads (present in DB but not in source).
      4. For each stale overload, generate DROP FUNCTION + CREATE OR REPLACE.
      5. --mode plan (default): print the combined SQL.
         --mode apply: execute all fixes in a single transaction.

    EXAMPLES:
      confiture migrate fix-signatures --env local
        ↳ Plan: show DROP + CREATE SQL for any stale overloads

      confiture migrate fix-signatures --env production --mode apply
        ↳ Apply fixes atomically in one transaction

      confiture migrate fix-signatures --env production --ssh lionel@prod-db --mode apply
        ↳ Apply via SSH tunnel
    """
    apply = mode == "apply"
    try:
        config = _resolve_config(config, env)
        if not config.exists():
            fail(
                ConfigurationError(
                    f"Config file not found: {config}",
                    error_code="CONFIG_004",
                    resolution_hint="Specify config with --config path/to/config.yaml.",
                ),
                json_mode=is_json(format_output),
            )
        config_data = load_config(config)
        source_sql = _resolve_source_sql(schema_file, config_data, format_output)

        declared = declared_routines(source_sql)
        # The same scope the reporter uses. This command executes `DROP FUNCTION`,
        # so the two disagreeing about which schemas are in play would be worse
        # than both being wrong the same way (#303).
        schemas = schemas_to_scan(check_signature_schemas, declared)
        effective_config = _ssh_override(config_data, ssh_via, format_output)

        body_report_after: Any = None
        with open_connection(effective_config) as conn:
            live = live_routines(conn, schemas)
            drift_report = FunctionSignatureDriftDetector().compare(
                declared, live, schemas_checked=schemas
            )
            if not drift_report.has_drift and not check_body:
                _render_clean(drift_report.summary(), format_output, output_file)
                return
            # when check_body and no sig drift: fall through to body detection
            definitions = replacing_definitions(source_sql)
            fix_blocks, missing_source = _plan_signature_fixes(
                drift_report, declared, live, definitions, format_output
            )
            if not fix_blocks and not check_body:
                error_console.print(
                    "[red]❌ No fixable overloads found "
                    "(source definitions missing for all stale overloads).[/red]"
                )
                raise typer.Exit(FINDINGS)
            body_fix_blocks, body_missing_source = _plan_body_fixes(
                check_body, declared, live, definitions
            )
            if not fix_blocks and not body_fix_blocks:
                _render_clean(
                    "No signature or body drift detected.",
                    format_output,
                    output_file,
                    extra={"body_drift_fixes_planned": 0} if check_body else None,
                )
                return
            if not apply:
                _render_fix_dry_run(
                    fix_blocks,
                    missing_source,
                    body_fix_blocks,
                    body_missing_source,
                    check_body=check_body,
                    format_output=format_output,
                    output_file=output_file,
                )
                return
            _apply_fix_blocks(conn, fix_blocks, body_fix_blocks)
            # Re-check to confirm zero drift.
            live_after = live_routines(conn, schemas)
            report_after = FunctionSignatureDriftDetector().compare(
                declared, live_after, schemas_checked=schemas
            )
            if check_body and declared:
                body_report_after = FunctionBodyDriftDetector().compare(declared, live_after)

        has_residual = report_after.has_drift or (
            body_report_after is not None and body_report_after.has_drift
        )
        _render_fix_applied(
            fix_blocks,
            missing_source,
            body_fix_blocks,
            body_missing_source,
            report_after=report_after,
            body_report_after=body_report_after,
            has_residual=has_residual,
            check_body=check_body,
            format_output=format_output,
            output_file=output_file,
        )
        if has_residual:
            raise typer.Exit(FINDINGS)
    except typer.Exit:
        raise
    # Reason: any failure below the config check is one error, rendered by the boundary
    except Exception as e:
        fail(ConfiturError(f"fix-signatures failed: {e}"), json_mode=is_json(format_output))


def _resolve_source_sql(schema_file: Path | None, config_data: Any, format_output: str) -> str:
    """``--schema FILE``, else the schema auto-built from the env's DDL files."""
    if schema_file is not None:
        return schema_file.read_text()
    try:
        env_name = (
            config_data.get("name")
            if isinstance(config_data, dict)
            else getattr(config_data, "name", None)
        )
        if not env_name:
            raise ValueError(
                "Config has no 'name' field — cannot auto-build schema. Pass --schema explicitly."
            )
        source_sql = _core_builder.SchemaBuilder(env=env_name).build(schema_only=True)
        if format_output == "text":
            console.print("[dim]  (schema auto-built from DDL files)[/dim]")
        return source_sql
    # Reason: an auto-build failure of any kind is reported with the --schema remedy
    except Exception as build_exc:
        error_console.print(
            f"[red]❌ --schema not provided and auto-build failed: {build_exc}[/red]\n"
            "  Either run 'confiture build' first or pass --schema explicitly."
        )
        raise typer.Exit(USAGE) from build_exc


def _ssh_override(config_data: Any, ssh_via: str | None, format_output: str) -> Any:
    """``--ssh-via [user@]host``: the connection goes through an SSH tunnel."""
    if not ssh_via:
        return config_data

    parts = ssh_via.split("@", 1)
    ssh_host = parts[1] if len(parts) == 2 else parts[0]
    ssh_user = parts[0] if len(parts) == 2 else None

    class _SshOverride:
        def __init__(self, base: Any, tunnel: SshTunnelConfig) -> None:
            self._base = base
            self.ssh_tunnel = tunnel

        @property
        def database_url(self) -> str:
            if hasattr(self._base, "database_url"):
                return self._base.database_url
            return self._base.get("database_url", "")

        def get(self, key: str, default: Any = None) -> Any:
            return getattr(self._base, key, None) or (
                self._base.get(key, default) if isinstance(self._base, dict) else default
            )

    if format_output == "text":
        console.print(f"[dim]  (connecting via SSH tunnel to {ssh_via})[/dim]")
    return _SshOverride(config_data, SshTunnelConfig(host=ssh_host, user=ssh_user))


def _render_clean(
    message: str,
    format_output: str,
    output_file: Path | None,
    *,
    extra: dict[str, Any] | None = None,
) -> None:
    if format_output == "json":
        emit(
            {"status": "clean", "message": message, "fixes_applied": 0, **(extra or {})},
            output_file,
            console,
        )
    else:
        console.print(f"[green]✅ {message}[/green]")


def _plan_signature_fixes(
    drift_report: Any,
    declared: list[Routine],
    live: list[Routine],
    definitions: Definitions,
    format_output: str,
) -> tuple[list[dict[str, Any]], list[str]]:
    """DROP each stale overload, and CREATE the overloads of its function the database lacks.

    An overload the database holds is not created again: for the deploy shape —
    a migration's ``CREATE OR REPLACE f(bigint)`` left ``f(integer)`` beside it —
    the drop is the whole fix, and ``create_sql`` is empty. Each lacking overload
    is created once, in its function's first block. A stale overload whose
    lacking overloads the source cannot render is skipped: dropping it would leave
    the function undefined.
    """
    fix_blocks: list[dict[str, Any]] = []
    missing_source: list[str] = []
    declared_by_fn, live_by_fn = by_function(declared), by_function(live)
    planned: set[str] = set()
    for overload in drift_report.stale_overloads:
        fn_key = f"{overload.schema}.{overload.name}"
        lacking = [
            routine
            for routine in declared_by_fn.get(fn_key, [])
            if matching(routine, live_by_fn.get(fn_key, [])) is None
            and printed_signature(routine) not in planned
        ]
        creates = [definition_of(definitions, routine) for routine in lacking]
        if fn_key not in definitions or None in creates:
            missing_source.append(overload.stale_signature)
            continue
        planned.update(printed_signature(routine) for routine in lacking)
        fix_blocks.append(
            {
                "stale_signature": overload.stale_signature,
                "drop_sql": overload.drop_sql,
                "create_sql": ";\n".join(create for create in creates if create),
            }
        )
    if missing_source and format_output == "text":
        console.print(
            "[yellow]⚠ Source definition not found for the following overloads "
            "(skipped — would leave function undefined):[/yellow]"
        )
        for sig in missing_source:
            console.print(f"[yellow]    {sig}[/yellow]")
    return fix_blocks, missing_source


def _plan_body_fixes(
    check_body: bool,
    declared: list[Routine],
    live: list[Routine],
    definitions: Definitions,
) -> tuple[list[dict[str, Any]], list[str]]:
    """``--check-body``: CREATE OR REPLACE for each body that drifted.

    A drifted body belongs to an overload both sides hold, which the signature
    fixes never create, so the two plans cannot overlap. Its definition is the
    declared routine the detector paired it with.
    """
    if not check_body:
        return [], []

    body_report = FunctionBodyDriftDetector().compare(declared, live)
    body_fix_blocks: list[dict[str, Any]] = []
    body_missing_source: list[str] = []
    if body_report.has_drift:
        declared_twin = {
            printed_signature(actual): expected for expected, actual in paired(declared, live)
        }
        for drift in body_report.body_drifts:
            expected = declared_twin.get(drift.signature_key)
            create_sql = definition_of(definitions, expected) if expected else None
            if create_sql is None:
                body_missing_source.append(drift.signature_key)
                continue
            body_fix_blocks.append({"signature_key": drift.signature_key, "create_sql": create_sql})
    return body_fix_blocks, body_missing_source


def _render_fix_dry_run(
    fix_blocks: list[dict[str, Any]],
    missing_source: list[str],
    body_fix_blocks: list[dict[str, Any]],
    body_missing_source: list[str],
    *,
    check_body: bool,
    format_output: str,
    output_file: Path | None,
) -> None:
    combined_sql = "\n\n".join(
        "\n".join(part for part in (b["drop_sql"], b["create_sql"]) if part) for b in fix_blocks
    )
    if format_output == "json":
        emit(
            {
                "status": "dry_run",
                "fixes_planned": len(fix_blocks),
                "missing_source": missing_source,
                "sql": combined_sql,
                "blocks": fix_blocks,
                **(
                    {
                        "body_drift_fixes_planned": len(body_fix_blocks),
                        "body_drift_blocks": body_fix_blocks,
                        "body_drift_missing_source": body_missing_source,
                    }
                    if check_body
                    else {}
                ),
            },
            output_file,
            console,
        )
        return
    if fix_blocks:
        console.print(
            f"[bold]Plan: {len(fix_blocks)} fix(es) (pass --mode apply to execute):[/bold]"
        )
        console.print()
        console.print(combined_sql)
    if body_fix_blocks:
        console.print(
            f"[bold]Plan: {len(body_fix_blocks)} body drift fix(es)"
            " (pass --mode apply to execute):[/bold]"
        )
        for block in body_fix_blocks:
            console.print()
            console.print(block["create_sql"])


def _apply_fix_blocks(
    conn: Any, fix_blocks: list[dict[str, Any]], body_fix_blocks: list[dict[str, Any]]
) -> None:
    """All fixes in one transaction; a failure rolls everything back."""
    # The drift reads left a transaction open, and psycopg refuses to change
    # ``autocommit`` inside one: end it first (nothing in it to keep), as
    # rebuild's DDL pass does (#93).
    conn.rollback()
    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            for block in fix_blocks:
                cur.execute(block["drop_sql"])
                if block["create_sql"]:
                    cur.execute(block["create_sql"])
            for block in body_fix_blocks:
                cur.execute(block["create_sql"])
        conn.commit()
    except DatabaseError as apply_exc:
        conn.rollback()
        error_console.print(f"[red]❌ Fix failed (rolled back): {apply_exc}[/red]")
        raise typer.Exit(exit_code_of("SQL_001")) from apply_exc


def _render_fix_applied(
    fix_blocks: list[dict[str, Any]],
    missing_source: list[str],
    body_fix_blocks: list[dict[str, Any]],
    body_missing_source: list[str],
    *,
    report_after: Any,
    body_report_after: Any,
    has_residual: bool,
    check_body: bool,
    format_output: str,
    output_file: Path | None,
) -> None:
    applied = [b["stale_signature"] for b in fix_blocks]
    body_applied = [b["signature_key"] for b in body_fix_blocks]
    if format_output == "json":
        emit(
            {
                "status": "applied" if not has_residual else "partial",
                "fixes_applied": len(fix_blocks),
                "applied": applied,
                "missing_source": missing_source,
                "remaining_drift": report_after.has_drift,
                "remaining_stale": [o.stale_signature for o in report_after.stale_overloads],
                **(
                    {
                        "body_drift_fixes_applied": len(body_fix_blocks),
                        "body_drift_applied": body_applied,
                        "body_drift_missing_source": body_missing_source,
                        "remaining_body_drift": (
                            body_report_after.has_drift if body_report_after else False
                        ),
                    }
                    if check_body
                    else {}
                ),
            },
            output_file,
            console,
        )
        return
    if fix_blocks:
        console.print(f"[green]✅ Applied {len(fix_blocks)} signature fix(es):[/green]")
        for sig in applied:
            console.print(f"[green]    {sig}[/green]")
    if body_fix_blocks:
        console.print(f"[green]✅ Applied {len(body_fix_blocks)} body drift fix(es):[/green]")
        for sig in body_applied:
            console.print(f"[green]    {sig}[/green]")
    if has_residual:
        console.print(
            "[yellow]⚠ Residual drift detected after apply — "
            "run --check-signatures --check-body to investigate.[/yellow]"
        )
    else:
        console.print("[green]✅ Zero drift confirmed after apply.[/green]")
