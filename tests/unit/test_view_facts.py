"""What a view outputs and what it reads, answered from the model (#812)."""

import pytest

from confiture.core.schema_model import (
    FunctionRead,
    ObjectRef,
    SchemaModel,
    TView,
    View,
    ref_for,
)
from confiture.platform import NotInModelError, SchemaError, parse_schema, view_columns, view_reads

TABLES = """
CREATE TABLE tb_a (id bigint PRIMARY KEY, tenant_id uuid, label text);
CREATE TABLE tb_b (id bigint, a_id bigint, note text);
"""


def _model(sql: str) -> SchemaModel:
    return parse_schema(TABLES + sql)


def _columns(select: str) -> tuple[str, ...]:
    return view_columns(_model(f"CREATE VIEW v AS {select};"), "v")


class TestViewColumns:
    def test_named_targets_in_order(self) -> None:
        assert _columns("SELECT label, id AS pk FROM tb_a") == ("label", "pk")

    def test_star_is_the_table_s_columns(self) -> None:
        assert _columns("SELECT * FROM tb_a") == ("id", "tenant_id", "label")

    def test_qualified_star_is_that_range_s_columns(self) -> None:
        assert _columns("SELECT b.*, a.label FROM tb_a a JOIN tb_b b ON b.a_id = a.id") == (
            "id",
            "a_id",
            "note",
            "label",
        )

    def test_using_puts_the_merged_column_first(self) -> None:
        assert _columns("SELECT * FROM tb_a JOIN tb_b USING (id)") == (
            "id",
            "tenant_id",
            "label",
            "a_id",
            "note",
        )

    def test_a_set_operation_is_named_by_its_first_branch(self) -> None:
        assert _columns("SELECT id AS k FROM tb_a UNION SELECT a_id FROM tb_b") == ("k",)

    def test_a_cte_and_a_subquery_are_expanded(self) -> None:
        select = "WITH c (x, y) AS (SELECT id, label FROM tb_a) SELECT * FROM c, (SELECT 1) s(z)"
        assert _columns(select) == ("x", "y", "z")

    def test_values_columns(self) -> None:
        assert _columns("SELECT * FROM (VALUES (1, 2)) v") == ("column1", "column2")

    def test_through_another_view(self) -> None:
        model = _model(
            "CREATE VIEW v_inner AS SELECT id, label FROM tb_a;"
            "CREATE VIEW v_outer AS SELECT i.*, 1 AS one FROM v_inner i;"
        )
        assert view_columns(model, "v_outer") == ("id", "label", "one")

    def test_a_view_s_column_list_renames_its_outputs(self) -> None:
        model = _model("CREATE VIEW v (x, y) AS SELECT id, label FROM tb_a;")
        assert view_columns(model, "v") == ("x", "y")

    def test_a_column_list_over_a_star(self) -> None:
        model = _model("CREATE VIEW v (x) AS SELECT * FROM tb_a;")
        assert view_columns(model, "v") == ("x", "tenant_id", "label")

    def test_a_matview_s_column_list(self) -> None:
        model = _model("CREATE MATERIALIZED VIEW mv (k) AS SELECT id, label FROM tb_a;")
        assert view_columns(model, "mv") == ("k", "label")

    def test_a_tview(self) -> None:
        model = _model("CREATE TABLE tv_a AS SELECT id AS pk_a, tenant_id, label FROM tb_a;")
        assert view_columns(model, "tv_a") == ("pk_a", "tenant_id", "label")

    def test_by_reference_and_qualified_name(self) -> None:
        model = _model("CREATE VIEW v AS SELECT id FROM tb_a;")
        (ref,) = model.views
        assert view_columns(model, ref) == view_columns(model, "public.v") == ("id",)


class TestUnnamedExpressions:
    """PostgreSQL's ``FigureColname``: the name an unaliased expression is given."""

    @pytest.mark.parametrize(
        ("expression", "name"),
        [
            ("1", "?column?"),
            ("id + 1", "?column?"),
            ("count(*)", "count"),
            ("public.lower(label)", "lower"),
            ("id::int", "id"),
            ("'x'::text", "text"),
            ("CASE WHEN id > 0 THEN 1 END", "case"),
            ("CASE WHEN id > 0 THEN 1 ELSE id END", "id"),
            ("CASE WHEN id > 0 THEN 1 END::int", "int4"),
            ("ARRAY[1, 2]", "array"),
            ("ROW(1, 2)", "row"),
            ("ARRAY[1]::bigint[]", "array"),
            ("coalesce(label, '')", "coalesce"),
            ("greatest(id, 1)", "greatest"),
            ("least(id, 1)", "least"),
            ("nullif(id, 1)", "nullif"),
            ("EXISTS (SELECT 1 FROM tb_b)", "exists"),
            ("ARRAY(SELECT id FROM tb_b)", "array"),
            ("(SELECT max(id) FROM tb_b)", "max"),
            ("(SELECT * FROM (SELECT note FROM tb_b) s LIMIT 1)", "note"),
            ("id IN (SELECT a_id FROM tb_b)", "?column?"),
            ("current_date", "current_date"),
            ("current_timestamp(0)", "current_timestamp"),
            ("current_user", "current_user"),
            ('label COLLATE "C"', "label"),
            ("(ROW(1, 2)).f1", "f1"),
            ("label IS NULL", "?column?"),
            ("xmlelement(name x)", "xmlelement"),
            ("json_object('a': 1)", "json_object"),
            ("json_value('{}', '$.a')", "json_value"),
        ],
    )
    def test_named_as_postgresql_names_it(self, expression: str, name: str) -> None:
        assert _columns(f"SELECT {expression} FROM tb_a") == (name,)


