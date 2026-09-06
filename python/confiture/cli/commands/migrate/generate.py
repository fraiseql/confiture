"""`confiture migrate generate`.

Split out of the monolithic migrate command modules (Phase 04, Cycle 8).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import typer

from confiture.cli.commands.migrate._settings import _load_environment_if_present
from confiture.cli.error_json import cli_boundary, fail
from confiture.cli.helpers import (
    console,
    error_console,
    is_json,
)
from confiture.cli.options import format_option
from confiture.core._migrator.discovery import parse_migration_filename
from confiture.core.migration_generator import MigrationGenerator
from confiture.exceptions import ValidationError

# A migration name becomes a filename and a class name. snake_case only: a `/`
# or `..` would walk out of the migrations directory, anything else is not a
# Python identifier fragment.
_MIGRATION_NAME_RE = re.compile(r"^[a-z0-9_]+$")


@cli_boundary
def migrate_generate(
    name: str = typer.Argument(..., help="Migration name (snake_case)"),
    migrations_dir: Path = typer.Option(
        Path("db/migrations"),
        "--migrations-dir",
        help="Migrations directory (default: db/migrations)",
    ),
    format_output: str = format_option("text", "json"),
    force: bool = typer.Option(
        False,
        "--force",
        help="Overwrite existing migration file (default: off)",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Show what would be generated without creating (default: off)",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Show version calculation details (default: off)",
    ),
    from_schema: Path | None = typer.Option(
        None,
        "--from",
        help="Old schema file path (required with --generator)",
    ),
    to_schema: Path | None = typer.Option(
        None,
        "--to",
        help="New schema file path (required with --generator)",
    ),
    generator: str | None = typer.Option(
        None,
        "--generator",
        help="Named external generator from migration_generators config",
    ),
    config: Path = typer.Option(
        Path("db/environments/local.yaml"),
        "--config",
        "-c",
        help="Environment config file (default: db/environments/local.yaml)",
    ),
    snapshot: bool | None = typer.Option(
        None,
        "--snapshot/--no-snapshot",
        help="Write schema history snapshot (default: from config, True)",
    ),
    snapshots_dir: Path | None = typer.Option(
        None,
        "--snapshots-dir",
        help="Override snapshot output directory (default: db/schema_history)",
    ),
    live_snapshot: bool | None = typer.Option(
        None,
        "--live-snapshot/--no-live-snapshot",
        help="Snapshot via temp database + pg_dump (captures DO-block objects)",
    ),
) -> None:
    """Generate a new migration file with timestamp-based version.

    PROCESS:
      Creates an empty migration template with a timestamp-based version number.
      Uses the current system time (YYYYMMDDHHmmSS format) to ensure uniqueness
      and avoid merge conflicts in multi-developer environments.

    EXAMPLES:
      confiture migrate generate add_user_email
        ↳ Create migration template with timestamp version (20260228120530_add_user_email.py)

      confiture migrate generate add_payment_column --verbose
        ↳ Show version calculation and scanning details

      confiture migrate generate stripe_integration --dry-run
        ↳ Preview what would be created without writing files

      confiture migrate generate hotfix --force
        ↳ Overwrite existing migration file if it exists

    RELATED:
      confiture migrate up      - Apply the generated migration
      confiture migrate status  - View all migrations
      confiture migrate diff    - Compare schema files
    """
    if not _MIGRATION_NAME_RE.match(name):
        fail(
            ValidationError(
                f"Invalid migration name {name!r}: use snake_case — lowercase letters, "
                "digits and underscores only (e.g. add_user_bio).",
                context={"name": name},
                resolution_hint="Rename the migration, e.g. `confiture migrate generate add_user_bio`.",
            ),
            json_mode=format_output == "json",
        )

    # External generator path
    if generator is not None:
        if from_schema is None or to_schema is None:
            error_console.print(
                "[red]❌ Error: --from and --to are required when --generator is used[/red]"
            )
            raise typer.Exit(2)

        env_config = _load_environment_if_present(config)

        if env_config is None or generator not in env_config.migration.migration_generators:
            error_console.print(
                f"[red]❌ Error: Generator '{generator}' not found in migration_generators config[/red]"
            )
            raise typer.Exit(2)

        gen_config = env_config.migration.migration_generators[generator]
        migrations_dir.mkdir(parents=True, exist_ok=True)
        gen_instance = MigrationGenerator(migrations_dir=migrations_dir)

        try:
            from confiture.exceptions import ExternalGeneratorError

            resolved_cmd, up_sql_path = gen_instance.run_external_generator(
                generator_config=gen_config,
                from_path=from_schema,
                to_path=to_schema,
                migration_name=name,
                dry_run=dry_run,
            )
        except FileNotFoundError as exc:
            error_console.print(f"[red]❌ Error: {exc}[/red]")
            raise typer.Exit(2) from exc
        except ExternalGeneratorError as exc:
            error_console.print(f"[red]❌ Generator error: {exc}[/red]")
            raise typer.Exit(3) from exc

        if dry_run:
            console.print(f"[dim]Resolved command:[/] {resolved_cmd}")
            console.print(f"[dim]Target file:      [/] {up_sql_path}")
            raise typer.Exit(0)

        console.print("[green]✅ Migration generated by external generator![/green]")
        console.print(f"\n📄 File: {up_sql_path.absolute()}")
        console.print("\n💡 Next steps:")
        console.print("  • Review and edit the generated SQL if needed")
        console.print("  • Apply: confiture migrate up")
        raise typer.Exit(0)

    try:
        # Ensure migrations directory exists
        migrations_dir.mkdir(parents=True, exist_ok=True)

        # Generate migration file template
        generator_instance = MigrationGenerator(migrations_dir=migrations_dir)

        # Collect warnings
        warnings = []

        # Verbose mode: show scanning info
        if verbose:
            console.print("[cyan]🔍 Scanning migrations directory...[/cyan]")
            console.print(f"  Directory: {migrations_dir.absolute()}")

            migration_files = sorted(migrations_dir.glob("*.py"))
            console.print(f"  Found {len(migration_files)} migration files:")

            for f in migration_files:
                version_str = parse_migration_filename(f.name)[0]
                console.print(f"    - {f.name} (version: {version_str})")

        # Check for duplicate versions (covers both .py and .up.sql files)
        from confiture.core.migrator import find_duplicate_migration_versions as _gen_find

        duplicates = _gen_find(migrations_dir)
        if duplicates:
            warning_msg = f"Duplicate versions detected: {', '.join(sorted(duplicates.keys()))}"
            warnings.append(warning_msg)
            if format_output == "text":
                console.print(f"[yellow]⚠️  Warning: {warning_msg}[/yellow]")

        # Check for name conflicts
        name_conflicts = generator_instance._check_name_conflict(name)
        if name_conflicts:
            warning_msg = f"Migration name '{name}' already exists in other versions"
            warnings.append(warning_msg)
            if format_output == "text":
                console.print(f"[yellow]⚠️  Warning: {warning_msg}[/yellow]")
                for f in name_conflicts:
                    console.print(f"    - {f.name}")

        # Calculate next version
        version = generator_instance._get_next_version()

        if verbose:
            console.print(f"\n  Highest version: {version[:-1] if int(version) > 1 else '000'}")
            console.print(f"  Next version: {version}")
            console.print(f"  Target file: {version}_{name}.py")
            console.print()

        # Generate class name and file path
        class_name = generator_instance._to_class_name(name)
        filename = f"{version}_{name}.py"
        filepath = migrations_dir / filename

        # Create template
        template = f'''"""Migration: {name}

