"""Admin commands: install_helpers, validate_profile, verify, restore."""

from pathlib import Path

import typer

from confiture.cli.helpers import console
from confiture.core.connection import create_connection
from confiture.core.error_handler import handle_cli_error


def install_helpers(
    config: Path = typer.Option(
        None,
        "--config",
        "-c",
        help="Configuration file (YAML)",
    ),
    env: str = typer.Option(
        "local",
        "--env",
        "-e",
        help="Environment name (default: local)",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Show SQL without executing",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Reinstall even if already installed",
    ),
) -> None:
    """Install confiture SQL helper functions in the target database.

    Creates the `confiture` schema with `save_and_drop_dependent_views()`
    and `recreate_saved_views()` PL/pgSQL functions for use in migrations
    that need to ALTER COLUMN TYPE on tables with dependent views.
    """
    try:
        from confiture.core.connection import load_config
        from confiture.core.view_manager import ViewManager

        if config:
            cfg = load_config(config)
        else:
            from confiture.config.environment import Environment

            environment = Environment.load(env)
            cfg = {"database": {"url": environment.database_url}}

        conn = create_connection(cfg)

        if dry_run:
            from importlib import resources

            sql = resources.files("confiture.sql").joinpath("view_helpers.sql").read_text()
            console.print("[bold]SQL that would be executed:[/bold]\n")
            console.print(sql)
            conn.close()
            return

        vm = ViewManager(conn)

        if not force and vm.helpers_installed():
            console.print("[green]✓[/green] View helpers already installed — nothing to do")
            console.print("  Use [bold]--force[/bold] to reinstall")
            conn.close()
            return

        vm.install_helpers()
        conn.close()

        console.print("[green]✓[/green] Installed confiture view helper functions")
        console.print("  Schema: [bold]confiture[/bold]")
        console.print("  Functions:")
        console.print("    • confiture.save_and_drop_dependent_views(schemas TEXT[])")
        console.print("    • confiture.recreate_saved_views()")

    except Exception as e:
        raise typer.Exit(handle_cli_error(e)) from e


def validate_profile(
    path: Path = typer.Argument(
        ...,
        help="Path to anonymization profile YAML file",
    ),
) -> None:
    """Validate anonymization profile YAML structure and schema.

    Performs security validation:
    - Uses safe_load() to prevent YAML injection
    - Validates against Pydantic schema
    - Checks strategy types are whitelisted
    - Verifies all required fields present

    Example:
        confiture validate-profile db/profiles/production.yaml
    """
    try:
        from confiture.core.anonymization.profile import AnonymizationProfile

        console.print(f"[cyan]📋 Validating profile: {path}[/cyan]")
        profile = AnonymizationProfile.load(path)

        # Print profile summary
        console.print("[green]✅ Valid profile![/green]")
        console.print(f"   Name: {profile.name}")
        console.print(f"   Version: {profile.version}")
        if profile.global_seed:
            console.print(f"   Global Seed: {profile.global_seed}")

        # List strategies
        console.print(f"\n[cyan]Strategies ({len(profile.strategies)})[/cyan]:")
        for strategy_name, strategy_def in profile.strategies.items():
            console.print(
                f"   • {strategy_name}: {strategy_def.type}",
                end="",
            )
            if strategy_def.seed_env_var:
                console.print(f" [env: {strategy_def.seed_env_var}]")
            else:
                console.print()

        # List tables
        console.print(f"\n[cyan]Tables ({len(profile.tables)})[/cyan]:")
        for table_name, table_def in profile.tables.items():
            console.print(f"   • {table_name}: {len(table_def.rules)} rules")
            for rule in table_def.rules:
                console.print(f"      - {rule.column} → {rule.strategy}", end="")
                if rule.seed:
                    console.print(f" [seed: {rule.seed}]")
                else:
                    console.print()

        console.print("[green]\n✅ Profile validation passed![/green]")

    except FileNotFoundError as e:
        console.print(f"[red]❌ File not found: {e}[/red]")
        raise typer.Exit(1) from e
    except ValueError as e:
        console.print(f"[red]❌ Invalid profile: {e}[/red]")
        raise typer.Exit(1) from e
    except Exception as e:
        console.print(f"[red]❌ Error validating profile: {e}[/red]")
        raise typer.Exit(1) from e


