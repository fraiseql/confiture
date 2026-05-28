"""``confiture bootstrap`` — one-shot environment ownership setup (issue #137).

Three modes:

- ``--check`` (default): report drift; exit 0 if clean, exit 1 if drift
  exists, exit 2 on fatal error.  Read-only.
- ``--dry-run``: print the exact SQL that ``--apply`` would run; no
  side effects.
- ``--apply``: execute.  Refuses to proceed without ``--all-schemas``
  if ``REASSIGN OWNED`` would affect schemas outside
  ``ownership.apply_to``.

Connection requirement
======================
All three modes connect with
``ownership.bootstrap_connection_url``.  Required for ``--apply``
because every step needs superuser; ``--check`` and ``--dry-run`` also
need it because the planner reads from pg_catalog with permissions
that the regular migrator role typically lacks.

Operational warning
===================
``REASSIGN OWNED`` grabs ``AccessExclusiveLock`` on affected objects.
Run during a maintenance window.  See ``docs/guides/bootstrap.md``.
"""

from __future__ import annotations

import json
from pathlib import Path

import typer

from confiture.cli.helpers import console, error_console
from confiture.cli.ownership_loader import load_ownership_expectation
from confiture.config._env_vars import expand_env_vars
from confiture.core.bootstrap import BootstrapExecutor, BootstrapPlanner
from confiture.core.connection import load_config
from confiture.exceptions import BootstrapError, BootstrapScopeError


def bootstrap(
    config: Path = typer.Option(
        Path("confiture.yaml"),
        "-c",
        "--config",
        help="Config file path. Use --env as a shortcut for db/environments/{name}.yaml.",
    ),
    env: str | None = typer.Option(
        None,
        "--env",
        help=(
            "Environment name — shortcut for --config db/environments/{name}.yaml "
            "(e.g. --env production). Cannot be combined with --config."
        ),
    ),
    check: bool = typer.Option(
        True,
        "--check/--no-check",
        help="Read-only: report drift; exit 1 if drift exists.  Default mode.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Print the SQL that --apply would run; no side effects.",
    ),
    apply_mode: bool = typer.Option(
        False,
        "--apply",
        help="Execute the bootstrap plan against the database.",
    ),
    all_schemas: bool = typer.Option(
        False,
        "--all-schemas",
        help=(
            "Authorize `REASSIGN OWNED` across schemas outside "
            "`ownership.apply_to`. Required when postgres-owned objects "
            "exist in non-scoped schemas. Use during maintenance windows."
        ),
    ),
    output_format: str = typer.Option(
        "text",
        "--format",
        "-f",
        help="Output format: text or json (default: text).",
    ),
) -> None:
    """One-shot environment ownership setup (idempotent).

    PROCESS:
      Connects with `ownership.bootstrap_connection_url` (superuser required),
      enumerates postgres-owned objects, and plans up to three steps:
        1. CREATE ROLE for the canonical migrator role (if missing).
        2. REASSIGN OWNED BY postgres TO <migrator> (database-wide).
        3. ALTER DEFAULT PRIVILEGES per schema/role/privs.

      All steps are idempotent — re-running produces an empty plan once
      the environment matches the desired state.

    EXAMPLES:
      confiture bootstrap --check --env production
        ↳ Report whether bootstrap is needed; exit 1 if drift exists.

      confiture bootstrap --dry-run --env production
        ↳ Print the SQL --apply would run.

      confiture bootstrap --apply --env production --all-schemas
        ↳ Execute the plan, authorizing database-wide REASSIGN OWNED.

    SAFETY:
      - --apply refuses to proceed without --all-schemas when postgres
        owns objects in schemas outside `ownership.apply_to`.
      - REASSIGN OWNED takes AccessExclusiveLock; run during a maintenance
        window.
    """
    if env and config != Path("confiture.yaml"):
        error_console.print("[red]❌ Cannot combine --env with --config[/red]")
        raise typer.Exit(2)
    if env:
        config = Path(f"db/environments/{env}.yaml")
    if not config.exists():
        error_console.print(f"[red]❌ Config file not found: {config}[/red]")
        raise typer.Exit(2)

    # Resolve mode: --apply and --dry-run override --check.
    if apply_mode and dry_run:
        error_console.print("[red]❌ Cannot combine --apply with --dry-run[/red]")
        raise typer.Exit(2)
    mode = "apply" if apply_mode else "dry-run" if dry_run else "check"

    config_data = load_config(config)
    ownership = load_ownership_expectation(config_data, config, require=True)
    assert ownership is not None  # noqa: S101 — require=True guarantees non-None

    if ownership.bootstrap_connection_url is None:
        error_console.print(
            "[red]❌ `ownership.bootstrap_connection_url` is required for "
            "`confiture bootstrap` (every step needs superuser; we don't "
            "guess a fallback).[/red]"
        )
        raise typer.Exit(2)

    # ${VAR} expansion already ran at config-load time on the ownership
    # subtree — including bootstrap_connection_url.
    bootstrap_url = expand_env_vars(
        ownership.bootstrap_connection_url, context="bootstrap_connection_url"
    )
    if not isinstance(bootstrap_url, str):
        # Defensive — env-var expansion preserves scalar type.
        error_console.print("[red]❌ bootstrap_connection_url did not resolve to a string[/red]")
        raise typer.Exit(2)

    # Build and (optionally) execute the plan.
    import psycopg

    try:
        conn = psycopg.connect(bootstrap_url, autocommit=False)
    except psycopg.OperationalError as exc:
        error_console.print(f"[red]❌ Could not connect with bootstrap_connection_url: {exc}[/red]")
        raise typer.Exit(2) from exc

    try:
        planner = BootstrapPlanner(ownership=ownership)
        try:
            plan = planner.plan(conn, all_schemas=all_schemas)
        except BootstrapScopeError as exc:
            if output_format == "json":
                print(
                    json.dumps(
                        {
                            "mode": mode,
                            "success": False,
                            "error": "scope",
                            "message": str(exc),
                        }
                    )
                )
            else:
                error_console.print(f"[red]❌ {exc}[/red]")
                if exc.resolution_hint:
                    error_console.print(f"[dim]💡 {exc.resolution_hint}[/dim]")
            raise typer.Exit(2) from exc

        if mode == "check":
            _render_check(plan, output_format)
            if plan.is_empty:
                raise typer.Exit(0)
            raise typer.Exit(1)

        if mode == "dry-run":
            _render_dry_run(plan, output_format)
            raise typer.Exit(0)

        # mode == "apply"
        executor = BootstrapExecutor()
        try:
            result = executor.apply(plan, conn)
        except BootstrapError as exc:
            if output_format == "json":
                print(
                    json.dumps(
                        {
                            "mode": "apply",
                            "success": False,
                            "error": str(exc),
                        }
                    )
                )
            else:
                error_console.print(f"[red]❌ {exc}[/red]")
                if exc.resolution_hint:
                    error_console.print(f"[dim]💡 {exc.resolution_hint}[/dim]")
            raise typer.Exit(2) from exc

        _render_apply(result, output_format)
        raise typer.Exit(0)
    finally:
        conn.close()


