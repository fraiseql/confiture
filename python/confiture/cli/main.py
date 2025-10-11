"""Main CLI entry point for Confiture.

This module defines the main Typer application and all CLI commands.
"""

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from confiture.core.differ import SchemaDiffer
from confiture.core.migration_generator import MigrationGenerator

# Create Typer app
app = typer.Typer(
    name="confiture",
    help="PostgreSQL migrations, sweetly done 🍓",
    add_completion=False,
)

# Create Rich console for pretty output
console = Console()

# Version
__version__ = "0.1.0"


def version_callback(value: bool) -> None:
    """Print version and exit."""
    if value:
        console.print(f"confiture version {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        False,
        "--version",
        callback=version_callback,
        is_eager=True,
        help="Show version and exit",
    ),
) -> None:
    """Confiture - PostgreSQL migrations, sweetly done 🍓."""
    pass


@app.command()
def init(
    path: Path = typer.Argument(
        Path("."),
        help="Project directory to initialize",
    ),
) -> None:
    """Initialize a new Confiture project.

    Creates necessary directory structure and configuration files.
    """
    try:
        # Create directory structure
        db_dir = path / "db"
        schema_dir = db_dir / "schema"
        migrations_dir = db_dir / "migrations"
        environments_dir = db_dir / "environments"

        # Check if already initialized
        if db_dir.exists():
            console.print(
                "[yellow]⚠️  Project already exists. Some files may be overwritten.[/yellow]"
            )
            if not typer.confirm("Continue?"):
                raise typer.Exit()

        # Create directories
        schema_dir.mkdir(parents=True, exist_ok=True)
        migrations_dir.mkdir(parents=True, exist_ok=True)
        environments_dir.mkdir(parents=True, exist_ok=True)

        # Create example schema directory structure
        (schema_dir / "00_common").mkdir(exist_ok=True)
        (schema_dir / "10_tables").mkdir(exist_ok=True)

        # Create example schema file
        example_schema = schema_dir / "00_common" / "extensions.sql"
        example_schema.write_text(
            """-- PostgreSQL extensions
-- Add commonly used extensions here

-- Example:
-- CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
-- CREATE EXTENSION IF NOT EXISTS "pg_trgm";
"""
        )

        # Create example table
        example_table = schema_dir / "10_tables" / "example.sql"
        example_table.write_text(
            """-- Example table
-- Replace with your actual schema

CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    email TEXT NOT NULL UNIQUE,
    created_at TIMESTAMP DEFAULT NOW()
);
"""
        )

        # Create local environment config
        local_config = environments_dir / "local.yaml"
        local_config.write_text(
            """# Local development environment configuration

name: local
include_dirs:
  - db/schema/00_common
  - db/schema/10_tables
exclude_dirs: []

database:
  host: localhost
  port: 5432
  database: myapp_local
  user: postgres
  password: postgres
"""
        )

        # Create README
        readme = db_dir / "README.md"
        readme.write_text(
            """# Database Schema

This directory contains your database schema and migrations.

## Directory Structure

- `schema/` - DDL files organized by category
  - `00_common/` - Extensions, types, functions
  - `10_tables/` - Table definitions
- `migrations/` - Python migration files
- `environments/` - Environment-specific configurations

## Quick Start

1. Edit schema files in `schema/`
2. Generate migrations: `confiture migrate diff old.sql new.sql --generate`
3. Apply migrations: `confiture migrate up`

## Learn More

Documentation: https://github.com/evoludigit/confiture
"""
        )

        console.print("[green]✅ Confiture project initialized successfully![/green]")
        console.print(f"\n📁 Created structure in: {path.absolute()}")
        console.print("\n📝 Next steps:")
        console.print("  1. Edit your schema files in db/schema/")
        console.print("  2. Configure environments in db/environments/")
        console.print("  3. Run 'confiture migrate diff' to detect changes")

    except Exception as e:
        console.print(f"[red]❌ Error initializing project: {e}[/red]")
        raise typer.Exit(1) from e


# Create migrate subcommand group
migrate_app = typer.Typer(help="Migration commands")
app.add_typer(migrate_app, name="migrate")


