"""``confiture bootstrap`` — one-shot environment ownership setup (issue #137).

Three modes, chosen with ``--mode``:

- ``check`` (default): report drift; exit 0 if clean, exit 1 if drift
  exists.  Read-only.
- ``plan``: print the exact SQL that ``apply`` would run; no side effects.
  Its JSON payload says ``"mode": "dry-run"``: that value is the payload's
  contract, which consumers match on, not the flag's spelling.
- ``apply``: execute.  Refuses to proceed without ``--all-schemas``
  if a superuser owns objects in schemas outside ``ownership.apply_to``.

Connection requirement
======================
All three modes connect with
``ownership.bootstrap_connection_url``.  Required for ``apply``
because every step needs superuser; ``check`` and ``plan`` also
need it because the planner reads from pg_catalog with permissions
that the regular migrator role typically lacks.

Operational warning
===================
``ALTER … OWNER TO`` takes ``AccessExclusiveLock`` on each object it hands over.
Run during a maintenance window.  See ``docs/guides/bootstrap.md``.
"""

from __future__ import annotations

from pathlib import Path

import typer

from confiture.cli.error_json import cli_boundary, fail
from confiture.cli.helpers import console, emit, is_json
from confiture.cli.markup import verbatim
from confiture.cli.options import (
    CONFITURE_YAML,
    config_option,
    env_option,
    format_option,
    mode_option,
)
from confiture.config._env_vars import expand_env_vars
from confiture.core.bootstrap import BootstrapExecutor, BootstrapPlanner
from confiture.core.connection import DatabaseError, connect_url, load_config
from confiture.core.validation.config_loaders import load_ownership_expectation
from confiture.error_codes import FINDINGS, SUCCESS
from confiture.exceptions import BootstrapError, BootstrapScopeError, ConfigurationError


@cli_boundary
def bootstrap(
    config: Path = config_option(CONFITURE_YAML),
    env: str | None = env_option(None),
    mode: str = mode_option(
        "check",
        "plan",
        "apply",
        help="check: report drift, exit 1 if any; plan: print the SQL apply would run; "
        "apply: execute it",
    ),
    all_schemas: bool = typer.Option(
        False,
        "--all-schemas",
        help=(
            "Hand over superuser-owned objects in every non-system schema, "
            "not only `ownership.apply_to`. Required when a superuser owns "
            "objects outside it. Use during maintenance windows."
        ),
    ),
    output_format: str = format_option("text", "json"),
) -> None:
    """One-shot environment ownership setup (idempotent).

    PROCESS:
      Connects with `ownership.bootstrap_connection_url` (superuser required),
      finds the objects a superuser owns, and plans up to three steps:
        1. CREATE ROLE for the canonical migrator role (if missing).
        2. ALTER … OWNER TO <migrator>, one per superuser-owned object in the
           target schemas (extension members and system schemas excluded).
        3. ALTER DEFAULT PRIVILEGES per schema/role/privs not already granted.

      All steps are idempotent — re-running produces an empty plan once
      the environment matches the desired state.

    EXAMPLES:
      confiture bootstrap --env production
        ↳ Report whether bootstrap is needed; exit 1 if drift exists.

      confiture bootstrap --mode plan --env production
        ↳ Print the SQL --mode apply would run.

      confiture bootstrap --mode apply --env production --all-schemas
        ↳ Execute the plan, handing over objects in every non-system schema.

    SAFETY:
      - --mode apply refuses to proceed without --all-schemas when a
        superuser owns objects in schemas outside `ownership.apply_to`.
      - ALTER … OWNER TO takes AccessExclusiveLock on each object; run
        during a maintenance window.
    """
    json_mode = is_json(output_format)

    if env and config != Path("confiture.yaml"):
        fail(ConfigurationError("Cannot combine --env with --config"), json_mode=json_mode)
    if env:
        config = Path(f"db/environments/{env}.yaml")
    if not config.exists():
        fail(
            ConfigurationError(
                f"Config file not found: {config}",
                error_code="CONFIG_004",
                resolution_hint="Check the path passed to --config (or --env).",
            ),
            json_mode=json_mode,
        )

    config_data = load_config(config)
    ownership = load_ownership_expectation(config_data, config, require=True)
    assert ownership is not None

    if ownership.bootstrap_connection_url is None:
        fail(
            ConfigurationError(
                "`ownership.bootstrap_connection_url` is required for "
                "`confiture bootstrap` (every step needs superuser; we don't "
                "guess a fallback).",
                resolution_hint="Set ownership.bootstrap_connection_url to a superuser DSN.",
            ),
            json_mode=json_mode,
        )

    # ${VAR} expansion already ran at config-load time on the ownership
    # subtree — including bootstrap_connection_url.
    bootstrap_url = expand_env_vars(
        ownership.bootstrap_connection_url, context="bootstrap_connection_url"
    )
    if not isinstance(bootstrap_url, str):
        # Defensive — env-var expansion preserves scalar type.
        fail(
            ConfigurationError("bootstrap_connection_url did not resolve to a string"),
            json_mode=json_mode,
        )

    # Build and (optionally) execute the plan.

    try:
        conn = connect_url(bootstrap_url, autocommit=False)
    except DatabaseError as exc:
        fail(
            ConfigurationError(
                f"Could not connect with bootstrap_connection_url: {exc}",
                error_code="CONFIG_006",
            ),
            json_mode=json_mode,
        )

    try:
        planner = BootstrapPlanner(ownership=ownership)
        try:
            plan = planner.plan(conn, all_schemas=all_schemas)
        except BootstrapScopeError as exc:
            fail(exc, json_mode=json_mode)

        if mode == "check":
            _render_check(plan, output_format)
            if plan.is_empty:
                raise typer.Exit(SUCCESS)  # success-signal: no drift
            raise typer.Exit(FINDINGS)  # success-signal: drift detected

        if mode == "plan":
            _render_dry_run(plan, output_format)
            raise typer.Exit(SUCCESS)  # success-signal: plan rendered, no side effects

        # Otherwise the mode is "apply".
        executor = BootstrapExecutor()
        try:
            result = executor.apply(plan, conn)
        except BootstrapError as exc:
            fail(exc, json_mode=json_mode)

        _render_apply(result, output_format)
        raise typer.Exit(SUCCESS)  # success-signal: applied
    finally:
        conn.close()


