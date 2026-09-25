"""DDL for the object changes the differ learned to report (issue #288).

``migrate diff --generate`` writes ``-- WARNING: no SQL derived for: …`` for a
change it cannot render. That is honest, but a view is one of the few objects
whose whole definition the differ holds, so it can write the real statement.
"""

import pytest

from confiture.core.ddl_objects import OBJECT_KEYWORD, REPLACE_IS_AUTHORS_WORK
from confiture.core.differ import SchemaDiffer
from confiture.core.differ_sql import DERIVED_KINDS, DifferSQLGenerator
from tests.unit._schema_changes import added, dropped

BASE = "CREATE TABLE tb_user (pk_user BIGINT PRIMARY KEY, name TEXT);\n"

#: One definition of each kind a migration is derived for.
DERIVED = {
    "view": "CREATE VIEW v AS SELECT pk_user FROM tb_user;",
    "matview": "CREATE MATERIALIZED VIEW mv AS SELECT pk_user FROM tb_user;",
    "function": "CREATE FUNCTION fn() RETURNS INT LANGUAGE sql AS $$ SELECT 1 $$;",
    "procedure": "CREATE PROCEDURE pr() LANGUAGE sql AS $$ SELECT 1 $$;",
    "aggregate": "CREATE AGGREGATE ag (INT) (sfunc = int4pl, stype = INT);",
    "domain": "CREATE DOMAIN d AS TEXT;",
    "type": "CREATE TYPE tc AS (x INT);",
}

TRIGGER = (
    "CREATE TRIGGER trg_touch BEFORE UPDATE ON tb_user FOR EACH ROW EXECUTE FUNCTION fn_touch();"
)


def change_of(old_extra: str, new_extra: str, change_type: str):
    changes = SchemaDiffer().compare(BASE + old_extra, BASE + new_extra).changes
    matching = [c for c in changes if c.to_wire().type == change_type]
    assert matching, f"expected a {change_type} among {[c.to_wire().type for c in changes]}"
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

    def test_drop_view_drops_it(self):
        change = change_of("CREATE VIEW v_user AS SELECT pk_user FROM tb_user;", "", "DROP_VIEW")
        assert "DROP VIEW IF EXISTS v_user" in DifferSQLGenerator().generate_up(change)

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
        generator = DifferSQLGenerator()
        for old, new in pairs:
            for change in SchemaDiffer().compare(BASE + old, BASE + new).changes:
                sql = generator.generate_up(change)
                assert "WARNING" not in sql, f"{change.to_wire().type} has no DDL generator"

    def test_the_exempt_changes_are_still_reported_and_still_have_no_generator(self):
        """Reported by the differ — the gate is what matters — and left to the author."""
        cases = {
            "REPLACE_DOMAIN": (
                "CREATE DOMAIN d AS TEXT CHECK (VALUE <> '');",
                "CREATE DOMAIN d AS TEXT CHECK (VALUE <> ' ');",
            ),
            "REPLACE_TYPE": (
                "CREATE TYPE t AS (x INT);",
                "CREATE TYPE t AS (x INT, y INT);",
            ),
            "REPLACE_TRIGGER": (
                "CREATE TRIGGER g BEFORE UPDATE ON tb_user FOR EACH ROW EXECUTE FUNCTION f();",
                "CREATE TRIGGER g AFTER UPDATE ON tb_user FOR EACH ROW EXECUTE FUNCTION f();",
            ),
            "REPLACE_POLICY": (
                "CREATE POLICY p ON tb_user USING (true);",
                "CREATE POLICY p ON tb_user USING (pk_user > 0);",
            ),
        }
        for change_type, (old, new) in cases.items():
            change = change_of(old, new, change_type)
            kind = change.ref.kind
            assert kind in REPLACE_IS_AUTHORS_WORK, f"{change_type} has no stated reason"
            assert DifferSQLGenerator().generate_up(change) is None
            assert DifferSQLGenerator().generate_down(change) is None

    def test_every_stated_exemption_names_a_kind_the_differ_can_emit(self):
        """A reason cannot outlive the thing it explains (the one-lexer idiom)."""
        from confiture.core.ddl_objects import OBJECT_KEYWORD

        unknown = sorted(set(REPLACE_IS_AUTHORS_WORK) - set(OBJECT_KEYWORD))
        assert unknown == [], f"exemptions for kinds that do not exist: {unknown}"

    def test_a_kind_with_a_bespoke_replace_is_not_also_exempt(self):
        """A view has `CREATE OR REPLACE`; claiming it has none would be false."""
        for kind in ("view", "function", "procedure"):
            assert kind not in REPLACE_IS_AUTHORS_WORK

    def test_an_exempt_change_reaches_the_migration_as_a_warning(self, tmp_path):
        """Not silence: the up file names the change the author has to write."""
        from confiture.core.migration_generator import MigrationGenerator

        diff = SchemaDiffer().compare(
            BASE + "CREATE TYPE t AS (x INT);", BASE + "CREATE TYPE t AS (x INT, y INT);"
        )
        migrations = tmp_path / "db" / "migrations"
        migrations.mkdir(parents=True)
        up = MigrationGenerator(migrations_dir=migrations).generate_sql(diff, "retype")
        text = up.read_text()
        assert "no SQL derived" in text
        assert "REPLACE TYPE t" in text


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
        sql = DifferSQLGenerator().generate_up(change)
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


