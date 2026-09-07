"""`confiture migrate generate`.

Split out of the monolithic migrate command modules.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Annotated

import typer

from confiture.cli.commands.migrate._settings import _load_environment_if_present
from confiture.cli.error_json import cli_boundary, fail
from confiture.cli.helpers import (
    console,
    error_console,
    is_json,
)
from confiture.cli.options import format_option
from confiture.core import schema_snapshot as _core_schema_snapshot
from confiture.core.migration_generator import MigrationGenerator
from confiture.core.migrator import (
    find_duplicate_migration_versions as _gen_find,
)
from confiture.core.migrator import (
    parse_migration_filename,
)
from confiture.exceptions import ExternalGeneratorError, ValidationError

# A migration name becomes a filename and a class name. snake_case only: a `/`
# or `..` would walk out of the migrations directory, anything else is not a
# Python identifier fragment.
_MIGRATION_NAME_RE = re.compile(r"^[a-z0-9_]+$")


MigrationsDirOpt = Annotated[
    Path, typer.Option("--migrations-dir", help="Migrations directory (default: db/migrations)")
]
ForceOpt = Annotated[
    bool, typer.Option("--force", help="Overwrite existing migration file (default: off)")
]
DryRunOpt = Annotated[
    bool,
    typer.Option("--dry-run", help="Show what would be generated without creating (default: off)"),
]
VerboseOpt = Annotated[
    bool, typer.Option("--verbose", "-v", help="Show version calculation details (default: off)")
]
FromSchemaOpt = Annotated[
    Path | None, typer.Option("--from", help="Old schema file path (required with --generator)")
]
ToSchemaOpt = Annotated[
    Path | None, typer.Option("--to", help="New schema file path (required with --generator)")
]
GeneratorOpt = Annotated[
    str | None,
    typer.Option("--generator", help="Named external generator from migration_generators config"),
]
ConfigOpt = Annotated[
    Path,
    typer.Option(
        "--config", "-c", help="Environment config file (default: db/environments/local.yaml)"
    ),
]
SnapshotOpt = Annotated[
    bool | None,
    typer.Option(
        "--snapshot/--no-snapshot",
        help="Write schema history snapshot (default: from config, True)",
    ),
]
SnapshotsDirOpt = Annotated[
    Path | None,
    typer.Option(
        "--snapshots-dir", help="Override snapshot output directory (default: db/schema_history)"
    ),
]
LiveSnapshotOpt = Annotated[
    bool | None,
    typer.Option(
        "--live-snapshot/--no-live-snapshot",
        help="Snapshot via temp database + pg_dump (captures DO-block objects)",
    ),
]


@cli_boundary
def migrate_generate(
    name: str = typer.Argument(..., help="Migration name (snake_case)"),
    migrations_dir: MigrationsDirOpt = Path("db/migrations"),
    format_output: str = format_option("text", "json"),
    force: ForceOpt = False,
    dry_run: DryRunOpt = False,
    verbose: VerboseOpt = False,
    from_schema: FromSchemaOpt = None,
    to_schema: ToSchemaOpt = None,
    generator: GeneratorOpt = None,
    config: ConfigOpt = Path("db/environments/local.yaml"),
    snapshot: SnapshotOpt = None,
    snapshots_dir: SnapshotsDirOpt = None,
    live_snapshot: LiveSnapshotOpt = None,
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
    if generator is not None:
        _run_external_generator(
            generator,
            name=name,
            from_schema=from_schema,
            to_schema=to_schema,
            migrations_dir=migrations_dir,
            config=config,
            dry_run=dry_run,
        )
        raise typer.Exit(0)

    migrations_dir.mkdir(parents=True, exist_ok=True)
    generator_instance = MigrationGenerator(migrations_dir=migrations_dir)
    warnings: list[str] = []
    if verbose:
        _show_scan(migrations_dir)

    duplicates = _gen_find(migrations_dir)
    if duplicates:
        warnings.append(f"Duplicate versions detected: {', '.join(sorted(duplicates.keys()))}")
        if format_output == "text":
            console.print(f"[yellow]⚠️  Warning: {warnings[-1]}[/yellow]")
    name_conflicts = generator_instance.check_name_conflict(name)
    if name_conflicts:
        warnings.append(f"Migration name '{name}' already exists in other versions")
        if format_output == "text":
            console.print(f"[yellow]⚠️  Warning: {warnings[-1]}[/yellow]")
            for f in name_conflicts:
                console.print(f"    - {f.name}")
    version = generator_instance.get_next_version()
    if verbose:
        console.print(f"\n  Highest version: {version[:-1] if int(version) > 1 else '000'}")
        console.print(f"  Next version: {version}")
        console.print(f"  Target file: {version}_{name}.py")
        console.print()
    class_name = generator_instance.to_class_name(name)
    filepath = migrations_dir / f"{version}_{name}.py"
    template = _MIGRATION_TEMPLATE.format(name=name, version=version, class_name=class_name)

    if dry_run:
        _render_dry_run_preview(
            version, name, class_name, filepath, template, warnings, format_output
        )
        return
    if filepath.exists() and not force:
        fail(
            ValidationError(
                f"Migration file already exists: {filepath.name}",
                context={"filepath": str(filepath.absolute())},
                resolution_hint="Use --force to overwrite the existing file.",
            ),
            json_mode=is_json(format_output),
        )
    if filepath.exists() and force and format_output == "text":
        console.print(f"[yellow]⚠️  Overwriting existing file: {filepath.name}[/yellow]")
    lock_fd = generator_instance.acquire_migration_lock()
    try:
        filepath.write_text(template)
    finally:
        generator_instance.release_migration_lock(lock_fd)

    snapshot_path, snapshot_mode = _write_history_snapshot(
        config,
        version=version,
        name=name,
        snapshot=snapshot,
        live_snapshot=live_snapshot,
        snapshots_dir=snapshots_dir,
        format_output=format_output,
    )
    _render_generated(
        version,
        name,
        class_name,
        filepath,
        migrations_dir=migrations_dir,
        snapshot_path=snapshot_path,
        snapshot_mode=snapshot_mode,
        warnings=warnings,
        format_output=format_output,
    )


_MIGRATION_TEMPLATE = '''"""Migration: {name}

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


