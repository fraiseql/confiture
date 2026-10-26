"""``confiture.load_migration_class`` turns either kind of migration file into its class (#737)."""

from pathlib import Path

import pytest

import confiture
from confiture.exceptions import MigrationError
from confiture.models.migration import Migration
from confiture.models.sql_file_migration import FileSQLMigration
from tests.unit._doubles import connection_double

_PY_MIGRATION = """
from confiture.models.migration import Migration


class CreateUsers(Migration):
    version = "001"
    name = "create_users"

    def up(self):
        self.execute("CREATE TABLE users (id bigint)")

    def down(self):
        self.execute("DROP TABLE users")
"""


def test_a_python_migration_loads_as_its_class(tmp_path: Path) -> None:
    path = tmp_path / "001_create_users.py"
    path.write_text(_PY_MIGRATION)

    cls = confiture.load_migration_class(path)
    migration = cls(connection=connection_double())

    assert (cls.__name__, migration.version, migration.name) == (
        "CreateUsers",
        "001",
        "create_users",
    )


def test_an_up_sql_file_loads_with_its_down_sql_twin(tmp_path: Path) -> None:
    up = tmp_path / "002_add_posts.up.sql"
    down = tmp_path / "002_add_posts.down.sql"
    up.write_text("CREATE TABLE posts (id bigint);\n")
    down.write_text("DROP TABLE posts;\n")

    cls = confiture.load_migration_class(up)
    migration = cls(connection=connection_double())

    assert isinstance(migration, FileSQLMigration)
    assert isinstance(migration, Migration)
    assert (migration.version, migration.name) == ("002", "add_posts")
    assert (migration.up_file, migration.down_file) == (up, down)


def test_an_up_sql_file_without_its_down_sql_is_refused(tmp_path: Path) -> None:
    up = tmp_path / "003_orphan.up.sql"
    up.write_text("SELECT 1;\n")

    with pytest.raises(MigrationError, match=r"003_orphan\.down\.sql"):
        confiture.load_migration_class(up)


def test_a_file_of_another_kind_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "004_notes.sql"
    path.write_text("SELECT 1;\n")

    with pytest.raises(MigrationError, match="Unknown migration file type"):
        confiture.load_migration_class(path)
