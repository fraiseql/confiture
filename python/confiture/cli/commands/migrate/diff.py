"""`confiture migrate diff`.

Split out of the monolithic migrate command modules.
"""

from dataclasses import replace
from pathlib import Path

import typer

from confiture.cli.error_json import cli_boundary, fail
from confiture.cli.formatters.migrate_formatter import format_migrate_diff_result
from confiture.cli.helpers import (
    _get_tracking_table,
    console,
    is_json,
)
from confiture.cli.options import (
    config_option,
    format_option,
    migrations_dir_option,
    scratch_url_option,
)
from confiture.config.environment import MigrationConfig
from confiture.core import connection as _core_connection
from confiture.core.desired_state import DesiredStateSource, EnvSource, load_desired_state
from confiture.core.destructive import data_loss_reason, resolve_policy
from confiture.core.differ import (
    MATERIALISED,
    ComparisonPolicy,
    SchemaDiffer,
    Side,
    refuse_undeclared_relations,
)
from confiture.core.migration_generator import MigrationGenerator
from confiture.core.schema_read import SchemaRead, read_segments
from confiture.core.schema_sources import database_side, materialised_side
from confiture.error_codes import FAILURE
from confiture.exceptions import DifferError, ValidationError
from confiture.models.results import MigrateDiffChange, MigrateDiffResult

_TO_ENV_HELP = (
    "Desired state: the environment's build — the files `confiture build --env` selects, "
    "in build order (a fragment composed through include_dirs). Instead of --to"
)


@cli_boundary
def migrate_diff(
    *,
    old_schema: Path | None = typer.Argument(None, help="Old schema file"),
    new_schema: Path | None = typer.Argument(None, help="New schema file"),
    from_: str | None = typer.Option(
        None,
        "--from",
        help=(
            "Current state: a schema file, a directory (every .sql under it, recursively), "
            "'-' for stdin, or 'db' for the configured database (default: the first positional)"
        ),
    ),
    to: str | None = typer.Option(
        None,
        "--to",
        help=(
            "Desired state: a schema file, a directory (every .sql under it, recursively — "
            "what fraiseql's emit-ddl option writes), or '-' for stdin "
            "(default: the second positional)"
        ),
    ),
    to_env: str | None = typer.Option(None, "--to-env", help=_TO_ENV_HELP),
    config: Path = config_option(
        help="Environment config, read for `--from db` (default: db/environments/local.yaml)"
    ),
    scratch_url: str | None = scratch_url_option(),
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
    migrations_dir: Path = migrations_dir_option(),
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
            to_env=to_env,
            json_mode=is_json(format_type),
            report=report_file,
        )
        desired_read = read_segments(desired.segments())
        try:
            current_side, desired_side, policy, fidelity = _compared(
                current, desired, desired_read, config=config, scratch_url=scratch_url
            )
            diff = SchemaDiffer().compare_sides(current_side, desired_side, policy)
        except DifferError as exc:  # a name that needs quotes (DIFFER_403) carries its own code
            fail(exc, json_mode=is_json(format_type), output_file=report_file)

        changes = [
            MigrateDiffChange(
                change.to_wire().type,
                str(change),
                irreversible_reason=data_loss_reason(change),
            )
            for change in diff.changes
        ]
        migration_file_name = None
        gate: str | None = None

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
            gate = _destructive_policy(
                config,
                allow=allow_destructive,
                forbid=forbid_destructive,
                json_mode=is_json(format_type),
                report=report_file,
            )
            try:
                migration_file = (
                    generator.generate_sql(diff, name=name, destructive=gate)
                    if ingest
                    else generator.generate(diff, name=name, destructive=gate)
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
            destructive_gate=gate,
            warnings=diff.warnings,
            fidelity=fidelity,
        )

        format_migrate_diff_result(result, format_type, report_file, console)

    except typer.Exit, typer.BadParameter:
        raise
    # Reason: the diff result carries the failure so the formatter can render it in every format
    except Exception as e:
        result = MigrateDiffResult(
            success=False,
            has_changes=False,
            error=str(e),
        )
        format_migrate_diff_result(result, format_type, report_file, console)
        raise typer.Exit(FAILURE) from e


def _one_desired_side(
    to: str | None, to_env: str | None, *, json_mode: bool, report: Path | None
) -> None:
    """Refuse ``--to`` and ``--to-env`` together: both name the desired side (exit 5)."""
    if to is not None and to_env is not None:
        fail(
            ValidationError(
                "--to and --to-env name the same side; give one.",
                resolution_hint="Use --to for a file or directory, --to-env for an environment's build.",
            ),
            json_mode=json_mode,
            output_file=report,
        )


def _resolve_sides(
    old_schema: Path | None,
    new_schema: Path | None,
    *,
    from_: str | None,
    to: str | None,
    to_env: str | None,
    json_mode: bool,
    report: Path | None,
) -> tuple[str, DesiredStateSource]:
    """The two sides of the diff: ``(current spec, desired-state source)``.

    Either both positionals or both ``--from``/``--to``; mixing the two forms
    is refused (exit 5). The current side is a spec string (``db`` is special),
    the desired side a :class:`DesiredStateSource`.
    """
    _one_desired_side(to, to_env, json_mode=json_mode, report=report)
    positional = old_schema is not None or new_schema is not None
    named = from_ is not None or to is not None or to_env is not None
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
        if from_ is None or (to is None and to_env is None):
            fail(
                ValidationError(
                    "--from and --to (or --to-env) go together.",
                    resolution_hint="Usage: confiture migrate diff --from current.sql --to desired/",
                ),
                json_mode=json_mode,
                output_file=report,
            )
        return from_, EnvSource(to_env) if to_env is not None else load_desired_state(str(to))
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


def _compared(
    spec: str,
    desired: DesiredStateSource,
    desired_read: SchemaRead,
    *,
    config: Path,
    scratch_url: str | None,
) -> tuple[Side, Side, ComparisonPolicy | None, str | None]:
    """The two sides, the policy they are compared under, and its fidelity when it is not theirs.

    The current side is a file/dir/stdin, or ``db``: the configured database, read
    through ``live_catalog`` in the schemas the desired tree names and compared with
    that tree through the parity rules, so a database built from the tree is no
    change from it. With a scratch server (``--scratch-url``, else the
    environment's ``scratch_url``), the tree is built there and read back, and its
    expressions compare as PostgreSQL stores them (``materialised``).
    """
    if spec != "db":
        current = Side.of(read_segments(load_desired_state(spec).segments()))
        return current, Side.of(desired_read), None, None
    config_data = _core_connection.load_config(config)
    database = database_side(
        _core_connection.dsn_from_config(config_data),
        against=desired_read.model,
        tracking_table=_get_tracking_table(config_data),
    )
    scratch = _core_connection.scratch_url_from_config(config_data, scratch_url)
    if scratch is None:
        return database, Side.of(desired_read, held=True), None, None
    # Before the scratch build, which would fail on the index rather than name it.
    refuse_undeclared_relations(database, Side.of(desired_read, held=True))
    built = materialised_side(desired.read(), scratch, declared=desired_read.model)
    return database, built, replace(MATERIALISED, author="new"), "materialised"


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
