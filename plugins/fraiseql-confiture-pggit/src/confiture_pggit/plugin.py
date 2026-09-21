"""The ``confiture.plugins`` entry point: pgGit's commands, added to ``confiture``.

``confiture branch`` and ``confiture coordinate`` are this distribution's groups, and
``from-branch``, ``preview`` and ``diff`` join ``confiture generate`` beside the
commands ``confiture`` ships there — every spelling a user typed before the
extraction still works once this is installed.
"""

from __future__ import annotations

import typer

from confiture.cli.generate import generate_app
from confiture_pggit.cli import generate
from confiture_pggit.cli.branch import branch_app
from confiture_pggit.cli.coordinate import coordinate_app


def register(app: typer.Typer) -> None:
    """Add pgGit's commands to *app*, ``confiture``'s root."""
    app.add_typer(branch_app, name="branch")
    app.add_typer(coordinate_app, name="coordinate")
    generate_app.command("from-branch")(generate.generate_from_branch)
    generate_app.command("preview")(generate.preview_generation)
    generate_app.command("diff")(generate.show_diff)
