"""Contract test pinning what fraiseql v1's ``migrate`` commands rely on a session doing.

``test_consumer_symbols.py`` pins the names and parameters fraiseql v1 reaches
(``fraiseql:src/fraiseql/cli/commands/migrate.py``, fraiseql-python@b1e53640). What
it does with them depends on three behaviours a signature cannot show:

- ``up`` / ``down`` / ``status`` run on a directory mixing ``.py`` migrations (the
  files ``fraiseql migrate create`` writes, :268) with ``.up.sql`` ones, which
  fraiseql lists side by side (:52), and confiture orders by version;
- a failed ``up`` *returns* ``success=False`` with an ``error_summary``, and
  fraiseql raises its own error from that (:461) — an exception escaping
  ``up`` would skip its report of what was applied (:454);
- ``status`` raises when the database cannot be reached, and fraiseql answers
  with the file list instead (:377).

Each test drives a session the way ``migrate.py`` does: one ``with`` per command,
opened by ``Migrator.from_config`` from an environment file (:49) or an
``Environment`` (:48).
"""

from pathlib import Path

import pytest

from confiture.config.environment import Environment
from confiture.core.migrator import Migrator

_PY = ("20261017000001", "create_widgets")
_SQL = ("20261017000002", "create_gadgets")
_BROKEN = ("20261017000003", "read_nothing")

# The shape of the file `fraiseql migrate create` writes (:268), with its
# commented example filled in.
_PY_MIGRATION = '''"""Migration: create_widgets"""

from confiture.models.migration import Migration


class CreateWidgets(Migration):
    """Migration: create_widgets."""

    version = "20261017000001"
    name = "create_widgets"

    def up(self) -> None:
        self.execute("CREATE TABLE widgets (id INT PRIMARY KEY)")

    def down(self) -> None:
        self.execute("DROP TABLE widgets")
'''


def _migrations(tmp_path: Path, *, mixed: bool = True) -> Path:
    """`_PY` and `_SQL`, or with ``mixed=False`` `_SQL` and the `_BROKEN` one after it."""
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    if mixed:
        (migrations / f"{_PY[0]}_{_PY[1]}.py").write_text(_PY_MIGRATION)
    stem = f"{_SQL[0]}_{_SQL[1]}"
    (migrations / f"{stem}.up.sql").write_text("CREATE TABLE gadgets (id INT PRIMARY KEY);\n")
    (migrations / f"{stem}.down.sql").write_text("DROP TABLE gadgets;\n")
    if not mixed:
        stem = f"{_BROKEN[0]}_{_BROKEN[1]}"
        (migrations / f"{stem}.up.sql").write_text("SELECT * FROM no_such_table;\n")
        (migrations / f"{stem}.down.sql").write_text("SELECT 1;\n")
    return migrations


def _environment_file(tmp_path: Path, database_url: str) -> Path:
    """The environment file `fraiseql migrate init` writes (:176)."""
    path = tmp_path / "local.yaml"
    path.write_text(
        "name: local\n"
        "include_dirs:\n"
        "  - db/schema/00_common\n"
        "exclude_dirs: []\n"
        f"database_url: {database_url}\n"
    )
    return path


@pytest.mark.usefixtures("clean_test_db")
def test_a_mixed_directory_is_listed_applied_and_rolled_back(
    test_db_url: str, tmp_path: Path
) -> None:
    migrations = _migrations(tmp_path)
    config = _environment_file(tmp_path, test_db_url)

    with Migrator.from_config(config, migrations_dir=migrations) as session:
        listed = [(m.version, m.name, m.status) for m in session.status().migrations]
    assert listed == [(*_PY, "pending"), (*_SQL, "pending")]

    with Migrator.from_config(config, migrations_dir=migrations) as session:
        first = session.up(target=_PY[0])
    assert [(m.version, m.name) for m in first.migrations_applied] == [_PY]

    with Migrator.from_config(config, migrations_dir=migrations) as session:
        rest = session.up(target=None)
    assert (rest.success, [(m.version, m.name) for m in rest.migrations_applied]) == (True, [_SQL])

    with Migrator.from_config(config, migrations_dir=migrations) as session:
        assert session.status().applied == [_PY[0], _SQL[0]]
        down = session.down(steps=1)
    assert (down.success, [(m.version, m.name) for m in down.migrations_rolled_back]) == (
        True,
        [_SQL],
    )


@pytest.mark.usefixtures("clean_test_db")
def test_a_failed_up_returns_its_failure(test_db_url: str, tmp_path: Path) -> None:
    migrations = _migrations(tmp_path, mixed=False)
    environment = Environment(name="local", database_url=test_db_url)

    with Migrator.from_config(environment, migrations_dir=migrations) as session:
        result = session.up(target=None)

    assert result.success is False
    assert [(m.version, m.name) for m in result.migrations_applied] == [_SQL]
    assert result.error_summary


def test_status_raises_when_the_database_is_unreachable(tmp_path: Path) -> None:
    migrations = _migrations(tmp_path)
    environment = Environment(
        name="local", database_url="postgresql://localhost:1/nowhere?connect_timeout=2"
    )

    with (
        pytest.raises(Exception),  # noqa: B017 - fraiseql catches Exception (:377)
        Migrator.from_config(environment, migrations_dir=migrations) as session,
    ):
        session.status()