@migrate_app.command("status")
def migrate_status(
    migrations_dir: Path = typer.Option(
        Path("db/migrations"),
        "--migrations-dir",
        help="Migrations directory",
    ),
    config: Path = typer.Option(
        None,
        "--config",
        "-c",
        help="Configuration file (optional, to show applied status)",
    ),
) -> None:
    """Show migration status.

    If config is provided, shows which migrations are applied vs pending.
    """
    try:
        if not migrations_dir.exists():
            console.print("[yellow]No migrations directory found.[/yellow]")
            console.print(f"Expected: {migrations_dir.absolute()}")
            return

        # Find migration files
        migration_files = sorted(migrations_dir.glob("*.py"))

        if not migration_files:
            console.print("[yellow]No migrations found.[/yellow]")
            return

        # Get applied migrations from database if config provided
        applied_versions = set()
        if config and config.exists():
            try:
                from confiture.core.connection import create_connection, load_config
                from confiture.core.migrator import Migrator

                config_data = load_config(config)
                conn = create_connection(config_data)
                migrator = Migrator(connection=conn)
                migrator.initialize()
                applied_versions = set(migrator.get_applied_versions())
                conn.close()
            except Exception as e:
                console.print(f"[yellow]⚠️  Could not connect to database: {e}[/yellow]")
                console.print("[yellow]Showing file list only (status unknown)[/yellow]\n")

        # Display migrations in a table
        table = Table(title="Migrations")
        table.add_column("Version", style="cyan")
        table.add_column("Name", style="green")
        table.add_column("Status", style="yellow")

        pending_count = 0
        applied_count = 0

        for migration_file in migration_files:
            # Extract version and name from filename (e.g., "001_add_users.py")
            parts = migration_file.stem.split("_", 1)
            version = parts[0] if len(parts) > 0 else "???"
            name = parts[1] if len(parts) > 1 else migration_file.stem

            # Determine status
            if applied_versions:
                if version in applied_versions:
                    status = "[green]✅ applied[/green]"
                    applied_count += 1
                else:
                    status = "[yellow]⏳ pending[/yellow]"
                    pending_count += 1
            else:
                status = "unknown"

            table.add_row(version, name, status)

        console.print(table)
        console.print(f"\n📊 Total: {len(migration_files)} migrations", end="")
        if applied_versions:
            console.print(f" ({applied_count} applied, {pending_count} pending)")
        else:
            console.print()

    except Exception as e:
        console.print(f"[red]❌ Error: {e}[/red]")
        raise typer.Exit(1) from e


@migrate_app.command("generate")
def migrate_generate(
    name: str = typer.Argument(..., help="Migration name (snake_case)"),
    migrations_dir: Path = typer.Option(
        Path("db/migrations"),
        "--migrations-dir",
        help="Migrations directory",
    ),
) -> None:
    """Generate a new migration file.

    Creates an empty migration template with the given name.
    """
    try:
        # Ensure migrations directory exists
        migrations_dir.mkdir(parents=True, exist_ok=True)

        # Generate migration file template
        generator = MigrationGenerator(migrations_dir=migrations_dir)

        # For empty migration, create a template manually
        version = generator._get_next_version()
        class_name = generator._to_class_name(name)
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
        # TODO: Add your SQL statements here
        # Example:
        # self.execute("CREATE TABLE users (id SERIAL PRIMARY KEY)")
        pass

    def down(self) -> None:
        """Rollback migration."""
        # TODO: Add your rollback SQL statements here
        # Example:
        # self.execute("DROP TABLE users")
        pass
