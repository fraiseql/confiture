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
from confiture.cli.commands.debug import debug_app
from confiture.cli.commands.drift import drift
from confiture.cli.commands.mcp import mcp_app
from confiture.cli.commands.migrate_analysis import (
    migrate_diff,
    migrate_fix,
    migrate_introspect,
    migrate_validate,
    migrate_verify,
)
from confiture.cli.commands.migrate_core import (
    migrate_down,
    migrate_estimate,
    migrate_generate,
    migrate_status,
    migrate_up,
)
from confiture.cli.commands.migrate_state import (
    migrate_baseline,
    migrate_rebuild,
    migrate_reinit,
)
from confiture.cli.commands.schema import build, init, introspect, lint, lint_unified
from confiture.cli.coordinate import coordinate_app
from confiture.cli.generate import generate_app
from confiture.cli.helpers import console
from confiture.cli.seed import seed_app

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
    "drift",
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

# Add mcp subcommand group (MCP server)
app.add_typer(mcp_app, name="mcp")

# Add debug subcommand group (CTE debugger)
app.add_typer(debug_app, name="debug")


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
app.command("lint-unified")(lint_unified)
app.command()(introspect)

# Register drift command
app.command()(drift)

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
migrate_app.command("estimate")(migrate_estimate)

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
