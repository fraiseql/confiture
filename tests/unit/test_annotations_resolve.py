"""Every annotation a consumer, typer or pydantic evaluates resolves when read.

On Python 3.14 an annotation is evaluated the first time it is read (PEP 649),
not when the module loads. A name imported only under ``TYPE_CHECKING`` then
raises ``NameError`` in the reader — a consumer calling
``inspect.get_annotations(Migration)``, typer building a command, pydantic
building a model — not in confiture. So each of those is read here the way such
a reader reads it (``Format.VALUE``).

The scope is what something outside confiture evaluates: the names confiture
and its platform seam export, the public packages (``models``, ``testing``,
``config``, the exceptions), every pydantic model, and every typer command
callback — the plugins' included. An internal module may keep a name
``TYPE_CHECKING``-only, which is how most of them break an import cycle; nothing
evaluates its annotations, and a dataclass reads its own as forward references.
"""

import annotationlib
import importlib
import inspect
import pkgutil
from collections.abc import Iterator
from typing import Any

import pydantic
import typer

import confiture
from confiture import platform

#: The packages a consumer imports from, read whole.
PUBLIC_PACKAGES = ("confiture.models", "confiture.testing", "confiture.config")
#: The public modules that are not packages.
PUBLIC_MODULES = ("confiture.exceptions", "confiture.platform")

#: Targets whose annotation names stay ``TYPE_CHECKING``-only, and why.
ALLOWED: dict[str, str] = {
    "confiture.exceptions:PreconditionError.__init__": (
        "core.preconditions imports confiture.exceptions to raise; importing it back is a cycle"
    ),
    "confiture.exceptions:PreconditionValidationError.__init__": (
        "core.preconditions imports confiture.exceptions to raise; importing it back is a cycle"
    ),
    "confiture.models.git:MigrationAccompanimentReport": (
        "models are leaves: test_import_layering forbids a run-time import from core"
    ),
    "confiture.models.git:MigrationAccompanimentReport.__init__": (
        "models are leaves: test_import_layering forbids a run-time import from core"
    ),
    "confiture.models.stub_models:_field_type": (
        "models are leaves: test_import_layering forbids a run-time import from core"
    ),
}


def _modules() -> Iterator[Any]:
    for info in pkgutil.walk_packages(confiture.__path__, prefix="confiture."):
        # The pytest plugin registers itself with pytest when imported.
        if not info.name.startswith("confiture.testing.pytest"):
            yield importlib.import_module(info.name)


def _public(name: str) -> bool:
    return name in PUBLIC_MODULES or any(
        name == package or name.startswith(f"{package}.") for package in PUBLIC_PACKAGES
    )


def _defined_in(module: Any) -> Iterator[Any]:
    for value in vars(module).values():
        if getattr(value, "__module__", None) == module.__name__:
            yield value


def _with_methods(value: Any) -> Iterator[Any]:
    if inspect.isclass(value):
        yield value
        yield from (m for m in vars(value).values() if inspect.isfunction(m))
    elif inspect.isfunction(value):
        yield value


def _exported() -> Iterator[Any]:
    """What ``confiture`` and ``confiture.platform`` export, and their methods."""
    for package in (confiture, platform):
        for name in package.__all__:
            yield from _with_methods(getattr(package, name))


def _callbacks(app: typer.Typer) -> Iterator[Any]:
    """Every command callback of *app* and of the groups added to it."""
    yield from (info.callback for info in app.registered_commands if info.callback)
    for group in app.registered_groups:
        if group.typer_instance is not None:
            if group.typer_instance.registered_callback is not None:
                yield group.typer_instance.registered_callback.callback
            yield from _callbacks(group.typer_instance)


def _commands() -> Iterator[Any]:
    # Reason: building the app registers every command, the plugins' among them
    from confiture.cli.main import app

    yield from (callback for callback in _callbacks(app) if callback is not None)


def _evaluated() -> Iterator[Any]:
    for module in _modules():
        for value in _defined_in(module):
            if _public(module.__name__):
                yield from _with_methods(value)
            elif inspect.isclass(value) and issubclass(value, pydantic.BaseModel):
                yield value
    yield from _exported()
    yield from _commands()


def _unresolved() -> dict[str, str]:
    unresolved = {}
    for target in _evaluated():
        try:
            annotationlib.get_annotations(target, format=annotationlib.Format.VALUE)
        except NameError as error:
            unresolved[f"{target.__module__}:{target.__qualname__}"] = str(error)
    return unresolved


def test_every_evaluated_annotation_resolves() -> None:
    unresolved = sorted(f"{t}: {e}" for t, e in _unresolved().items() if t not in ALLOWED)
    assert unresolved == [], (
        "import these names at run time; a TYPE_CHECKING-only name raises in "
        f"whoever reads the annotation: {unresolved}"
    )


def test_every_allowed_target_is_still_unresolved() -> None:
    stale = sorted(set(ALLOWED) - set(_unresolved()))
    assert stale == [], f"remove these allow-list entries, they resolve now: {stale}"


def test_the_scope_reaches_the_command_callbacks() -> None:
    """The walk finds the commands, so an empty answer above is not an empty scope."""
    names = {callback.__name__ for callback in _commands()}
    assert {"build", "lint", "drift"} <= names
