"""Function parsing for INSERT extraction.

Reads every ``CREATE FUNCTION`` of a file through pglast — its name, its body
(the ``AS`` clause, or a ``BEGIN ATOMIC`` body deparsed) and the statement's
source — and the ``INSERT INTO`` statements inside the body through
libpg_query's scanner, so a comment, a string literal or a commented-out
function is never mistaken for code. An ``EXECUTE '…'`` literal is read as
dynamic SQL: its inserts carry ``is_dynamic``.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

import pglast.parser
from pglast.stream import RawStream

from confiture.core import sql_lexer

# Keyword kinds PostgreSQL accepts as a plain identifier (``INSERT INTO user``).
_IDENTIFIER_KINDS = frozenset({"UNRESERVED_KEYWORD", "COL_NAME_KEYWORD", "TYPE_FUNC_NAME_KEYWORD"})
_COMMENTS = frozenset({"SQL_COMMENT", "C_COMMENT"})
_DOT, _OPEN, _CLOSE, _COMMA = "ASCII_46", "ASCII_40", "ASCII_41", "ASCII_44"


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


def _sval(node: Any) -> str:
    return str(getattr(node, "sval", node))


def _is_identifier(token: Any) -> bool:
    return token.name == "IDENT" or token.kind in _IDENTIFIER_KINDS


def _identifier_text(sql: str, token: Any) -> str:
    text = sql[token.start : token.end + 1]
    if text[:1] == '"' and text[-1:] == '"' and text != '"':
        return text[1:-1].replace('""', '"')
    return text


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

    def extract_function_name(self, sql: str) -> str | None:
        """Extract function name from CREATE FUNCTION statement.

        Args:
            sql: SQL containing CREATE FUNCTION statement

        Returns:
            Function name (may be schema-qualified) or None
        """
        stmt = self._first_function(sql)
        return self._name(stmt) if stmt is not None else None

    def extract_function_body(self, sql: str) -> str | None:
        """Extract function body from CREATE FUNCTION statement.

        Handles dollar-quoted (``$$`` or ``$tag$``) and single-quoted bodies,
        and a ``LANGUAGE sql BEGIN ATOMIC`` body (deparsed).

        Args:
            sql: SQL containing CREATE FUNCTION statement

        Returns:
            Function body text or None if not found
        """
        stmt = self._first_function(sql)
        return self._body(stmt) if stmt is not None else None

    def extract_insert_statements(
        self, body: str, *, is_dynamic: bool = False
    ) -> list[InsertStatement]:
        """Extract all INSERT statements from function body.

        Args:
            body: Function body text
            is_dynamic: The body is the text of an ``EXECUTE`` literal

        Returns:
            List of InsertStatement objects
        """
        toks = [t for t in sql_lexer.tokens(body) if t.name not in _COMMENTS]
        found: list[InsertStatement] = []
        i = 0
        while i < len(toks):
            token = toks[i]
            following = toks[i + 1] if i + 1 < len(toks) else None
            if token.name == "INSERT" and following is not None and following.name == "INTO":
                statement, i = self._read_insert(body, toks, i, is_dynamic)
                if statement is not None:
                    found.append(statement)
                continue
            if (
                token.name == "EXECUTE"
                and following is not None
                and following.name == "SCONST"
                and body[following.start] == "'"
            ):
                literal = body[following.start + 1 : following.end].replace("''", "'")
                offset = body.count("\n", 0, following.start)
                found.extend(
                    replace(nested, line_number=nested.line_number + offset)
                    for nested in self.extract_insert_statements(literal, is_dynamic=True)
                )
                i += 2
                continue
            i += 1
        return found

    def extract_functions(self, sql: str) -> list[FunctionInfo]:
        """Extract all functions from SQL.

        Args:
            sql: SQL that may contain multiple CREATE FUNCTION statements

        Returns:
            List of FunctionInfo objects with their INSERT statements

        Raises:
            pglast.parser.ParseError: ``sql`` is not SQL PostgreSQL would accept.
        """
        functions: list[FunctionInfo] = []
        for parsed in sql_lexer.parse(sql):
            stmt = parsed.stmt
            if type(stmt).__name__ != "CreateFunctionStmt" or stmt.is_procedure:
                continue
            name = self._name(stmt)
            body = self._body(stmt)
            if not name or body is None:
                continue
            start = sql_lexer.skip_leading_comments(sql, parsed.location)
            end = parsed.location + parsed.length if parsed.length else len(sql)
            functions.append(
                FunctionInfo(
                    name=name,
                    body=body,
                    inserts=self.extract_insert_statements(body),
                    raw_sql=sql[start:end].strip(),
                )
            )
        return functions

    # ------------------------------------------------------------------ #
    # The CREATE FUNCTION envelope, from the parser                       #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _first_function(sql: str) -> Any | None:
        try:
            statements = sql_lexer.parse(sql)
        except pglast.parser.ParseError:
            return None
        for parsed in statements:
            if type(parsed.stmt).__name__ == "CreateFunctionStmt":
                return parsed.stmt
        return None

    @staticmethod
    def _name(stmt: Any) -> str:
        return ".".join(_sval(part) for part in stmt.funcname or ())

    @staticmethod
    def _body(stmt: Any) -> str | None:
        if stmt.sql_body is not None:
            statements = [s for group in stmt.sql_body for s in _as_tuple(group)]
            return "\n".join(RawStream()(s) + ";" for s in statements)
        for option in stmt.options or ():
            if option.defname == "as":
                values = [_sval(a) for a in _as_tuple(option.arg)]
                return values[0] if values else None
        return None

    # ------------------------------------------------------------------ #
    # INSERT INTO, from the scanner                                        #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _read_insert(
        body: str, toks: list[Any], i: int, is_dynamic: bool
    ) -> tuple[InsertStatement | None, int]:
        """The INSERT starting at ``toks[i]`` and the index to resume from."""
        j = i + 2
        parts: list[str] = []
        while j < len(toks) and _is_identifier(toks[j]):
            parts.append(_identifier_text(body, toks[j]))
            j += 1
            if j < len(toks) and toks[j].name == _DOT:
                j += 1
            else:
                break
        if not parts:
            return None, j
        end = toks[j - 1].end
        columns: list[str] | None = None
        if j < len(toks) and toks[j].name == _OPEN:
            names: list[str] | None = []
            k = j + 1
            while k < len(toks) and toks[k].name != _CLOSE and names is not None:
                if _is_identifier(toks[k]):
                    names.append(_identifier_text(body, toks[k]))
                elif toks[k].name != _COMMA:
                    names = None
                k += 1
            if names is not None and k < len(toks):
                columns, end, j = names, toks[k].end, k + 1
        if j < len(toks) and toks[j].kind != "NO_KEYWORD":
            end = toks[j].end  # VALUES / SELECT / DEFAULT — the shape the fragment shows
        return (
            InsertStatement(
                table_name=".".join(parts),
                columns=columns,
                line_number=body.count("\n", 0, toks[i].start) + 1,
                raw_sql=body[toks[i].start : end + 1],
                is_dynamic=is_dynamic,
            ),
            j,
        )


def _as_tuple(value: Any) -> tuple[Any, ...]:
    if value is None:
        return ()
    return tuple(value) if isinstance(value, (tuple, list)) else (value,)
