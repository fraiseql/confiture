"""Every registered command runs inside ``cli_boundary``.

The boundary re-raises ``typer.Exit`` and routes everything else through
``fail()``. Discovery walks Typer's own registry, so a new command cannot skip
it by omission.
"""

from __future__ import annotations

import pytest
import typer

from confiture.cli.main import app


def _registered_callbacks(t: typer.Typer, path: tuple[str, ...] = ()) -> list[tuple[str, object]]:
    found: list[tuple[str, object]] = []
    for info in t.registered_commands:
        name = info.name or info.callback.__name__.replace("_", "-")  # type: ignore[union-attr]
        found.append((" ".join((*path, name)), info.callback))
    for group in t.registered_groups:
        found.extend(_registered_callbacks(group.typer_instance, (*path, group.name or "")))
    return sorted(found, key=lambda item: item[0])


COMMANDS = _registered_callbacks(app)


def test_registry_is_populated() -> None:
    assert len(COMMANDS) >= 70, [c for c, _ in COMMANDS]


@pytest.mark.parametrize(("name", "callback"), COMMANDS, ids=[c for c, _ in COMMANDS])
def test_command_runs_inside_the_boundary(name: str, callback: object) -> None:
    assert getattr(callback, "__confiture_boundary__", False), (
        f"{name} is not wrapped by cli_boundary"
    )
