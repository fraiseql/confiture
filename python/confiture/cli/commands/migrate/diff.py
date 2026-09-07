"""`confiture migrate diff`.

Split out of the monolithic migrate command modules.
"""

from __future__ import annotations

from pathlib import Path

import typer

from confiture.cli.error_json import cli_boundary, fail
from confiture.cli.formatters.migrate_formatter import format_migrate_diff_result
from confiture.cli.helpers import (
    console,
    is_json,
)
from confiture.cli.options import format_option
from confiture.config.environment import MigrationConfig
from confiture.core import connection as _core_connection
from confiture.core.desired_state import DesiredStateSource, load_desired_state
from confiture.core.destructive import data_loss_reason, resolve_policy
from confiture.core.differ import SchemaDiffer
from confiture.core.migration_generator import MigrationGenerator
from confiture.core.temp_database import clean_pg_dump_output, pg_dump_schema
from confiture.exceptions import DifferError, ValidationError
from confiture.models.results import MigrateDiffChange, MigrateDiffResult


@cli_boundary
def migrate_diff(
    old_schema: Path | None = typer.Argument(None, help="Old schema file"),
    new_schema: Path | None = typer.Argument(None, help="New schema file"),
    from_: str | None = typer.Option(
        None,
        "--from",
        help=(
            "Current state: a schema file, a directory of .sql files, '-' for stdin, "
            "or 'db' for the configured database (default: the first positional)"
        ),
    ),
    to: str | None = typer.Option(
        None,
        "--to",
        help=(
            "Desired state: a schema file, a directory of .sql files (what fraiseql's "
            "emit-ddl option writes), or '-' for stdin (default: the second positional)"
        ),
    ),
    config: Path = typer.Option(
        Path("db/environments/local.yaml"),
        "--config",
        "-c",
        help="Environment config, read for `--from db` (default: db/environments/local.yaml)",
    ),
    generate: bool = typer.Option(
        False,
        "--generate",
        help="Generate a migration from the differences: a .up.sql/.down.sql pair with --from/--to, a Python migration with positional files",
    ),
    name: str = typer.Option(
        None,
        "--name",
        help="Migration name (default: none, required with --generate)",
    ),
    migrations_dir: Path = typer.Option(
        Path("db/migrations"),
        "--migrations-dir",
        help="Migrations directory (default: db/migrations)",
    ),
    format_type: str = format_option("text", "json", "csv"),
    allow_destructive: bool = typer.Option(
        False,
        "--allow-destructive",
        help="Write data-losing DDL unmarked, whatever migration.destructive says",
    ),
    forbid_destructive: bool = typer.Option(
        False,
        "--forbid-destructive",
        help="Refuse to generate a migration that loses data (exit 5, DIFFER_401)",
    ),
    report_file: Path | None = typer.Option(
        None,
        "--report",
        "-o",
        help="Save report to file (default: stdout)",
    ),
) -> None:
    """Compare two schema files and identify differences.

    PROCESS:
      Compares old and new schema files, shows additions/modifications/removals.
      Optionally generates a migration file from the detected differences.

    EXAMPLES:
      confiture migrate diff schema_old.sql schema_new.sql
        ↳ Show all differences between two schemas

      confiture migrate diff schema_old.sql schema_new.sql --generate --name add_payments
        ↳ Generate migration file from differences

      confiture migrate diff db/generated/schema_local.sql db/schema/production.sql
        ↳ Compare local schema with production target

    RELATED:
      confiture migrate generate - Create migration template
      confiture migrate validate - Check migration integrity
      confiture build             - Build schema from DDL files
    """
    try:
        current, desired = _resolve_sides(
            old_schema,
            new_schema,
            from_=from_,
            to=to,
            json_mode=is_json(format_type),
            report=report_file,
        )
        old_sql = _read_current(current, config)
        new_sql = desired.read()

        # Compare schemas
        differ = SchemaDiffer()
        diff = differ.compare(old_sql, new_sql)

        # Convert changes to SchemaChange objects

        changes = [
            MigrateDiffChange(
                change.type,
                str(change),
                irreversible_reason=data_loss_reason(change),
            )
            for change in diff.changes
        ]
        migration_file_name = None
        policy: str | None = None

        # Handle migration generation if requested
        if generate:
            if not name:
                fail(
                    ValidationError(
                        "--generate requires --name",
                        resolution_hint=(
                            "Usage: confiture migrate diff old.sql new.sql --generate --name migration_name"
                        ),
                    ),
                    json_mode=is_json(format_type),
                    output_file=report_file,
                )

            # Ensure migrations directory exists
            migrations_dir.mkdir(parents=True, exist_ok=True)

            # Generate migration
            generator = MigrationGenerator(migrations_dir=migrations_dir)
            ingest = from_ is not None or to is not None
            policy = _destructive_policy(
                config,
                allow=allow_destructive,
                forbid=forbid_destructive,
                json_mode=is_json(format_type),
                report=report_file,
            )
            try:
                migration_file = (
                    generator.generate_sql(diff, name=name, destructive=policy)
                    if ingest
                    else generator.generate(diff, name=name, destructive=policy)
                )
            except DifferError as exc:  # the gate's refusal (DIFFER_401) carries its own code
                fail(exc, json_mode=is_json(format_type), output_file=report_file)
            migration_file_name = migration_file.name

        # Create result and format output
        result = MigrateDiffResult(
            success=True,
            has_changes=diff.has_changes(),
            changes=changes,
            migration_generated=generate and migration_file_name is not None,
            migration_file=migration_file_name,
            source=desired.describe(),
            destructive_gate=policy,
        )

        format_migrate_diff_result(result, format_type, report_file, console)

    except (typer.Exit, typer.BadParameter):
        raise
    # Reason: the diff result carries the failure so the formatter can render it in every format
    except Exception as e:
        result = MigrateDiffResult(
            success=False,
            has_changes=False,
            error=str(e),
        )
        format_migrate_diff_result(result, format_type, report_file, console)
        raise typer.Exit(1) from e


