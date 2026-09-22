"""Commands other distributions add to ``confiture``: the ``confiture.plugins`` entry points.

An installed distribution declares
``[project.entry-points."confiture.plugins"] name = "module:register"``, and
``register`` receives the root Typer app before the command tree is built, to add
its groups or commands to it. pgGit's ``branch`` and ``coordinate`` arrive this way
from ``plugins/fraiseql-confiture-pggit/``, and so do the ``from-branch``,
``preview`` and ``diff`` it adds to ``confiture generate``.

A plugin adds names; it never replaces one. Typer keeps a group's commands in a
dict where the later registration wins and groups land after commands, so a plugin's
``migrate`` group would replace the built-in one and a plugin's ``seed`` command
would vanish under the ``seed`` group without a word. Every group of the tree is
therefore recorded before a plugin runs and checked after it: a command, group or
group callback the plugin put over a name the tree already had is taken back and
named on standard error, and the plugin's other names stay.

A plugin that fails to load, whatever it raises — ``SystemExit`` included, only
``KeyboardInterrupt`` passes — is named on standard error and everything it
registered before failing is taken back: a broken extension costs its own commands,
never the ones ``confiture`` ships.
"""

from __future__ import annotations

import sys
from collections.abc import Sequence
from dataclasses import dataclass
from importlib.metadata import EntryPoint, entry_points
from typing import TYPE_CHECKING, TypeVar

from typer.main import get_command_name, solve_typer_info_defaults
from typer.models import CommandInfo, TyperInfo

if TYPE_CHECKING:
    import typer

#: The entry-point group ``confiture`` reads.
GROUP = "confiture.plugins"

_Entry = TypeVar("_Entry", CommandInfo, TyperInfo)


@dataclass(frozen=True)
class _Group:
    """One group of the command tree as it stood before a plugin ran."""

    path: str
    app: typer.Typer
    commands: list[CommandInfo]
    groups: list[TyperInfo]
    callback: TyperInfo | None


def _name(entry: CommandInfo | TyperInfo) -> str | None:
    """The name Typer gives *entry* on the command line; ``None`` for an unnamed group."""
    if isinstance(entry, CommandInfo):
        function = getattr(entry.callback, "__name__", "")
        return entry.name or (get_command_name(function) if function else None)
    return solve_typer_info_defaults(entry).name or None


def _names(entries: Sequence[CommandInfo | TyperInfo]) -> set[str]:
    """The names *entries* occupy in their group; an unnamed group lends its own."""
    found: set[str] = set()
    for entry in entries:
        name = _name(entry)
        if name:
            found.add(name)
        elif isinstance(entry, TyperInfo) and entry.typer_instance is not None:
            inner = entry.typer_instance
            found |= _names(inner.registered_commands) | _names(inner.registered_groups)
    return found


def _groups(app: typer.Typer, path: str = "confiture") -> dict[int, _Group]:
    """Every group reachable from *app*, keyed by identity, with what each holds now."""
    found = {
        id(app): _Group(
            path,
            app,
            list(app.registered_commands),
            list(app.registered_groups),
            app.registered_callback,
        )
    }
    for info in app.registered_groups:
        if info.typer_instance is not None and id(info.typer_instance) not in found:
            name = _name(info)
            found |= _groups(info.typer_instance, f"{path} {name}" if name else path)
    return found


def _restore(before: dict[int, _Group]) -> None:
    for group in before.values():
        group.app.registered_commands[:] = group.commands
        group.app.registered_groups[:] = group.groups
        group.app.registered_callback = group.callback


def _added(
    now: list[_Entry], was: list[_Entry], taken: set[str], path: str
) -> tuple[list[_Entry], list[str]]:
    """The entries a plugin added to one group whose names are free, and the names refused."""
    kept: list[_Entry] = []
    refused: list[str] = []
    for entry in now:
        if any(entry is old for old in was):
            continue
        clash = sorted(_names([entry]) & taken)
        if clash:
            refused.extend(repr(f"{path} {name}") for name in clash)
        else:
            kept.append(entry)
    return kept, refused


def _keep_builtins(before: dict[int, _Group]) -> list[str]:
    """Take back everything a plugin put over what the tree had; what was taken back."""
    refused: list[str] = []
    for group in before.values():
        taken = _names(group.commands) | _names(group.groups)
        commands, lost = _added(group.app.registered_commands, group.commands, taken, group.path)
        groups, lost_groups = _added(group.app.registered_groups, group.groups, taken, group.path)
        group.app.registered_commands[:] = [*group.commands, *commands]
        group.app.registered_groups[:] = [*group.groups, *groups]
        refused += lost + lost_groups
        if group.app.registered_callback is not group.callback:
            group.app.registered_callback = group.callback
            refused.append(f"the options of {group.path!r}")
    return refused


def _label(point: EntryPoint) -> str:
    dist = getattr(point, "dist", None)
    source = f" of {dist.name}" if dist is not None else ""
    return f"plugin {point.name!r}{source} ({point.value})"


def load_plugins(app: typer.Typer) -> list[str]:
    """Hand *app* to every installed plugin; the names of those that loaded."""
    loaded: list[str] = []
    for point in entry_points(group=GROUP):
        before = _groups(app)
        try:
            point.load()(app)
        except KeyboardInterrupt:
            raise
        except BaseException as exc:  # Reason: a plugin is another distribution's code; whatever it raises, SystemExit included, costs its commands, never confiture's
            _restore(before)
            print(
                f"confiture: {_label(point)} failed to load: {type(exc).__name__}: {exc}",
                file=sys.stderr,
            )
            continue
        for refused in _keep_builtins(before):
            print(
                f"confiture: {_label(point)} cannot replace {refused}; confiture's own is kept",
                file=sys.stderr,
            )
        loaded.append(point.name)
    return loaded
