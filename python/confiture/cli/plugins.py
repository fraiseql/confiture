"""Commands other distributions add to ``confiture``: the ``confiture.plugins`` entry points.

An installed distribution declares
``[project.entry-points."confiture.plugins"] name = "module:register"``, and
``register`` receives the root Typer app before the command tree is built, to add
its groups or commands to it. pgGit's ``branch`` and ``coordinate`` arrive this way
from ``plugins/fraiseql-confiture-pggit/``.

A plugin that fails to load is named on standard error and skipped: a broken
extension costs its own commands, never the ones ``confiture`` ships.
"""

from __future__ import annotations

import sys
from importlib.metadata import entry_points
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import typer

#: The entry-point group ``confiture`` reads.
GROUP = "confiture.plugins"


def load_plugins(app: typer.Typer) -> list[str]:
    """Hand *app* to every installed plugin; the names of those that loaded."""
    loaded: list[str] = []
    for point in entry_points(group=GROUP):
        try:
            point.load()(app)
        except Exception as exc:  # Reason: a plugin is another distribution's code; whatever it raises costs its commands, never confiture's
            print(
                f"confiture: plugin {point.name!r} ({point.value}) failed to load: {exc}",
                file=sys.stderr,
            )
            continue
        loaded.append(point.name)
    return loaded