def _run_external_generator(
    generator: str,
    *,
    name: str,
    from_schema: Path | None,
    to_schema: Path | None,
    migrations_dir: Path,
    config: Path,
    dry_run: bool,
) -> None:
    """``--generator <name>``: hand the diff to a configured external generator."""
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
        return
    console.print("[green]✅ Migration generated by external generator![/green]")
    console.print(f"\n📄 File: {up_sql_path.absolute()}")
    console.print("\n💡 Next steps:")
    console.print("  • Review and edit the generated SQL if needed")
    console.print("  • Apply: confiture migrate up")


def _show_scan(migrations_dir: Path) -> None:
    console.print("[cyan]🔍 Scanning migrations directory...[/cyan]")
    console.print(f"  Directory: {migrations_dir.absolute()}")
    migration_files = sorted(migrations_dir.glob("*.py"))
    console.print(f"  Found {len(migration_files)} migration files:")
    for f in migration_files:
        console.print(f"    - {f.name} (version: {parse_migration_filename(f.name)[0]})")


def _render_dry_run_preview(
    version: str,
    name: str,
    class_name: str,
    filepath: Path,
    template: str,
    warnings: list[str],
    format_output: str,
) -> None:
    if format_output == "json":
        print(
            json.dumps(
                {
                    "status": "dry_run",
                    "version": version,
                    "name": name,
                    "filepath": str(filepath.absolute()),
                    "class_name": class_name,
                    "template": template,
                    "warnings": warnings,
                },
                indent=2,
            )
        )
        return
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


def _write_history_snapshot(
    config: Path,
    *,
    version: str,
    name: str,
    snapshot: bool | None,
    live_snapshot: bool | None,
    snapshots_dir: Path | None,
    format_output: str,
) -> tuple[Path | None, str]:
    """Write the schema-history snapshot (non-fatal); returns ``(path, mode)``."""
    settings = _load_environment_if_present(config)
    should = (
        snapshot
        if snapshot is not None
        else (settings.migration.snapshot_history if settings else True)
    )
    if not should:
        return None, "static"
    use_live = (
        live_snapshot
        if live_snapshot is not None
        else (settings.migration.live_snapshot if settings else False)
    )
    live_db_url = settings.database_url if (use_live and settings is not None) else None
    try:
        resolved_dir = snapshots_dir
        if resolved_dir is None and settings is not None:
            resolved_dir = Path(settings.migration.snapshots_dir)
        if resolved_dir is None:
            resolved_dir = Path("db/schema_history")
        snap_gen = _core_schema_snapshot.SchemaSnapshotGenerator(snapshots_dir=resolved_dir)
        env_name, project_dir = config.stem, config.parent.parent.parent
        if live_db_url:
            try:
                return (
                    snap_gen.write_snapshot(
                        env_name, version, name, project_dir, database_url=live_db_url
                    ),
                    "live",
                )
            # Reason: a live snapshot failure of any kind falls back to the static snapshot (documented)
            except Exception as live_err:
                if format_output == "text":
                    console.print(
                        f"[yellow]⚠️  Live snapshot failed, falling back to static: {live_err}[/yellow]"
                    )
        return snap_gen.write_snapshot(env_name, version, name, project_dir), "static"
    # Reason: snapshot writing is documented non-fatal; any failure degrades to 'static'
    except Exception as snap_err:
        if format_output == "text":
            console.print(f"[yellow]⚠️  Snapshot write failed (non-fatal): {snap_err}[/yellow]")
        return None, "static"


def _render_generated(
    version: str,
    name: str,
    class_name: str,
    filepath: Path,
    *,
    migrations_dir: Path,
    snapshot_path: Path | None,
    snapshot_mode: str,
    warnings: list[str],
    format_output: str,
) -> None:
    if format_output == "json":
        print(
            json.dumps(
                {
                    "status": "success",
                    "version": version,
                    "name": name,
                    "filepath": str(filepath.absolute()),
                    "class_name": class_name,
                    "migrations_dir": str(migrations_dir.absolute()),
                    "next_available_version": version,
                    "snapshot": str(snapshot_path.absolute()) if snapshot_path else None,
                    "snapshot_mode": snapshot_mode if snapshot_path else None,
                    "warnings": warnings,
                },
                indent=2,
            )
        )
        return
    console.print("[green]✅ Migration generated successfully![/green]")
    print(f"\n📄 File: {filepath.absolute()}")
    if snapshot_path:
        console.print(f"📸 Snapshot: {snapshot_path.absolute()}")
    console.print("\n✏️  Edit the migration file to add your SQL statements.")
    console.print("\n💡 Next steps:")
    console.print("  • Edit file and add SQL")
    console.print("  • Apply: confiture migrate up")
    console.print("  • Or verify first: confiture migrate up --dry-run")
