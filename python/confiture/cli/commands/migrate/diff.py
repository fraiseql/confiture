"""`confiture migrate diff`.

Split out of the monolithic migrate command modules.
"""

from __future__ import annotations

from pathlib import Path

import typer

from confiture.cli.error_json import cli_boundary, fail
from confiture.cli.helpers import (
    console,
    is_json,
)
from confiture.cli.options import format_option
from confiture.core.differ import SchemaDiffer
from confiture.core.migration_generator import MigrationGenerator
from confiture.exceptions import ValidationError


@cli_boundary
def migrate_diff(
    old_schema: Path = typer.Argument(..., help="Old schema file"),
    new_schema: Path = typer.Argument(..., help="New schema file"),
    generate: bool = typer.Option(
        False,
        "--generate",
        help="Generate migration from diff (default: off)",
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
        # Validate format

        # Validate files exist
        for label, schema_path in (("Old", old_schema), ("New", new_schema)):
            if not schema_path.exists():
                fail(
                    ValidationError(
                        f"{label} schema file not found: {schema_path}",
                        context={"path": str(schema_path)},
                        resolution_hint="Pass two existing schema files: migrate diff OLD.sql NEW.sql",
                    ),
                    json_mode=is_json(format_type),
                    output_file=report_file,
                )

        # Read schemas
        old_sql = old_schema.read_text()
        new_sql = new_schema.read_text()

        # Compare schemas
        differ = SchemaDiffer()
        diff = differ.compare(old_sql, new_sql)

        # Convert changes to SchemaChange objects
        from confiture.cli.formatters.migrate_formatter import format_migrate_diff_result
        from confiture.models.results import MigrateDiffChange, MigrateDiffResult

        changes = [MigrateDiffChange(change.type, str(change)) for change in diff.changes]
        migration_file_name = None

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
            migration_file = generator.generate(diff, name=name)
            migration_file_name = migration_file.name

        # Create result and format output
        result = MigrateDiffResult(
            success=True,
            has_changes=diff.has_changes(),
            changes=changes,
            migration_generated=generate and migration_file_name is not None,
            migration_file=migration_file_name,
        )

        format_migrate_diff_result(result, format_type, report_file, console)

    except typer.Exit:
        raise
    # Reason: the diff result carries the failure so the formatter can render it in every format
    except Exception as e:
        from confiture.cli.formatters.migrate_formatter import format_migrate_diff_result
        from confiture.models.results import MigrateDiffResult

        result = MigrateDiffResult(
            success=False,
            has_changes=False,
            error=str(e),
        )
        format_migrate_diff_result(result, format_type, report_file, console)
        raise typer.Exit(1) from e
