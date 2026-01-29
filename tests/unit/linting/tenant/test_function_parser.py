"""Tests for function parsing for INSERT extraction."""

from confiture.core.linting.tenant.function_parser import FunctionParser


class TestExtractFunctionName:
    """Tests for extracting function name from CREATE FUNCTION."""

    def test_extract_function_name_simple(self):
        """Extract function name from simple CREATE FUNCTION."""
        sql = "CREATE FUNCTION fn_create_item(p_name TEXT) RETURNS BIGINT AS $$ BEGIN END; $$ LANGUAGE plpgsql;"

        parser = FunctionParser()
        name = parser.extract_function_name(sql)

        assert name == "fn_create_item"

    def test_extract_function_name_or_replace(self):
        """Extract function name from CREATE OR REPLACE FUNCTION."""
        sql = "CREATE OR REPLACE FUNCTION fn_update_item() RETURNS VOID AS $$ BEGIN END; $$ LANGUAGE plpgsql;"

        parser = FunctionParser()
        name = parser.extract_function_name(sql)

        assert name == "fn_update_item"

    def test_extract_function_name_schema_qualified(self):
        """Extract schema-qualified function name."""
        sql = "CREATE FUNCTION myschema.fn_create_item(p_name TEXT) RETURNS BIGINT AS $$ BEGIN END; $$"

        parser = FunctionParser()
        name = parser.extract_function_name(sql)

        assert name == "myschema.fn_create_item"

    def test_extract_function_name_returns_none_for_non_function(self):
        """Return None for non-function SQL."""
        sql = "CREATE TABLE tb_item (id INT);"

        parser = FunctionParser()
        name = parser.extract_function_name(sql)

        assert name is None


class TestExtractFunctionBody:
    """Tests for extracting function body from CREATE FUNCTION."""

    def test_extract_function_body_dollar_quote(self):
        """Extract body from $$ quoted function."""
        sql = """
        CREATE FUNCTION fn_test() RETURNS VOID AS $$
        BEGIN
            INSERT INTO tb_item (id) VALUES (1);
        END;
        $$ LANGUAGE plpgsql;
        """

        parser = FunctionParser()
        body = parser.extract_function_body(sql)

        assert body is not None
        assert "INSERT INTO tb_item" in body
        assert "BEGIN" in body

    def test_extract_function_body_tagged_dollar_quote(self):
        """Extract body from $tag$ quoted function."""
        sql = """
        CREATE FUNCTION fn_test() RETURNS VOID AS $fn$
        BEGIN
            INSERT INTO tb_item (id) VALUES (1);
        END;
        $fn$ LANGUAGE plpgsql;
        """

        parser = FunctionParser()
        body = parser.extract_function_body(sql)

        assert body is not None
        assert "INSERT INTO tb_item" in body

    def test_extract_function_body_single_quote(self):
        """Extract body from single-quoted SQL function."""
        sql = """
        CREATE FUNCTION fn_add(a INT, b INT) RETURNS INT AS '
            SELECT a + b;
        ' LANGUAGE sql;
        """

        parser = FunctionParser()
        body = parser.extract_function_body(sql)

        assert body is not None
        assert "SELECT a + b" in body

    def test_extract_function_body_returns_none_for_no_body(self):
        """Return None if no function body found."""
        sql = "CREATE TABLE tb_item (id INT);"

        parser = FunctionParser()
        body = parser.extract_function_body(sql)

        assert body is None


