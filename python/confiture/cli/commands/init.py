"""``confiture init``: scaffold a new project's ``db/`` tree."""

from __future__ import annotations

from pathlib import Path

import typer

from confiture.cli.error_json import cli_boundary
from confiture.cli.helpers import (
    console,
)
from confiture.cli.markup import verbatim
from confiture.core.error_handler import handle_cli_error, print_error_to_console
from confiture.core.scaffold.project import scaffold


@cli_boundary
def init(
    path: Path = typer.Argument(
        Path(),
        help="Project directory to initialize",
    ),
) -> None:
    """Initialize a new Confiture project.

    Creates necessary directory structure and configuration files.
    """
    db_dir = path / "db"
    try:
        if db_dir.exists():
            console.print(
                "[yellow]⚠️  Project already exists. Some files may be overwritten.[/yellow]"
            )
            if not typer.confirm("Continue?"):
                raise typer.Exit()
        scaffold(db_dir)
    except typer.Exit:
        raise
    except OSError as e:
        print_error_to_console(e)
        raise typer.Exit(handle_cli_error(e)) from e

    console.print("[green]✅ Confiture project initialized successfully![/green]")
    console.print(f"\n📁 Created structure in: {verbatim(path.absolute())}")
    console.print("\n📝 Next steps:")
    console.print("  1. Edit your schema files in db/schema/")
    console.print("  2. Configure environments in db/environments/")
    console.print("  3. Run 'confiture migrate diff' to detect changes")