class TestViewColumnsRefuses:
    def test_a_name_that_is_no_view(self) -> None:
        with pytest.raises(NotInModelError, match="tb_a"):
            view_columns(_model(""), "tb_a")

    def test_a_table_s_reference(self) -> None:
        model = _model("")
        (ref, _) = model.tables
        with pytest.raises(NotInModelError):
            view_columns(model, ref)

    def test_a_star_over_a_relation_the_model_lacks(self) -> None:
        with pytest.raises(SchemaError, match=r"v\b.*elsewhere"):
            _columns("SELECT * FROM elsewhere")

    def test_a_star_over_a_function(self) -> None:
        with pytest.raises(SchemaError, match="function"):
            _columns("SELECT * FROM generate_series(1, 3)")

    def test_a_definition_the_parser_rejects(self) -> None:
        ref = ref_for("view", "public", "v")
        model = SchemaModel(views={ref: View(name="v", schema="public", definition="SELEC 1")})
        with pytest.raises(SchemaError, match="v"):
            view_columns(model, ref)

    def test_a_view_with_no_definition(self) -> None:
        ref = ref_for("view", "public", "v")
        model = SchemaModel(views={ref: View(name="v", schema="public")})
        with pytest.raises(SchemaError, match="no definition"):
            view_columns(model, ref)


def _names(refs: frozenset[ObjectRef]) -> set[tuple[str, str, str]]:
    return {(ref.kind, ref.schema or "", ref.name) for ref in refs}


class TestViewReads:
    def test_the_tables_it_reads(self) -> None:
        model = _model("CREATE VIEW v AS SELECT a.id FROM tb_a a JOIN tb_b b ON b.a_id = a.id;")
        assert _names(view_reads(model, "v")) == {
            ("table", "public", "tb_a"),
            ("table", "public", "tb_b"),
        }

    def test_through_views_matviews_and_tviews(self) -> None:
        model = _model(
            "CREATE VIEW v_a AS SELECT * FROM tb_a;"
            "CREATE MATERIALIZED VIEW mv_b AS SELECT * FROM tb_b;"
            "CREATE TABLE tv_a AS SELECT id AS pk_a FROM v_a;"
            "CREATE VIEW v AS SELECT * FROM tv_a, mv_b;"
        )
        assert _names(view_reads(model, "v")) == {
            ("tview", "public", "tv_a"),
            ("view", "public", "v_a"),
            ("table", "public", "tb_a"),
            ("matview", "public", "mv_b"),
            ("table", "public", "tb_b"),
        }

    def test_a_sub_select_anywhere_is_read(self) -> None:
        model = _model(
            "CREATE VIEW v AS SELECT id, EXISTS (SELECT 1 FROM tb_b WHERE a_id = id) FROM tb_a;"
        )
        assert ("table", "public", "tb_b") in _names(view_reads(model, "v"))

    def test_a_cte_is_no_relation(self) -> None:
        model = _model("CREATE VIEW v AS WITH c AS (SELECT * FROM tb_a) SELECT * FROM c;")
        assert _names(view_reads(model, "v")) == {("table", "public", "tb_a")}

    def test_a_schema_qualified_relation(self) -> None:
        model = parse_schema(
            "CREATE SCHEMA app; CREATE TABLE app.tb_x (id int);"
            "CREATE VIEW app.v AS SELECT id FROM app.tb_x;"
        )
        assert _names(view_reads(model, "app.v")) == {("table", "app", "tb_x")}

    def test_a_relation_the_model_lacks_is_returned_not_dropped(self) -> None:
        model = _model("CREATE VIEW v AS SELECT * FROM tb_a, other.thing;")
        assert _names(view_reads(model, "v")) == {
            ("table", "public", "tb_a"),
            ("relation", "other", "thing"),
        }

    def test_a_tview_s_function_reads(self) -> None:
        ref = ref_for("tview", "public", "tv_a")
        tables = parse_schema(TABLES).tables
        tview = TView(
            name="tv_a",
            schema="public",
            definition="SELECT id AS pk_a, public.label_of(id) FROM tb_a",
            function_reads=(FunctionRead("public.label_of(bigint)", ("public.tb_b",)),),
        )
        model = SchemaModel(tables=tables, tviews={ref: tview})
        assert _names(view_reads(model, ref)) == {
            ("table", "public", "tb_a"),
            ("table", "public", "tb_b"),
        }

    def test_a_name_that_is_no_view(self) -> None:
        with pytest.raises(NotInModelError):
            view_reads(_model(""), "tb_a")

    def test_a_definition_the_parser_rejects(self) -> None:
        ref = ref_for("view", "public", "v")
        model = SchemaModel(views={ref: View(name="v", schema="public", definition="SELEC 1")})
        with pytest.raises(SchemaError, match="v"):
            view_reads(model, ref)
