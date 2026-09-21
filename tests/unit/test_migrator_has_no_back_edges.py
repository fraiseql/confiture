"""No module under ``core/_migrator/`` names the engine or the session it serves.

``engine.MigrationEngine`` and ``session.MigratorSession`` import their concern
modules — ``state``, ``apply``, ``rollback``, ``baseline``, ``discovery``,
``policy``; ``apply_loop``, ``rollback_loop``, ``replay``, ``reporting`` — and each of
those took its host as a parameter and imported the host's class under
``TYPE_CHECKING`` to annotate it: an annotation-only back-edge, a layering the
interpreter never checks. What a concern needs of its host is ``_migrator/ports.py``'s
``EngineHost`` / ``SessionHost`` protocols, which name exactly the members it reads.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import confiture
from confiture.core._migrator.engine import MigrationEngine
from confiture.core._migrator.ports import EngineHost, SessionHost
from confiture.core._migrator.session import MigratorSession

MIGRATOR = Path(confiture.__file__).resolve().parent / "core" / "_migrator"
HOSTS = ("confiture.core._migrator.engine", "confiture.core._migrator.session")
#: The modules above the hosts: they build a host, and are not imported by one.
ABOVE = {"factory.py", "session.py"}


def _host_imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [
        f"{path.name}:{node.lineno} {node.module}"
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module in HOSTS
    ]


def test_no_concern_module_imports_its_host() -> None:
    found = [
        hit
        for path in sorted(MIGRATOR.glob("*.py"))
        if path.name not in ABOVE
        for hit in _host_imports(path)
    ]
    assert found == [], "a concern module names its host:\n  " + "\n  ".join(found)


def _members(protocol: type) -> list[str]:
    """What a protocol declares: its annotated attributes, properties and methods."""
    declared = set(protocol.__dict__.get("__annotations__", {}))
    declared |= {
        name
        for name, value in protocol.__dict__.items()
        if not name.startswith("__") and (callable(value) or isinstance(value, property))
    }
    return sorted(declared)


def _parameters(member: object) -> list[str]:
    target = member.fget if isinstance(member, property) else member
    return list(inspect.signature(target).parameters)


def _missing(protocol: type, host: object) -> list[str]:
    """The members *protocol* declares that *host* lacks, or has with other parameters."""
    missing = []
    for name in _members(protocol):
        if not hasattr(host, name):
            missing.append(name)
            continue
        declared = inspect.getattr_static(protocol, name, None)
        real = inspect.getattr_static(type(host), name, None)
        is_callable = callable(declared) or isinstance(declared, property)
        if is_callable and (real is None or _parameters(declared) != _parameters(real)):
            missing.append(f"{name} (parameters differ)")
    return missing


def _engine() -> MigrationEngine:
    return MigrationEngine(connection=MagicMock())


def _session() -> MigratorSession:
    return MigratorSession(None, Path("db/migrations"))


@pytest.mark.parametrize(
    ("protocol", "host"),
    [(EngineHost, _engine), (SessionHost, _session)],
    ids=["engine", "session"],
)
def test_each_host_is_what_its_parts_read(protocol: type, host: object) -> None:
    """ty does not check a protocol's conformance where a host hands itself over; this does."""
    assert _members(protocol), "the protocol declares nothing — the check would pass vacuously"
    assert _missing(protocol, host()) == []  # type: ignore[operator]


def test_the_conformance_check_sees_a_missing_member() -> None:
    """The guard, seen red: a member the host does not have is reported."""

    class Wider(EngineHost):  # type: ignore[misc]
        def no_such_member(self) -> int: ...

    assert _missing(Wider, _engine()) == ["no_such_member"]
