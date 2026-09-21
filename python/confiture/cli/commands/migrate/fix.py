"""`confiture migrate fix`.

Split out of the monolithic migrate command modules.
"""

from __future__ import annotations

from pathlib import Path

import typer

from confiture.cli.error_json import cli_boundary
from confiture.cli.helpers import console, is_json
from confiture.cli.idempotency import _fix_idempotency
from confiture.cli.options import config_option, format_option, migrations_dir_option, output_option
from confiture.cli.ownership import _fix_ownership
from confiture.core.connection import load_config
from confiture.exceptions import ConfigurationError

#: Where ``--ownership`` looks when no ``--config`` is given. The option's
#: default is ``None`` so the body can tell "not given" from "given this"; the
#: documented default lives here.
DEFAULT_CONFIG_PATH = Path("confiture.yaml")


@cli_boundary
def migrate_fix(
    migrations_dir: Path = migrations_dir_option(),
    idempotent: bool = typer.Option(
        False,
        "--idempotent",
        help="Fix non-idempotent SQL statements (default: off)",
    ),
    ownership: bool = typer.Option(
        False,
        "--ownership",
        help=(
            "Insert missing `ALTER … OWNER TO <expected_owner>` after each "
            "CREATE that lacks one.  Requires an `ownership:` block in the "
            "config."
        ),
    ),
    config_path: Path | None = config_option(
        None, help="Config file (needed for --ownership; defaults to confiture.yaml)"
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help=(
            "With --ownership --apply: rewrite migration files even when "
            "their checksum is already recorded in the local tracking table.  "
            "Use with care — downstream `migrate verify` will report drift."
        ),
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Preview changes without modifying files (default: off)",
    ),
    format_output: str = format_option("text", "json"),
    output_file: Path | None = output_option(),
) -> None:
    """Auto-fix non-idempotent SQL in migrations.

    PROCESS:
      Transforms non-idempotent statements to safe-to-rerun equivalents:
      CREATE TABLE → CREATE TABLE IF NOT EXISTS, CREATE INDEX → CREATE INDEX
      IF NOT EXISTS, DROP TABLE → DROP TABLE IF EXISTS, and more.

    EXAMPLES:
      confiture migrate fix --idempotent --dry-run
        ↳ Preview what would be fixed without modifying files

      confiture migrate fix --idempotent
        ↳ Apply all fixes to migration files

      confiture migrate fix --idempotent --format json --output fixes.json
        ↳ Generate JSON report of all transformations

    JSON SCHEMA:
      See docs/reference/json-schemas.md for the JSON output schema
      (migrate-fix.schema.json).

    RELATED:
      confiture migrate validate - Check migration quality
      confiture migrate up       - Apply migrations
      confiture migrate generate - Create new migration
    """
    is_json(format_output)
    # A --config the operator typed is read whatever this run goes on to do
    # (#284). Only --ownership uses it, so `migrate fix --idempotent --config
    # broken.yaml` used to rewrite migration files while never opening the file
    # the operator named, and `migrate fix --config broken.yaml` with no fix
    # type printed a usage warning and exited 0.
    if config_path is not None:
        load_config(config_path)
    config_path = config_path or DEFAULT_CONFIG_PATH
    if not migrations_dir.exists():
        raise ConfigurationError(
            f"Migrations directory not found: {migrations_dir.absolute()}",
            error_code="CONFIG_004",
        )

    if not idempotent and not ownership:
        console.print(
            "[yellow]⚠️  No fix type specified.  Use --idempotent and/or --ownership.[/yellow]"
        )
        return

    if idempotent:
        _fix_idempotency(migrations_dir, dry_run, format_output, output_file)

    if ownership:
        _fix_ownership(
            migrations_dir=migrations_dir,
            config_path=config_path,
            dry_run=dry_run,
            force=force,
            format_output=format_output,
            output_file=output_file,
        )
