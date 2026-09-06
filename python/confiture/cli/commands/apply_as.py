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

from confiture.cli.error_json import fail
from confiture.cli.helpers import _get_tracking_table, console, is_json
from confiture.core.connection import load_config
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
      2. Open a MigratorSession on that URL (typically a superuser DSN).
      3. Load the named migration version from --migrations-dir.
      4. Refuse if the version is unknown or already applied.
      5. session.apply_one(version, applied_by=<role>) under the migration lock.

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
    apply_as_block = config_data.get("apply_as") or {}
    role_block = apply_as_block.get(role)
    url_spec = role_block.get("url") if isinstance(role_block, dict) else None
    if url_spec is None:
        fail(
            ConfigurationError(
                f"`apply_as.{role}.url` is required in {config} for `migrate apply-as {role}`.",
                resolution_hint=f"Add an `apply_as.{role}.url` block to {config}.",
            ),
            json_mode=json_mode,
        )

    from confiture.config._env_vars import expand_env_vars

    raw_url = expand_env_vars(url_spec, context=f"apply_as.{role}.url")
    if not isinstance(raw_url, str):
        fail(
            ConfigurationError(f"`apply_as.{role}.url` did not resolve to a string"),
            json_mode=json_mode,
        )

    # Find the migration file for this version.
    if not migrations_dir.exists():
        fail(
            ConfigurationError(
                f"Migrations directory not found: {migrations_dir}",
                error_code="CONFIG_004",
            ),
            json_mode=json_mode,
        )
    migration_file = _find_migration_file(migrations_dir, version)
    if migration_file is None:
        fail(
            MigrationError(
                f"Migration version {version!r} not found in {migrations_dir}.",
                version=version,
                error_code="MIGR_100",
            ),
            json_mode=json_mode,
        )

    from confiture.core.migrator import MigratorSession

    tracking_table = _get_tracking_table(config_data)
    try:
        with MigratorSession(
            None,
            migrations_dir,
            database_url_override=raw_url,
            migration_table_override=tracking_table,
            command="confiture migrate apply-as",
        ) as session:
            try:
                applied = session.apply_one(version, applied_by=role)
            except MigrationError as exc:
                fail(exc, json_mode=json_mode)
    except ConfigurationError as exc:
        fail(exc, json_mode=json_mode)

    if output_format == "json":
        print(
            json.dumps(
                {
                    "success": True,
                    "version": applied.version,
                    "name": applied.name,
                    "applied_by": role,
                }
            )
        )
    else:
        console.print(
            f"[green]✅ Applied migration {applied.version} ({applied.name}) as {role!r}.[/green]"
        )


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
