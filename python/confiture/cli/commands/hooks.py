"""CLI: ``confiture hooks`` — operate on configured notification hooks.

Currently exposes a single command:

* ``confiture hooks test [--id <id>] [--no-dry-run]`` — fire a synthetic
  notification through one configured hook.  Default is ``--dry-run``
  (the real transport is swapped for :class:`StdoutTransport` so no
  external service is contacted).  Pass ``--no-dry-run`` to call the
  real transport.

The command reads the ``notifications:`` block from the environment YAML
indicated by ``--config`` (or ``--env``), validates it via the same
machinery the migrator uses at runtime, and exits with a non-zero code
if anything is malformed.  This makes the command useful for verifying
hook setup before a real migration ever fires.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import typer
import yaml

from confiture.cli.error_json import fail
from confiture.cli.helpers import _resolve_config, console
from confiture.core.hooks.context import ExecutionContext, HookContext
from confiture.core.hooks.notifications.config import load_notifications_config
from confiture.core.hooks.notifications.factory import from_config
from confiture.core.hooks.notifications.transport import StdoutTransport
from confiture.exceptions import ConfigurationError

hooks_app = typer.Typer(
    help="Operate on configured notification hooks",
    no_args_is_help=True,
)


def _load_notifications_from_yaml(config_path: Path) -> Any:
    """Read the ``notifications:`` block from *config_path* and validate it.

    Returns the validated :class:`NotificationsRootConfig`.  Raises
    :class:`ConfigurationError` for any problem (missing file, malformed
    YAML, no notifications section, validation failure).
    """
    if not config_path.exists():
        raise ConfigurationError(f"Config file not found: {config_path}")

    try:
        with config_path.open() as fp:
            raw = yaml.safe_load(fp) or {}
    except yaml.YAMLError as exc:
        raise ConfigurationError(f"Invalid YAML in {config_path}: {exc}") from exc

    notifications_raw = raw.get("notifications")
    if notifications_raw is None:
        raise ConfigurationError(
            f"No 'notifications:' section in {config_path}.\n"
            "Add hooks under:\n\n"
            "  notifications:\n"
            "    hooks:\n"
            "      - id: my-hook\n"
            "        transport: {type: stdout}\n"
            "        renderer: {type: raw_json}\n"
        )

    return load_notifications_config(notifications_raw)


def _synthetic_execution_context() -> ExecutionContext:
    """Build an :class:`ExecutionContext` that looks like a real migration.

    Used by the ``hooks test`` command so renderers receive realistic input
    without touching the database.
    """
    return ExecutionContext(
        elapsed_time_ms=247,
        rows_affected=42,
        metadata={
            "migration_name": "synthetic_test_migration",
            "migration_version": "20260520120000",
            "direction": "up",
            "success": True,
            "database_name": "confiture_test",
            "schema": "public",
            "migrations_applied": ["20260520120000_synthetic_test_migration"],
        },
    )


@hooks_app.command("test")
def hooks_test(
    config: Path = typer.Option(
        Path("confiture.yaml"),
        "--config",
        "-c",
        help="Path to environment config (default: confiture.yaml)",
    ),
    env: str | None = typer.Option(
        None,
        "--env",
        "-e",
        help="Environment name — shortcut for db/environments/{env}.yaml",
    ),
    hook_id: str | None = typer.Option(
        None,
        "--id",
        help="Hook id to test (required when multiple hooks configured)",
    ),
    no_dry_run: bool = typer.Option(
        False,
        "--no-dry-run",
        help=(
            "Send through the real transport.  Default is dry-run — the "
            "configured transport is swapped for StdoutTransport so no "
            "external service is contacted."
        ),
    ),
) -> None:
    """Fire a synthetic notification through one configured hook."""
    try:
        config_path = _resolve_config(config, env)
        root_cfg = _load_notifications_from_yaml(config_path)
    except ConfigurationError as exc:
        fail(exc, json_mode=False)

    hooks = root_cfg.hooks
    if not hooks:
        fail(
            ConfigurationError(
                "No notification hooks configured.",
                resolution_hint=(
                    "Add at least one entry under `notifications.hooks` in your config."
                ),
            ),
            json_mode=False,
        )

    if hook_id is None:
        if len(hooks) > 1:
            ids = ", ".join(h.id for h in hooks)
            fail(
                ConfigurationError(f"Multiple hooks configured ({ids}); pass --id to choose one."),
                json_mode=False,
            )
        chosen = hooks[0]
    else:
        matches = [h for h in hooks if h.id == hook_id]
        if not matches:
            ids = ", ".join(h.id for h in hooks)
            fail(
                ConfigurationError(f"Hook id {hook_id!r} not found.  Configured: {ids}"),
                json_mode=False,
            )
        chosen = matches[0]

    hook = from_config(chosen, allow_templated_renderers=root_cfg.allow_templated_renderers)

    if not no_dry_run:
        # Default path — swap to StdoutTransport so the real service is not
        # contacted.  The renderer is unchanged so the user sees exactly
        # what would be sent.
        hook.transport = StdoutTransport()
        console.print(
            f"[cyan]🔍 Dry-run for hook {chosen.id!r} "
            "(transport swapped to stdout).  Pass --no-dry-run to send for real.[/cyan]"
        )
    else:
        console.print(
            f"[yellow]⚠️  Sending real notification through hook {chosen.id!r} "
            f"(transport: {type(hook.transport).__name__}).[/yellow]"
        )

    ctx = _synthetic_execution_context()
    wrapped = HookContext(phase=chosen.phase, data=ctx)
    result = asyncio.run(hook.execute(wrapped))

    if result.success:
        console.print(f"[green]✅ Hook {chosen.id!r} executed successfully.[/green]")
        raise typer.Exit(0)  # success-signal: clean pass
    console.print(f"[red]❌ Hook {chosen.id!r} failed: {result.error}[/red]")
    # success-signal: the test ran and is reporting that the configured hook
    # failed — the diagnostic result the user asked for, not a confiture error.
    raise typer.Exit(1)
