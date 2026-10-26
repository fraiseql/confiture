"""A column change a view reads is generated inside a drop and a recreate of the view (#765).

``ALTER COLUMN … TYPE`` and ``DROP COLUMN`` are refused while a view reads the
column. The diff carries the views to drop (``DependentsDropped``) and to create
again from the new tree (``DependentsRecreated``); the generated SQL is read back
with pglast.
"""

import pglast
import pytest

from confiture.core._pglast_enums import member
from confiture.core.change_order import apply_order
from confiture.core.change_set import classify_statements
from confiture.core.change_set.diff_tiers import tier_of
from confiture.core.differ import Side
from confiture.core.differ_sql import DifferSQLGenerator
from confiture.core.risk_tier import RiskTier, worst_tier
from confiture.core.schema_change import (
    DependentsDropped,
    DependentsRecreated,
    ObjectReplaced,
    SchemaChange,
)
from confiture.core.schema_read import read_text
from confiture.core.view_dependents import dependents
from confiture.platform import diff

_TABLE = "CREATE TABLE t (id bigint PRIMARY KEY, a integer, b text);\n"
_RETYPED = _TABLE.replace("a integer", "a bigint")
_DROPPED = "CREATE TABLE t (id bigint PRIMARY KEY, b text);\n"
_AT_ALTER_COLUMN_TYPE = member("AlterTableType", "AT_AlterColumnType")


def _held(sql: str, column: str) -> list[str]:
    side = Side.of(read_text(_TABLE + sql))
    return [ref.name for ref in dependents(side.objects, [(("public", "t"), column)])]


def _rebuilds(old: str, new: str) -> list[SchemaChange]:
    return [
        c for c in diff(old, new).changes if isinstance(c, DependentsDropped | DependentsRecreated)
    ]


def _up(old: str, new: str) -> str:
    renderer = DifferSQLGenerator()
    return "".join(renderer.generate_up(c) or "" for c in apply_order(diff(old, new).changes))


def _statements(sql: str) -> list[str]:
    """Each statement's node and the relation it names, in order."""
    found = []
    for raw in pglast.parse_sql(sql):
        stmt = raw.stmt
        kind = type(stmt).__name__
        if kind == "DropStmt":
            found.extend(f"drop {'.'.join(p.sval for p in o)}" for o in stmt.objects)
        elif kind == "ViewStmt":
            found.append(f"create {stmt.view.relname}")
        elif kind == "CreateTableAsStmt":
            found.append(f"create {stmt.into.rel.relname}")
        elif kind == "AlterTableStmt":
            found.append(f"alter {stmt.relation.relname}")
        else:
            found.append(kind)
    return found


class TestWhichViewsHoldAColumn:
    def test_a_view_naming_the_column(self) -> None:
        assert _held("CREATE VIEW v AS SELECT id, a FROM t;", "a") == ["v"]

    def test_not_a_view_naming_other_columns(self) -> None:
        assert _held("CREATE VIEW v AS SELECT id, b FROM t;", "a") == []

    @pytest.mark.parametrize(
        "query",
        [
            "SELECT * FROM t",
            "SELECT x.* FROM t x",
            "SELECT row_to_json(t) FROM t",
            "SELECT 1 AS one FROM t JOIN t u USING (a)",
            "SELECT t.a + 1 AS n FROM t",
        ],
    )
    def test_a_view_reading_every_column_or_naming_it_after_a_range(self, query: str) -> None:
        assert _held(f"CREATE VIEW v AS {query};", "a") == ["v"]

    def test_views_on_the_view_in_dependency_order(self) -> None:
        sql = (
            "CREATE VIEW v2 AS SELECT id FROM v1;\n"
            "CREATE VIEW v1 AS SELECT id, a FROM t;\n"
            "CREATE MATERIALIZED VIEW m AS SELECT id FROM v2;\n"
            "CREATE VIEW unrelated AS SELECT b FROM t;\n"
        )
        assert _held(sql, "a") == ["v1", "v2", "m"]

    def test_a_tview_reading_a_held_view(self) -> None:
        sql = (
            "CREATE VIEW v AS SELECT id, a FROM t;\n"
            "SELECT pg_tviews_create_or_replace('tv_t', $$SELECT id FROM v$$);\n"
        )
        assert _held(sql, "a") == ["v", "tv_t"]

    def test_a_relation_of_the_same_name_in_another_schema_holds_nothing(self) -> None:
        assert _held("CREATE VIEW v AS SELECT id, a FROM other.t;", "a") == []


