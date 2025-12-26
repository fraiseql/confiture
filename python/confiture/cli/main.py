"""Main CLI entry point for Confiture.

This module defines the main Typer application and all CLI commands.
"""

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from confiture.cli.lint_formatter import format_lint_report, save_report
from confiture.core.builder import SchemaBuilder
from confiture.core.differ import SchemaDiffer
from confiture.core.linting import SchemaLinter
from confiture.core.migration_generator import MigrationGenerator
from confiture.models.lint import LintConfig

# Valid output formats for linting
LINT_FORMATS = ("table", "json", "csv")

# Create Typer app
app = typer.Typer(
    name="confiture",
    help="PostgreSQL migrations, sweetly done 🍓",
    add_completion=False,
)

# Create Rich console for pretty output
console = Console()

# Version
__version__ = "0.3.0"


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
        seeds_dir = db_dir / "seeds"
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
        (seeds_dir / "common").mkdir(parents=True, exist_ok=True)
        (seeds_dir / "development").mkdir(parents=True, exist_ok=True)
        (seeds_dir / "test").mkdir(parents=True, exist_ok=True)
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

        # Create example seed file
        example_seed = seeds_dir / "common" / "00_example.sql"
        example_seed.write_text(
            """-- Common seed data
-- These records are included in all non-production environments

-- Example: Test users
-- INSERT INTO users (username, email) VALUES
--     ('admin', 'admin@example.com'),
--     ('editor', 'editor@example.com'),
--     ('reader', 'reader@example.com');
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


@app.command()
def build(
    env: str = typer.Option(
        "local",
        "--env",
        "-e",
        help="Environment to build (references db/environments/{env}.yaml)",
    ),
    output: Path = typer.Option(
        None,
        "--output",
        "-o",
        help="Output file path (default: db/generated/schema_{env}.sql)",
    ),
    project_dir: Path = typer.Option(
        Path("."),
        "--project-dir",
        help="Project directory (default: current directory)",
    ),
    show_hash: bool = typer.Option(
        False,
        "--show-hash",
        help="Display schema hash after build",
    ),
    schema_only: bool = typer.Option(
        False,
        "--schema-only",
        help="Build schema only, exclude seed data",
    ),
) -> None:
    """Build complete schema from DDL files.

    This command builds a complete schema by concatenating all SQL files
    from the db/schema/ directory in deterministic order. This is the
    fastest way to create or recreate a database from scratch.

    The build process:
    1. Reads environment configuration (db/environments/{env}.yaml)
    2. Discovers all .sql files in configured include_dirs
    3. Concatenates files in alphabetical order
    4. Adds metadata headers (environment, file count, timestamp)
    5. Writes to output file (default: db/generated/schema_{env}.sql)

    Examples:
        # Build local environment schema
        confiture build

        # Build for specific environment
        confiture build --env production

        # Custom output location
        confiture build --output /tmp/schema.sql

        # Show hash for change detection
        confiture build --show-hash
    """
    try:
        # Create schema builder
        builder = SchemaBuilder(env=env, project_dir=project_dir)

        # Override to exclude seeds if --schema-only is specified
        if schema_only:
            builder.include_dirs = [d for d in builder.include_dirs if "seed" not in str(d).lower()]
            # Recalculate base_dir after filtering
            if builder.include_dirs:
                builder.base_dir = builder._find_common_parent(builder.include_dirs)

        # Set default output path if not specified
        if output is None:
            output_dir = project_dir / "db" / "generated"
            output_dir.mkdir(parents=True, exist_ok=True)
            output = output_dir / f"schema_{env}.sql"

        # Build schema
        console.print(f"[cyan]🔨 Building schema for environment: {env}[/cyan]")

        sql_files = builder.find_sql_files()
        console.print(f"[cyan]📄 Found {len(sql_files)} SQL files[/cyan]")

        schema = builder.build(output_path=output)

        # Success message
        console.print("[green]✅ Schema built successfully![/green]")
        console.print(f"\n📁 Output: {output.absolute()}")
        console.print(f"📏 Size: {len(schema):,} bytes")
        console.print(f"📊 Files: {len(sql_files)}")

        # Show hash if requested
        if show_hash:
            schema_hash = builder.compute_hash()
            console.print(f"🔐 Hash: {schema_hash}")

        console.print("\n💡 Next steps:")
        console.print(f"  • Apply schema: psql -f {output}")
        console.print("  • Or use: confiture migrate up")

    except FileNotFoundError as e:
        console.print(f"[red]❌ File not found: {e}[/red]")
        console.print("\n💡 Tip: Run 'confiture init' to create project structure")
        raise typer.Exit(1) from e
    except Exception as e:
        console.print(f"[red]❌ Error building schema: {e}[/red]")
        raise typer.Exit(1) from e


@app.command()
def lint(
    env: str = typer.Option(
        "local",
        "--env",
        "-e",
        help="Environment to lint (references db/environments/{env}.yaml)",
    ),
    project_dir: Path = typer.Option(
        Path("."),
        "--project-dir",
        help="Project directory (default: current directory)",
    ),
    format_type: str = typer.Option(
        "table",
        "--format",
        "-f",
        help="Output format (table, json, csv)",
    ),
    output: Path = typer.Option(
        None,
        "--output",
        "-o",
        help="Output file path (only with json/csv format)",
    ),
    fail_on_error: bool = typer.Option(
        True,
        "--fail-on-error",
        help="Exit with code 1 if errors found",
    ),
    fail_on_warning: bool = typer.Option(
        False,
        "--fail-on-warning",
        help="Exit with code 1 if warnings found (stricter)",
    ),
) -> None:
    """Lint schema against best practices.

    Validates the schema against 6 built-in linting rules:
    - Naming conventions (snake_case)
    - Primary keys on all tables
    - Documentation (COMMENT on tables)
    - Multi-tenant identifier columns
    - Indexes on foreign keys
    - Security best practices (passwords, tokens, secrets)

    Examples:
        # Lint local environment, display as table
        confiture lint

        # Lint production environment, output as JSON
        confiture lint --env production --format json

        # Save results to file
        confiture lint --format json --output lint-report.json

        # Strict mode: fail on warnings
        confiture lint --fail-on-warning
    """
    try:
        # Validate format option
        if format_type not in LINT_FORMATS:
            console.print(f"[red]❌ Invalid format: {format_type}[/red]")
            console.print(f"Valid formats: {', '.join(LINT_FORMATS)}")
            raise typer.Exit(1)

        # Create linter configuration
        config = LintConfig(
            enabled=True,
            fail_on_error=fail_on_error,
            fail_on_warning=fail_on_warning,
        )

        # Create linter and run linting
        console.print(f"[cyan]🔍 Linting schema for environment: {env}[/cyan]")
        linter = SchemaLinter(env=env, config=config)
        report = linter.lint()

        # Display results based on format
        if format_type == "table":
            format_lint_report(report, format_type="table", console=console)
        else:
            # JSON/CSV format: format and optionally save
            formatted = format_lint_report(
                report,
                format_type=format_type,
                console=console,
            )

            if output:
                save_report(report, output, format_type=format_type)
                console.print(f"[green]✅ Report saved to: {output.absolute()}[/green]")
            else:
                console.print(formatted)

        # Determine exit code based on violations and fail mode
        should_fail = (
            (report.has_errors and fail_on_error) or
            (report.has_warnings and fail_on_warning)
        )
        if should_fail:
            raise typer.Exit(1)

    except FileNotFoundError as e:
        console.print(f"[red]❌ File not found: {e}[/red]")
        console.print("\n💡 Tip: Make sure schema files exist in db/schema/")
        raise typer.Exit(1) from e
    except Exception as e:
        console.print(f"[red]❌ Error linting schema: {e}[/red]")
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
    strict: bool = typer.Option(
        False,
        "--strict",
        help="Enable strict mode (fail on warnings)",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Force migration application, skipping state checks",
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

        # Try to load environment config for migration settings
        effective_strict_mode = strict
        if (
            not strict
            and config.parent.name == "environments"
            and config.parent.parent.name == "db"
        ):
            # Check if config is in standard environments directory
            try:
                from confiture.config.environment import Environment

                env_name = config.stem  # e.g., "local" from "local.yaml"
                project_dir = config.parent.parent.parent
                env_config = Environment.load(env_name, project_dir=project_dir)
                effective_strict_mode = env_config.migration.strict_mode
            except Exception:
                # If environment config loading fails, use default (False)
                pass

        # Show warnings for force mode before attempting database operations
        if force:
            console.print(
                "[yellow]⚠️  Force mode enabled - skipping migration state checks[/yellow]"
            )
            console.print(
                "[yellow]This may cause issues if applied incorrectly. Use with caution![/yellow]\n"
            )

        # Create database connection
        conn = create_connection(config_data)

        # Create migrator
        migrator = Migrator(connection=conn)
        migrator.initialize()

        # Find migrations to apply
        if force:
            # In force mode, apply all migrations regardless of state
            migrations_to_apply = migrator.find_migration_files(migrations_dir=migrations_dir)
            if not migrations_to_apply:
                console.print("[yellow]⚠️  No migration files found.[/yellow]")
                conn.close()
                return
            console.print(
                f"[cyan]📦 Force mode: Found {len(migrations_to_apply)} migration(s) to apply[/cyan]\n"
            )
        else:
            # Normal mode: only apply pending migrations
            migrations_to_apply = migrator.find_pending(migrations_dir=migrations_dir)
            if not migrations_to_apply:
                console.print("[green]✅ No pending migrations. Database is up to date.[/green]")
                conn.close()
                return
            console.print(
                f"[cyan]📦 Found {len(migrations_to_apply)} pending migration(s)[/cyan]\n"
            )

        # Apply migrations
        applied_count = 0
        failed_migration = None
        failed_exception = None

        for migration_file in migrations_to_apply:
            # Load migration module
            module = load_migration_module(migration_file)
            migration_class = get_migration_class(module)

            # Create migration instance
            migration = migration_class(connection=conn)
            # Override strict_mode from CLI/config if not already set on class
            if effective_strict_mode and not getattr(migration_class, "strict_mode", False):
                migration.strict_mode = effective_strict_mode

            # Check target
            if target and migration.version > target:
                console.print(f"[yellow]⏭️  Skipping {migration.version} (after target)[/yellow]")
                break

            # Apply migration
            console.print(
                f"[cyan]⚡ Applying {migration.version}_{migration.name}...[/cyan]", end=" "
            )

            try:
                migrator.apply(migration, force=force)
                console.print("[green]✅[/green]")
                applied_count += 1
            except Exception as e:
                console.print("[red]❌[/red]")
                failed_migration = migration
                failed_exception = e
                break

        # Handle results
        if failed_migration:
            console.print("\n[red]❌ Migration failed![/red]")
            if applied_count > 0:
                console.print(
                    f"[yellow]⚠️  {applied_count} migration(s) were applied successfully before the failure.[/yellow]"
                )

            # Show detailed error information
            _show_migration_error_details(failed_migration, failed_exception, applied_count)
            conn.close()
            raise typer.Exit(1)
        else:
            if force:
                console.print(
                    f"\n[green]✅ Force mode: Successfully applied {applied_count} migration(s)![/green]"
                )
                console.print(
                    "[yellow]⚠️  Remember to verify your database state after force application[/yellow]"
                )
            else:
                console.print(
                    f"\n[green]✅ Successfully applied {applied_count} migration(s)![/green]"
                )
            conn.close()

    except Exception as e:
        console.print(f"[red]❌ Error: {e}[/red]")
        raise typer.Exit(1) from e


def _show_migration_error_details(failed_migration, exception, applied_count: int) -> None:
    """Show detailed error information for a failed migration with actionable guidance.

    Args:
        failed_migration: The Migration instance that failed
        exception: The exception that was raised
        applied_count: Number of migrations that succeeded before this one
    """
    from confiture.exceptions import MigrationError

    console.print("\n[red]Failed Migration Details:[/red]")
    console.print(f"  Version: {failed_migration.version}")
    console.print(f"  Name: {failed_migration.name}")
    console.print(f"  File: db/migrations/{failed_migration.version}_{failed_migration.name}.py")

    # Analyze error type and provide specific guidance
    error_message = str(exception)

    # Check if this is a SQL error wrapped in a MigrationError
    if "SQL execution failed" in error_message:
        console.print("  Error Type: SQL Execution Error")

        # Extract SQL and error details from the message
        # Message format: "...SQL execution failed | SQL: ... | Error: ..."
        parts = error_message.split(" | ")
        sql_part = next((part for part in parts if part.startswith("SQL: ")), None)
        error_part = next((part for part in parts if part.startswith("Error: ")), None)

        if sql_part:
            sql_content = sql_part[5:].strip()  # Remove "SQL: " prefix
            console.print(
                f"  SQL Statement: {sql_content[:100]}{'...' if len(sql_content) > 100 else ''}"
            )

        if error_part:
            db_error = error_part[7:].strip()  # Remove "Error: " prefix
            console.print(f"  Database Error: {db_error.split(chr(10))[0]}")

            # Specific SQL error guidance
            error_msg = db_error.lower()
            if "syntax error" in error_msg:
                console.print("\n[yellow]🔍 SQL Syntax Error Detected:[/yellow]")
                console.print("  • Check for typos in SQL keywords, table names, or column names")
                console.print(
                    "  • Verify quotes, parentheses, and semicolons are properly balanced"
                )
                if sql_part:
                    sql_content = sql_part[5:].strip()
                    console.print(f'  • Test the SQL manually: psql -c "{sql_content}"')
            elif "does not exist" in error_msg:
                if "schema" in error_msg:
                    console.print("\n[yellow]🔍 Missing Schema Error:[/yellow]")
                    console.print(
                        "  • Create the schema first: CREATE SCHEMA IF NOT EXISTS schema_name;"
                    )
                    console.print("  • Or use the public schema by default")
                elif "table" in error_msg or "relation" in error_msg:
                    console.print("\n[yellow]🔍 Missing Table Error:[/yellow]")
                    console.print("  • Ensure dependent migrations ran first")
                    console.print("  • Check table name spelling and schema qualification")
                elif "function" in error_msg:
                    console.print("\n[yellow]🔍 Missing Function Error:[/yellow]")
                    console.print("  • Define the function before using it")
                    console.print("  • Check function name and parameter types")
            elif "already exists" in error_msg:
                console.print("\n[yellow]🔍 Object Already Exists:[/yellow]")
                console.print("  • Use IF NOT EXISTS clauses for safe creation")
                console.print("  • Check if migration was partially applied")
            elif "permission denied" in error_msg:
                console.print("\n[yellow]🔍 Permission Error:[/yellow]")
                console.print("  • Verify database user has required privileges")
                console.print("  • Check GRANT statements in earlier migrations")

    elif isinstance(exception, MigrationError):
        console.print("  Error Type: Migration Framework Error")
        console.print(f"  Message: {exception}")

        # Migration-specific guidance
        error_msg = str(exception).lower()
        if "already been applied" in error_msg:
            console.print("\n[yellow]🔍 Migration Already Applied:[/yellow]")
            console.print("  • Check migration status: confiture migrate status")
            console.print("  • This migration may have run successfully before")
        elif "connection" in error_msg:
            console.print("\n[yellow]🔍 Database Connection Error:[/yellow]")
            console.print("  • Verify database is running and accessible")
            console.print("  • Check connection string in config file")
            console.print("  • Test connection: psql 'your-connection-string'")

    else:
        console.print(f"  Error Type: {type(exception).__name__}")
        console.print(f"  Message: {exception}")

    # General troubleshooting
    console.print("\n[yellow]🛠️  General Troubleshooting:[/yellow]")
    console.print(
        f"  • View migration file: cat db/migrations/{failed_migration.version}_{failed_migration.name}.py"
    )
    console.print("  • Check database logs for more details")
    console.print("  • Test SQL manually in psql")

    if applied_count > 0:
        console.print(f"  • {applied_count} migration(s) succeeded - database is partially updated")
        console.print("  • Fix the error and re-run: confiture migrate up")
        console.print(f"  • Or rollback and retry: confiture migrate down --steps {applied_count}")
    else:
        console.print("  • No migrations applied yet - database state is clean")
        console.print("  • Fix the error and re-run: confiture migrate up")


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
        # Use plain print to avoid Rich wrapping long paths
        print(f"\n📄 File: {filepath.absolute()}")
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
                console.print("[red]❌ Migration name is required when using --generate[/red]")
                console.print(
                    "Usage: confiture migrate diff old.sql new.sql --generate --name migration_name"
                )
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
            console.print(
                f"[cyan]⚡ Rolling back {migration.version}_{migration.name}...[/cyan]", end=" "
            )
            migrator.rollback(migration)
            console.print("[green]✅[/green]")
            rolled_back_count += 1

        console.print(
            f"\n[green]✅ Successfully rolled back {rolled_back_count} migration(s)![/green]"
        )
        conn.close()

    except Exception as e:
        console.print(f"[red]❌ Error: {e}[/red]")
        raise typer.Exit(1) from e


if __name__ == "__main__":
    app()
