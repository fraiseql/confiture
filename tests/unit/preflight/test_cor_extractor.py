"""Tests for the CREATE OR REPLACE target extractor."""

from __future__ import annotations

from pathlib import Path

import pytest

# pglast is required for these tests. Skip the whole module if it's not installed.
pglast = pytest.importorskip("pglast")

from confiture.core.cor_extractor import (  # noqa: E402
    find_cor_targets,
    find_cor_targets_in_file,
)
from confiture.models.preflight import CorTarget  # noqa: E402


class TestSingleView:
    def test_qualified_view(self) -> None:
        targets = find_cor_targets("CREATE OR REPLACE VIEW public.v_users AS SELECT id FROM users;")
        assert len(targets) == 1
        t = targets[0]
        assert t.kind == "view"
        assert t.schema == "public"
        assert t.name == "v_users"

    def test_unqualified_view_defaults_to_public(self) -> None:
        targets = find_cor_targets("CREATE OR REPLACE VIEW v_users AS SELECT id FROM users;")
        assert targets[0].schema == "public"
        assert targets[0].name == "v_users"


class TestCorVariants:
    def test_materialized_view_is_not_a_cor_target(self) -> None:
        # PostgreSQL rejects CREATE OR REPLACE MATERIALIZED VIEW, so plain
        # CREATE MATERIALIZED VIEW is never a CoR target. The regex
        # idempotency detector flags it separately if needed.
        targets = find_cor_targets("CREATE MATERIALIZED VIEW mv_x AS SELECT 1;")
        assert targets == []

    def test_function(self) -> None:
        sql = (
            "CREATE OR REPLACE FUNCTION schema_a.f_summary() "
            "RETURNS void AS $$ BEGIN END; $$ LANGUAGE plpgsql;"
        )
        targets = find_cor_targets(sql)
        assert len(targets) == 1
        assert targets[0].kind == "function"
        assert targets[0].schema == "schema_a"
        assert targets[0].name == "f_summary"

    def test_procedure(self) -> None:
        sql = "CREATE OR REPLACE PROCEDURE p_sync() AS $$ BEGIN END; $$ LANGUAGE plpgsql;"
        targets = find_cor_targets(sql)
        assert len(targets) == 1
        assert targets[0].kind == "procedure"
        assert targets[0].name == "p_sync"


class TestCorGuard:
    def test_create_view_without_or_replace_is_not_target(self) -> None:
        assert find_cor_targets("CREATE VIEW v_x AS SELECT 1;") == []

    def test_create_function_without_or_replace_is_not_target(self) -> None:
        sql = "CREATE FUNCTION f_x() RETURNS void AS $$ BEGIN END; $$ LANGUAGE plpgsql;"
        assert find_cor_targets(sql) == []

    def test_mixed_create_and_create_or_replace(self) -> None:
        sql = "CREATE VIEW v_other AS SELECT 1;CREATE OR REPLACE VIEW v_x AS SELECT 1;"
        targets = find_cor_targets(sql)
        assert len(targets) == 1
        assert targets[0].name == "v_x"


class TestCorTargetsInPythonMigration:
    def test_py_migration_with_cor_view(self, tmp_path: Path) -> None:
        migration = tmp_path / "20260101000000_cor_view.py"
        migration.write_text(
            "from confiture.models.migration import Migration\n"
            "\n"
            "class M(Migration):\n"
            '    version = "20260101000000"\n'
            '    name = "cor_view"\n'
            "    def up(self) -> None:\n"
            '        self.execute("CREATE OR REPLACE VIEW v_users AS SELECT 1;")\n'
            "    def down(self) -> None:\n"
            "        pass\n",
            encoding="utf-8",
        )

        targets = find_cor_targets_in_file(migration, project_root=tmp_path)
        assert len(targets) == 1
        t = targets[0]
        assert t.kind == "view"
        assert t.name == "v_users"
        assert t.source_file == migration
        assert t.source_line == 7

    def test_py_migration_with_no_cor(self, tmp_path: Path) -> None:
        migration = tmp_path / "20260101000001_plain.py"
        migration.write_text(
            "from confiture.models.migration import Migration\n"
            "\n"
            "class M(Migration):\n"
            '    version = "20260101000001"\n'
            '    name = "plain"\n'
            "    def up(self) -> None:\n"
            '        self.execute("CREATE TABLE foo (id int);")\n'
            "    def down(self) -> None:\n"
            "        pass\n",
            encoding="utf-8",
        )
        assert find_cor_targets_in_file(migration, project_root=tmp_path) == []

    def test_sql_file_routing(self, tmp_path: Path) -> None:
        sql_path = tmp_path / "001_x.up.sql"
        sql_path.write_text("CREATE OR REPLACE VIEW v_x AS SELECT 1;\n", encoding="utf-8")
        targets = find_cor_targets_in_file(sql_path)
        assert len(targets) == 1
        assert targets[0].source_file == sql_path
        # SQL files don't have a meaningful source_line — None is fine
        assert targets[0].source_line is None or isinstance(targets[0].source_line, int)


def test_cor_target_dataclass_is_frozen() -> None:
    from dataclasses import FrozenInstanceError

    t = CorTarget(kind="view", schema="public", name="v", source_file=None, source_line=None)
    with pytest.raises(FrozenInstanceError):
        t.kind = "function"  # type: ignore[misc]
