"""Validate INSERT statements using semantic AST analysis.

This module provides InsertValidator for checking if INSERT statements can be
safely converted to COPY format. Uses sqlglot's AST for semantic analysis instead
of fragile regex patterns.
"""

from __future__ import annotations

from sqlglot import exp, parse_one


class InsertValidator:
    """Validate INSERT statements for COPY conversion compatibility.

    Uses sqlglot's AST for semantic analysis instead of regex patterns.
    This is more reliable and handles PostgreSQL edge cases correctly.
    """

    def can_convert_to_copy(self, insert_sql: str) -> tuple[bool, str | None]:
        """Check if INSERT statement can be converted to COPY format.

        Args:
            insert_sql: SQL INSERT statement

        Returns:
            Tuple of (can_convert: bool, reason: str | None)
            - (True, None) if convertible
            - (False, reason) if not convertible
        """
        try:
            ast = parse_one(insert_sql, dialect="postgres")
        except Exception as e:
            return False, f"Parse error: {str(e)}"

        # Must be INSERT statement
        if not isinstance(ast, exp.Insert):
            return False, "Not an INSERT statement"

        # Must be VALUES-based (not SELECT)
        if isinstance(ast.expression, exp.Select):
            return False, "INSERT ... SELECT cannot be converted to COPY"

        if not isinstance(ast.expression, exp.Values):
            return False, "Unknown INSERT expression type"

        # Cannot have ON CONFLICT
        if ast.args.get("conflict"):
            return False, "ON CONFLICT clause not compatible with COPY"

        # Cannot have RETURNING
        if ast.args.get("returning"):
            return False, "RETURNING clause not compatible with COPY"

        # Cannot have any functions in VALUES (NOW(), uuid_generate_v4(), etc.)
        if self._has_functions_in_values(ast.expression):
            return False, "Function calls in VALUES not compatible with COPY"

        # Cannot have subqueries in VALUES
        if self._has_subqueries(ast.expression):
            return False, "Subqueries in VALUES not compatible with COPY"

        # Cannot have CASE expressions
        if ast.find(exp.Case):
            return False, "CASE expressions in VALUES not compatible with COPY"

        # Cannot have arithmetic or string operations
        if self._has_incompatible_operations(ast.expression):
            return False, "Operations in VALUES not compatible with COPY"

        return True, None

    def _has_functions_in_values(self, values_expr: exp.Values) -> bool:
        """Check if VALUES clause contains any function calls.

        Args:
            values_expr: VALUES expression node

        Returns:
            True if any function calls found, False otherwise
        """
        # Find all function calls (Anonymous = user-defined/unknown functions)
        # This catches NOW(), uuid_generate_v4(), etc.
        if values_expr.find(exp.Anonymous):
            return True

        # Also check for built-in functions that can't be literal values
        incompatible_funcs = {
            exp.CurrentDate,
            exp.CurrentTime,
            exp.CurrentTimestamp,
            exp.CurrentUser,
            exp.Extract,
            exp.DateAdd,
            exp.DateDiff,
            exp.Cast,
            exp.TryCast,
            # String functions
            exp.Upper,
            exp.Lower,
            exp.Substring,
            exp.Length,
            exp.Replace,
            exp.Trim,
            # Other functions
            exp.Coalesce,
            exp.Nullif,
            exp.Round,
            exp.Ceil,
            exp.Floor,
            exp.Abs,
        }

        for func_type in incompatible_funcs:
            if values_expr.find(func_type):
                return True

        return False

    def _has_subqueries(self, values_expr: exp.Values) -> bool:
        """Check if VALUES clause contains subqueries.

        Args:
            values_expr: VALUES expression node

        Returns:
            True if any subqueries found, False otherwise
        """
        return bool(values_expr.find(exp.Subquery))

    def _has_incompatible_operations(self, values_expr: exp.Values) -> bool:
        """Check for arithmetic and string operations.

        Args:
            values_expr: VALUES expression node

        Returns:
            True if incompatible operations found, False otherwise
        """
        # String concatenation (||) - sqlglot uses DPipe
        if values_expr.find(exp.DPipe):
            return True

        # Also check for Concat (in case sqlglot changes representation)
        if values_expr.find(exp.Concat):
            return True

        # Arithmetic operations
        arithmetic_types = {
            exp.Add,
            exp.Sub,
            exp.Mul,
            exp.Div,
            exp.Mod,
        }

        for op_type in arithmetic_types:
            if values_expr.find(op_type):
                return True

        return False

    def extract_rows(
        self,
        insert_sql: str,
    ) -> list[list[str | None]] | None:
        """Extract rows from VALUES clause.

        Args:
            insert_sql: SQL INSERT statement

        Returns:
            List of rows (each row is list of values), or None if not VALUES-based
        """
        try:
            ast = parse_one(insert_sql, dialect="postgres")
        except Exception:
            return None

        if not isinstance(ast.expression, exp.Values):
            return None

        rows = []

        for row_expr in ast.expression.expressions:
            if not isinstance(row_expr, exp.Tuple):
                # Single value wrapped in Tuple
                row_expr = exp.Tuple(expressions=[row_expr])

            values = []
            for col_expr in row_expr.expressions:
                value = self._extract_value(col_expr)
                values.append(value)

            rows.append(values)

        return rows

    def _extract_value(self, expr: exp.Expression) -> str | None:
        """Extract value from expression.

        Args:
            expr: Expression node

        Returns:
            Extracted value as string or None
        """
        if isinstance(expr, exp.Null):
            return None

        if isinstance(expr, exp.Literal):
            return expr.this

        if isinstance(expr, exp.Boolean):
            return str(expr).lower()

        # For anything else, return string representation
        return str(expr)

    def extract_table_name(self, insert_sql: str) -> str | None:
        """Extract table name from INSERT statement.

        Args:
            insert_sql: SQL INSERT statement

        Returns:
            Table name (may be schema-qualified), or None if not found
        """
        try:
            ast = parse_one(insert_sql, dialect="postgres")
            if not isinstance(ast, exp.Insert):
                return None

            # ast.this is a Schema, ast.this.this is the Table
            if not hasattr(ast.this, "this"):
                return None

            table = ast.this.this
            if isinstance(table, exp.Table):
                # Use SQL method to get qualified name (handles schema.table)
                return table.sql(dialect="postgres")
            return None
        except Exception:
            return None

    def extract_columns(self, insert_sql: str) -> list[str] | None:
        """Extract column names from INSERT statement.

        Args:
            insert_sql: SQL INSERT statement

        Returns:
            List of column names, or None if not specified
        """
        try:
            ast = parse_one(insert_sql, dialect="postgres")
            if not isinstance(ast, exp.Insert):
                return None

            # Columns are in ast.this.expressions (Schema object)
            # ast.this is a Schema with table and column expressions
            if not hasattr(ast.this, "expressions") or not ast.this.expressions:
                return None

            columns = []
            for col_expr in ast.this.expressions:
                if isinstance(col_expr, exp.Identifier):
                    columns.append(col_expr.this)
                elif hasattr(col_expr, "name"):
                    columns.append(col_expr.name)
                else:
                    columns.append(str(col_expr))

            return columns
        except Exception:
            return None
