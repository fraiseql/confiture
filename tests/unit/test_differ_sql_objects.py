"""DDL for the object changes the differ learned to report (issue #288).

``migrate diff --generate`` writes ``-- WARNING: no SQL derived for: …`` for a
change it cannot render. That is honest, but a view is one of the few objects
whose whole definition the differ holds, so it can write the real statement.
"""

import pglast
import pytest

from confiture.core.ddl_objects import OBJECT_KEYWORD, REPLACE_IS_AUTHORS_WORK
from confiture.core.differ import SchemaDiffer
from confiture.core.differ_sql import DERIVED_KINDS, DifferSQLGenerator

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
    "trigger": (
        "CREATE TRIGGER trg_touch BEFORE UPDATE ON tb_user FOR EACH ROW EXECUTE FUNCTION fn_t();"
    ),
    "extension": "CREATE EXTENSION pgcrypto;",
    "schema": "CREATE SCHEMA app;",
    "policy": "CREATE POLICY p_own ON tb_user USING (true);",
}

TRIGGER = (
    "CREATE TRIGGER trg_touch BEFORE UPDATE ON tb_user FOR EACH ROW EXECUTE FUNCTION fn_touch();"
)


def _statements(sql: str) -> list:
    return [raw.stmt for raw in pglast.parse_sql(sql)]


def _view_columns(stmt) -> list[str]:
    return [target.name or target.val.fields[-1].sval for target in stmt.query.targetList]


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

    def test_replace_view_rolls_back_by_dropping_what_or_replace_cannot_remove(self):
        """The old view had fewer columns: ``OR REPLACE`` cannot take one away (#408)."""
        change = change_of(
            "CREATE VIEW v_user AS SELECT pk_user FROM tb_user;",
            "CREATE VIEW v_user AS SELECT pk_user, name FROM tb_user;",
            "REPLACE_VIEW",
        )
        down = _statements(DifferSQLGenerator().generate_down(change))
        assert [type(s).__name__ for s in down] == ["DropStmt", "ViewStmt"]
        assert _view_columns(down[1]) == ["pk_user"]

    def test_replace_view_rolls_back_in_place_when_the_columns_are_the_same(self):
        change = change_of(
            "CREATE VIEW v_user AS SELECT pk_user, name FROM tb_user;",
            "CREATE VIEW v_user AS SELECT pk_user, name FROM tb_user WHERE pk_user > 0;",
            "REPLACE_VIEW",
        )
        (down,) = _statements(DifferSQLGenerator().generate_down(change))
        assert down.replace
        assert down.query.whereClause is None

    def test_replace_view_that_drops_a_column_is_dropped_and_created(self):
        """The up side has the same limit: a column removed or renamed (#408)."""
        change = change_of(
            "CREATE VIEW v_user AS SELECT pk_user, name FROM tb_user;",
            "CREATE VIEW v_user AS SELECT pk_user AS id FROM tb_user;",
            "REPLACE_VIEW",
        )
        up = DifferSQLGenerator().generate_up(change)
        assert "-- review:" in up
        statements = _statements(up)
        assert [type(s).__name__ for s in statements] == ["DropStmt", "ViewStmt"]
        assert _view_columns(statements[1]) == ["id"]

    def test_a_view_whose_columns_cannot_be_named_is_replaced_in_place(self):
        """``*`` names nothing confiture can read; ``OR REPLACE`` is kept, as before."""
        change = change_of(
            "CREATE VIEW v_user AS SELECT * FROM tb_user;",
            "CREATE VIEW v_user AS SELECT * FROM tb_user WHERE pk_user > 0;",
            "REPLACE_VIEW",
        )
        (up,) = _statements(DifferSQLGenerator().generate_up(change))
        assert up.replace

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


def _guarded(statement: str) -> str:
    return (
        "DO $confiture$\nBEGIN\n"
        f"    {statement};\n"
        "EXCEPTION WHEN duplicate_object THEN NULL;\n"
        "END\n$confiture$;\n"
    )


class TestEveryKindReappliesAndDrops:
    """#335: a trigger, extension, schema or policy derived no SQL; each now does.

    Each up re-applies without error — the kind's own existence clause where
    PostgreSQL has one, a ``duplicate_object`` guard where it has none — and each
    down drops what the up created, a trigger or policy ``ON`` its table.
    """

    @pytest.mark.parametrize(
        ("kind", "up", "down"),
        [
            (
                "extension",
                "CREATE EXTENSION IF NOT EXISTS pgcrypto;\n",
                "DROP EXTENSION IF EXISTS pgcrypto;\n",
            ),
            ("schema", "CREATE SCHEMA IF NOT EXISTS app;\n", "DROP SCHEMA IF EXISTS app;\n"),
            (
                "trigger",
                "CREATE OR REPLACE TRIGGER trg_touch BEFORE UPDATE ON tb_user FOR EACH ROW"
                " EXECUTE PROCEDURE fn_t();\n",
                "DROP TRIGGER IF EXISTS trg_touch ON tb_user;\n",
            ),
            (
                "policy",
                _guarded(
                    "CREATE POLICY p_own ON tb_user AS PERMISSIVE FOR all TO PUBLIC USING (TRUE)"
                ),
                "DROP POLICY IF EXISTS p_own ON tb_user;\n",
            ),
            ("domain", _guarded("CREATE DOMAIN d AS text"), "DROP DOMAIN IF EXISTS d;\n"),
            ("type", _guarded("CREATE TYPE tc AS (x integer)"), "DROP TYPE IF EXISTS tc;\n"),
        ],
    )
    def test_an_added_one(self, kind: str, up: str, down: str) -> None:
        (change,) = SchemaDiffer().compare(BASE, BASE + DERIVED[kind]).changes
        generator = DifferSQLGenerator()
        assert (generator.generate_up(change), generator.generate_down(change)) == (up, down)

    def test_a_dropped_one_comes_back_guarded(self) -> None:
        (change,) = SchemaDiffer().compare(BASE + DERIVED["policy"], BASE).changes
        generator = DifferSQLGenerator()
        assert generator.generate_up(change) == "DROP POLICY IF EXISTS p_own ON tb_user;\n"
        assert generator.generate_down(change).startswith("DO $confiture$")

    def test_a_quoted_trigger_name_is_quoted_in_its_drop(self) -> None:
        trigger = (
            'CREATE TRIGGER "Touch" BEFORE UPDATE ON tb_user FOR EACH ROW EXECUTE FUNCTION fn_t();'
        )
        (change,) = SchemaDiffer().compare(BASE, BASE + trigger).changes
        assert DifferSQLGenerator().generate_down(change) == (
            'DROP TRIGGER IF EXISTS "Touch" ON tb_user;\n'
        )

    def test_a_schema_with_elements_has_no_if_not_exists(self) -> None:
        """PostgreSQL refuses ``IF NOT EXISTS`` beside a schema's own elements."""
        (change,) = [
            c
            for c in SchemaDiffer()
            .compare(BASE, BASE + "CREATE SCHEMA app CREATE VIEW v AS SELECT 1 AS one;")
            .changes
            if c.ref.kind == "schema"
        ]
        assert "IF NOT EXISTS" not in DifferSQLGenerator().generate_up(change)


class TestOnlyTheDerivedKindsDeriveSQL:
    """A migration is derived for ``DERIVED_KINDS``; every other kind is reported.

    A rule, an event trigger, statistics, a server, … reach the migration as the
    generator's ``-- WARNING: no SQL derived`` and the author writes the DDL.
    """

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
