"""`confiture migrate fix-signatures`.

Split out of the monolithic migrate command modules (Phase 04, Cycle 8).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import psycopg
import typer

from confiture.cli.error_json import cli_boundary
from confiture.cli.helpers import (
    _output_json,
    _resolve_config,
    console,
    error_console,
    open_connection,
)
from confiture.cli.options import format_option
from confiture.core.connection import load_config
from confiture.core.sql_lexer import split_statements


def _extract_function_source(sql: str, schema: str, name: str) -> str | None:
    """Return the full CREATE [OR REPLACE] FUNCTION statement for (schema, name).

    Splits *sql* into individual statements with sqlparse, then returns the
    first one whose header matches ``[schema.]name(``.  Returns ``None`` when
    no matching statement is found.
    """
    # Pattern matches both qualified (schema.name) and unqualified (name) forms
    header_re = re.compile(
        r"CREATE\s+(?:OR\s+REPLACE\s+)?(?:FUNCTION|PROCEDURE)\s+"
        rf"(?:{re.escape(schema)}\.)?{re.escape(name)}\s*\(",
        re.IGNORECASE,
    )
    for stripped in split_statements(sql):
        if header_re.search(stripped):
            return stripped
    return None


@cli_boundary
def migrate_fix_signatures(
    config: Path = typer.Option(
        Path("confiture.yaml"),
        "-c",
        "--config",
        help="Config file path. Use --env as a shortcut for db/environments/{name}.yaml.",
    ),
    env: str | None = typer.Option(
        None,
        "--env",
        help="Environment name — shortcut for --config db/environments/{name}.yaml.",
    ),
    schema_file: Path | None = typer.Option(
        None,
        "--schema",
        help=(
            "Schema SQL file containing the authoritative function definitions. "
            "If omitted, schema is auto-built from DDL files."
        ),
    ),
    check_signature_schemas: str = typer.Option(
        "public",
        "--schemas",
        help="Comma-separated list of schemas to inspect (default: public).",
    ),
    ssh_via: str | None = typer.Option(
        None,
        "--ssh",
        help=(
            "Open an SSH tunnel before connecting: user@host or host. "
            "Overrides the ssh_tunnel block in the config file."
        ),
    ),
    apply: bool = typer.Option(
        False,
        "--apply",
        help=(
            "Execute the fixes in a single transaction. "
            "Default is dry-run: print the SQL and exit without changing the DB."
        ),
    ),
    format_output: str = format_option("text", "json"),
    output_file: Path | None = typer.Option(
        None,
        "--output",
        "-o",
        help="Save output to file (default: stdout).",
    ),
    check_body: bool = typer.Option(
        False,
        "--check-body",
        help=(
            "Also detect and fix function body drift (same signature, different body). "
            "Runs CREATE OR REPLACE from source for each drifted function — no DROP needed."
        ),
    ),
) -> None:
    """Fix stale function overloads: DROP old signature + re-apply source definition.

    PROCESS:
      1. Parse function signatures from --schema (or auto-built DDL).
      2. Introspect live database signatures.
      3. Detect stale overloads (present in DB but not in source).
      4. For each stale overload, generate DROP FUNCTION + CREATE OR REPLACE.
      5. Dry-run (default): print the combined SQL.
         With --apply: execute all fixes in a single transaction.

    EXAMPLES:
      confiture migrate fix-signatures --env local
        ↳ Dry-run: show DROP + CREATE SQL for any stale overloads

      confiture migrate fix-signatures --env production --apply
        ↳ Apply fixes atomically in one transaction

      confiture migrate fix-signatures --env production --ssh lionel@prod-db --apply
        ↳ Apply via SSH tunnel
    """
    try:
        config = _resolve_config(config, env)
        if not config.exists():
            error_console.print(f"[red]❌ Config file not found: {config}[/red]")
            raise typer.Exit(2)
        config_data = load_config(config)
        schemas = [s.strip() for s in check_signature_schemas.split(",") if s.strip()]
        source_sql = _resolve_source_sql(schema_file, config_data, format_output)

        from confiture.core.function_signature_drift import (
            FunctionSignatureDriftDetector,
        )
        from confiture.core.function_signature_parser import (
            FunctionSignatureParser,
        )
        from confiture.core.live_function_catalog import (
            LiveFunctionCatalog,
        )

        source_sigs = FunctionSignatureParser().parse(source_sql)
        effective_config = _ssh_override(config_data, ssh_via, format_output)

        body_report_after: Any = None
        with open_connection(effective_config) as conn:
            live_catalog = LiveFunctionCatalog(conn)
            live_sigs = live_catalog.get_signatures(schemas=schemas)
            drift_report = FunctionSignatureDriftDetector().compare(
                source_sigs, live_sigs, schemas_checked=schemas
            )
            if not drift_report.has_drift and not check_body:
                _render_clean(drift_report.summary(), format_output, output_file)
                return
            # when check_body and no sig drift: fall through to body detection
            fix_blocks, missing_source = _plan_signature_fixes(
                drift_report, source_sql, format_output
            )
            if not fix_blocks and not check_body:
                error_console.print(
                    "[red]❌ No fixable overloads found "
                    "(source definitions missing for all stale overloads).[/red]"
                )
                raise typer.Exit(1)
            source_bodies, body_fix_blocks, body_missing_source = _plan_body_fixes(
                check_body, live_catalog, source_sql, schemas, fix_blocks
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
            report_after = FunctionSignatureDriftDetector().compare(
                source_sigs,
                LiveFunctionCatalog(conn).get_signatures(schemas=schemas),
                schemas_checked=schemas,
            )
            if check_body and source_bodies:
                from confiture.core.function_body_drift import (
                    FunctionBodyDriftDetector,
                )

                live_bodies_after = LiveFunctionCatalog(conn).get_bodies(
                    schemas=schemas, sig_keys=set(source_bodies)
                )
                body_report_after = FunctionBodyDriftDetector().compare(
                    source_bodies, live_bodies_after
                )

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
            raise typer.Exit(1)
    except typer.Exit:
        raise
    # Reason: text-only command: every failure is printed with its context and exits 2
    except Exception as e:
        error_console.print(f"[red]❌ fix-signatures failed: {e}[/red]")
        raise typer.Exit(2) from e


def _resolve_source_sql(schema_file: Path | None, config_data: Any, format_output: str) -> str:
    """``--schema FILE``, else the schema auto-built from the env's DDL files."""
    if schema_file is not None:
        return schema_file.read_text()
    try:
        from confiture.core.builder import SchemaBuilder

        env_name = (
            config_data.get("name")
            if isinstance(config_data, dict)
            else getattr(config_data, "name", None)
        )
        if not env_name:
            raise ValueError(
                "Config has no 'name' field — cannot auto-build schema. Pass --schema explicitly."
            )
        source_sql = SchemaBuilder(env=env_name).build(schema_only=True)
        if format_output == "text":
            console.print("[dim]  (schema auto-built from DDL files)[/dim]")
        return source_sql
    # Reason: an auto-build failure of any kind is reported with the --schema remedy
    except Exception as build_exc:
        error_console.print(
            f"[red]❌ --schema not provided and auto-build failed: {build_exc}[/red]\n"
            "  Either run 'confiture build' first or pass --schema explicitly."
        )
        raise typer.Exit(2) from build_exc


def _ssh_override(config_data: Any, ssh_via: str | None, format_output: str) -> Any:
    """``--ssh-via [user@]host``: the connection goes through an SSH tunnel."""
    if not ssh_via:
        return config_data
    from confiture.config.environment import SshTunnelConfig

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
        _output_json(
            {"status": "clean", "message": message, "fixes_applied": 0, **(extra or {})},
            output_file,
            console,
        )
    else:
        console.print(f"[green]✅ {message}[/green]")


def _plan_signature_fixes(
    drift_report: Any, source_sql: str, format_output: str
) -> tuple[list[dict[str, Any]], list[str]]:
    """DROP + CREATE for each stale overload whose source definition exists."""
    fix_blocks: list[dict[str, Any]] = []
    missing_source: list[str] = []
    for overload in drift_report.stale_overloads:
        create_sql = _extract_function_source(source_sql, overload.schema, overload.name)
        if create_sql is None:
            missing_source.append(overload.stale_signature)
            continue
        fix_blocks.append(
            {
                "stale_signature": overload.stale_signature,
                "drop_sql": overload.drop_sql,
                "create_sql": create_sql,
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
    live_catalog: Any,
    source_sql: str,
    schemas: list[str],
    fix_blocks: list[dict[str, Any]],
) -> tuple[dict[str, str | None], list[dict[str, Any]], list[str]]:
    """``--check-body``: CREATE OR REPLACE for bodies that drifted (a DROP+CREATE already covers its function)."""
    if not check_body:
        return {}, [], []
    from confiture.core.function_body_drift import FunctionBodyDriftDetector
    from confiture.core.function_signature_parser import FunctionSignatureParser

    source_bodies = {
        sig.signature_key(): body
        for sig, body in FunctionSignatureParser().parse_with_bodies(source_sql)
    }
    live_bodies = live_catalog.get_bodies(schemas=schemas, sig_keys=set(source_bodies))
    body_report = FunctionBodyDriftDetector().compare(source_bodies, live_bodies)
    body_fix_blocks: list[dict[str, Any]] = []
    body_missing_source: list[str] = []
    if body_report.has_drift:
        stale_fn_keys = {b["stale_signature"].split("(")[0] for b in fix_blocks}
        for drift in body_report.body_drifts:
            if f"{drift.schema}.{drift.name}" in stale_fn_keys:
                continue
            create_sql = _extract_function_source(source_sql, drift.schema, drift.name)
            if create_sql is None:
                body_missing_source.append(drift.signature_key)
                continue
            body_fix_blocks.append({"signature_key": drift.signature_key, "create_sql": create_sql})
    return source_bodies, body_fix_blocks, body_missing_source


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
    combined_sql = "\n\n".join(f"{b['drop_sql']}\n{b['create_sql']}" for b in fix_blocks)
    if format_output == "json":
        _output_json(
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
            f"[bold]Dry-run: {len(fix_blocks)} fix(es) planned (pass --apply to execute):[/bold]"
        )
        console.print()
        console.print(combined_sql)
    if body_fix_blocks:
        console.print(
            f"[bold]Dry-run: {len(body_fix_blocks)} body drift fix(es) planned"
            " (pass --apply to execute):[/bold]"
        )
        for block in body_fix_blocks:
            console.print()
            console.print(block["create_sql"])


def _apply_fix_blocks(
    conn: Any, fix_blocks: list[dict[str, Any]], body_fix_blocks: list[dict[str, Any]]
) -> None:
    """All fixes in one transaction; a failure rolls everything back."""
    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            for block in fix_blocks:
                cur.execute(block["drop_sql"])
                cur.execute(block["create_sql"])
            for block in body_fix_blocks:
                cur.execute(block["create_sql"])
        conn.commit()
    except psycopg.Error as apply_exc:
        conn.rollback()
        error_console.print(f"[red]❌ Fix failed (rolled back): {apply_exc}[/red]")
        raise typer.Exit(1) from apply_exc


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
        _output_json(
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
