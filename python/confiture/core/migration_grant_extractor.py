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
#
# A *qname* is a possibly-schema-qualified identifier with quoting support.
# A *qname list* is one or more qnames separated by commas (Postgres allows
# ``GRANT … ON a, s.b, c TO …`` and ``DROP TABLE a, b, c``).
_QNAME = r"""(?:"[^"]+"|\w+)(?:\.(?:"[^"]+"|\w+))?"""
_QNAME_LIST = rf"""(?:{_QNAME})(?:\s*,\s*(?:{_QNAME}))*"""

_CREATE_TABLE_RE = re.compile(
    rf"""
    \bCREATE\s+
    (?:(?:GLOBAL|LOCAL)\s+)?
    (?P<modifier>TEMP(?:ORARY)?|UNLOGGED)?\s*
    TABLE\s+
    (?:IF\s+NOT\s+EXISTS\s+)?
    (?P<qname>{_QNAME})
    """,
    re.IGNORECASE | re.VERBOSE,
)
# ``CREATE TABLE foo_2026 PARTITION OF foo FOR VALUES …`` — partition
# child detection for the sqlparse fallback path.  Matched against the
# small lookahead window after each qname; mirrors pglast's
# ``stmt.partbound is not None`` test.
_PARTITION_OF_RE = re.compile(r"^\s*PARTITION\s+OF\b", re.IGNORECASE)
_DROP_TABLE_RE = re.compile(
    rf"""
    \bDROP\s+TABLE\s+
    (?:IF\s+EXISTS\s+)?
    (?P<qnames>{_QNAME_LIST})
    """,
    re.IGNORECASE | re.VERBOSE,
)
_GRANT_RE = re.compile(
    rf"""
    \bGRANT\s+
    (?P<privs>.+?)
    \s+ON\s+(?:TABLE\s+)?
    (?P<qnames>{_QNAME_LIST})
    \s+TO\s+
    (?P<roles>.+?)
    \s*;
    """,
    re.IGNORECASE | re.DOTALL | re.VERBOSE,
)
# Trailing modifiers that follow the role list in a GRANT.  See the
# ``role_specification`` grammar in the PostgreSQL docs.
_WITH_OPTION_SUFFIX_RE = re.compile(
    r"\s+WITH\s+(?:GRANT|HIERARCHY|ADMIN)\s+OPTION\s*;?\s*$",
    re.IGNORECASE,
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

    Unqualified names default to schema ``"public"``.  Migrations that
    rely on ``SET search_path`` to land tables in a non-public schema
    won't be picked up correctly; explicit qualification is the
    documented recommendation (see :doc:`/guides/acl-coverage`).
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


def _split_qname_list(qnames: str) -> list[str]:
    """Split a comma-separated qname list, respecting quoted identifiers.

    Postgres permits ``"weird,name"`` as a legal table name; the embedded
    comma must not split the list.  Iterates char-by-char tracking quote
    state, only splitting on top-level commas.
    """
    items: list[str] = []
    current: list[str] = []
    inside_quote = False
    for ch in qnames:
        if ch == '"':
            inside_quote = not inside_quote
            current.append(ch)
        elif ch == "," and not inside_quote:
            items.append("".join(current).strip())
            current = []
        else:
            current.append(ch)
    last = "".join(current).strip()
    if last:
        items.append(last)
    return items


def _normalize_grantee(name: str) -> str:
    """Map a parsed grantee string to its canonical form.

    Strips surrounding double quotes (preserving case for quoted names),
    leaves unquoted names as-is (Postgres folds them to lower-case at
    parse time, but the role lookup is case-insensitive in
    ``has_table_privilege``).  ``PUBLIC`` and other pseudo-roles flow
    through unchanged from the sqlparse path; the pglast path emits the
    literal ``"PUBLIC"`` string when ``roletype == ROLESPEC_PUBLIC``.
    """
    name = name.strip()
    if name.startswith('"') and name.endswith('"'):
        return name[1:-1]
    return name


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

    def extract_grants(self, sql: str) -> list[tuple[str, str, str, frozenset[str]]]:
        """Return ``(schema, table, role, privileges)`` for every ``GRANT``.

        Multi-target grants (``GRANT … ON a, b, c TO …``) expand to one
        tuple per ``(target, role)`` pair.  ``GRANT … TO PUBLIC`` emits
        the literal role name ``"PUBLIC"``.  ``WITH GRANT OPTION`` /
        ``WITH HIERARCHY OPTION`` / ``WITH ADMIN OPTION`` suffixes are
        stripped before parsing the role list — Confiture treats the
        grant itself, not its propagation flag, as the unit of coverage.
        """
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
                # TEMP tables don't persist beyond the session, so ACL
                # coverage doesn't apply.  UNLOGGED tables are permanent
                # objects with normal grant semantics — include them.
                # relpersistence: 'p'=permanent, 'u'=unlogged, 't'=temp.
                if stmt.relation.relpersistence == "t":
                    continue
                # Partition children (``CREATE TABLE foo_2026 PARTITION
                # OF foo FOR VALUES …``) inherit grants from the parent.
                # Excluding them keeps coverage focused on the schema
                # surface the operator actually grants against — a
                # partitioned parent — and avoids false positives that
                # would multiply with every new partition.  partbound
                # is set on children, None on parents and plain tables.
                if stmt.partbound is not None:
                    continue
                schema = stmt.relation.schemaname or "public"
                out.append((schema, stmt.relation.relname))
            elif kind == "CreateTableAsStmt":
                # CREATE TABLE … AS SELECT — same shape for ACL purposes.
                rel = stmt.into.rel
                if rel.relpersistence == "t":
                    continue
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

    def _grants_pglast(self, sql: str) -> list[tuple[str, str, str, frozenset[str]]]:
        import pglast  # noqa: PLC0415
        from pglast.enums.parsenodes import (  # noqa: PLC0415
            GrantTargetType,
            ObjectType,
            RoleSpecType,
        )

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

            # PUBLIC is a real grantee target — Postgres treats grants
            # to PUBLIC as a wildcard, and ``has_table_privilege`` honours
            # them.  Emit the literal "PUBLIC" so library consumers see
            # the same shape both backends produce.
            roles: list[str] = []
            for g in stmt.grantees or []:
                if g.roletype == RoleSpecType.ROLESPEC_PUBLIC:
                    roles.append("PUBLIC")
                elif g.rolename:
                    roles.append(g.rolename)
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
        out: list[tuple[str, str]] = []
        for m in _CREATE_TABLE_RE.finditer(cleaned):
            modifier = (m.group("modifier") or "").upper()
            # TEMP tables don't persist; ACL coverage doesn't apply.
            # UNLOGGED tables are permanent — keep them.
            if modifier.startswith("TEMP"):
                continue
            # Partition children inherit grants from the parent.  Peek
            # at the small window immediately after the qname for the
            # ``PARTITION OF`` clause — same exclusion the pglast path
            # applies via ``stmt.partbound``.
            tail = cleaned[m.end() : m.end() + 32]
            if _PARTITION_OF_RE.match(tail):
                continue
            out.append(_parse_qualified_name(m.group("qname")))
        return out

    def _drops_sqlparse(self, sql: str) -> list[tuple[str, str]]:
        cleaned = sqlparse.format(sql, strip_comments=True)
        out: list[tuple[str, str]] = []
        for m in _DROP_TABLE_RE.finditer(cleaned):
            for qname in _split_qname_list(m.group("qnames")):
                out.append(_parse_qualified_name(qname))
        return out

    def _grants_sqlparse(self, sql: str) -> list[tuple[str, str, str, frozenset[str]]]:
        cleaned = sqlparse.format(sql, strip_comments=True)
        out: list[tuple[str, str, str, frozenset[str]]] = []
        for m in _GRANT_RE.finditer(cleaned):
            priv_text = m.group("privs").strip().upper()
            if priv_text in ("ALL", "ALL PRIVILEGES"):
                privs: frozenset[str] = _ALL_TABLE_PRIVILEGES
            else:
                privs = frozenset(p.strip() for p in priv_text.split(","))
            # Strip ``WITH GRANT/HIERARCHY/ADMIN OPTION`` so the suffix
            # doesn't leak into the role list.  pglast handles this in
            # the AST via the ``grant_option`` flag.
            roles_text = _WITH_OPTION_SUFFIX_RE.sub("", m.group("roles"))
            qnames = _split_qname_list(m.group("qnames"))
            for qname in qnames:
                schema, table = _parse_qualified_name(qname)
                for role_raw in roles_text.split(","):
                    role = _normalize_grantee(role_raw.rstrip(";"))
                    if role:
                        out.append((schema, table, role, privs))
        return out


__all__ = [
    "MigrationGrantExtractor",
    "_ALL_TABLE_PRIVILEGES",
]
