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
from dataclasses import dataclass, field

import sqlparse

# Optional dep — pglast lives behind the ``[ast]`` extra.
_HAS_PGLAST: bool = importlib.util.find_spec("pglast") is not None

# Every privilege a table can hold.  ``GRANT ALL`` expands to this set.
# Order matters only for deterministic test output; storage uses frozenset.
_ALL_TABLE_PRIVILEGES: frozenset[str] = frozenset(
    {"SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER"}
)
# ``GRANT ALL`` expands differently per object class (issue #162).
_ALL_SEQUENCE_PRIVILEGES: frozenset[str] = frozenset({"USAGE", "SELECT", "UPDATE"})
_ALL_FUNCTION_PRIVILEGES: frozenset[str] = frozenset({"EXECUTE"})
_ALL_SCHEMA_PRIVILEGES: frozenset[str] = frozenset({"USAGE", "CREATE"})

_ALL_PRIVILEGES_BY_OBJTYPE: dict[str, frozenset[str]] = {
    "TABLE": _ALL_TABLE_PRIVILEGES,
    "SEQUENCE": _ALL_SEQUENCE_PRIVILEGES,
    "FUNCTION": _ALL_FUNCTION_PRIVILEGES,
    "SCHEMA": _ALL_SCHEMA_PRIVILEGES,
}

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

# Statement-level GRANT/REVOKE matcher for the regex fallback path of
# ``extract_grant_statements`` (issue #162). Captures the privilege list, the
# raw ``ON`` clause (classified separately), and the grantee list, for both
# ``GRANT … TO …`` and ``REVOKE … FROM …``.
_GRANT_REVOKE_STMT_RE = re.compile(
    r"""
    ^\s*
    (?P<action>GRANT|REVOKE)\s+
    (?P<go_for>GRANT\s+OPTION\s+FOR\s+)?   # REVOKE GRANT OPTION FOR …
    (?P<privs>.+?)
    \s+ON\s+
    (?P<onclause>.+?)
    \s+(?:TO|FROM)\s+
    (?P<roles>.+?)
    \s*;?\s*$
    """,
    re.IGNORECASE | re.DOTALL | re.VERBOSE,
)
_ALL_IN_SCHEMA_RE = re.compile(
    r"""
    ^ALL\s+
    (?P<plural>TABLES|SEQUENCES|FUNCTIONS|ROUTINES|PROCEDURES)\s+
    IN\s+SCHEMA\s+
    (?P<schema>.+)$
    """,
    re.IGNORECASE | re.VERBOSE,
)
_ALTER_DEFAULT_PRIVS_RE = re.compile(r"^\s*ALTER\s+DEFAULT\s+PRIVILEGES\b", re.IGNORECASE)
_WITH_GRANT_OPTION_RE = re.compile(r"\bWITH\s+GRANT\s+OPTION\b", re.IGNORECASE)
_ALL_IN_SCHEMA_PLURAL_TO_OBJTYPE: dict[str, str] = {
    "TABLES": "TABLE",
    "SEQUENCES": "SEQUENCE",
    "FUNCTIONS": "FUNCTION",
    "ROUTINES": "FUNCTION",
    "PROCEDURES": "FUNCTION",
}


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


def _fold_grantee(name: str) -> str:
    """Canonicalize a grantee for the semantic match key (D12, issue #162).

    Mirrors PostgreSQL identifier folding so the regex fallback agrees with
    pglast (which already folds): unquoted names lower-case, quoted names keep
    their case, and ``PUBLIC`` (any case) maps to the literal ``"PUBLIC"`` so
    it lines up with pglast's ``ROLESPEC_PUBLIC`` emission.
    """
    name = name.strip()
    if name.startswith('"') and name.endswith('"'):
        return name[1:-1]
    folded = name.lower()
    if folded == "public":
        return "PUBLIC"
    return folded


