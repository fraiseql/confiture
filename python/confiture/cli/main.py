"""Main CLI entry point for Confiture.

This module defines the main Typer application and registers all CLI commands.
"""

import typer

# Sub-applications
from confiture.cli.branch import branch_app
from confiture.cli.commands.admin import (
    install_helpers,
    restore,
    validate_profile,
    verify,
)
from confiture.cli.commands.migrate_analysis import (
    migrate_diff,
    migrate_fix,
    migrate_introspect,
    migrate_validate,
    migrate_verify,
)
from confiture.cli.commands.migrate_core import (
    migrate_down,
    migrate_generate,
    migrate_status,
    migrate_up,
)
from confiture.cli.commands.migrate_state import (
    migrate_baseline,
    migrate_rebuild,
    migrate_reinit,
)
from confiture.cli.commands.schema import build, init, introspect, lint
from confiture.cli.coordinate import coordinate_app
from confiture.cli.generate import generate_app

# Helpers — also re-exported here so existing mock patch paths continue to work
from confiture.cli.helpers import (
    _convert_linter_report,  # noqa: F401
    _find_orphaned_sql_files,  # noqa: F401
    _fix_idempotency,  # noqa: F401
    _get_suggestion,  # noqa: F401
    _get_tracking_table,  # noqa: F401
    _output_json,  # noqa: F401
    _output_yaml,  # noqa: F401
    _print_duplicate_versions_warning,  # noqa: F401
    _print_orphaned_files_warning,  # noqa: F401
    _validate_idempotency,  # noqa: F401
    console,
    error_console,  # noqa: F401
)
from confiture.cli.lint_formatter import save_report  # noqa: F401
from confiture.cli.seed import seed_app

# Re-exported for backward-compatible mock patch targets in tests
from confiture.core.connection import create_connection  # noqa: F401
from confiture.core.introspector import SchemaIntrospector  # noqa: F401
from confiture.core.linting import SchemaLinter  # noqa: F401

# Valid output formats for linting
LINT_FORMATS = ("table", "json", "csv")

# Common command names for "Did you mean?" suggestions
COMMON_COMMANDS = [
    "init",
    "build",
    "migrate",
    "lint",
    "introspect",
    "seed",
    "branch",
    "generate",
    "coordinate",
    "install-helpers",
    "restore",
    "migrate-up",
    "migrate-down",
    "migrate-status",
    "migrate-validate",
]

# Create Typer app
app = typer.Typer(
    name="confiture",
    help="PostgreSQL migrations, sweetly done 🍓",
    add_completion=False,
)

# Create migrate subcommand group
migrate_app = typer.Typer(help="Migration commands")
app.add_typer(migrate_app, name="migrate")

# Add branch subcommand group (pgGit integration)
app.add_typer(branch_app, name="branch")

# Add generate subcommand group (pgGit migration generation)
app.add_typer(generate_app, name="generate")

# Add coordinate subcommand group (multi-agent coordination)
app.add_typer(coordinate_app, name="coordinate")

# Add seed subcommand group (seed validation)
app.add_typer(seed_app, name="seed")


def version_callback(value: bool) -> None:
    """Print version and exit."""
    if value:
        from confiture import __version__

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


# Register schema commands
app.command()(init)
app.command()(build)
app.command()(lint)
app.command()(introspect)

# Register admin commands
app.command("install-helpers")(install_helpers)
app.command()(validate_profile)
app.command()(verify)
app.command()(restore)

# Register migrate core commands
migrate_app.command("status")(migrate_status)
migrate_app.command("up")(migrate_up)
migrate_app.command("down")(migrate_down)
migrate_app.command("generate")(migrate_generate)

# Register migrate state commands
migrate_app.command("baseline")(migrate_baseline)
migrate_app.command("reinit")(migrate_reinit)
migrate_app.command("rebuild")(migrate_rebuild)

# Register migrate analysis commands
migrate_app.command("diff")(migrate_diff)
migrate_app.command("validate")(migrate_validate)
migrate_app.command("fix")(migrate_fix)
migrate_app.command("introspect")(migrate_introspect)
migrate_app.command("verify")(migrate_verify)


if __name__ == "__main__":
    # Note: QW4 "Did you mean?" feature requires custom Click/Typer error handler
    # infrastructure is ready (_get_suggestion helper), but full integration
    # requires wrapping Click's exception handling at a lower level.
    # See: https://github.com/evoludigit/confiture/issues/qw4
    app()
