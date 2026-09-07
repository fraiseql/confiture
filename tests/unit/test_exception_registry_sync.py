"""Every exception the package raises resolves to a registered code.

``fail()`` maps an exception to its exit code through the registry; an
exception whose default code is unregistered crashed the error path itself
(``UnsafeOperationError`` → ``DDL_001``), and ``PreconditionError`` sat outside
the ``ConfiturError`` hierarchy, so a failed precondition never reached the
envelope at all. This test builds one instance of every subclass — with the
smallest arguments its constructor accepts — and asks for its exit code.
"""

from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any

import pytest

import confiture.exceptions as exceptions_module
from confiture.core.preconditions import PreconditionError, PreconditionValidationError
from confiture.exceptions import ConfiturError


def _subclasses() -> list[type[ConfiturError]]:
    return sorted(
        (
            cls
            for _, cls in inspect.getmembers(exceptions_module, inspect.isclass)
            if issubclass(cls, ConfiturError) and cls is not ConfiturError
        ),
        key=lambda c: c.__name__,
    )


def _dummy(param: inspect.Parameter) -> Any:
    annotation = str(param.annotation)
    name = param.name
    if "Path" in annotation or name.endswith(("path", "file")):
        return Path("x")
    if "Exception" in annotation or name == "original_error":
        return RuntimeError("x")
    if annotation.startswith("list") or name == "failures":
        return []
    if annotation.startswith("tuple") or name == "params":
        return None
    return "x"


def _instantiate(cls: type[ConfiturError]) -> ConfiturError:
    """Positional parameters get the smallest plausible value; keywords take their defaults."""
    args = [
        _dummy(p)
        for p in list(inspect.signature(cls.__init__).parameters.values())[1:]
        if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD) and p.default is p.empty
    ]
    return cls(*args)


@pytest.mark.parametrize("cls", _subclasses(), ids=lambda c: c.__name__)
def test_every_exception_resolves_an_exit_code(cls: type[ConfiturError]) -> None:
    exc = _instantiate(cls)
    assert isinstance(exc.exit_code, int), cls.__name__


def test_precondition_errors_are_confiture_errors() -> None:
    assert issubclass(PreconditionError, ConfiturError)
    assert issubclass(PreconditionValidationError, ConfiturError)
    assert PreconditionError("x").error_code.startswith("PRECON_")
    assert isinstance(PreconditionError("x").exit_code, int)