@dataclass(frozen=True)
class GrantStatement:
    """A single, comparable GRANT/REVOKE fact (issue #162).

    Fanned out to one instance per ``(object × grantee × privilege)`` — the
    same philosophy as the legacy ``extract_grants`` tuple, but extended to
    REVOKE and to schema/sequence/function objects. The seven leading fields
    *are* the match key the semantic engine compares; ``grant_option`` is
    deliberately excluded from equality/hash (``compare=False``) because
    Confiture treats the grant itself — not its propagation flag — as the unit
    of coverage. The accompaniment engine still reads ``grant_option`` to detect
    a change that differs *only* by the option.
    """

    action: str  # "GRANT" | "REVOKE"
    objtype: str  # "TABLE" | "SEQUENCE" | "FUNCTION" | "SCHEMA"
    target_kind: str  # "OBJECT" | "ALL_IN_SCHEMA"
    schema: str  # schema name (or the target schema for ALL_IN_SCHEMA)
    object: str | None  # table/seq name, function signature, or None for schema-level
    grantee: str  # role name, or "PUBLIC"
    privilege: str  # one privilege per statement; ALL expanded per objtype
    grant_option: bool = field(default=False, compare=False)

    def describe(self) -> str:
        """Render a human-readable SQL-ish form for failure messages."""
        if self.target_kind == "ALL_IN_SCHEMA":
            plural = {
                "TABLE": "TABLES",
                "SEQUENCE": "SEQUENCES",
                "FUNCTION": "FUNCTIONS",
            }.get(self.objtype, f"{self.objtype}S")
            target = f"ALL {plural} IN SCHEMA {self.schema}"
        elif self.objtype == "SCHEMA":
            target = f"SCHEMA {self.schema}"
        elif self.objtype == "TABLE":
            target = f"{self.schema}.{self.object}"
        else:
            target = f"{self.objtype} {self.schema}.{self.object}"
        preposition = "TO" if self.action == "GRANT" else "FROM"
        suffix = " WITH GRANT OPTION" if self.grant_option and self.action == "GRANT" else ""
        return f"{self.action} {self.privilege} ON {target} {preposition} {self.grantee}{suffix}"


@dataclass(frozen=True)
class UnrepresentableGrant:
    """A parse-clean privilege change the extractor refuses to key (D9).

    Never silently dropped: the semantic gate degrades to file-presence and
    surfaces a note for each of these rather than passing a grant that would
    never reach a migrate environment.
    """

    reason: str  # "unmodeled_objtype" | "column_privileges" |
    # "alter_default_privileges" | "dynamic_sql" | "parse_error"
    detail: str  # human text for the surfaced note


@dataclass(frozen=True)
class GrantExtraction:
    """Result of :meth:`MigrationGrantExtractor.extract_grant_statements`."""

    statements: list[GrantStatement]
    unrepresentable: list[UnrepresentableGrant]


