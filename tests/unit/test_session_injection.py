"""The session takes its factories as parameters; the migrator module is not a patch seam (Phase 08).

``confiture.core.migrator`` re-exported two call-time wrappers,
``create_connection`` and ``load_migration_class``, whose only purpose was to
give tests a name to patch. That is a test-shaped shim in production code.
``MigratorSession`` now takes ``connection_factory`` and ``migration_loader``;
``Migrator.from_config`` passes them through; the CLI hands the session its one
seam (``confiture.cli.helpers.create_connection``, what ``connect`` calls); and
the public module exposes only the documented names.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

import confiture.core.migrator as public
from confiture.core.migrator import Migrator, MigratorSession
from confiture.models.migration import Migration
from tests.unit._doubles import connection_double

DOCUMENTED = {
    "Migrator",
    "MigratorSession",
    "UpEvent",
    "UpObserver",
    "LockConfig",
    "MigrationLock",
    "find_duplicate_migration_versions",
    "discover_migration_files",
    "parse_migration_filename",
    "_version_from_migration_filename",
}


def test_the_public_module_exposes_only_the_documented_names() -> None:
    assert set(public.__all__) == DOCUMENTED
    assert not hasattr(public, "create_connection")
    assert not hasattr(public, "load_migration_class")


def test_an_injected_connection_factory_opens_the_session() -> None:
    conn = connection_double()
    factory = MagicMock(return_value=conn)
    session = MigratorSession(
        None,
        Path("db/migrations"),
        database_url_override="postgresql://x/y",
        connection_factory=factory,
    )
    with session as s:
        factory.assert_called_once_with("postgresql://x/y")
        assert s.migrator.connection is conn
    conn.close.assert_called_once()


def test_from_config_passes_the_factories_through(tmp_path: Path) -> None:
    from confiture.config.environment import Environment

    env = Environment.model_validate(
        {"name": "t", "database_url": "postgresql://x/y", "include_dirs": ["db/schema"]}
    )
    conn = connection_double()
    factory = MagicMock(return_value=conn)
    loader = MagicMock()
    with Migrator.from_config(env, connection_factory=factory, migration_loader=loader) as s:
        factory.assert_called_once_with("postgresql://x/y")
        assert s.migrator.connection is conn


def test_an_injected_loader_is_what_up_uses_to_load_a_migration(tmp_path: Path) -> None:
    migrations = tmp_path / "db" / "migrations"
    migrations.mkdir(parents=True)
    migration_file = migrations / "20260907000001_add_thing.py"
    migration_file.write_text("# loaded through the injected loader, never imported\n")

    instances: list[MagicMock] = []

    def loader(path: Path) -> type:
        assert path == migration_file

        class Loaded(Migration):  # the real base: the engine reads its preconditions and flags
            version = "20260907000001"
            name = "add_thing"

            def __init__(self, connection):
                super().__init__(connection)
                instances.append(MagicMock(connection=connection))

            def up(self) -> None:
                instances[-1].up()

            def down(self) -> None:
                pass

        return Loaded

    session = MigratorSession(
        None,
        migrations,
        database_url_override="postgresql://x/y",
        connection_factory=lambda _url: connection_double(),
        migration_loader=loader,
    )
    with session as s:
        result = s.up(no_lock=True, verify_checksums=False)
    assert [m.version for m in result.migrations_applied] == ["20260907000001"]
    instances[-1].up.assert_called_once()


def test_the_class_level_default_is_read_when_the_session_enters_not_at_construction() -> None:
    """Without an injected factory the session reads ``default_connection_factory`` on enter."""
    from tests.unit._doubles import injected_connection

    session = MigratorSession(None, Path("db/migrations"), database_url_override="postgresql://x/y")
    conn = connection_double()
    with injected_connection(conn) as factory, session as s:
        assert s.migrator.connection is conn
    factory.assert_called_once_with("postgresql://x/y")


@pytest.mark.parametrize("name", ["create_connection", "load_migration_class"])
def test_no_test_patches_the_removed_seam(name: str) -> None:
    root = Path(__file__).resolve().parents[1]
    import re

    needle = f"confiture.core.migrator.{name}"
    by_object = re.compile(rf'patch\.object\(\s*\w+\s*,\s*"{name}"')
    offenders = []
    for p in root.rglob("*.py"):
        if p.name == Path(__file__).name:
            continue
        text = p.read_text(encoding="utf-8")
        if needle in text or ("confiture.core.migrator" in text and by_object.search(text)):
            offenders.append(p.relative_to(root).as_posix())
    assert offenders == [], f"{needle} is not a seam any more; inject the factory: {offenders}"
