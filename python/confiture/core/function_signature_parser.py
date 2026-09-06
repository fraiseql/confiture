"""Parse PostgreSQL function/procedure signatures from SQL text.

Two-tier strategy mirroring differ.py:
- Tier 1: pglast (when [ast] extra is installed) — PostgreSQL's own C parser
- Tier 2: regex fallback — works without any optional dependencies
"""

from __future__ import annotations

import dataclasses
import re
from typing import Any

import pglast

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
# Used by parse_with_bodies to then extract balanced args separately.
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
        return self._parse_pglast(sql, pglast)

    def _parse_pglast(self, sql: str, pglast: Any) -> list[FunctionSignature]:
        """Parse using pglast (PostgreSQL's C parser).

        Uses .sval on String nodes (pglast 6+ API).
        Mode is a FunctionParameterMode enum with single-char values:
          'i'=IN, 'o'=OUT, 'b'=INOUT, 'v'=VARIADIC, 't'=TABLE, 'd'=DEFAULT(IN)
        We include IN ('i'), INOUT ('b'), DEFAULT ('d') and skip OUT/VARIADIC/TABLE.
        """
        # ParseError propagates: the caller reports it.
        return self._parse_pglast_nodes([stmt.stmt for stmt in pglast.parse_sql(sql) or []])

    def _parse_pglast_nodes(self, nodes: list[Any]) -> list[FunctionSignature]:
        from pglast.enums.parsenodes import FunctionParameterMode

        _SKIP_PARAM_MODES = {
            FunctionParameterMode.FUNC_PARAM_OUT,
            FunctionParameterMode.FUNC_PARAM_TABLE,
            FunctionParameterMode.FUNC_PARAM_VARIADIC,
        }
        result = []
        for node in nodes:
            try:
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
                        # pglast records array-ness in arrayBounds (one entry per
                        # dimension, -1 = unbounded), NOT in names.  Append a '[]'
                        # per dimension so array types survive normalisation and
                        # stay symmetric with the introspected live side (#176).
                        array_bounds = getattr(arg_type, "arrayBounds", None)
                        if array_bounds:
                            type_str += "[]" * len(array_bounds)
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

    def parse_with_bodies(self, sql: str) -> list[tuple[FunctionSignature, str | None]]:
        """Parse signatures and their bodies from the AST.

        ``body`` is the text between the dollar quotes exactly as written, or
        ``None`` for ``LANGUAGE c`` / ``LANGUAGE internal`` functions whose
        ``AS`` clause names a symbol, not SQL.
        """
        result: list[tuple[FunctionSignature, str | None]] = []
        for raw in pglast.parse_sql(sql) or []:
            node = raw.stmt
            if type(node).__name__ != "CreateFunctionStmt":
                continue
            sigs = self._parse_pglast_nodes([node])
            if not sigs:
                continue
            result.append((sigs[0], _function_body(node)))
        return result

    # Trailing array suffix: one or more '[]' groups, each optionally sized
    # (e.g. 'text[]', 'int[][]', 'text[5]').  PostgreSQL ignores the size, so we
    # canonicalise every dimension to bare '[]'.
    _ARRAY_SUFFIX_RE = re.compile(r"(?:\s*\[\s*\d*\s*\])+\s*$")

    def _normalise_type(self, raw: str) -> str:
        """Normalise a PostgreSQL type name to a canonical form.

        Examples:
            'INT' -> 'integer'
            'BIGINT' -> 'bigint'
            'pg_catalog.int4' -> 'integer'
            'VARCHAR(255)' -> 'character varying'
            'int4[]' -> 'integer[]'
            'numeric(10,2)[]' -> 'numeric[]'

        The array suffix is split off first so the *base* type is aliased and the
        canonical ``[]`` re-appended per dimension.  This keeps the source side
        symmetric with the live side (which introspects ``format_type`` output
        such as ``integer[]``); without it, array params falsely read as stale
        overloads and generate a destructive ``DROP FUNCTION`` (issue #176).
        """
        clean = raw.lower().strip()
        if clean.startswith("pg_catalog."):
            clean = clean[len("pg_catalog.") :]
        # Split off a trailing array suffix so the base can be aliased.
        array_dims = 0
        suffix_match = self._ARRAY_SUFFIX_RE.search(clean)
        if suffix_match:
            array_dims = suffix_match.group(0).count("[")
            clean = clean[: suffix_match.start()].strip()
        # Strip precision/scale: varchar(255) -> varchar
        clean = re.sub(r"\([^)]*\)", "", clean).strip()
        base = _TYPE_ALIASES.get(clean, clean)
        return base + "[]" * array_dims


def _function_body(node: Any) -> str | None:
    """The dollar-quoted body of a ``CreateFunctionStmt``, or ``None`` for C/internal."""
    language = None
    body = None
    for opt in node.options or []:
        args = opt.arg if isinstance(opt.arg, tuple | list) else [opt.arg]
        values = [getattr(a, "sval", None) for a in args]
        if opt.defname == "language":
            language = values[0].lower() if values and values[0] else None
        elif opt.defname == "as":
            body = values[0] if values else None
    if language in ("c", "internal"):
        return None
    return body