# Object classes that parse cleanly but Confiture does not model (D9). The
# regex fallback detects them by the leading ``ON <keyword>`` token.
_UNMODELED_ON_KEYWORDS: tuple[str, ...] = (
    "DATABASE",
    "LANGUAGE",
    "TYPE",
    "DOMAIN",
    "FOREIGN DATA WRAPPER",
    "FOREIGN SERVER",
    "TABLESPACE",
    "LARGE OBJECT",
)


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

    def extract_grant_statements(self, sql: str) -> GrantExtraction:
        """Extract GRANT/REVOKE facts from *sql* for semantic matching (issue #162).

        Returns a :class:`GrantExtraction` carrying both the representable
        :class:`GrantStatement` rows (fanned out one per object × grantee ×
        privilege, across table / schema-wide / sequence / function objects)
        **and** an explicit list of :class:`UnrepresentableGrant` markers for
        everything that parses cleanly but can't be keyed (D9): unmodeled
        object classes (``ON DATABASE``/``LANGUAGE``/``TYPE``/…), ``ALTER
        DEFAULT PRIVILEGES``, column-level privileges, dynamic SQL, and parse
        failures. Nothing privilege-shaped is ever silently dropped and the
        method never raises — the semantic engine must be able to see
        everything that changed so it can degrade honestly.
        """
        statements: list[GrantStatement] = []
        unrepresentable: list[UnrepresentableGrant] = []

        # Dynamic SQL hides grants from any static parser — surface it so the
        # gate degrades rather than passing an invisible privilege change.
        if self.has_dynamic_sql(sql):
            unrepresentable.append(
                UnrepresentableGrant(
                    reason="dynamic_sql",
                    detail=(
                        "EXECUTE format(...) / dynamic SQL — grants built at runtime "
                        "cannot be statically verified"
                    ),
                )
            )

        parsed = False
        if _HAS_PGLAST:
            try:
                self._statements_pglast(sql, statements, unrepresentable)
                parsed = True
            except Exception:  # noqa: BLE001 — fall through to the regex backend
                statements.clear()
                parsed = False
        if not parsed:
            try:
                self._statements_sqlparse(sql, statements, unrepresentable)
                parsed = True
            except Exception:  # noqa: BLE001 — report rather than raise
                parsed = False
        if not parsed:
            unrepresentable.append(
                UnrepresentableGrant(
                    reason="parse_error",
                    detail="SQL could not be parsed by pglast or the regex fallback",
                )
            )

        return GrantExtraction(statements=statements, unrepresentable=unrepresentable)

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

    def _statements_pglast(
        self,
        sql: str,
        statements: list[GrantStatement],
        unrepresentable: list[UnrepresentableGrant],
    ) -> None:
        """pglast backend for :meth:`extract_grant_statements` (issue #162)."""
        import pglast  # noqa: PLC0415
        from pglast.enums.parsenodes import (  # noqa: PLC0415
            GrantTargetType,
            ObjectType,
            RoleSpecType,
        )

        objtype_map = {
            ObjectType.OBJECT_TABLE: "TABLE",
            ObjectType.OBJECT_SEQUENCE: "SEQUENCE",
            ObjectType.OBJECT_FUNCTION: "FUNCTION",
            ObjectType.OBJECT_ROUTINE: "FUNCTION",
            ObjectType.OBJECT_PROCEDURE: "FUNCTION",
            ObjectType.OBJECT_SCHEMA: "SCHEMA",
        }

        for raw in pglast.parse_sql(sql):
            stmt = raw.stmt
            kind = type(stmt).__name__

            if kind == "AlterDefaultPrivilegesStmt":
                unrepresentable.append(
                    UnrepresentableGrant(
                        reason="alter_default_privileges",
                        detail="ALTER DEFAULT PRIVILEGES affects future objects; not statically modeled",
                    )
                )
                continue
            if kind != "GrantStmt":
                continue

            action = "GRANT" if stmt.is_grant else "REVOKE"
            modeled = objtype_map.get(stmt.objtype)
            if modeled is None:
                unrepresentable.append(
                    UnrepresentableGrant(
                        reason="unmodeled_objtype",
                        detail=f"{action} on an object class outside table/schema/sequence/function",
                    )
                )
                continue

            # Column-level privileges (``GRANT SELECT (col) …``) carry a
            # non-empty ``cols`` list — keying them as table grants would let a
            # column grant match (or vanish against) a whole-table grant.
            if any(p.cols for p in (stmt.privileges or [])):
                unrepresentable.append(
                    UnrepresentableGrant(
                        reason="column_privileges",
                        detail=f"{action} with a column-level privilege list is not modeled",
                    )
                )
                continue

            if stmt.privileges is None:
                privs = _ALL_PRIVILEGES_BY_OBJTYPE[modeled]
            else:
                privs = frozenset(p.priv_name.upper() for p in stmt.privileges if p.priv_name)
                if not privs:  # an empty/None priv name means ALL
                    privs = _ALL_PRIVILEGES_BY_OBJTYPE[modeled]

            grant_option = bool(stmt.grant_option)

            grantees: list[str] = []
            for g in stmt.grantees or []:
                if g.roletype == RoleSpecType.ROLESPEC_PUBLIC:
                    grantees.append("PUBLIC")
                elif g.rolename:
                    grantees.append(g.rolename)  # pglast already folds case

            if stmt.targtype == GrantTargetType.ACL_TARGET_ALL_IN_SCHEMA:
                # objects are String nodes naming the target schema(s).
                for o in stmt.objects or []:
                    schema_name = getattr(o, "sval", None)
                    if not schema_name:
                        continue
                    self._emit_statements(
                        statements,
                        action,
                        modeled,
                        "ALL_IN_SCHEMA",
                        schema_name,
                        None,
                        grantees,
                        privs,
                        grant_option,
                    )
                continue

            for o in stmt.objects or []:
                schema_name, obj_name, reason = self._pglast_object_identity(modeled, o)
                if reason is not None:
                    unrepresentable.append(
                        UnrepresentableGrant(
                            reason=reason,
                            detail=f"{action} {modeled} target could not be resolved to a stable key",
                        )
                    )
                    continue
                self._emit_statements(
                    statements,
                    action,
                    modeled,
                    "OBJECT",
                    schema_name,
                    obj_name,
                    grantees,
                    privs,
                    grant_option,
                )

    @staticmethod
    def _emit_statements(
        statements: list[GrantStatement],
        action: str,
        objtype: str,
        target_kind: str,
        schema: str,
        obj: str | None,
        grantees: list[str],
        privs: frozenset[str],
        grant_option: bool,
    ) -> None:
        for grantee in grantees:
            for priv in sorted(privs):
                statements.append(
                    GrantStatement(
                        action=action,
                        objtype=objtype,
                        target_kind=target_kind,
                        schema=schema,
                        object=obj,
                        grantee=grantee,
                        privilege=priv,
                        grant_option=grant_option,
                    )
                )

    @staticmethod
    def _pglast_object_identity(objtype: str, obj: object) -> tuple[str, str | None, str | None]:
        """Resolve a pglast grant target to ``(schema, object, unrepresentable_reason)``.

        On success the third element is None. When the object can't be keyed
        reliably (an overload-ambiguous function, an unexpected node shape), it
        names an unrepresentable reason instead so the caller degrades.
        """
        if objtype == "SCHEMA":
            # ``GRANT … ON SCHEMA s`` — the object IS the schema; no nested name.
            name = getattr(obj, "sval", None)
            if not name:
                return ("", None, "unmodeled_objtype")
            return (name, None, None)

        if objtype == "FUNCTION":
            # ObjectWithArgs: objname is the qualified name, objargs the types.
            if getattr(obj, "args_unspecified", False):
                # ``GRANT … ON FUNCTION s.fn`` (no parens) can't pin an overload.
                return ("", None, "unmodeled_objtype")
            names = [n.sval for n in (getattr(obj, "objname", None) or [])]
            if not names:
                return ("", None, "unmodeled_objtype")
            schema = names[-2] if len(names) >= 2 else "public"
            fn = names[-1]
            argtypes: list[str] = []
            for a in getattr(obj, "objargs", None) or []:
                type_parts = [n.sval for n in (getattr(a, "names", None) or [])]
                if not type_parts:
                    return ("", None, "unmodeled_objtype")
                argtypes.append(".".join(type_parts))
            return (schema, f"{fn}({','.join(argtypes)})", None)

        # TABLE / SEQUENCE → RangeVar.
        schema = getattr(obj, "schemaname", None) or "public"
        relname = getattr(obj, "relname", None)
        if not relname:
            return ("", None, "unmodeled_objtype")
        return (schema, relname, None)

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

    def _statements_sqlparse(
        self,
        sql: str,
        statements: list[GrantStatement],
        unrepresentable: list[UnrepresentableGrant],
    ) -> None:
        """Regex fallback backend for :meth:`extract_grant_statements` (issue #162).

        Intentionally weaker than pglast for non-table objects: function
        signatures and exotic object classes are reported as unrepresentable
        rather than guessed, leaning on the honest-degradation contract.
        """
        cleaned = sqlparse.format(sql, strip_comments=True)
        for stmt_text in sqlparse.split(cleaned):
            stmt_text = stmt_text.strip()
            if not stmt_text:
                continue
            if _ALTER_DEFAULT_PRIVS_RE.match(stmt_text):
                unrepresentable.append(
                    UnrepresentableGrant(
                        reason="alter_default_privileges",
                        detail="ALTER DEFAULT PRIVILEGES affects future objects; not statically modeled",
                    )
                )
                continue
            m = _GRANT_REVOKE_STMT_RE.match(stmt_text)
            if m is None:
                continue

            action = m.group("action").upper()
            priv_text = m.group("privs").strip()
            # Column-level privileges carry a parenthesised column list.
            if "(" in priv_text:
                unrepresentable.append(
                    UnrepresentableGrant(
                        reason="column_privileges",
                        detail=f"{action} with a column-level privilege list is not modeled",
                    )
                )
                continue

            items, reason = self._classify_on_clause(m.group("onclause").strip())
            if reason is not None:
                unrepresentable.append(
                    UnrepresentableGrant(
                        reason=reason,
                        detail=f"{action} on an object class outside table/schema/sequence/function",
                    )
                )
                continue
            if not items:
                continue

            objtype = items[0][0]
            priv_upper = priv_text.upper()
            if priv_upper in ("ALL", "ALL PRIVILEGES"):
                privs = _ALL_PRIVILEGES_BY_OBJTYPE.get(objtype, _ALL_TABLE_PRIVILEGES)
            else:
                privs = frozenset(p.strip().upper() for p in priv_upper.split(",") if p.strip())

            roles_text = m.group("roles")
            grant_option = bool(m.group("go_for")) or bool(_WITH_GRANT_OPTION_RE.search(roles_text))
            roles_text = _WITH_OPTION_SUFFIX_RE.sub("", roles_text)
            grantees = [
                _fold_grantee(r.rstrip(";")) for r in roles_text.split(",") if r.strip().rstrip(";")
            ]
            grantees = [g for g in grantees if g]

            for objtype_i, target_kind, schema, obj in items:
                self._emit_statements(
                    statements,
                    action,
                    objtype_i,
                    target_kind,
                    schema,
                    obj,
                    grantees,
                    privs,
                    grant_option,
                )

    @staticmethod
    def _classify_on_clause(
        onclause: str,
    ) -> tuple[list[tuple[str, str, str, str | None]], str | None]:
        """Classify a regex-path ``ON`` clause into grant targets or a degrade reason.

        Returns ``(items, reason)`` where each item is
        ``(objtype, target_kind, schema, object)``. When ``reason`` is set the
        item list is empty and the caller marks the statement unrepresentable.
        """
        onclause = onclause.strip()

        all_match = _ALL_IN_SCHEMA_RE.match(onclause)
        if all_match:
            objtype = _ALL_IN_SCHEMA_PLURAL_TO_OBJTYPE[all_match.group("plural").upper()]
            if objtype == "FUNCTION":
                # Function/routine signatures are beyond the regex fallback.
                return ([], "unmodeled_objtype")
            schema = _strip_quotes(all_match.group("schema").strip())
            return ([(objtype, "ALL_IN_SCHEMA", schema, None)], None)

        upper = onclause.upper()
        for keyword in _UNMODELED_ON_KEYWORDS:
            if upper.startswith(keyword):
                return ([], "unmodeled_objtype")

        if upper.startswith(("FUNCTION", "ROUTINE", "PROCEDURE")):
            # Signatures are too ambiguous for the regex fallback — degrade.
            return ([], "unmodeled_objtype")

        if upper.startswith("SCHEMA"):
            names = _split_qname_list(onclause[len("SCHEMA") :].strip())
            return ([("SCHEMA", "OBJECT", _strip_quotes(n), None) for n in names], None)

        if upper.startswith("SEQUENCE"):
            qnames = _split_qname_list(onclause[len("SEQUENCE") :].strip())
            items = []
            for qname in qnames:
                schema, seq = _parse_qualified_name(qname)
                items.append(("SEQUENCE", "OBJECT", schema, seq))
            return (items, None)

        rest = onclause[len("TABLE") :].strip() if upper.startswith("TABLE") else onclause
        items = []
        for qname in _split_qname_list(rest):
            schema, table = _parse_qualified_name(qname)
            items.append(("TABLE", "OBJECT", schema, table))
        return (items, None)


__all__ = [
    "GrantExtraction",
    "GrantStatement",
    "MigrationGrantExtractor",
    "UnrepresentableGrant",
    "_ALL_FUNCTION_PRIVILEGES",
    "_ALL_SCHEMA_PRIVILEGES",
    "_ALL_SEQUENCE_PRIVILEGES",
    "_ALL_TABLE_PRIVILEGES",
]