def _render_check(plan, output_format: str) -> None:
    if output_format == "json":
        emit(
            {
                "mode": "check",
                "drift": not plan.is_empty,
                "plan": plan.to_dict(),
            }
        )
        return
    if plan.is_empty:
        console.print("[green]✅ Bootstrap is up to date — no drift detected.[/green]")
        return
    console.print(f"[yellow]⚠ Bootstrap drift detected ({len(plan.steps)} step(s)):[/yellow]")
    for step in plan.steps:
        console.print(f"  • [bold]{verbatim(step.label)}[/bold]: {verbatim(step.description)}")
    console.print(
        "[dim]Run `confiture bootstrap --mode plan` to see the SQL, then `--mode apply` to "
        "execute it.[/dim]"
    )


def _render_dry_run(plan, output_format: str) -> None:
    if output_format == "json":
        emit({"mode": "dry-run", "plan": plan.to_dict()})
        return
    if plan.is_empty:
        console.print("[green]✅ Nothing to do — the plan is empty.[/green]")
        return
    console.print(f"[cyan]🔍 Dry-run plan ({len(plan.steps)} step(s)):[/cyan]")
    for step in plan.steps:
        console.print(f"\n[bold]{verbatim(step.label)}[/bold]: {verbatim(step.description)}")
        console.print(f"  [dim]{verbatim(step.sql)};[/dim]")


def _render_apply(result, output_format: str) -> None:
    if output_format == "json":
        emit({"mode": "apply", **result.to_dict()})
        return
    if not result.applied_steps:
        console.print("[green]✅ Bootstrap is already up to date.[/green]")
        return
    console.print(f"[green]✅ Bootstrap applied — {len(result.applied_steps)} step(s):[/green]")
    for label in result.applied_steps:
        console.print(f"  • {verbatim(label)}")


__all__ = ["bootstrap"]