def _render_check(plan, output_format: str) -> None:
    if output_format == "json":
        print(
            json.dumps(
                {
                    "mode": "check",
                    "drift": not plan.is_empty,
                    "plan": plan.to_dict(),
                }
            )
        )
        return
    if plan.is_empty:
        console.print("[green]✅ Bootstrap is up to date — no drift detected.[/green]")
        return
    console.print(f"[yellow]⚠ Bootstrap drift detected ({len(plan.steps)} step(s)):[/yellow]")
    for step in plan.steps:
        console.print(f"  • [bold]{step.label}[/bold]: {step.description}")
    console.print(
        "[dim]Run `confiture bootstrap --dry-run` to see the SQL, then `--apply` to execute.[/dim]"
    )


def _render_dry_run(plan, output_format: str) -> None:
    if output_format == "json":
        print(json.dumps({"mode": "dry-run", "plan": plan.to_dict()}))
        return
    if plan.is_empty:
        console.print("[green]✅ Nothing to do — the plan is empty.[/green]")
        return
    console.print(f"[cyan]🔍 Dry-run plan ({len(plan.steps)} step(s)):[/cyan]")
    for step in plan.steps:
        console.print(f"\n[bold]{step.label}[/bold]: {step.description}")
        console.print(f"  [dim]{step.sql};[/dim]")


def _render_apply(result, output_format: str) -> None:
    if output_format == "json":
        print(json.dumps({"mode": "apply", **result.to_dict()}))
        return
    if not result.applied_steps:
        console.print("[green]✅ Bootstrap is already up to date.[/green]")
        return
    console.print(f"[green]✅ Bootstrap applied — {len(result.applied_steps)} step(s):[/green]")
    for label in result.applied_steps:
        console.print(f"  • {label}")


__all__ = ["bootstrap"]