def verify(
    migrations_dir: Path = typer.Option(
        Path("db/migrations"),
        "--migrations-dir",
        help="Migrations directory",
    ),
    config: Path = typer.Option(
        Path("db/environments/local.yaml"),
        "--config",
        "-c",
        help="Configuration file",
    ),
    fix: bool = typer.Option(
        False,
        "--fix",
        help="Update stored checksums to match current files (dangerous)",
    ),
) -> None:
    """Verify migration file integrity against stored checksums.

    Compares SHA-256 checksums of migration files against the checksums
    stored when migrations were applied. Detects if files have been
    modified after application.

    This helps prevent:
    - Silent schema drift between environments
    - Production/staging mismatches
    - Debugging nightmares from modified migrations

    Examples:
        # Verify all migrations
        confiture verify

        # Verify with specific config
        confiture verify --config db/environments/production.yaml

        # Fix checksums (update stored to match current files)
        confiture verify --fix
    """
    from confiture.core.checksum import (
        ChecksumConfig,
        ChecksumMismatchBehavior,
        MigrationChecksumVerifier,
    )
    from confiture.core.connection import create_connection, load_config

    try:
        # Load config and connect
        config_data = load_config(config)
        conn = create_connection(config_data)

        # Run verification (warn mode - we'll handle display)
        verifier = MigrationChecksumVerifier(
            conn,
            ChecksumConfig(
                enabled=True,
                on_mismatch=ChecksumMismatchBehavior.WARN,
            ),
        )
        mismatches = verifier.verify_all(migrations_dir)

        if not mismatches:
            console.print("[green]✅ All migration checksums verified![/green]")
            conn.close()
            return

        # Display mismatches
        console.print(f"[red]❌ Found {len(mismatches)} checksum mismatch(es):[/red]\n")

        for m in mismatches:
            console.print(f"  [yellow]{m.version}_{m.name}[/yellow]")
            console.print(f"    File: {m.file_path}")
            console.print(f"    Expected: {m.expected[:16]}...")
            console.print(f"    Actual:   {m.actual[:16]}...")
            console.print()

        if fix:
            # Update checksums in database
            console.print("[yellow]⚠️  Updating stored checksums...[/yellow]")
            updated = verifier.update_all_checksums(migrations_dir)
            console.print(f"[green]✅ Updated {updated} checksum(s)[/green]")
        else:
            console.print(
                "[yellow]💡 Tip: Use --fix to update stored checksums (dangerous)[/yellow]"
            )
            conn.close()
            raise typer.Exit(1)

        conn.close()

    except typer.Exit:
        raise
    except Exception as e:
        console.print(f"[red]❌ Error: {e}[/red]")
        raise typer.Exit(1) from e


def restore(
    backup_file: Path = typer.Argument(
        ...,
        help="Path to pg_dump backup file. Must be custom (-Fc) or directory (-Fd) format.",
    ),
    database: str = typer.Option(
        ...,
        "--database",
        "-d",
        help="Target database name",
    ),
    host: str = typer.Option(
        "/var/run/postgresql",
        "--host",
        help="PostgreSQL host or socket path",
    ),
    port: int = typer.Option(
        5432,
        "--port",
        help="PostgreSQL port",
    ),
    username: str | None = typer.Option(
        None,
        "--username",
        "-U",
        help="PostgreSQL user",
    ),
    jobs: int = typer.Option(
        4,
        "--jobs",
        "-j",
        help="Parallel workers for the data phase",
    ),
    no_owner: bool = typer.Option(
        False,
        "--no-owner/--owner",
        help="Skip ownership restoration",
    ),
    no_acl: bool = typer.Option(
        False,
        "--no-acl/--acl",
        help="Skip access privilege restoration",
    ),
    exit_on_error: bool = typer.Option(
        True,
        "--exit-on-error/--no-exit-on-error",
        help="Abort on first error (recommended for production restores)",
    ),
    min_tables: int = typer.Option(
        0,
        "--min-tables",
        help="Post-restore: minimum expected table count (0 = skip check)",
    ),
    min_tables_schema: str = typer.Option(
        "public",
        "--min-tables-schema",
        help="Schema for --min-tables validation",
    ),
    superuser: str | None = typer.Option(
        None,
        "--superuser",
        help="Run pg_restore via sudo as this OS user",
    ),
) -> None:
    """Restore a PostgreSQL backup using three-phase pg_restore.

    Prevents FK constraint race conditions during parallel restore by running
    pre-data and post-data phases serially, parallelising only the data phase
    (where no FK constraints exist yet).

    Requires custom format (-Fc) or directory format (-Fd) dumps. To create one:

      pg_dump -Fc mydb > backup.pgdump

    Example usage:

      confiture restore prod.pgdump --database staging --jobs 4

      confiture restore prod.pgdump --database staging --jobs 8 --min-tables 300

      confiture restore /backups/dump --database staging --superuser postgres
    """
    from confiture.core.restorer import DatabaseRestorer, RestoreOptions
    from confiture.exceptions import RestoreError

    if not backup_file.exists():
        console.print(f"[red]Error:[/red] Backup file not found: {backup_file}")
        raise typer.Exit(1)

    options = RestoreOptions(
        backup_path=backup_file,
        target_db=database,
        host=host,
        port=port,
        username=username,
        jobs=jobs,
        no_owner=no_owner,
        no_acl=no_acl,
        exit_on_error=exit_on_error,
        superuser=superuser,
        min_tables=min_tables,
        min_tables_schema=min_tables_schema,
    )

    console.print(
        f"[bold]Restoring[/bold] [cyan]{backup_file.name}[/cyan] → [cyan]{database}[/cyan]"
    )

    def on_stderr_line(line: str) -> None:
        if "pg_restore: error:" in line:
            console.print(f"  [red]{line}[/red]")
        elif "pg_restore: warning:" in line:
            console.print(f"  [yellow]{line}[/yellow]")

    try:
        result = DatabaseRestorer().restore(options, on_stderr_line=on_stderr_line)
    except RestoreError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1) from e

    if result.warnings:
        console.print(f"[yellow]⚠ {len(result.warnings)} warning(s) during restore[/yellow]")

    if result.success:
        console.print(f"[green]✓ Restore complete[/green] ({len(result.phases_completed)} phases)")
        if result.table_count is not None:
            console.print(f"  Tables verified: {result.table_count} (≥ {min_tables} required)")
    else:
        for err in result.errors:
            console.print(f"[red]{err}[/red]")
        raise typer.Exit(1)
