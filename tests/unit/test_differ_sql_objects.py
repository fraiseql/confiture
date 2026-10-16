"""DDL for the object changes the differ learned to report (issue #288).

``migrate diff --generate`` writes ``-- WARNING: no SQL derived for: …`` for a
change it cannot render. That is honest, but a view is one of the few objects
whose whole definition the differ holds, so it can write the real statement.
"""

import pglast
import pytest

from confiture.core.ddl_objects import OBJECT_KEYWORD, REPLACE_IS_AUTHORS_WORK, DDLObject
from confiture.core.differ import SchemaDiffer
from confiture.core.differ_sql import DERIVED_KINDS, DifferSQLGenerator
from confiture.core.schema_change import ObjectAdded, ObjectDropped, ObjectReplaced
from confiture.core.schema_model import ref_for
from confiture.exceptions import DifferError

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
    "tview": "CREATE TABLE tv_user AS SELECT pk_user FROM tb_user;",
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


MV = "CREATE MATERIALIZED VIEW mv_user AS SELECT pk_user, name FROM tb_user;\n"
MV_OTHER = "CREATE MATERIALIZED VIEW mv_user AS SELECT pk_user FROM tb_user;\n"
MV_UNIQUE = "CREATE UNIQUE INDEX ux_mv_user ON mv_user (pk_user);\n"
MV_NAME = "CREATE INDEX ix_mv_user_name ON mv_user (name);\n"


def _kinds(sql: str) -> list[str]:
    return [type(stmt).__name__ for stmt in _statements(sql)]


def _indexes_of(sql: str) -> list:
    return [stmt for stmt in _statements(sql) if type(stmt).__name__ == "IndexStmt"]


class TestMaterializedViewIndexes:
    """A matview is created with its indexes, as a table is: plain and ``IF NOT EXISTS``."""

    def test_add_matview_creates_its_indexes_after_it(self):
        change = change_of("", MV + MV_UNIQUE + MV_NAME, "ADD_MATVIEW")
        sql = DifferSQLGenerator().generate_up(change)
        assert _kinds(sql) == ["CreateTableAsStmt", "IndexStmt", "IndexStmt"]
        indexes = _indexes_of(sql)
        assert [i.idxname for i in indexes] == ["ux_mv_user", "ix_mv_user_name"]
        assert all(i.relation.relname == "mv_user" for i in indexes)
        assert all(not i.concurrent and i.if_not_exists for i in indexes)
        assert indexes[0].unique

    def test_replace_matview_recreates_its_new_indexes(self):
        change = change_of(MV + MV_NAME, MV_OTHER + MV_UNIQUE, "REPLACE_MATVIEW")
        sql = DifferSQLGenerator().generate_up(change)
        assert _kinds(sql) == ["DropStmt", "CreateTableAsStmt", "IndexStmt"]
        (index,) = _indexes_of(sql)
        assert index.idxname == "ux_mv_user"
        assert not index.concurrent

    def test_replace_matview_down_recreates_its_old_indexes(self):
        change = change_of(MV + MV_NAME, MV_OTHER + MV_UNIQUE, "REPLACE_MATVIEW")
        sql = DifferSQLGenerator().generate_down(change)
        assert _kinds(sql) == ["DropStmt", "CreateTableAsStmt", "IndexStmt"]
        assert [i.idxname for i in _indexes_of(sql)] == ["ix_mv_user_name"]

    def test_carried_index_changes_do_not_reach_the_sql(self):
        """The recreate writes the index sets whole; the changes it carries are a reader's.

        ``ix_mv_user_name`` goes and ``ux_mv_user`` comes, so the change carries both
        index changes, and its up and down are still the statements without them.
        """
        from dataclasses import replace

        change = change_of(MV + MV_NAME, MV_OTHER + MV_UNIQUE, "REPLACE_MATVIEW")
        assert len(change.index_changes) == 2
        bare = replace(change, index_changes=())
        generator = DifferSQLGenerator()
        for render in (generator.generate_up, generator.generate_down):
            assert _statements(render(change)) == _statements(render(bare))

    def test_drop_matview_down_recreates_its_indexes(self):
        change = change_of(MV + MV_UNIQUE, "", "DROP_MATVIEW")
        assert _kinds(DifferSQLGenerator().generate_up(change)) == ["DropStmt"]
        sql = DifferSQLGenerator().generate_down(change)
        assert _kinds(sql) == ["CreateTableAsStmt", "IndexStmt"]
        assert [i.idxname for i in _indexes_of(sql)] == ["ux_mv_user"]

    def test_matview_unnamed_index_is_named_as_missing(self):
        change = change_of("", MV + "CREATE INDEX ON mv_user (name);\n", "ADD_MATVIEW")
        sql = DifferSQLGenerator().generate_up(change)
        assert _kinds(sql) == ["CreateTableAsStmt"]
        assert "WARNING: Cannot generate the index on mv_user (name) without an index name" in sql