class TestExtractInsertStatements:
    """Tests for extracting INSERT statements from function body."""

    def test_extract_single_insert(self):
        """Extract single INSERT from function body."""
        body = """
        BEGIN
            INSERT INTO tb_item (id, name, fk_org)
            VALUES (nextval('seq'), p_name, p_org_id);
        END;
        """

        parser = FunctionParser()
        inserts = parser.extract_insert_statements(body)

        assert len(inserts) == 1
        assert inserts[0].table_name == "tb_item"
        assert inserts[0].columns == ["id", "name", "fk_org"]

    def test_extract_multiple_inserts(self):
        """Extract multiple INSERTs from function body."""
        body = """
        BEGIN
            INSERT INTO tb_item (id, name) VALUES (1, 'test');
            INSERT INTO tb_audit_log (action) VALUES ('created');
        END;
        """

        parser = FunctionParser()
        inserts = parser.extract_insert_statements(body)

        assert len(inserts) == 2
        assert inserts[0].table_name == "tb_item"
        assert inserts[1].table_name == "tb_audit_log"

    def test_extract_insert_with_returning(self):
        """Handle INSERT with RETURNING clause."""
        body = """
        INSERT INTO tb_item (id, name)
        VALUES (1, 'test')
        RETURNING id INTO v_id;
        """

        parser = FunctionParser()
        inserts = parser.extract_insert_statements(body)

        assert len(inserts) == 1
        assert inserts[0].columns == ["id", "name"]

    def test_extract_insert_without_column_list(self):
        """Handle INSERT without explicit column list."""
        body = """
        INSERT INTO tb_item VALUES (1, 'test', 123);
        """

        parser = FunctionParser()
        inserts = parser.extract_insert_statements(body)

        assert len(inserts) == 1
        assert inserts[0].columns is None  # Unknown columns

    def test_extract_insert_schema_qualified_table(self):
        """Handle INSERT with schema-qualified table name."""
        body = """
        INSERT INTO myschema.tb_item (id, name) VALUES (1, 'test');
        """

        parser = FunctionParser()
        inserts = parser.extract_insert_statements(body)

        assert len(inserts) == 1
        assert inserts[0].table_name == "myschema.tb_item"

    def test_extract_insert_with_select(self):
        """Handle INSERT ... SELECT."""
        body = """
        INSERT INTO tb_item_archive (id, name)
        SELECT id, name FROM tb_item WHERE archived = true;
        """

        parser = FunctionParser()
        inserts = parser.extract_insert_statements(body)

        assert len(inserts) == 1
        assert inserts[0].table_name == "tb_item_archive"
        assert inserts[0].columns == ["id", "name"]

    def test_extract_insert_default_values(self):
        """Handle INSERT with DEFAULT VALUES."""
        body = """
        INSERT INTO tb_config DEFAULT VALUES;
        """

        parser = FunctionParser()
        inserts = parser.extract_insert_statements(body)

        assert len(inserts) == 1
        assert inserts[0].table_name == "tb_config"
        assert inserts[0].columns is None

    def test_extract_insert_line_number(self):
        """Track line number of INSERT statement."""
        body = """
        -- Line 1
        -- Line 2
        BEGIN
            INSERT INTO tb_item (id) VALUES (1);
        END;
        """

        parser = FunctionParser()
        inserts = parser.extract_insert_statements(body)

        assert len(inserts) == 1
        # INSERT is on line 5 (counting from 1)
        assert inserts[0].line_number == 5

    def test_extract_insert_preserves_raw_sql(self):
        """INSERT statement includes raw SQL."""
        body = """
        INSERT INTO tb_item (id, name) VALUES (1, 'test');
        """

        parser = FunctionParser()
        inserts = parser.extract_insert_statements(body)

        assert len(inserts) == 1
        assert "INSERT INTO tb_item" in inserts[0].raw_sql

    def test_no_inserts_returns_empty_list(self):
        """Return empty list if no INSERT statements."""
        body = """
        BEGIN
            UPDATE tb_item SET name = 'updated';
        END;
        """

        parser = FunctionParser()
        inserts = parser.extract_insert_statements(body)

        assert inserts == []


class TestExtractFunctions:
    """Tests for extracting multiple functions from SQL."""

    def test_extract_single_function(self):
        """Extract single function from SQL."""
        sql = """
        CREATE FUNCTION fn_create_item() RETURNS VOID AS $$
        BEGIN
            INSERT INTO tb_item (id) VALUES (1);
        END;
        $$ LANGUAGE plpgsql;
        """

        parser = FunctionParser()
        functions = parser.extract_functions(sql)

        assert len(functions) == 1
        assert functions[0].name == "fn_create_item"

    def test_extract_multiple_functions(self):
        """Extract multiple functions from SQL."""
        sql = """
        CREATE FUNCTION fn_create_item() RETURNS VOID AS $$
        BEGIN
            INSERT INTO tb_item (id) VALUES (1);
        END;
        $$ LANGUAGE plpgsql;

        CREATE FUNCTION fn_update_item() RETURNS VOID AS $$
        BEGIN
            UPDATE tb_item SET name = 'test';
        END;
        $$ LANGUAGE plpgsql;
        """

        parser = FunctionParser()
        functions = parser.extract_functions(sql)

        assert len(functions) == 2
        names = {f.name for f in functions}
        assert names == {"fn_create_item", "fn_update_item"}

    def test_extract_function_with_inserts(self):
        """Extracted function includes its INSERT statements."""
        sql = """
        CREATE FUNCTION fn_create_item() RETURNS VOID AS $$
        BEGIN
            INSERT INTO tb_item (id, name) VALUES (1, 'test');
        END;
        $$ LANGUAGE plpgsql;
        """

        parser = FunctionParser()
        functions = parser.extract_functions(sql)

        assert len(functions) == 1
        assert len(functions[0].inserts) == 1
        assert functions[0].inserts[0].table_name == "tb_item"