'''

        filepath.write_text(template)

        console.print("[green]✅ Migration generated successfully![/green]")
        console.print(f"\n📄 File: {filepath.absolute()}")
        console.print("\n✏️  Edit the migration file to add your SQL statements.")

    except Exception as e:
        console.print(f"[red]❌ Error generating migration: {e}[/red]")
        raise typer.Exit(1) from e


@migrate_app.command("diff")
def migrate_diff(
    old_schema: Path = typer.Argument(..., help="Old schema file"),
    new_schema: Path = typer.Argument(..., help="New schema file"),
    generate: bool = typer.Option(
        False,
        "--generate",
        help="Generate migration from diff",
    ),
    name: str = typer.Option(
        None,
        "--name",
        help="Migration name (required with --generate)",
    ),
    migrations_dir: Path = typer.Option(
        Path("db/migrations"),
        "--migrations-dir",
        help="Migrations directory",
    ),
) -> None:
    """Compare two schema files and show differences.

    Optionally generate a migration file from the diff.
    """
    try:
        # Validate files exist
        if not old_schema.exists():
            console.print(f"[red]❌ Old schema file not found: {old_schema}[/red]")
            raise typer.Exit(1)

        if not new_schema.exists():
            console.print(f"[red]❌ New schema file not found: {new_schema}[/red]")
            raise typer.Exit(1)

        # Read schemas
        old_sql = old_schema.read_text()
        new_sql = new_schema.read_text()

        # Compare schemas
        differ = SchemaDiffer()
        diff = differ.compare(old_sql, new_sql)

        # Display diff
        if not diff.has_changes():
            console.print("[green]✅ No changes detected. Schemas are identical.[/green]")
            return

        console.print("[cyan]📊 Schema differences detected:[/cyan]\n")

        # Display changes in a table
        table = Table()
        table.add_column("Type", style="yellow")
        table.add_column("Details", style="white")

        for change in diff.changes:
            table.add_row(change.type, str(change))

        console.print(table)
        console.print(f"\n📈 Total changes: {len(diff.changes)}")

        # Generate migration if requested
        if generate:
            if not name:
                console.print(
                    "[red]❌ Migration name is required when using --generate[/red]"
                )
                console.print("Usage: confiture migrate diff old.sql new.sql --generate --name migration_name")
                raise typer.Exit(1)

            # Ensure migrations directory exists
            migrations_dir.mkdir(parents=True, exist_ok=True)

            # Generate migration
            generator = MigrationGenerator(migrations_dir=migrations_dir)
            migration_file = generator.generate(diff, name=name)

            console.print(f"\n[green]✅ Migration generated: {migration_file.name}[/green]")

    except Exception as e:
        console.print(f"[red]❌ Error: {e}[/red]")
        raise typer.Exit(1) from e


@migrate_app.command("up")
def migrate_up(
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
    target: str = typer.Option(
        None,
        "--target",
        "-t",
        help="Target migration version (applies all if not specified)",
    ),
) -> None:
    """Apply pending migrations.

    Applies all pending migrations up to the target version (or all if no target).
    """
    from confiture.core.connection import (
        create_connection,
        get_migration_class,
        load_config,
        load_migration_module,
    )
    from confiture.core.migrator import Migrator

    try:
        # Load configuration
        config_data = load_config(config)

        # Create database connection
        conn = create_connection(config_data)

        # Create migrator
        migrator = Migrator(connection=conn)
        migrator.initialize()

        # Find pending migrations
        pending_migrations = migrator.find_pending(migrations_dir=migrations_dir)

        if not pending_migrations:
            console.print("[green]✅ No pending migrations. Database is up to date.[/green]")
            conn.close()
            return

        console.print(f"[cyan]📦 Found {len(pending_migrations)} pending migration(s)[/cyan]\n")

        # Apply migrations
        applied_count = 0
        for migration_file in pending_migrations:
            # Load migration module
            module = load_migration_module(migration_file)
            migration_class = get_migration_class(module)

            # Create migration instance
            migration = migration_class(connection=conn)

            # Check target
            if target and migration.version > target:
                console.print(f"[yellow]⏭️  Skipping {migration.version} (after target)[/yellow]")
                break

            # Apply migration
            console.print(f"[cyan]⚡ Applying {migration.version}_{migration.name}...[/cyan]", end=" ")
            migrator.apply(migration)
            console.print("[green]✅[/green]")
            applied_count += 1

        console.print(f"\n[green]✅ Successfully applied {applied_count} migration(s)![/green]")
        conn.close()

    except Exception as e:
        console.print(f"[red]❌ Error: {e}[/red]")
        raise typer.Exit(1) from e


@migrate_app.command("down")
def migrate_down(
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
    steps: int = typer.Option(
        1,
        "--steps",
        "-n",
        help="Number of migrations to rollback",
    ),
) -> None:
    """Rollback applied migrations.

    Rolls back the last N applied migrations (default: 1).
    """
    from confiture.core.connection import (
        create_connection,
        get_migration_class,
        load_config,
        load_migration_module,
    )
    from confiture.core.migrator import Migrator

    try:
        # Load configuration
        config_data = load_config(config)

        # Create database connection
        conn = create_connection(config_data)

        # Create migrator
        migrator = Migrator(connection=conn)
        migrator.initialize()

        # Get applied migrations
        applied_versions = migrator.get_applied_versions()

        if not applied_versions:
            console.print("[yellow]⚠️  No applied migrations to rollback.[/yellow]")
            conn.close()
            return

        # Get migrations to rollback (last N)
        versions_to_rollback = applied_versions[-steps:]

        console.print(f"[cyan]📦 Rolling back {len(versions_to_rollback)} migration(s)[/cyan]\n")

        # Rollback migrations in reverse order
        rolled_back_count = 0
        for version in reversed(versions_to_rollback):
            # Find migration file
            migration_files = migrator.find_migration_files(migrations_dir=migrations_dir)
            migration_file = None
            for mf in migration_files:
                if migrator._version_from_filename(mf.name) == version:
                    migration_file = mf
                    break

            if not migration_file:
                console.print(f"[red]❌ Migration file for version {version} not found[/red]")
                continue

            # Load migration module
            module = load_migration_module(migration_file)
            migration_class = get_migration_class(module)

            # Create migration instance
            migration = migration_class(connection=conn)

            # Rollback migration
            console.print(f"[cyan]⚡ Rolling back {migration.version}_{migration.name}...[/cyan]", end=" ")
            migrator.rollback(migration)
            console.print("[green]✅[/green]")
            rolled_back_count += 1

        console.print(f"\n[green]✅ Successfully rolled back {rolled_back_count} migration(s)![/green]")
        conn.close()

    except Exception as e:
        console.print(f"[red]❌ Error: {e}[/red]")
        raise typer.Exit(1) from e


if __name__ == "__main__":
    app()
