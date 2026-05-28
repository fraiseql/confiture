"""``confiture migrate apply-as <role> <version>`` (issue #137 part 2).

Apply exactly one migration as an explicit PostgreSQL role.  Companion
to ``MigratorSession.up()``'s halt-at-first-skip behavior: when up
halts at a ``requires_superuser=True`` migration, the operator runs
this command to apply that one migration with superuser, then re-runs
``migrate up`` to resume the chain.

Connection
==========
The connection URL is read from a new ``apply_as.<role>.url`` config
block (env-var-expanded).  We never silently reuse the env's main URL
because the whole point of ``apply-as`` is to use a different role
than the default migrator.
"""

from __future__ import annotations

import json
from pathlib import Path

import typer

from confiture.cli.helpers import console, error_console
from confiture.core.connection import load_config, load_migration_class
from confiture.exceptions import ConfigurationError, MigrationError


def migrate_apply_as(
    role: str = typer.Argument(
        ...,
        help=(
            "PostgreSQL role under which to apply the migration. "
            "Connection URL is read from `apply_as.<role>.url` in the env config."
        ),
    ),
    version: str = typer.Argument(
        ...,
        help="Migration version to apply (e.g. 20260528120000).",
    ),
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
            "Environment name — shortcut for --config db/environments/{name}.yaml. "
            "Cannot be combined with --config."
        ),
    ),
    migrations_dir: Path = typer.Option(
        Path("db/migrations"),
        "--migrations-dir",
        help="Migrations directory (default: db/migrations).",
    ),
    output_format: str = typer.Option(
        "text",
        "--format",
        "-f",
        help="Output format: text or json (default: text).",
    ),
) -> None:
    """Apply exactly one migration as an explicit PostgreSQL role.

    PROCESS:
      1. Look up `apply_as.<role>.url` in the env config; refuse if absent.
      2. Connect with that URL (typically a superuser DSN).
      3. Load the named migration version from --migrations-dir.
      4. Refuse if the version is unknown or already applied.
      5. Run apply() with applied_by=<role>; record in the tracking table.

    EXAMPLES:
      confiture migrate apply-as postgres 20260528120000 --env production
        ↳ Apply migration 20260528120000 as `postgres`.

      confiture migrate apply-as postgres 20260528120000 --env staging --format json
        ↳ Same, JSON output.

    RECOVERY WORKFLOW:
      1. `confiture migrate up` halts at a requires_superuser=True migration.
      2. Run `confiture migrate apply-as <role> <version>` for that one.
      3. Re-run `confiture migrate up` to apply the remaining chain.
    """
    if env and config != Path("confiture.yaml"):
        error_console.print("[red]❌ Cannot combine --env with --config[/red]")
        raise typer.Exit(2)
    if env:
        config = Path(f"db/environments/{env}.yaml")
    if not config.exists():
        error_console.print(f"[red]❌ Config file not found: {config}[/red]")
        raise typer.Exit(2)

    config_data = load_config(config)
    apply_as_block = config_data.get("apply_as") or {}
    role_block = apply_as_block.get(role)
    if not isinstance(role_block, dict) or "url" not in role_block:
        error_console.print(
            f"[red]❌ `apply_as.{role}.url` is required in {config} for "
            f"`migrate apply-as {role}`.[/red]"
        )
        raise typer.Exit(2)

    from confiture.config._env_vars import expand_env_vars

    raw_url = expand_env_vars(role_block["url"], context=f"apply_as.{role}.url")
    if not isinstance(raw_url, str):
        error_console.print(f"[red]❌ `apply_as.{role}.url` did not resolve to a string[/red]")
        raise typer.Exit(2)

    # Find the migration file for this version.
    if not migrations_dir.exists():
        error_console.print(f"[red]❌ Migrations directory not found: {migrations_dir}[/red]")
        raise typer.Exit(2)
    migration_file = _find_migration_file(migrations_dir, version)
    if migration_file is None:
        error_console.print(
            f"[red]❌ Migration version {version!r} not found in {migrations_dir}.[/red]"
        )
        raise typer.Exit(2)

    import psycopg

    from confiture.core._migrator.engine import Migrator

    try:
        conn = psycopg.connect(raw_url, autocommit=False)
    except psycopg.OperationalError as exc:
        error_console.print(f"[red]❌ Could not connect with apply_as.{role}.url: {exc}[/red]")
        raise typer.Exit(2) from exc

    try:
        tracking_table = config_data.get("migration", {}).get("tracking_table") or "tb_confiture"
        migrator = Migrator(connection=conn, migration_table=tracking_table)
        migrator.initialize()

        # Refuse if already applied.
        applied = set(migrator.get_applied_versions())
        if version in applied:
            if output_format == "json":
                print(
                    json.dumps(
                        {
                            "success": False,
                            "error": "already_applied",
                            "version": version,
                        }
                    )
                )
            else:
                error_console.print(f"[yellow]⚠ Migration {version} is already applied.[/yellow]")
            raise typer.Exit(2)

        migration_class = load_migration_class(migration_file)
        migration = migration_class(connection=conn)

        try:
            migrator.apply(
                migration,
                migration_file=migration_file,
                applied_by=role,
            )
        except MigrationError as exc:
            if output_format == "json":
                print(json.dumps({"success": False, "error": str(exc)}))
            else:
                error_console.print(f"[red]❌ apply-as failed: {exc}[/red]")
            raise typer.Exit(3) from exc

        if output_format == "json":
            print(
                json.dumps(
                    {
                        "success": True,
                        "version": migration.version,
                        "name": migration.name,
                        "applied_by": role,
                    }
                )
            )
        else:
            console.print(
                f"[green]✅ Applied migration {migration.version} "
                f"({migration.name}) as {role!r}.[/green]"
            )
    except ConfigurationError as exc:
        error_console.print(f"[red]❌ {exc}[/red]")
        raise typer.Exit(2) from exc
    finally:
        conn.close()


def _find_migration_file(migrations_dir: Path, version: str) -> Path | None:
    """Return the migration file matching *version*, or None.

    Looks for both ``<version>_*.py`` and ``<version>_*.up.sql``
    patterns.  Matches the discovery convention used by the migrator.
    """
    matches: list[Path] = []
    for suffix in (".py", ".up.sql"):
        matches.extend(migrations_dir.glob(f"{version}_*{suffix}"))
    if not matches:
        return None
    # Prefer .py over .up.sql if both somehow exist for the same version.
    return sorted(matches)[0]


__all__ = ["migrate_apply_as"]
