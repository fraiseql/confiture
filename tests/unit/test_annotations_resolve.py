"""Every annotation confiture defines resolves when something reads it.

On Python 3.14 an annotation is evaluated the first time it is read (PEP 649),
not when the module loads. A name imported only under ``TYPE_CHECKING`` then
raises ``NameError`` in the reader — a consumer calling
``inspect.get_annotations(Migration)``, typer building a command, pydantic
building a model — not in confiture. So each class, method and function is read
here the way such a consumer reads it.
"""

import annotationlib
import importlib
import inspect
import pkgutil
from collections.abc import Iterator
from typing import Any

import confiture


def _modules() -> Iterator[Any]:
    for info in pkgutil.walk_packages(confiture.__path__, prefix="confiture."):
        # The pytest plugin registers itself with pytest when imported.
        if not info.name.startswith("confiture.testing.pytest"):
            yield importlib.import_module(info.name)


def _annotated(module: Any) -> Iterator[Any]:
    for value in vars(module).values():
        if getattr(value, "__module__", None) != module.__name__:
            continue
        if inspect.isclass(value):
            yield value
            yield from (m for m in vars(value).values() if inspect.isfunction(m))
        elif inspect.isfunction(value):
            yield value


def test_every_annotation_resolves() -> None:
    unresolved = []
    for module in _modules():
        for target in _annotated(module):
            try:
                annotationlib.get_annotations(target, format=annotationlib.Format.VALUE)
            except NameError as error:
                unresolved.append(f"{module.__name__}:{target.__qualname__}: {error}")
    assert unresolved == [], (
        "import these names at run time; a TYPE_CHECKING-only name raises in "
        f"whoever reads the annotation: {unresolved}"
    )
