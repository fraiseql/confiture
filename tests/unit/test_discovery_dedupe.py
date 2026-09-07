"""One discovery, one filename parser, one loader."""

from __future__ import annotations

import sys
from pathlib import Path

from confiture.core._migrator.engine import Migrator
from confiture.core.connection import load_migration_module
from confiture.core.migrator import MigratorSession
from confiture.models.sql_file_migration import FileSQLMigration
from tests.unit._doubles import connection_double


def _sql_pair(directory: Path, version: str, name: str, sql: str) -> Path:
    up = directory / f"{version}_{name}.up.sql"
    up.write_text(sql)
    (directory / f"{version}_{name}.down.sql").write_text("SELECT 1;\n")
    return up


def test_status_ignores_helpers_like_up_does(tmp_path: Path) -> None:
    (tmp_path / "__init__.py").write_text("")
    (tmp_path / "_helper.py").write_text("X = 1\n")
    _sql_pair(tmp_path, "20260101120000", "real", "CREATE TABLE t (id int);\n")
    conn = connection_double()
    session = MigratorSession.attached(Migrator(connection=conn), tmp_path)

    status = session.status()

    assert [m.name for m in status.migrations] == ["real"]
    assert [m.version for m in status.migrations] == ["20260101120000"]


def test_dry_run_returns_the_sql_files_statements(tmp_path: Path) -> None:
    up = _sql_pair(
        tmp_path, "20260101120000", "two", "CREATE TABLE a (id int);\nCREATE TABLE b (id int);\n"
    )
    conn = connection_double()
    migration = FileSQLMigration.from_files(up, up.with_name(up.name.replace(".up.", ".down.")))(
        connection=conn
    )

    result = Migrator(connection=conn).dry_run(migration)

    # Statements come from the one lexer (pglast's scanner), which drops the
    # terminating semicolon the old sqlparse split kept.
    assert [s.sql for s in result.statements] == [
        "CREATE TABLE a (id int)",
        "CREATE TABLE b (id int)",
    ]


def test_loading_json_py_leaves_the_stdlib_alone(tmp_path: Path) -> None:
    import json

    before = sys.modules["json"]
    (tmp_path / "json.py").write_text(
        "from confiture.models.migration import Migration\n"
        "class Json(Migration):\n"
        "    version = '001'\n    name = 'json'\n"
        "    def up(self): pass\n    def down(self): pass\n"
    )
    try:
        module = load_migration_module(tmp_path / "json.py")
        assert module.Json.version == "001"
        assert sys.modules["json"] is before, "the migration module shadowed the stdlib json"
        assert json.dumps({"a": 1}) == '{"a": 1}'
    finally:
        sys.modules["json"] = before