class TestOnlyTheDerivedKindsDeriveSQL:
    """A migration is derived for ``DERIVED_KINDS``; every other kind is reported.

    A trigger, an extension, a schema, a policy, … reach the migration as the
    generator's ``-- WARNING: no SQL derived`` and the author writes the DDL.
    """

    @pytest.mark.parametrize("factory", [added, dropped], ids=["added", "dropped"])
    @pytest.mark.parametrize(
        ("kind", "qualified", "create_sql"),
        [
            ("trigger", "tb_user.trg_touch", TRIGGER),
            ("extension", "pgcrypto", "CREATE EXTENSION pgcrypto"),
            ("schema", "app", "CREATE SCHEMA app"),
            ("policy", "tb_user.p_own", "CREATE POLICY p_own ON tb_user USING (true)"),
        ],
        ids=["trigger", "extension", "schema", "policy"],
    )
    def test_a_kind_outside_them_derives_no_sql_either_way(
        self, factory, kind, qualified, create_sql
    ):
        """There is no statement, so nothing for the gate to weigh."""
        assert kind not in DERIVED_KINDS
        change = factory(kind, qualified, create_sql)
        assert DifferSQLGenerator().generate_up(change) is None
        assert DifferSQLGenerator().generate_down(change) is None

    @pytest.mark.parametrize("kind", sorted(DERIVED_KINDS))
    def test_dropping_a_derived_kind_writes_the_drop(self, kind):
        """The destructive gate weighs it, as it does ``DROP TABLE`` (#335)."""
        (change,) = SchemaDiffer().compare(BASE + DERIVED[kind], BASE).changes
        sql = DifferSQLGenerator().generate_up(change)
        assert sql.startswith(f"DROP {OBJECT_KEYWORD[kind]} IF EXISTS ")

    def test_every_add_and_drop_of_a_derived_kind_renders_and_no_other_does(self):
        """A derived kind renders a statement either way; every other kind derives none."""
        extras = [
            *DERIVED.values(),
            TRIGGER,
            "CREATE POLICY p ON tb_user USING (true);",
            "CREATE EXTENSION pgcrypto;",
            "CREATE SCHEMA app;",
            "CREATE RULE r AS ON DELETE TO tb_user DO INSTEAD NOTHING;",
            "CREATE EVENT TRIGGER et ON ddl_command_start EXECUTE FUNCTION fn_t();",
            "CREATE TYPE tr AS RANGE (subtype = INT);",
            "CREATE STATISTICS st ON pk_user, name FROM tb_user;",
            "CREATE SERVER srv FOREIGN DATA WRAPPER fdw;",
        ]
        generator = DifferSQLGenerator()
        seen = 0
        rendered: set[str] = set()
        for extra in extras:
            for old, new in (("", extra), (extra, "")):
                for change in SchemaDiffer().compare(BASE + old, BASE + new).changes:
                    wire_type = change.to_wire().type
                    both = (generator.generate_up(change), generator.generate_down(change))
                    if change.ref.kind in DERIVED_KINDS:
                        for sql in both:
                            assert sql is not None, f"{wire_type} derives no SQL"
                            assert "WARNING" not in sql, f"{wire_type} renders a warning"
                            assert sql.strip(), f"{wire_type} renders nothing"
                        rendered.add(change.ref.kind)
                    else:
                        assert both == (None, None), f"{wire_type} derives SQL"
                    seen += 1
        assert seen == 2 * len(extras), f"expected one change per case, saw {seen}"
        assert rendered == DERIVED_KINDS