def _resolve_sides(
    old_schema: Path | None,
    new_schema: Path | None,
    *,
    from_: str | None,
    to: str | None,
    json_mode: bool,
    report: Path | None,
) -> tuple[str, DesiredStateSource]:
    """The two sides of the diff: ``(current spec, desired-state source)``.

    Either both positionals or both ``--from``/``--to``; mixing the two forms
    is refused (exit 5). The current side is a spec string (``db`` is special),
    the desired side a :class:`DesiredStateSource`.
    """
    positional = old_schema is not None or new_schema is not None
    named = from_ is not None or to is not None
    if positional and named:
        fail(
            ValidationError(
                "Use either `migrate diff OLD NEW` or `--from … --to …`, not both.",
                resolution_hint="Drop the positional arguments, or the --from/--to options.",
            ),
            json_mode=json_mode,
            output_file=report,
        )
    if named:
        if from_ is None or to is None:
            fail(
                ValidationError(
                    "--from and --to go together.",
                    resolution_hint="Usage: confiture migrate diff --from current.sql --to desired/",
                ),
                json_mode=json_mode,
                output_file=report,
            )
        return from_, load_desired_state(to)
    if old_schema is None or new_schema is None:
        # A missing positional is a usage error (exit 2), as it was when the
        # arguments were required; the sides only became optional for --from/--to.
        raise typer.BadParameter(
            "Missing argument: give OLD_SCHEMA and NEW_SCHEMA, or --from/--to.",
            param_hint="OLD_SCHEMA NEW_SCHEMA",
        )
    for label, schema_path in (("Old", old_schema), ("New", new_schema)):
        if not schema_path.exists():
            fail(
                ValidationError(
                    f"{label} schema file not found: {schema_path}",
                    context={"path": str(schema_path)},
                    resolution_hint="Pass two existing schema files: migrate diff OLD.sql NEW.sql",
                ),
                json_mode=json_mode,
                output_file=report,
            )
    return str(old_schema), load_desired_state(str(new_schema))


def _read_current(spec: str, config: Path) -> str:
    """The current schema's DDL: ``db`` dumps the configured database, else a file/dir/stdin."""
    if spec == "db":
        return clean_pg_dump_output(
            pg_dump_schema(_core_connection.dsn_from_config(_core_connection.load_config(config)))
        )
    return load_desired_state(spec).read()


def _destructive_policy(
    config: Path, *, allow: bool, forbid: bool, json_mode: bool, report: Path | None
) -> str:
    """The gate policy for this run: the flags, else ``migration.destructive`` from ``config``.

    A missing config file (the positional form needs none) means the default,
    ``gated``. Both flags at once is a validation error (exit 5).
    """
    configured = "gated"
    if config.exists():
        migration = _core_connection.load_config(config).get("migration") or {}
        configured = MigrationConfig.model_validate(migration).destructive
    try:
        return resolve_policy(configured, allow=allow, forbid=forbid)
    except ValidationError as exc:
        fail(exc, json_mode=json_mode, output_file=report)
