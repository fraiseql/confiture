"""Unit tests verifying graceful failure when pglast is not installed.

All SQL AST functions must raise ImportError with a clear install instruction
when pglast is absent from the environment.
"""

import sys
from unittest.mock import patch

import pytest

from confiture.core.introspection import sql_ast


def _block_pglast():
    """Context manager that makes pglast appear uninstalled."""
    return patch.dict(sys.modules, {"pglast": None})


class TestExtractCtesWithoutPglast:
    def test_raises_import_error(self):
        with _block_pglast():
            with pytest.raises(ImportError) as exc_info:
                sql_ast.extract_ctes("WITH foo AS (SELECT 1) SELECT * FROM foo")
        assert "pglast" in str(exc_info.value).lower()

    def test_error_message_contains_install_hint(self):
        with _block_pglast():
            with pytest.raises(ImportError) as exc_info:
                sql_ast.extract_ctes("SELECT 1")
        assert "uv add pglast" in str(exc_info.value)


class TestInferJsonbShapeWithoutPglast:
    def test_raises_import_error(self):
        with _block_pglast():
            with pytest.raises(ImportError) as exc_info:
                sql_ast.infer_jsonb_shape("SELECT jsonb_build_object('key', val)")
        assert "pglast" in str(exc_info.value).lower()

    def test_error_message_contains_install_hint(self):
        with _block_pglast():
            with pytest.raises(ImportError) as exc_info:
                sql_ast.infer_jsonb_shape("")
        assert "uv add pglast" in str(exc_info.value)


class TestParseFunctionBodyWithoutPglast:
    def test_raises_import_error(self):
        with _block_pglast():
            with pytest.raises(ImportError) as exc_info:
                sql_ast.parse_function_body("BEGIN SELECT 1; END;")
        assert "pglast" in str(exc_info.value).lower()

    def test_error_message_contains_install_hint(self):
        with _block_pglast():
            with pytest.raises(ImportError) as exc_info:
                sql_ast.parse_function_body("")
        assert "uv add pglast" in str(exc_info.value)


class TestRequirePglastHelper:
    def test_raises_import_error_when_blocked(self):
        with _block_pglast():
            with pytest.raises(ImportError):
                sql_ast._require_pglast()

    def test_message_is_actionable(self):
        with _block_pglast():
            with pytest.raises(ImportError) as exc_info:
                sql_ast._require_pglast()
        msg = str(exc_info.value)
        assert "pglast" in msg
        assert "uv add pglast" in msg


class TestCTENodeDataclass:
    """Test that CTENode can be constructed without pglast."""

    def test_basic_construction(self):
        node = sql_ast.CTENode(
            name="my_cte",
            query_text="SELECT 1",
            dependencies=[],
        )
        assert node.name == "my_cte"
        assert node.query_text == "SELECT 1"
        assert node.dependencies == []
        assert node.is_recursive is False
        assert node.is_materialized is None
        assert node.is_writable is False

    def test_writable_cte(self):
        node = sql_ast.CTENode(
            name="ins",
            query_text="INSERT INTO foo VALUES (1) RETURNING id",
            dependencies=[],
            is_writable=True,
        )
        assert node.is_writable is True

    def test_recursive_cte(self):
        node = sql_ast.CTENode(
            name="tree",
            query_text="SELECT id, parent_id FROM nodes UNION ALL ...",
            dependencies=[],
            is_recursive=True,
        )
        assert node.is_recursive is True


class TestJSONBKeyDataclass:
    """Test that JSONBKey can be constructed without pglast."""

    def test_basic_construction(self):
        key = sql_ast.JSONBKey(key="user_id", value_expr="u.id")
        assert key.key == "user_id"
        assert key.value_expr == "u.id"
        assert key.inferred_type is None

    def test_with_inferred_type(self):
        key = sql_ast.JSONBKey(key="amount", value_expr="o.total", inferred_type="numeric")
        assert key.inferred_type == "numeric"
