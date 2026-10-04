"""Every annotation something reads at run time resolves.

Python 3.14 evaluates annotations lazily (PEP 649): an annotation is a value
again, computed the first time something reads it. A name imported only under
``TYPE_CHECKING`` is then a ``NameError`` waiting for the first reader — typer
building a command's parameters, pydantic building a model, dataclasses listing
fields. These are the readers confiture hands its annotations to, so each is
asked here, for everything it reads (FastAPI's endpoints are built by
``test_mcp_http.py``).
"""

import dataclasses
import importlib
import pkgutil
from collections.abc import Iterator
from typing import Any

import pydantic
import pytest
from typer.main import get_command
from typer.testing import CliRunner

import confiture
from confiture.cli.main import app


def _leaves(command: Any, path: tuple[str, ...] = ()) -> Iterator[tuple[str, ...]]:
    subcommands = getattr(command, "commands", None)
    if not subcommands:
        yield path
        return
    for name, sub in sorted(subcommands.items()):
        yield from _leaves(sub, (*path, name))


def _modules() -> list[Any]:
    names = [
        info.name
        for info in pkgutil.walk_packages(confiture.__path__, prefix="confiture.")
        if not info.name.startswith("confiture.testing.pytest")
    ]
    return [importlib.import_module(name) for name in sorted(names)]


def _defined_here(module: Any) -> Iterator[type]:
    for value in vars(module).values():
        if isinstance(value, type) and value.__module__ == module.__name__:
            yield value


MODULES = _modules()
COMMANDS = list(_leaves(get_command(app)))


@pytest.mark.parametrize("path", COMMANDS, ids=" ".join)
def test_every_command_builds_its_help(path: tuple[str, ...]) -> None:
    result = CliRunner().invoke(app, [*path, "--help"])
    assert result.exit_code == 0, result.output


def test_every_pydantic_model_is_complete() -> None:
    incomplete = []
    for module in MODULES:
        for cls in _defined_here(module):
            if issubclass(cls, pydantic.BaseModel) and cls is not pydantic.BaseModel:
                try:
                    cls.model_rebuild(force=True)
                except pydantic.PydanticUserError as error:
                    incomplete.append(f"{cls.__module__}.{cls.__qualname__}: {error}")
    assert incomplete == []


def test_every_dataclass_lists_its_fields() -> None:
    """``dataclasses.fields`` is what ``asdict``, ``replace`` and the wire writers read."""
    count = 0
    for module in MODULES:
        for cls in _defined_here(module):
            if dataclasses.is_dataclass(cls):
                assert dataclasses.fields(cls) is not None
                count += 1
    assert count > 100
