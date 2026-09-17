"""DDL for the object changes the differ learned to report (issue #288).

``migrate diff --generate`` writes ``-- WARNING: no SQL derived for: …`` for a
change it cannot render. That is honest, but a view is one of the few objects
whose whole definition the differ holds, so it can write the real statement.
"""

import pytest

from confiture.core.differ import SchemaDiffer
from confiture.core.differ_sql import DifferSQLGenerator
from confiture.exceptions import UnsafeOperationError

BASE = "CREATE TABLE tb_user (pk_user BIGINT PRIMARY KEY, name TEXT);\n"


def change_of(old_extra: str, new_extra: str, change_type: str):
    changes = SchemaDiffer().compare(BASE + old_extra, BASE + new_extra).changes
    matching = [c for c in changes if c.type == change_type]
    assert matching, f"expected a {change_type} among {[c.type for c in changes]}"
    return matching[0]


class TestViewDDL:
    def test_add_view_generates_a_replaceable_create(self):
        """``OR REPLACE`` so re-applying the migration is not an error."""
        change = change_of("", "CREATE VIEW v_user AS SELECT pk_user FROM tb_user;", "ADD_VIEW")
        sql = DifferSQLGenerator().generate_up(change)
        assert sql.startswith("CREATE OR REPLACE VIEW v_user AS")
        assert "pk_user" in sql
        assert sql.rstrip().endswith(";")

    def test_add_view_rolls_back_by_dropping_it(self):
        change = change_of("", "CREATE VIEW v_user AS SELECT pk_user FROM tb_user;", "ADD_VIEW")
        assert "DROP VIEW IF EXISTS v_user" in DifferSQLGenerator().generate_down(change)

    def test_replace_view_generates_the_new_definition(self):
        change = change_of(
            "CREATE VIEW v_user AS SELECT pk_user FROM tb_user;",
            "CREATE VIEW v_user AS SELECT pk_user, name FROM tb_user;",
            "REPLACE_VIEW",
        )
        sql = DifferSQLGenerator().generate_up(change)
        assert sql.startswith("CREATE OR REPLACE VIEW v_user AS")
        assert "name" in sql

    def test_replace_view_rolls_back_to_the_old_definition(self):
        """The down side is the definition that was there before, not a drop."""
        change = change_of(
            "CREATE VIEW v_user AS SELECT pk_user FROM tb_user;",
            "CREATE VIEW v_user AS SELECT pk_user, name FROM tb_user;",
            "REPLACE_VIEW",
        )
        down = DifferSQLGenerator().generate_down(change)
        assert down.startswith("CREATE OR REPLACE VIEW v_user AS")
        assert "name" not in down

    def test_drop_view_is_destructive_without_force(self):
        change = change_of("CREATE VIEW v_user AS SELECT pk_user FROM tb_user;", "", "DROP_VIEW")
        with pytest.raises(UnsafeOperationError):
            DifferSQLGenerator().generate_up(change)

    def test_drop_view_with_force_drops_it(self):
        change = change_of("CREATE VIEW v_user AS SELECT pk_user FROM tb_user;", "", "DROP_VIEW")
        assert "DROP VIEW IF EXISTS v_user" in DifferSQLGenerator(True).generate_up(change)

    def test_drop_view_rolls_back_by_recreating_it(self):
        change = change_of("CREATE VIEW v_user AS SELECT pk_user FROM tb_user;", "", "DROP_VIEW")
        assert "CREATE OR REPLACE VIEW v_user AS" in DifferSQLGenerator().generate_down(change)


class TestMaterializedViewDDL:
    """A matview has no ``OR REPLACE``: PostgreSQL only offers drop and recreate."""

    def test_add_matview_generates_if_not_exists(self):
        change = change_of(
            "", "CREATE MATERIALIZED VIEW mv_user AS SELECT pk_user FROM tb_user;", "ADD_MATVIEW"
        )
        sql = DifferSQLGenerator().generate_up(change)
        assert sql.startswith("CREATE MATERIALIZED VIEW IF NOT EXISTS mv_user AS")

    def test_replace_matview_drops_and_recreates(self):
        change = change_of(
            "CREATE MATERIALIZED VIEW mv_user AS SELECT pk_user FROM tb_user;",
            "CREATE MATERIALIZED VIEW mv_user AS SELECT pk_user, name FROM tb_user;",
            "REPLACE_MATVIEW",
        )
        sql = DifferSQLGenerator().generate_up(change)
        assert "DROP MATERIALIZED VIEW IF EXISTS mv_user" in sql
        assert "CREATE MATERIALIZED VIEW IF NOT EXISTS mv_user AS" in sql
        assert "name" in sql


