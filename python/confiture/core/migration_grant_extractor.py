"""Static extraction of ``CREATE TABLE`` and ``GRANT`` statements from a
migration's SQL text.

Used by the ACL coverage lint rule (issue #120) to answer: *"does this
migration's `CREATE TABLE` have a matching `GRANT` either in the same
file or in the configured global grant sweep directory?"*

Two-tier parsing, mirroring :mod:`confiture.core.differ`:

* **Primary — pglast**: PostgreSQL's own C parser via ``libpg_query``.
  Limit-free, syntax-accurate, preserves identifier case for quoted
  names.
* **Fallback — sqlparse + regex**: kicks in when pglast isn't installed
  (it's an optional extra in this project).  Good enough for hand-written
  migrations; not used as the test ground truth.

Dynamic SQL (``EXECUTE format('CREATE TABLE …')``) is invisible to any
static parser.  We surface that via :meth:`has_dynamic_sql` so callers
can emit an INFO note rather than silently miss the table.
"""

from __future__ import annotations

import importlib.util
import re

import sqlparse

# Optional dep — pglast lives behind the ``[ast]`` extra.
_HAS_PGLAST: bool = importlib.util.find_spec("pglast") is not None

# Every privilege a table can hold.  ``GRANT ALL`` expands to this set.
# Order matters only for deterministic test output; storage uses frozenset.
_ALL_TABLE_PRIVILEGES: frozenset[str] = frozenset(
    {"SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER"}
)

# Regex helpers for the sqlparse fallback path.
_CREATE_TABLE_RE = re.compile(
    r"""
    \bCREATE\s+TABLE\s+
    (?:IF\s+NOT\s+EXISTS\s+)?
    (?P<qname>(?:"[^"]+"|\w+)(?:\.(?:"[^"]+"|\w+))?)
    """,
    re.IGNORECASE | re.VERBOSE,
)
_DROP_TABLE_RE = re.compile(
    r"""
    \bDROP\s+TABLE\s+
    (?:IF\s+EXISTS\s+)?
    (?P<qname>(?:"[^"]+"|\w+)(?:\.(?:"[^"]+"|\w+))?)
    """,
    re.IGNORECASE | re.VERBOSE,
)
_GRANT_RE = re.compile(
    r"""
    \bGRANT\s+
    (?P<privs>.+?)
    \s+ON\s+(?:TABLE\s+)?
    (?P<qname>(?:"[^"]+"|\w+)(?:\.(?:"[^"]+"|\w+))?)
    \s+TO\s+
    (?P<roles>.+?)
    \s*;
    """,
    re.IGNORECASE | re.DOTALL | re.VERBOSE,
)
_DYNAMIC_SQL_RE = re.compile(r"\bEXECUTE\s+(?:format\s*\(|['\"])", re.IGNORECASE)


def _strip_quotes(ident: str) -> str:
    """Return the bare identifier, preserving case for ``"Quoted"`` names."""
    ident = ident.strip()
    if ident.startswith('"') and ident.endswith('"'):
        return ident[1:-1]
    # Unquoted PostgreSQL identifiers fold to lowercase at parse time.
    return ident.lower()


def _parse_qualified_name(qname: str) -> tuple[str, str]:
    """Split a possibly-qualified identifier into ``(schema, relname)``.

    Unqualified names default to schema ``"public"`` — matches the
    documented v1 behavior (see Phase 2 "Risks" section for the
    ``search_path`` caveat).
    """
    qname = qname.strip()
    # Split on a dot that isn't inside double quotes.
    parts: list[str] = []
    current: list[str] = []
    inside_quote = False
    for ch in qname:
        if ch == '"':
            inside_quote = not inside_quote
            current.append(ch)
        elif ch == "." and not inside_quote:
            parts.append("".join(current))
            current = []
        else:
            current.append(ch)
    parts.append("".join(current))

    if len(parts) == 1:
        return ("public", _strip_quotes(parts[0]))
    return (_strip_quotes(parts[0]), _strip_quotes(parts[1]))


