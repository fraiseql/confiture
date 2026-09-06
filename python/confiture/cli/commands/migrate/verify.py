"""`confiture migrate verify`.

Split out of the monolithic migrate command modules (Phase 04, Cycle 8).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import typer

from confiture.cli.error_json import cli_boundary, fail
from confiture.cli.helpers import (
    DATABASE_URL_OPTION_HELP,
    NO_CONFIG_OPTION_HELP,
    _output_json,
    console,
    is_json,
)
from confiture.cli.options import format_option
from confiture.exceptions import ConfigurationError, ConfiturError


@cli_boundary
def migrate_verify(
    ctx: typer.Context,
    migrations_dir: Path = typer.Option(
        Path("db/migrations"),
        "--migrations-dir",
        help="Migrations directory (default: db/migrations)",
    ),
    config: Path | None = typer.Option(
        None,
        "--config",
        "-c",
        help="Configuration file path",
    ),
    database_url: str | None = typer.Option(
        None,
        "--database-url",
        "-d",
        help=DATABASE_URL_OPTION_HELP,
    ),
    no_config: bool = typer.Option(
        False,
        "--no-config",
        help=NO_CONFIG_OPTION_HELP,
    ),
    version: str | None = typer.Option(
        None,
        "--version",
        help="Verify a single migration version (default: verify all applied)",
    ),
    format_output: str = format_option("text", "json"),
    output_file: Path | None = typer.Option(
        None,
        "--output",
        "-o",
        help="Save output to file (default: stdout)",
    ),
    allow_uninitialized: bool = typer.Option(
        False,
        "--allow-uninitialized",
        help=(
            "Treat a database with no migration ledger as success (exit 0) instead "
            "of exit 2.  For gates that legitimately run against schema-built "
            "databases."
        ),
    ),
) -> None:
    """Verify applied migrations using .verify.sql sidecar files (runtime correctness).

    Each .verify.sql file contains a SELECT query that returns a truthy value
    when the migration was applied correctly. Queries run inside SAVEPOINT
    (read-only, no side effects).

    This checks *runtime correctness* — did the migrations produce the expected
    schema/data state? For *file-checksum integrity* (have applied migration
    files been modified since?) use `confiture verify-checksums` instead.

    EXAMPLES:
      confiture migrate verify -c db/environments/local.yaml
        -> Verify all applied migrations that have .verify.sql files

      confiture migrate verify --version 003 -c db/environments/local.yaml
        -> Verify a single migration

      confiture migrate verify --format json -c db/environments/local.yaml
        -> Output as JSON for CI/CD pipelines

    RELATED:
      confiture migrate status  - View migration history
      confiture migrate up      - Apply pending migrations
    """
    from confiture.cli.commands.admin import _NO_LEDGER_HINT
    from confiture.cli.formatters.migrate_formatter import format_verify_results
    from confiture.cli.helpers import (
        _get_tracking_table,
        config_is_explicit,
        has_intentional_dsn_source,
        resolve_database_url,
    )
    from confiture.core.connection import create_connection, load_config
    from confiture.core.migration_verifier import MigrationVerifier
    from confiture.core.migrator import Migrator
    from confiture.exceptions import DatabaseNotInitializedError
    from confiture.models.results import VerifyAllResult

    json_mode = is_json(format_output)
    try:
        # Connection source (#152): a --database-url flag, --no-config, an
        # explicit --config, or the canonical CONFITURE_DATABASE_URL. An ambient
        # DATABASE_URL alone does NOT satisfy "config required"; two explicit
        # sources fail loud (CONFIG_007).
        config_data: Any = None
        if has_intentional_dsn_source(ctx, database_url, no_config):
            _db_url_override = resolve_database_url(
                database_url,
                config,
                config_explicit=config_is_explicit(ctx),
                no_config=no_config,
            )
            if _db_url_override is not None:
                config_data = {"database_url": _db_url_override}
            elif config and config.exists():
                config_data = load_config(config)
        if config_data is None:
            raise ConfigurationError("Config file or --database-url required for migrate verify")
        tracking_table = _get_tracking_table(config_data)

        conn = create_connection(config_data)
        try:
            migrator = Migrator(connection=conn, migration_table=tracking_table)

            # #182: get_applied_versions() raises psycopg's UndefinedTable on an
            # absent ledger. Absent is a distinct state from "present but empty",
            # so probe rather than swallowing the error into an empty result.
            if not migrator.tracking_table_exists():
                if not allow_uninitialized:
                    raise DatabaseNotInitializedError(
                        f"No migration ledger found: `{tracking_table}` is not present "
                        "in this database",
                        resolution_hint=_NO_LEDGER_HINT,
                    )
                empty = VerifyAllResult(
                    results=[],
                    verified_count=0,
                    failed_count=0,
                    skipped_count=0,
                    total_applied=0,
                    ledger_present=False,
                )
                if format_output == "json":
                    _output_json(empty.to_dict(), output_file, console)
                else:
                    console.print(
                        f"[yellow]ℹ️  No migration ledger found (`{tracking_table}` is not "
                        "present in this database) — 0 migrations recorded, nothing to "
                        "verify.[/yellow]"
                    )
                return

            applied_versions = migrator.get_applied_versions()

            verifier = MigrationVerifier(connection=conn, migrations_dir=migrations_dir)
            results = verifier.verify_all(applied_versions, target_version=version)

            verify_result = VerifyAllResult(
                results=results,
                verified_count=sum(1 for r in results if r.status == "verified"),
                failed_count=sum(1 for r in results if r.status == "failed"),
                skipped_count=sum(1 for r in results if r.status == "no_file"),
                total_applied=len(applied_versions),
            )

            if format_output == "json":
                _output_json(verify_result.to_dict(), output_file, console)
            else:
                format_verify_results(verify_result, console)

            if verify_result.failed_count > 0:
                raise typer.Exit(1)

        finally:
            conn.close()

    except typer.Exit:
        raise
    except ConfiturError as e:
        fail(e, json_mode=json_mode, output_file=output_file)
    except Exception as e:
        fail(e, json_mode=json_mode, output_file=output_file)
