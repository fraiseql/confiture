"""Function parsing for INSERT extraction.

This module provides tools to parse PostgreSQL function definitions
and extract INSERT statements for tenant isolation analysis.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class InsertStatement:
    """Represents a parsed INSERT statement.

    Attributes:
        table_name: Target table of the INSERT
        columns: List of column names, or None if not specified
        line_number: Line number within the function body
        raw_sql: The raw INSERT SQL fragment
        is_dynamic: True if INSERT is in dynamic SQL (EXECUTE)
    """

    table_name: str
    columns: list[str] | None
    line_number: int
    raw_sql: str
    is_dynamic: bool = False


@dataclass
class FunctionInfo:
    """Information about a parsed function.

    Attributes:
        name: Function name (may be schema-qualified)
        body: The function body text
        inserts: List of INSERT statements found in the function
        raw_sql: The complete CREATE FUNCTION SQL
    """

    name: str
    body: str
    inserts: list[InsertStatement] = field(default_factory=list)
    raw_sql: str = ""


class FunctionParser:
    """Parses PostgreSQL function definitions.

    Extracts function names, bodies, and INSERT statements for
    tenant isolation analysis.

    Example:
        >>> parser = FunctionParser()
        >>> sql = '''
        ... CREATE FUNCTION fn_create_item(p_name TEXT) RETURNS BIGINT AS $$
        ... BEGIN
        ...     INSERT INTO tb_item (id, name) VALUES (1, p_name);
        ...     RETURN 1;
        ... END;
        ... $$ LANGUAGE plpgsql;
        ... '''
        >>> functions = parser.extract_functions(sql)
        >>> functions[0].name
        'fn_create_item'
        >>> functions[0].inserts[0].table_name
        'tb_item'
    """

    # Pattern: CREATE [OR REPLACE] FUNCTION [schema.]name(...)
    FUNCTION_NAME_PATTERN = re.compile(
        r"CREATE\s+(?:OR\s+REPLACE\s+)?FUNCTION\s+((?:\w+\.)?(\w+))\s*\(",
        re.IGNORECASE,
    )

    # Pattern: AS $tag$...$tag$ or AS $$...$$
    DOLLAR_BODY_PATTERN = re.compile(
        r"AS\s+\$(\w*)\$(.*?)\$\1\$",
        re.IGNORECASE | re.DOTALL,
    )

    # Pattern: AS '...' (single-quoted function body)
    SINGLE_QUOTE_BODY_PATTERN = re.compile(
        r"AS\s+'((?:[^']|'')*)'",
        re.IGNORECASE | re.DOTALL,
    )

    # Pattern: INSERT INTO [schema.]table [(columns)] VALUES|SELECT|DEFAULT VALUES
    INSERT_PATTERN = re.compile(
        r"INSERT\s+INTO\s+((?:\w+\.)?(\w+))\s*"
        r"(?:\(([^)]+)\)\s*)?"
        r"(VALUES|SELECT|DEFAULT\s+VALUES)",
        re.IGNORECASE | re.DOTALL,
    )

    # Pattern for extracting complete functions
    FUNCTION_PATTERN = re.compile(
        r"(CREATE\s+(?:OR\s+REPLACE\s+)?FUNCTION\s+(?:\w+\.)?(\w+)\s*\([^)]*\)"
        r"[^$]*"
        r"AS\s+\$(\w*)\$.*?\$\3\$"
        r"[^;]*;)",
        re.IGNORECASE | re.DOTALL,
    )

    def extract_function_name(self, sql: str) -> str | None:
        """Extract function name from CREATE FUNCTION statement.

        Args:
            sql: SQL containing CREATE FUNCTION statement

        Returns:
            Function name (may be schema-qualified) or None
        """
        match = self.FUNCTION_NAME_PATTERN.search(sql)
        if match:
            return match.group(1)
        return None

    def extract_function_body(self, sql: str) -> str | None:
        """Extract function body from CREATE FUNCTION statement.

        Handles both dollar-quoted ($$ or $tag$) and single-quoted bodies.

        Args:
            sql: SQL containing CREATE FUNCTION statement

        Returns:
            Function body text or None if not found
        """
        # Try dollar-quoted body first
        match = self.DOLLAR_BODY_PATTERN.search(sql)
        if match:
            return match.group(2)

        # Try single-quoted body
        match = self.SINGLE_QUOTE_BODY_PATTERN.search(sql)
        if match:
            # Unescape doubled single quotes
            return match.group(1).replace("''", "'")

        return None

    def extract_insert_statements(self, body: str) -> list[InsertStatement]:
        """Extract all INSERT statements from function body.

        Args:
            body: Function body text

        Returns:
            List of InsertStatement objects
        """
        statements = []

        for match in self.INSERT_PATTERN.finditer(body):
            table_name = match.group(1)  # Full table name (may include schema)
            columns_str = match.group(3)  # Column list or None

            # Parse column list
            columns = None
            if columns_str:
                columns = [c.strip() for c in columns_str.split(",")]

            # Calculate line number (1-based)
            line_num = body[: match.start()].count("\n") + 1

            # Get raw SQL (approximate - up to VALUES/SELECT/DEFAULT)
            raw_sql = match.group(0)

            statements.append(
                InsertStatement(
                    table_name=table_name,
                    columns=columns,
                    line_number=line_num,
                    raw_sql=raw_sql,
                )
            )

        return statements

    def extract_functions(self, sql: str) -> list[FunctionInfo]:
        """Extract all functions from SQL.

        Args:
            sql: SQL that may contain multiple CREATE FUNCTION statements

        Returns:
            List of FunctionInfo objects with their INSERT statements
        """
        functions = []

        for match in self.FUNCTION_PATTERN.finditer(sql):
            raw_sql = match.group(1)
            name = self.extract_function_name(raw_sql)
            body = self.extract_function_body(raw_sql)

            if name and body:
                inserts = self.extract_insert_statements(body)
                functions.append(
                    FunctionInfo(
                        name=name,
                        body=body,
                        inserts=inserts,
                        raw_sql=raw_sql,
                    )
                )

        return functions