class TestTheDiff:
    VIEW = "CREATE VIEW v AS SELECT id, a FROM t;\n"

    def test_a_retype_under_a_view_drops_and_recreates_it(self) -> None:
        dropped, recreated = _rebuilds(_TABLE + self.VIEW, _RETYPED + self.VIEW)

        assert [d.ref.name for d in dropped.dependents] == ["v"]
        assert [d.ref.name for d in recreated.dependents] == ["v"]

    def test_a_change_no_view_reads_carries_no_rebuild(self) -> None:
        view = "CREATE VIEW v AS SELECT id, b FROM t;\n"
        assert _rebuilds(_TABLE + view, _RETYPED + view) == []

    def test_the_recreate_is_the_new_definition(self) -> None:
        new = _DROPPED + "CREATE VIEW v AS SELECT id, b FROM t;\n"
        _, recreated = _rebuilds(_TABLE + self.VIEW, new)

        assert "b FROM t" in recreated.dependents[0].obj.create_sql

    def test_the_diff_keeps_the_redefinition_drift_reads(self) -> None:
        new = _DROPPED + "CREATE VIEW v AS SELECT id, b FROM t;\n"
        changes = diff(_TABLE + self.VIEW, new).changes

        assert any(isinstance(c, ObjectReplaced) for c in changes)
        assert not any(isinstance(c, ObjectReplaced) for c in apply_order(changes))

    def test_a_view_only_the_old_tree_defines_is_dropped_by_its_own_change(self) -> None:
        old = _TABLE + self.VIEW + "CREATE VIEW gone AS SELECT id FROM v;\n"
        dropped, _ = _rebuilds(old, _RETYPED + self.VIEW)

        assert [d.ref.name for d in dropped.dependents] == ["v"]
        sql = _up(old, _RETYPED + self.VIEW)
        assert _statements(sql) == ["drop gone", "drop v", "alter t", "create v"]

    def test_grants_comments_and_owner_are_written_again(self) -> None:
        extra = (
            "GRANT SELECT ON v TO PUBLIC;\nCOMMENT ON VIEW v IS 'x';\n"
            "ALTER VIEW v OWNER TO CURRENT_USER;\nGRANT SELECT ON t TO PUBLIC;\n"
        )
        _, recreated = _rebuilds(_TABLE + self.VIEW + extra, _RETYPED + self.VIEW + extra)

        assert recreated.dependents[0].attached == (
            "GRANT SELECT ON v TO PUBLIC;\n",
            "COMMENT ON VIEW v IS 'x';\n",
            "ALTER VIEW v OWNER TO CURRENT_USER;\n",
        )

    def test_a_matview_carries_its_indexes(self) -> None:
        mv = "CREATE MATERIALIZED VIEW m AS SELECT id, a FROM t;\nCREATE INDEX m_id ON m (id);\n"
        _, recreated = _rebuilds(_TABLE + mv, _RETYPED + mv)

        assert [i.name for i in recreated.dependents[0].indexes] == ["m_id"]


class TestTheGeneratedSQL:
    OLD = _TABLE + "CREATE VIEW v1 AS SELECT id, a FROM t;\nCREATE VIEW v2 AS SELECT id FROM v1;\n"

    def test_readers_are_dropped_first_and_created_last(self) -> None:
        sql = _up(self.OLD, self.OLD.replace("a integer", "a bigint"))

        assert _statements(sql) == ["drop v2", "drop v1", "alter t", "create v1", "create v2"]
        (alter,) = [
            r.stmt for r in pglast.parse_sql(sql) if type(r.stmt).__name__ == "AlterTableStmt"
        ]
        assert int(alter.cmds[0].subtype) == _AT_ALTER_COLUMN_TYPE

    def test_the_down_mirrors_it_with_the_old_definitions(self) -> None:
        new = (
            _DROPPED + "CREATE VIEW v1 AS SELECT id FROM t;\nCREATE VIEW v2 AS SELECT id FROM v1;\n"
        )
        renderer = DifferSQLGenerator()
        down = "".join(
            renderer.generate_down(c) or ""
            for c in reversed(apply_order(diff(self.OLD, new).changes))
        )

        assert _statements(down) == ["drop v2", "drop v1", "alter t", "create v1", "create v2"]
        assert "SELECT id, a FROM t" in down

    def test_a_new_view_reading_a_recreated_one_comes_after_it(self) -> None:
        new = self.OLD.replace("a integer", "a bigint") + "CREATE VIEW v3 AS SELECT id FROM v2;\n"
        assert _statements(_up(self.OLD, new))[-1] == "create v3"


class TestARecreatedViewReadingAnAddedOne:
    """A view the rebuild creates again may read a view only the new tree defines (#787)."""

    OLD = _TABLE + "CREATE VIEW v1 AS SELECT id, a FROM t;\nCREATE VIEW v2 AS SELECT id FROM v1;\n"
    NEW = _RETYPED + (
        "CREATE VIEW v_new AS SELECT id, a FROM t;\n"
        "CREATE VIEW v1 AS SELECT n.id, n.a FROM v_new n;\n"
        "CREATE VIEW v2 AS SELECT id FROM v1;\n"
        "CREATE VIEW v3 AS SELECT id FROM v2;\n"
    )

    def test_the_added_view_is_created_before_the_one_reading_it(self) -> None:
        assert _statements(_up(self.OLD, self.NEW)) == [
            "drop v2",
            "drop v1",
            "alter t",
            "create v_new",
            "create v1",
            "create v2",
            "create v3",
        ]

    def test_the_down_drops_it_after_the_one_reading_it(self) -> None:
        renderer = DifferSQLGenerator()
        down = "".join(
            renderer.generate_down(c) or ""
            for c in reversed(apply_order(diff(self.OLD, self.NEW).changes))
        )

        assert _statements(down)[:4] == ["drop v3", "drop v2", "drop v1", "drop v_new"]

    def test_an_added_view_between_two_recreated_ones_splits_the_recreate(self) -> None:
        new = _RETYPED + (
            "CREATE VIEW v1 AS SELECT id, a FROM t;\n"
            "CREATE VIEW v_mid AS SELECT id FROM v1;\n"
            "CREATE VIEW v2 AS SELECT id FROM v_mid;\n"
        )
        assert _statements(_up(self.OLD, new))[-3:] == ["create v1", "create v_mid", "create v2"]

    def test_without_a_rebuild_added_views_keep_their_place(self) -> None:
        old = _TABLE + "CREATE VIEW v1 AS SELECT id FROM t;\n"
        new = old + "CREATE VIEW v0 AS SELECT id FROM v1;\n"
        assert _statements(_up(old, new)) == ["create v0"]