class TestTViewDDL:
    """A pg_tviews TVIEW (#504) is written through pg_tviews' own functions.

    ``tviews.pg_tviews_create_or_replace()`` creates, replaces in place or rebuilds,
    and returns ``unchanged`` when applied again; ``tviews.pg_tviews_drop(…,
    if_exists => true)`` drops. Both are pg_tviews' read contract, so the
    migration re-applies and never guesses at a ``CREATE TABLE … AS``.
    """

    OLD = "CREATE TABLE tv_user AS SELECT pk_user FROM tb_user;"
    NEW = "CREATE TABLE tv_user AS SELECT pk_user, name FROM tb_user;"

    @staticmethod
    def _calls(sql: str) -> list[tuple[str, list, dict]]:
        """Each statement as ``(function, positional args, named args)``; it must be a call."""
        found = []
        for stmt in _statements(sql):
            assert type(stmt).__name__ == "SelectStmt", sql
            (target,) = stmt.targetList
            call = target.val
            function = ".".join(part.sval for part in call.funcname)
            positional = [a.val.sval for a in call.args if type(a).__name__ == "A_Const"]
            named = {
                a.name: getattr(a.arg.val, "sval", getattr(a.arg.val, "boolval", None))
                for a in call.args
                if type(a).__name__ == "NamedArgExpr"
            }
            found.append((function, positional, named))
        return found

    @staticmethod
    def _query(select: str) -> str:
        from pglast.stream import RawStream

        return RawStream()(pglast.parse_sql(select)[0].stmt)

    def test_add_tview_creates_or_replaces_it(self):
        change = change_of("", self.OLD, "ADD_TVIEW")
        generator = DifferSQLGenerator()
        assert self._calls(generator.generate_up(change)) == [
            (
                "tviews.pg_tviews_create_or_replace",
                ["tv_user", self._query("SELECT pk_user FROM tb_user")],
                {},
            )
        ]
        assert self._calls(generator.generate_down(change)) == [
            ("tviews.pg_tviews_drop", ["tv_user"], {"if_exists": True})
        ]

    def test_replace_tview_replaces_it_without_a_drop(self):
        """pg_tviews replaces in place, or rebuilds, keeping grants and user indexes."""
        change = change_of(self.OLD, self.NEW, "REPLACE_TVIEW")
        generator = DifferSQLGenerator()
        up, down = generator.generate_up(change), generator.generate_down(change)
        assert [c[0] for c in self._calls(up)] == ["tviews.pg_tviews_create_or_replace"]
        assert [c[0] for c in self._calls(down)] == ["tviews.pg_tviews_create_or_replace"]
        assert self._calls(up)[0][1][1] == self._query("SELECT pk_user, name FROM tb_user")
        assert self._calls(down)[0][1][1] == self._query("SELECT pk_user FROM tb_user")

    def test_drop_tview_drops_it_and_rolls_back_by_creating_it(self):
        change = change_of(self.OLD, "", "DROP_TVIEW")
        generator = DifferSQLGenerator()
        assert self._calls(generator.generate_up(change)) == [
            ("tviews.pg_tviews_drop", ["tv_user"], {"if_exists": True})
        ]
        assert [c[0] for c in self._calls(generator.generate_down(change))] == [
            "tviews.pg_tviews_create_or_replace"
        ]

    def test_the_name_is_spelled_as_the_author_wrote_it(self):
        """``app.tv_user`` stays qualified; a bare ``tv_user`` is never given ``public.``."""
        change = change_of(
            "", "CREATE TABLE app.tv_user AS SELECT pk_user FROM tb_user;", "ADD_TVIEW"
        )
        generator = DifferSQLGenerator()
        assert self._calls(generator.generate_up(change))[0][1][0] == "app.tv_user"
        assert self._calls(generator.generate_down(change))[0][1][0] == "app.tv_user"

    @pytest.mark.parametrize(
        ("ctas", "options"),
        [
            ("CREATE UNLOGGED TABLE tv_user AS", {"logged": False}),
            ("CREATE TABLE tv_user WITH (fillfactor = 70) AS", {"fillfactor": 70}),
            (
                "CREATE UNLOGGED TABLE tv_user WITH (fillfactor = 90) AS",
                {"fillfactor": 90, "logged": False},
            ),
        ],
        ids=["unlogged", "fillfactor", "both"],
    )
    def test_the_storage_the_tree_pins_is_passed_as_options(self, ctas, options):
        """What the CTAS says is pinned; what it leaves out keeps pg_tviews' current value."""
        import json

        change = change_of("", f"{ctas} SELECT pk_user FROM tb_user;", "ADD_TVIEW")
        ((_, _, named),) = self._calls(DifferSQLGenerator().generate_up(change))
        assert json.loads(named["options"]) == options

    def test_a_query_holding_a_dollar_quote_is_kept_whole(self):
        select = "SELECT pk_user, $tview$x$tview$ AS tag FROM tb_user"
        change = change_of("", f"CREATE TABLE tv_user AS {select};", "ADD_TVIEW")
        ((_, positional, _),) = self._calls(DifferSQLGenerator().generate_up(change))
        assert positional[1] == self._query(select)


