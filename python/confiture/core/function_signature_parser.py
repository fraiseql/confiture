"""Parse PostgreSQL function/procedure signatures from SQL text.

Two-tier strategy mirroring differ.py:
- Tier 1: pglast (when [ast] extra is installed) — PostgreSQL's own C parser
- Tier 2: regex fallback — works without any optional dependencies
"""

from __future__ import annotations

import dataclasses
import re
from typing import Any

_FUNC_RE = re.compile(
    r"""
    CREATE \s+ (?:OR \s+ REPLACE \s+)?
    (?:FUNCTION|PROCEDURE) \s+
    (?:(?P<schema>[\w"]+)\.)?(?P<name>[\w"]+)
    \s* \( (?P<args>[^)]*) \)
    """,
    re.IGNORECASE | re.VERBOSE,
)

# Header-only variant: matches up to and including the opening '('.
# Used in _parse_regex to then extract balanced args separately.
_FUNC_HEADER_RE = re.compile(
    r"""
    CREATE \s+ (?:OR \s+ REPLACE \s+)?
    (?:FUNCTION|PROCEDURE) \s+
    (?:(?P<schema>[\w"]+)\.)?(?P<name>[\w"]+)
    \s* \(
    """,
    re.IGNORECASE | re.VERBOSE,
)

_TYPE_ALIASES: dict[str, str] = {
    "int": "integer",
    "int4": "integer",
    "integer": "integer",
    "int8": "bigint",
    "bigint": "bigint",
    "int2": "smallint",
    "smallint": "smallint",
    "bool": "boolean",
    "boolean": "boolean",
    "float4": "real",
    "real": "real",
    "float8": "double precision",
    "double precision": "double precision",
    "varchar": "character varying",
    "character varying": "character varying",
    "text": "text",
    "numeric": "numeric",
    "decimal": "numeric",
    "timestamptz": "timestamp with time zone",
    "timestamp with time zone": "timestamp with time zone",
    "uuid": "uuid",
}

# Keywords that start a parameter mode prefix to strip
_MODE_PREFIXES = re.compile(r"^(?:INOUT|IN)\s+", re.IGNORECASE)
# Keywords indicating OUT/VARIADIC/TABLE params to skip
_SKIP_MODES = re.compile(r"^(?:OUT|VARIADIC|TABLE)\s+", re.IGNORECASE)


@dataclasses.dataclass(frozen=True)
class FunctionSignature:
    """Parsed function signature from SQL DDL.

    Attributes:
        schema: Schema name (normalised to lowercase, "public" if unqualified)
        name: Function name (normalised to lowercase)
        param_types: IN/INOUT param types only (normalised, immutable tuple)
    """

    schema: str
    name: str
    param_types: tuple[str, ...]

    def signature_key(self) -> str:
        """Canonical key: 'schema.name(type1,type2)'"""
        return f"{self.schema}.{self.name}({','.join(self.param_types)})"

    def function_key(self) -> str:
        """Key without param types: 'schema.name'"""
        return f"{self.schema}.{self.name}"