Version: {version}
"""

from confiture.models.migration import Migration


class {class_name}(Migration):
    """Migration: {name}."""

    version = "{version}"
    name = "{name}"

    def up(self) -> None:
        """Apply migration."""
        # Add your forward migration SQL here
        # Example:
        # self.execute("CREATE TABLE users (id SERIAL PRIMARY KEY)")
        pass

    def down(self) -> None:
        """Rollback migration."""
        # Add your rollback SQL here
        # Example:
        # self.execute("DROP TABLE users")
        pass
'''

        # Dry-run mode: show preview and exit
        if dry_run:
            if format_output == "json":
                output = {
                    "status": "dry_run",
                    "version": version,
                    "name": name,
                    "filepath": str(filepath.absolute()),
                    "class_name": class_name,
                    "template": template,
                    "warnings": warnings,
                }
                print(json.dumps(output, indent=2))
            else:
                console.print("[cyan]🔍 Dry-run mode - no files will be created[/cyan]\n")
                console.print("Would create migration:")
                console.print(f"  Version: {version}")
                console.print(f"  Name: {name}")
                console.print(f"  Class: {class_name}")
                console.print(f"  File: {filepath.absolute()}")
                console.print("\n[dim]Template preview:[/dim]")
                console.print("[dim]" + "─" * 60 + "[/dim]")
                console.print(template)
                console.print("[dim]" + "─" * 60 + "[/dim]")
            return

        # Check if file exists
        if filepath.exists() and not force:
            fail(
                ValidationError(
                    f"Migration file already exists: {filepath.name}",
                    context={"filepath": str(filepath.absolute())},
                    resolution_hint="Use --force to overwrite the existing file.",
                ),
                json_mode=is_json(format_output),
            )

        # Warn if overwriting
        if filepath.exists() and force and format_output == "text":
            console.print(f"[yellow]⚠️  Overwriting existing file: {filepath.name}[/yellow]")

        # Write file (with lock protection)
        lock_fd = generator_instance._acquire_migration_lock()
        try:
            filepath.write_text(template)
        finally:
            generator_instance._release_migration_lock(lock_fd)

        # Write schema history snapshot (non-fatal if it fails)
        _snapshot_path: Path | None = None
        _snapshot_env_config = _load_environment_if_present(config)

        _should_snapshot = snapshot
        if _should_snapshot is None:
            _should_snapshot = (
                _snapshot_env_config.migration.snapshot_history
                if _snapshot_env_config is not None
                else True
            )

        _snapshot_mode = "static"
        if _should_snapshot:
            # Resolve live-snapshot mode from CLI flag or config
            _use_live = live_snapshot
            if _use_live is None:
                _use_live = (
                    _snapshot_env_config.migration.live_snapshot
                    if _snapshot_env_config is not None
                    else False
                )

            _live_db_url: str | None = None
            if _use_live and _snapshot_env_config is not None:
                _live_db_url = _snapshot_env_config.database_url

            try:
                from confiture.core.schema_snapshot import SchemaSnapshotGenerator

                _resolved_snapshots_dir = snapshots_dir
                if _resolved_snapshots_dir is None and _snapshot_env_config is not None:
                    _resolved_snapshots_dir = Path(_snapshot_env_config.migration.snapshots_dir)
                if _resolved_snapshots_dir is None:
                    _resolved_snapshots_dir = Path("db/schema_history")

                _snap_gen = SchemaSnapshotGenerator(snapshots_dir=_resolved_snapshots_dir)
                _snap_env_name = config.stem
                _snap_project_dir = config.parent.parent.parent

                if _live_db_url:
                    try:
                        _snapshot_path = _snap_gen.write_snapshot(
                            _snap_env_name,
                            version,
                            name,
                            _snap_project_dir,
                            database_url=_live_db_url,
                        )
                        _snapshot_mode = "live"
                    except Exception as _live_err:
                        if format_output == "text":
                            console.print(
                                f"[yellow]⚠️  Live snapshot failed, falling back to static: {_live_err}[/yellow]"
                            )
                        _snapshot_path = _snap_gen.write_snapshot(
                            _snap_env_name, version, name, _snap_project_dir
                        )
                        _snapshot_mode = "static"
                else:
                    _snapshot_path = _snap_gen.write_snapshot(
                        _snap_env_name, version, name, _snap_project_dir
                    )
            except Exception as _snap_err:
                if format_output == "text":
                    console.print(
                        f"[yellow]⚠️  Snapshot write failed (non-fatal): {_snap_err}[/yellow]"
                    )

        # Output success message
        if format_output == "json":
            output = {
                "status": "success",
                "version": version,
                "name": name,
                "filepath": str(filepath.absolute()),
                "class_name": class_name,
                "migrations_dir": str(migrations_dir.absolute()),
                "next_available_version": version,
                "snapshot": str(_snapshot_path.absolute()) if _snapshot_path else None,
                "snapshot_mode": _snapshot_mode if _snapshot_path else None,
                "warnings": warnings,
            }
            print(json.dumps(output, indent=2))
        else:
            console.print("[green]✅ Migration generated successfully![/green]")
            print(f"\n📄 File: {filepath.absolute()}")
            if _snapshot_path:
                console.print(f"📸 Snapshot: {_snapshot_path.absolute()}")
            console.print("\n✏️  Edit the migration file to add your SQL statements.")
            console.print("\n💡 Next steps:")
            console.print("  • Edit file and add SQL")
            console.print("  • Apply: confiture migrate up")
            console.print("  • Or verify first: confiture migrate up --dry-run")

    except typer.Exit:
        raise
    except Exception as e:
        fail(e, json_mode=is_json(format_output))