class MigrationGrantExtractor:
    """Pull ``CREATE TABLE``, ``DROP TABLE``, and ``GRANT`` statements out of SQL."""

    # ------------------------------------------------------------------ #
    # Public API                                                          #
    # ------------------------------------------------------------------ #

    def extract_creates(self, sql: str) -> list[tuple[str, str]]:
        """Return ``(schema, table)`` for every ``CREATE TABLE`` in *sql*."""
        if _HAS_PGLAST:
            try:
                return self._creates_pglast(sql)
            except Exception:
                pass  # Fall through to sqlparse on any pglast hiccup.
        return self._creates_sqlparse(sql)

    def extract_drops(self, sql: str) -> list[tuple[str, str]]:
        """Return ``(schema, table)`` for every ``DROP TABLE`` in *sql*."""
        if _HAS_PGLAST:
            try:
                return self._drops_pglast(sql)
            except Exception:
                pass
        return self._drops_sqlparse(sql)

    def extract_grants(
        self, sql: str
    ) -> list[tuple[str, str, str, frozenset[str]]]:
        """Return ``(schema, table, role, privileges)`` for every ``GRANT``."""
        if _HAS_PGLAST:
            try:
                return self._grants_pglast(sql)
            except Exception:
                pass
        return self._grants_sqlparse(sql)

    def has_dynamic_sql(self, sql: str) -> bool:
        """Return ``True`` if *sql* contains ``EXECUTE format(…)`` patterns.

        Dynamic SQL is invisible to static parsing, so the caller may
        want to emit an INFO note that ACL coverage cannot be verified
        for the dynamic portion.
        """
        # Strip comments before scanning so we don't false-positive on
        # examples inside documentation.
        cleaned = sqlparse.format(sql, strip_comments=True)
        return bool(_DYNAMIC_SQL_RE.search(cleaned))

    # ------------------------------------------------------------------ #
    # pglast primary path                                                 #
    # ------------------------------------------------------------------ #

    def _creates_pglast(self, sql: str) -> list[tuple[str, str]]:
        import pglast  # noqa: PLC0415

        out: list[tuple[str, str]] = []
        for raw in pglast.parse_sql(sql):
            stmt = raw.stmt
            kind = type(stmt).__name__
            if kind == "CreateStmt":
                schema = stmt.relation.schemaname or "public"
                out.append((schema, stmt.relation.relname))
            elif kind == "CreateTableAsStmt":
                # CREATE TABLE … AS SELECT — same shape for ACL purposes.
                rel = stmt.into.rel
                schema = rel.schemaname or "public"
                out.append((schema, rel.relname))
        return out

    def _drops_pglast(self, sql: str) -> list[tuple[str, str]]:
        import pglast  # noqa: PLC0415
        from pglast.enums.parsenodes import ObjectType  # noqa: PLC0415

        out: list[tuple[str, str]] = []
        for raw in pglast.parse_sql(sql):
            stmt = raw.stmt
            if type(stmt).__name__ != "DropStmt":
                continue
            if stmt.removeType != ObjectType.OBJECT_TABLE:
                continue
            for obj in stmt.objects or []:
                # obj is a tuple of String nodes naming the target.
                parts = [n.sval for n in obj]
                if len(parts) == 1:
                    out.append(("public", parts[0]))
                else:
                    out.append((parts[0], parts[1]))
        return out

    def _grants_pglast(
        self, sql: str
    ) -> list[tuple[str, str, str, frozenset[str]]]:
        import pglast  # noqa: PLC0415
        from pglast.enums.parsenodes import GrantTargetType, ObjectType  # noqa: PLC0415

        out: list[tuple[str, str, str, frozenset[str]]] = []
        for raw in pglast.parse_sql(sql):
            stmt = raw.stmt
            if type(stmt).__name__ != "GrantStmt":
                continue
            if not stmt.is_grant:  # REVOKE
                continue
            if stmt.objtype != ObjectType.OBJECT_TABLE:
                continue
            # ACL_TARGET_ALL_IN_SCHEMA → not v1 scope.  Skip.
            if stmt.targtype != GrantTargetType.ACL_TARGET_OBJECT:
                continue

            # GRANT ALL → privileges is None.
            if stmt.privileges is None:
                privs = _ALL_TABLE_PRIVILEGES
            else:
                privs = frozenset(p.priv_name.upper() for p in stmt.privileges)

            roles = [g.rolename for g in stmt.grantees or [] if g.rolename]
            for obj in stmt.objects or []:
                # obj is a RangeVar for table grants.
                schema = obj.schemaname or "public"
                table = obj.relname
                for role in roles:
                    out.append((schema, table, role, privs))
        return out

    # ------------------------------------------------------------------ #
    # sqlparse fallback path                                              #
    # ------------------------------------------------------------------ #

    def _creates_sqlparse(self, sql: str) -> list[tuple[str, str]]:
        cleaned = sqlparse.format(sql, strip_comments=True)
        return [_parse_qualified_name(m.group("qname")) for m in _CREATE_TABLE_RE.finditer(cleaned)]

    def _drops_sqlparse(self, sql: str) -> list[tuple[str, str]]:
        cleaned = sqlparse.format(sql, strip_comments=True)
        return [_parse_qualified_name(m.group("qname")) for m in _DROP_TABLE_RE.finditer(cleaned)]

    def _grants_sqlparse(
        self, sql: str
    ) -> list[tuple[str, str, str, frozenset[str]]]:
        cleaned = sqlparse.format(sql, strip_comments=True)
        out: list[tuple[str, str, str, frozenset[str]]] = []
        for m in _GRANT_RE.finditer(cleaned):
            priv_text = m.group("privs").strip().upper()
            if priv_text in ("ALL", "ALL PRIVILEGES"):
                privs: frozenset[str] = _ALL_TABLE_PRIVILEGES
            else:
                privs = frozenset(p.strip() for p in priv_text.split(","))
            schema, table = _parse_qualified_name(m.group("qname"))
            for role_raw in m.group("roles").split(","):
                role = role_raw.strip().rstrip(";").strip()
                # Strip trailing/leading whitespace; preserve quoted role
                # case via _strip_quotes only when it actually has quotes.
                if role.startswith('"') and role.endswith('"'):
                    role = role[1:-1]
                if role:
                    out.append((schema, table, role, privs))
        return out


__all__ = [
    "MigrationGrantExtractor",
    "_ALL_TABLE_PRIVILEGES",
]