class TestTheMigrationIsNotShort:
    """A change the differ reports and the generator cannot render is named."""

    def test_every_object_change_the_differ_emits_can_be_rendered(self):
        """No object change falls through to ``-- WARNING: no SQL derived``."""
        pairs = [
            ("", "CREATE VIEW v AS SELECT pk_user FROM tb_user;"),
            ("CREATE VIEW v AS SELECT pk_user FROM tb_user;", ""),
            (
                "CREATE VIEW v AS SELECT pk_user FROM tb_user;",
                "CREATE VIEW v AS SELECT name FROM tb_user;",
            ),
            ("", "CREATE MATERIALIZED VIEW mv AS SELECT pk_user FROM tb_user;"),
            ("CREATE MATERIALIZED VIEW mv AS SELECT pk_user FROM tb_user;", ""),
            (
                "CREATE MATERIALIZED VIEW mv AS SELECT pk_user FROM tb_user;",
                "CREATE MATERIALIZED VIEW mv AS SELECT name FROM tb_user;",
            ),
            ("", "CREATE FUNCTION fn() RETURNS INT LANGUAGE sql AS $$ SELECT 1 $$;"),
            ("CREATE FUNCTION fn() RETURNS INT LANGUAGE sql AS $$ SELECT 1 $$;", ""),
            (
                "CREATE FUNCTION fn() RETURNS INT LANGUAGE sql AS $$ SELECT 1 $$;",
                "CREATE FUNCTION fn() RETURNS INT LANGUAGE sql AS $$ SELECT 2 $$;",
            ),
            ("", "CREATE PROCEDURE pr() LANGUAGE sql AS $$ SELECT 1 $$;"),
            ("CREATE PROCEDURE pr() LANGUAGE sql AS $$ SELECT 1 $$;", ""),
            ("", "CREATE AGGREGATE ag (INT) (sfunc = int4pl, stype = INT);"),
            ("CREATE AGGREGATE ag (INT) (sfunc = int4pl, stype = INT);", ""),
        ]
        generator = DifferSQLGenerator(True)
        for old, new in pairs:
            for change in SchemaDiffer().compare(BASE + old, BASE + new).changes:
                sql = generator.generate_up(change)
                assert "WARNING" not in sql, f"{change.type} has no DDL generator"


class TestGeneratedMigrationCarriesTheView:
    """End of the chain: what `migrate diff --generate` actually writes."""

    def test_the_up_file_contains_the_view_not_a_warning(self, tmp_path):
        from confiture.core.migration_generator import MigrationGenerator

        diff = SchemaDiffer().compare(
            BASE, BASE + "CREATE VIEW v_user AS SELECT pk_user FROM tb_user;"
        )
        migrations = tmp_path / "db" / "migrations"
        migrations.mkdir(parents=True)
        up = MigrationGenerator(migrations_dir=migrations).generate_sql(diff, "add_v_user")

        text = up.read_text()
        assert "CREATE OR REPLACE VIEW v_user AS" in text
        assert "no SQL derived" not in text

        down = up.with_name(up.name.replace(".up.sql", ".down.sql"))
        assert "DROP VIEW IF EXISTS v_user" in down.read_text()


class TestRoutineDDL:
    """A dropped routine must name its arguments, or PostgreSQL cannot pick it."""

    FN = "CREATE FUNCTION fn_c(p BIGINT) RETURNS BIGINT LANGUAGE sql AS $$ SELECT 1 $$;"

    def test_drop_function_names_the_overload(self):
        change = change_of(self.FN, "", "DROP_FUNCTION")
        sql = DifferSQLGenerator(True).generate_up(change)
        assert sql.strip() == "DROP FUNCTION IF EXISTS fn_c(bigint);"

    def test_add_function_rolls_back_by_dropping_that_overload(self):
        change = change_of("", self.FN, "ADD_FUNCTION")
        assert "DROP FUNCTION IF EXISTS fn_c(bigint)" in DifferSQLGenerator().generate_down(change)

    def test_add_function_generates_a_replaceable_create(self):
        change = change_of("", self.FN, "ADD_FUNCTION")
        assert (
            DifferSQLGenerator()
            .generate_up(change)
            .startswith("CREATE OR REPLACE FUNCTION fn_c(p bigint)")
        )

    def test_add_function_still_honours_a_hand_built_source(self):
        """`details["source"]` predates #288 and its caller must keep working."""
        from confiture.models.schema import SchemaChange

        change = SchemaChange(
            type="ADD_FUNCTION", table="myfunc", details={"source": "CREATE FUNCTION myfunc()"}
        )
        assert "CREATE FUNCTION myfunc()" in DifferSQLGenerator().generate_up(change)