class TestWhatTheDropTakes:
    """The rebuild writes again what the drop takes, then what the new side writes (#787)."""

    VIEW = "CREATE VIEW v AS SELECT id, a FROM t;\n"

    def test_a_grant_only_the_old_side_writes_is_kept(self) -> None:
        grant = "GRANT SELECT ON v TO PUBLIC;\n"
        _, recreated = _rebuilds(_TABLE + self.VIEW + grant, _RETYPED + self.VIEW)

        assert recreated.dependents[0].attached == (grant,)

    def test_a_statement_both_sides_write_is_written_once(self) -> None:
        grant = "GRANT SELECT ON v TO PUBLIC;\n"
        comment = "COMMENT ON VIEW v IS 'new';\n"
        dropped, recreated = _rebuilds(
            _TABLE + self.VIEW + grant, _RETYPED + self.VIEW + grant + comment
        )

        assert recreated.dependents[0].attached == (grant, comment)
        assert dropped.dependents[0].attached == (grant, comment)


class TestTheTier:
    VIEW = "CREATE VIEW v AS SELECT id, a FROM t;\n"
    MATVIEW = "CREATE MATERIALIZED VIEW m AS SELECT id, a FROM t;\n"

    def test_a_plain_view_rebuilt_is_a_replacement(self) -> None:
        assert {tier_of(c) for c in _rebuilds(_TABLE + self.VIEW, _RETYPED + self.VIEW)} == {
            RiskTier.REVERSIBLE
        }

    def test_a_materialized_view_rebuilt_is_a_lock_risk(self) -> None:
        assert {tier_of(c) for c in _rebuilds(_TABLE + self.MATVIEW, _RETYPED + self.MATVIEW)} == {
            RiskTier.LOCK_RISKY
        }

    def test_the_file_classifies_the_rebuild_as_the_diff_tiers_it(self) -> None:
        """Read whole, as preflight reads it: the drop is paired with the recreate below it."""
        sql = _up(_TABLE + self.MATVIEW, _RETYPED + self.MATVIEW)
        entries = [e for e in classify_statements(sql) if "materialized_view" in e.kind]

        assert {e.tier for e in entries} <= {RiskTier.LOCK_RISKY, RiskTier.ADDITIVE}
        assert worst_tier(e.tier for e in entries) is RiskTier.LOCK_RISKY


class TestADropCreatedAgainInOneFile:
    """The change set reads a view dropped and created again as the replacement it is."""

    def _drop_tier(self, sql: str) -> RiskTier | None:
        return classify_statements(sql)[0].tier

    @pytest.mark.parametrize(
        ("sql", "tier"),
        [
            ("DROP VIEW v;\nCREATE VIEW v AS SELECT 1;", RiskTier.REVERSIBLE),
            (
                "DROP MATERIALIZED VIEW m;\nCREATE MATERIALIZED VIEW m AS SELECT 1;",
                RiskTier.LOCK_RISKY,
            ),
            (
                "SELECT pg_tviews_drop('tv_t');\n"
                "SELECT pg_tviews_create_or_replace('tv_t', $$SELECT 1$$);",
                RiskTier.LOCK_RISKY,
            ),
        ],
    )
    def test_its_drop_is_the_replacement(self, sql: str, tier: RiskTier) -> None:
        assert self._drop_tier(sql) is tier

    @pytest.mark.parametrize(
        "sql",
        [
            "DROP VIEW v;",
            "DROP VIEW v;\nCREATE VIEW public.v AS SELECT 1;",
            "DROP VIEW v CASCADE;\nCREATE VIEW v AS SELECT 1;",
            "DROP VIEW v;\nCREATE MATERIALIZED VIEW v AS SELECT 1;",
            "CREATE VIEW v AS SELECT 1;\nDROP VIEW v;",
        ],
    )
    def test_anything_else_is_still_destructive(self, sql: str) -> None:
        tiers = [e.tier for e in classify_statements(sql) if e.kind == "drop_view"]
        assert tiers == [RiskTier.DESTRUCTIVE]
