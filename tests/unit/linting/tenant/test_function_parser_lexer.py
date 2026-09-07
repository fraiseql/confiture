"""The tenant function parser reads functions through pglast and bodies through the scanner.

Five regexes used to find ``CREATE FUNCTION``, its dollar-quoted body and the
``INSERT INTO`` statements inside it. A regex cannot tell a comment from code:
a commented-out function was a function, an ``INSERT`` in a ``RAISE NOTICE``
literal was an insert, an ``EXECUTE 'INSERT …'`` was a static one, and a
``LANGUAGE sql BEGIN ATOMIC`` body — no dollar quotes — was not a body at all.
"""

from __future__ import annotations

from confiture.core.linting.schema_linter import LintReport
from confiture.core.linting.tenant.function_parser import FunctionParser
from confiture.core.linting.tenant.tenant_isolation_rule import TenantIsolationRule


class TestFunctionEnvelope:
    def test_a_commented_out_function_is_not_a_function(self) -> None:
        sql = (
            "-- CREATE FUNCTION fn_old() RETURNS void AS $$\n"
            "-- BEGIN\n"
            "--     INSERT INTO tb_old (id) VALUES (1);\n"
            "-- END;\n"
            "-- $$ LANGUAGE plpgsql;\n"
            "CREATE FUNCTION fn_new() RETURNS void AS $$\n"
            "BEGIN\n"
            "    INSERT INTO tb_new (id) VALUES (1);\n"
            "END;\n"
            "$$ LANGUAGE plpgsql;\n"
        )

        functions = FunctionParser().extract_functions(sql)

        assert [f.name for f in functions] == ["fn_new"]
        assert [i.table_name for i in functions[0].inserts] == ["tb_new"]

    def test_a_begin_atomic_body_is_read(self) -> None:
        sql = (
            "CREATE FUNCTION fn_atomic() RETURNS void LANGUAGE sql BEGIN ATOMIC\n"
            "    INSERT INTO tb_item (id, name) VALUES (1, 'x');\n"
            "END;\n"
        )

        functions = FunctionParser().extract_functions(sql)

        assert len(functions) == 1
        assert functions[0].name == "fn_atomic"
        assert [(i.table_name, i.columns) for i in functions[0].inserts] == [
            ("tb_item", ["id", "name"])
        ]

    def test_raw_sql_is_the_statement_text(self) -> None:
        sql = (
            "-- header\n"
            "CREATE FUNCTION fn_a() RETURNS void AS $$ BEGIN NULL; END; $$ LANGUAGE plpgsql;\n"
            "CREATE FUNCTION fn_b() RETURNS void AS $$ BEGIN NULL; END; $$ LANGUAGE plpgsql;\n"
        )

        functions = FunctionParser().extract_functions(sql)

        assert [f.name for f in functions] == ["fn_a", "fn_b"]
        assert functions[0].raw_sql.startswith("CREATE FUNCTION fn_a()")
        assert "fn_b" not in functions[0].raw_sql


class TestInsertsInsideTheBody:
    def test_insert_in_a_comment_or_literal_is_not_an_insert(self) -> None:
        body = (
            "BEGIN\n"
            "    -- INSERT INTO tb_old (id) VALUES (1);\n"
            "    RAISE NOTICE 'INSERT INTO tb_log (x) VALUES (1)';\n"
            "    /* INSERT INTO tb_block (id) VALUES (1); */\n"
            "    INSERT INTO tb_real (id) VALUES (1);\n"
            "END;\n"
        )

        inserts = FunctionParser().extract_insert_statements(body)

        assert [(i.table_name, i.line_number) for i in inserts] == [("tb_real", 5)]

    def test_execute_literal_is_a_dynamic_insert(self) -> None:
        body = (
            "BEGIN\n"
            "    EXECUTE 'INSERT INTO tb_dyn (id, name) VALUES (1, ''x'')';\n"
            "    INSERT INTO tb_static (id) VALUES (1);\n"
            "END;\n"
        )

        inserts = FunctionParser().extract_insert_statements(body)

        assert [(i.table_name, i.columns, i.is_dynamic, i.line_number) for i in inserts] == [
            ("tb_dyn", ["id", "name"], True, 2),
            ("tb_static", ["id"], False, 3),
        ]

    def test_quoted_identifiers_keep_their_spelling(self) -> None:
        body = 'INSERT INTO "Tenant"."Tb Item" ("Id", name) VALUES (1, 2);'

        inserts = FunctionParser().extract_insert_statements(body)

        assert [(i.table_name, i.columns) for i in inserts] == [("Tenant.Tb Item", ["Id", "name"])]

    def test_a_keyword_used_as_a_table_name(self) -> None:
        inserts = FunctionParser().extract_insert_statements("INSERT INTO type (name) VALUES (1);")

        assert [(i.table_name, i.columns) for i in inserts] == [("type", ["name"])]


class TestRuleOnUnparseableSql:
    def test_unparseable_function_sql_is_reported_not_skipped(self) -> None:
        report = LintReport()

        TenantIsolationRule().run(
            view_sqls=[], function_sqls=["CREATE FUNCTION ("], report=report, file_path="f.sql"
        )

        assert [v.rule_id for v in report.info] == ["UNPARSEABLE"]
        assert report.info[0].file_path == "f.sql"
        assert report.errors == [] and report.warnings == []