class FunctionSignatureParser:
    """Parse function/procedure signatures from SQL DDL strings."""

    def parse(self, sql: str) -> list[FunctionSignature]:
        """Return all function/procedure signatures found in sql."""
        try:
            import pglast  # noqa: PLC0415

            return self._parse_pglast(sql, pglast)
        except ImportError:
            return self._parse_regex(sql)

    def _parse_pglast(self, sql: str, pglast: Any) -> list[FunctionSignature]:
        """Parse using pglast (PostgreSQL's C parser).

        Uses .sval on String nodes (pglast 6+ API).
        Mode is a FunctionParameterMode enum with single-char values:
          'i'=IN, 'o'=OUT, 'b'=INOUT, 'v'=VARIADIC, 't'=TABLE, 'd'=DEFAULT(IN)
        We include IN ('i'), INOUT ('b'), DEFAULT ('d') and skip OUT/VARIADIC/TABLE.
        """
        from pglast.enums.parsenodes import FunctionParameterMode  # noqa: PLC0415

        _SKIP_PARAM_MODES = {
            FunctionParameterMode.FUNC_PARAM_OUT,
            FunctionParameterMode.FUNC_PARAM_TABLE,
            FunctionParameterMode.FUNC_PARAM_VARIADIC,
        }

        result = []
        try:
            stmts = pglast.parse_sql(sql)
        except Exception:
            return self._parse_regex(sql)

        for stmt in stmts:
            try:
                node = stmt.stmt
                if node.__class__.__name__ != "CreateFunctionStmt":
                    continue

                funcname = node.funcname
                if funcname is None:
                    continue

                parts = [n.sval for n in funcname if hasattr(n, "sval")]
                if not parts:
                    continue
                if len(parts) == 1:
                    schema = "public"
                    name = parts[0].lower().strip('"')
                else:
                    schema = parts[-2].lower().strip('"')
                    name = parts[-1].lower().strip('"')

                param_types: list[str] = []
                parameters = node.parameters or []
                for param in parameters:
                    mode = param.mode
                    if mode is not None and mode in _SKIP_PARAM_MODES:
                        continue

                    arg_type = param.argType
                    if arg_type is None:
                        continue

                    names = arg_type.names
                    if names:
                        type_str = ".".join(n.sval for n in names if hasattr(n, "sval"))
                        if type_str.startswith("pg_catalog."):
                            type_str = type_str[len("pg_catalog.") :]
                        param_types.append(self._normalise_type(type_str))

                result.append(
                    FunctionSignature(
                        schema=schema,
                        name=name,
                        param_types=tuple(param_types),
                    )
                )
            except Exception:
                # Skip malformed nodes gracefully
                continue

        return result

    def _parse_regex(self, sql: str) -> list[FunctionSignature]:
        """Parse using regex fallback (no optional dependencies).

        Uses _FUNC_HEADER_RE to locate the opening '(' of each function, then
        extracts the argument list with balanced-parenthesis tracking so that
        complex DEFAULT expressions such as ``ROW(NULL, NULL)::mytype`` are
        captured correctly rather than truncated at the first ')'.
        """
        result = []
        for match in _FUNC_HEADER_RE.finditer(sql):
            schema_raw = match.group("schema")
            schema = schema_raw.lower().strip('"') if schema_raw else "public"
            name = match.group("name").lower().strip('"')
            # match.end() points to the char after '(' — the start of the args
            args_raw = self._extract_balanced_args(sql, match.end() - 1)
            if args_raw is None:
                continue
            param_types = self._parse_args_regex(args_raw.strip())
            result.append(
                FunctionSignature(
                    schema=schema,
                    name=name,
                    param_types=tuple(param_types),
                )
            )
        return result

    @staticmethod
    def _extract_balanced_args(sql: str, open_pos: int) -> str | None:
        """Return the content inside the balanced parentheses starting at open_pos.

        ``sql[open_pos]`` must be ``'('``.  Scans forward tracking depth;
        returns the substring between the opening and matching closing paren,
        or ``None`` if the parentheses are unbalanced.
        """
        depth = 0
        for i in range(open_pos, len(sql)):
            if sql[i] == "(":
                depth += 1
            elif sql[i] == ")":
                depth -= 1
                if depth == 0:
                    return sql[open_pos + 1 : i]
        return None

    def _parse_args_regex(self, args_raw: str) -> list[str]:
        """Parse a parameter list into normalised type strings.

        Splits on commas only at paren-depth 0 so that complex DEFAULT
        expressions containing nested parentheses (e.g.
        ``DEFAULT ROW(NULL, NULL)::mytype``) are treated as a single
        parameter token rather than multiple ones.
        """
        if not args_raw:
            return []

        # Depth-aware comma split
        parts: list[str] = []
        depth = 0
        current: list[str] = []
        for ch in args_raw:
            if ch == "(":
                depth += 1
                current.append(ch)
            elif ch == ")":
                depth -= 1
                current.append(ch)
            elif ch == "," and depth == 0:
                parts.append("".join(current))
                current = []
            else:
                current.append(ch)
        if current:
            parts.append("".join(current))

        param_types = []
        for arg in parts:
            arg = arg.strip()
            if not arg:
                continue

            # Remove DEFAULT clause (including complex expressions with nested parens)
            arg = re.sub(r"\s+DEFAULT\s+.*$", "", arg, flags=re.IGNORECASE | re.DOTALL).strip()
            arg = re.sub(r"\s*=\s*.*$", "", arg, flags=re.DOTALL).strip()

            # Skip OUT / VARIADIC / TABLE params
            if _SKIP_MODES.match(arg):
                continue

            # Strip IN / INOUT prefix
            arg = _MODE_PREFIXES.sub("", arg).strip()

            tokens = arg.split()
            if not tokens:
                continue

            type_str = self._extract_type_from_tokens(tokens)
            if type_str:
                param_types.append(self._normalise_type(type_str))

        return param_types

    def _extract_type_from_tokens(self, tokens: list[str]) -> str:
        """Extract the type portion from a list of tokens (last word(s))."""
        if len(tokens) >= 3 and " ".join(tokens[-3:]).lower() == "timestamp with time zone":
            return "timestamp with time zone"
        if len(tokens) >= 2 and " ".join(tokens[-2:]).lower() == "double precision":
            return "double precision"
        if len(tokens) >= 2 and " ".join(tokens[-2:]).lower() == "character varying":
            return "character varying"
        return tokens[-1]

    def _normalise_type(self, raw: str) -> str:
        """Normalise a PostgreSQL type name to a canonical form.

        Examples:
            'INT' -> 'integer'
            'BIGINT' -> 'bigint'
            'pg_catalog.int4' -> 'integer'
            'VARCHAR(255)' -> 'character varying'
        """
        clean = raw.lower().strip()
        if clean.startswith("pg_catalog."):
            clean = clean[len("pg_catalog.") :]
        # Strip precision/scale: varchar(255) -> varchar
        clean = re.sub(r"\([^)]*\)", "", clean).strip()
        return _TYPE_ALIASES.get(clean, clean)