TV = "CREATE TABLE tv_user AS SELECT pk_user, name FROM tb_user;\n"
TV_NAME = "CREATE INDEX ix_tv_user_name ON tv_user (name);\n"
TV_UNIQUE = "CREATE UNIQUE INDEX ux_tv_user ON tv_user (pk_user);\n"


class TestTViewIndexes:
    """A TVIEW is created with its indexes, after ``pg_tviews_create_or_replace()``."""

    def test_add_tview_creates_its_indexes_after_it(self):
        change = change_of("", TV + TV_UNIQUE + TV_NAME, "ADD_TVIEW")
        sql = DifferSQLGenerator().generate_up(change)
        assert _kinds(sql) == ["SelectStmt", "IndexStmt", "IndexStmt"]
        indexes = _indexes_of(sql)
        assert [i.idxname for i in indexes] == ["ux_tv_user", "ix_tv_user_name"]
        assert all(i.relation.relname == "tv_user" for i in indexes)
        assert all(not i.concurrent and i.if_not_exists for i in indexes)
        assert _kinds(DifferSQLGenerator().generate_down(change)) == ["SelectStmt"]

    def test_drop_tview_down_recreates_its_indexes(self):
        change = change_of(TV + TV_NAME, "", "DROP_TVIEW")
        assert _kinds(DifferSQLGenerator().generate_up(change)) == ["SelectStmt"]
        sql = DifferSQLGenerator().generate_down(change)
        assert _kinds(sql) == ["SelectStmt", "IndexStmt"]
        assert [i.idxname for i in _indexes_of(sql)] == ["ix_tv_user_name"]

    def test_a_tview_index_change_is_concurrent(self):
        change = change_of(TV, TV + TV_NAME, "ADD_INDEX")
        (index,) = _indexes_of(DifferSQLGenerator().generate_up(change))
        assert (index.idxname, index.concurrent, index.if_not_exists) == (
            "ix_tv_user_name",
            True,
            True,
        )
        (drop,) = _statements(DifferSQLGenerator().generate_down(change))
        assert (type(drop).__name__, drop.concurrent) == ("DropStmt", True)


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

    @pytest.mark.usefixtures("quoted_names_allowed")
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
        if kind == "tview":
            assert sql.startswith("SELECT tviews.pg_tviews_drop(")
        else:
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


#: The kinds a change renders from its statement, each with no statement at all —
#: what a side that is compared and never generated from carries (``stated_side``).
UNSTATED = ["domain", "type", "policy", "trigger", "view", "matview", "function", "aggregate"]


def _unstated(kind: str) -> DDLObject:
    return DDLObject(ref_for(kind, None, "t.x" if kind in {"policy", "trigger"} else "x"), "", "")


def _refused(render, change) -> None:
    with pytest.raises(DifferError) as refused:
        render(change)
    assert refused.value.error_code == "DIFFER_409"


class TestAChangeWithNoStatementIsRefused:
    """A change carrying no statement is refused, in both directions, never half-written."""

    @pytest.mark.parametrize("kind", UNSTATED)
    def test_creating_it(self, kind: str) -> None:
        obj = _unstated(kind)
        _refused(DifferSQLGenerator().generate_up, ObjectAdded(obj.ref, obj))

    @pytest.mark.parametrize("kind", UNSTATED)
    def test_undoing_its_creation(self, kind: str) -> None:
        obj = _unstated(kind)
        _refused(DifferSQLGenerator().generate_down, ObjectAdded(obj.ref, obj))

    @pytest.mark.parametrize("kind", UNSTATED)
    def test_dropping_it(self, kind: str) -> None:
        obj = _unstated(kind)
        _refused(DifferSQLGenerator().generate_up, ObjectDropped(obj.ref, obj))

    @pytest.mark.parametrize("kind", ["view", "matview", "function"])
    @pytest.mark.parametrize("direction", ["generate_up", "generate_down"])
    def test_replacing_it(self, kind: str, direction: str) -> None:
        obj = _unstated(kind)
        _refused(getattr(DifferSQLGenerator(), direction), ObjectReplaced(obj.ref, obj, obj))

    def test_a_tview_is_created_from_its_statement(self) -> None:
        obj = _unstated("tview")
        _refused(DifferSQLGenerator().generate_up, ObjectAdded(obj.ref, obj))

    def test_a_tview_is_dropped_by_name(self) -> None:
        obj = _unstated("tview")
        down = DifferSQLGenerator().generate_down(ObjectAdded(obj.ref, obj))
        assert down is not None and "pg_tviews_drop" in down

    def test_a_kind_whose_redefinition_is_the_authors_renders_nothing(self) -> None:
        obj = _unstated("domain")
        assert DifferSQLGenerator().generate_up(ObjectReplaced(obj.ref, obj, obj)) is None
