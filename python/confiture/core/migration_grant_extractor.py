"""Static extraction of ``CREATE TABLE`` and ``GRANT`` statements from a
migration's SQL text.

Used by the ACL coverage lint rule (issue #120) to answer: *"does this
migration's `CREATE TABLE` have a matching `GRANT` either in the same
file or in the configured global grant sweep directory?"*

Statements are read by pglast — PostgreSQL's own C parser via
``libpg_query``: limit-free, syntax-accurate, and preserving identifier case
for quoted names.

Dynamic SQL (``EXECUTE format('CREATE TABLE …')``) is invisible to any
static parser.  We surface that via :meth:`has_dynamic_sql` so callers
can emit an INFO note rather than silently miss the table.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import pglast
import pglast.parser
from pglast.enums.parsenodes import GrantTargetType, ObjectType, RoleSpecType

from confiture.core.schema_identity import DEFAULT_SCHEMA
from confiture.core.sql_lexer import strip_comments

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


@dataclass(frozen=True)
class GrantStatement:
    """A single, comparable GRANT/REVOKE fact (issue #162).

    Fanned out to one instance per ``(object × grantee × privilege)`` — the
    same philosophy as the ``extract_grants`` tuple, but extended to
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


def _unrepresentable_grant(stmt: Any, action: str, modeled: str | None) -> Any | None:
    """Why a ``GrantStmt`` cannot be keyed statically, or ``None`` when it can."""
    if modeled is None:
        return UnrepresentableGrant(
            reason="unmodeled_objtype",
            detail=f"{action} on an object class outside table/schema/sequence/function",
        )
    # Column-level privileges (``GRANT SELECT (col) …``) carry a non-empty
    # ``cols`` list — keying them as table grants would let a column grant
    # match (or vanish against) a whole-table grant.
    if any(p.cols for p in (stmt.privileges or [])):
        return UnrepresentableGrant(
            reason="column_privileges",
            detail=f"{action} with a column-level privilege list is not modeled",
        )
    return None


def _grant_privileges(stmt: Any, modeled: str) -> frozenset[str]:
    """The privilege names a ``GrantStmt`` carries; ``ALL`` (or none named) expands per object type."""
    if stmt.privileges is None:
        return _ALL_PRIVILEGES_BY_OBJTYPE[modeled]
    privs = frozenset(p.priv_name.upper() for p in stmt.privileges if p.priv_name)
    return privs or _ALL_PRIVILEGES_BY_OBJTYPE[modeled]  # an empty/None priv name means ALL


def _grantees(stmt: Any, role_spec_type: Any) -> list[str]:
    grantees: list[str] = []
    for g in stmt.grantees or []:
        if g.roletype == role_spec_type.ROLESPEC_PUBLIC:
            grantees.append("PUBLIC")
        elif g.rolename:
            grantees.append(g.rolename)  # pglast already folds case
    return grantees


class MigrationGrantExtractor:
    """Pull ``CREATE TABLE``, ``DROP TABLE``, and ``GRANT`` statements out of SQL."""

    # ------------------------------------------------------------------ #
    # Public API                                                          #
    # ------------------------------------------------------------------ #

    def extract_creates(self, sql: str) -> list[tuple[str, str]]:
        """Return ``(schema, table)`` for every ``CREATE TABLE`` in *sql*."""
        return self._creates_pglast(sql)

    def extract_drops(self, sql: str) -> list[tuple[str, str]]:
        """Return ``(schema, table)`` for every ``DROP TABLE`` in *sql*."""
        return self._drops_pglast(sql)

    def extract_grants(self, sql: str) -> list[tuple[str, str, str, frozenset[str]]]:
        """Return ``(schema, table, role, privileges)`` for every ``GRANT``.

        Multi-target grants (``GRANT … ON a, b, c TO …``) expand to one
        tuple per ``(target, role)`` pair.  ``GRANT … TO PUBLIC`` emits
        the literal role name ``"PUBLIC"``.  ``WITH GRANT OPTION`` /
        ``WITH HIERARCHY OPTION`` / ``WITH ADMIN OPTION`` suffixes are
        ignored — Confiture treats the grant itself, not its propagation
        flag, as the unit of coverage.
        """
        return self._grants_pglast(sql)

    def has_dynamic_sql(self, sql: str) -> bool:
        """Return ``True`` if *sql* contains ``EXECUTE format(…)`` patterns.

        Dynamic SQL is invisible to static parsing, so the caller may
        want to emit an INFO note that ACL coverage cannot be verified
        for the dynamic portion.
        """
        # Strip comments before scanning so we don't false-positive on
        # examples inside documentation.
        return bool(_DYNAMIC_SQL_RE.search(strip_comments(sql)))

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

        try:
            self._statements_pglast(sql, statements, unrepresentable)
        except pglast.parser.ParseError as exc:
            # Reported, never raised: the semantic engine degrades honestly (D9).
            statements.clear()
            unrepresentable.append(
                UnrepresentableGrant(
                    reason="parse_error", detail=f"pglast could not parse the SQL: {exc}"
                )
            )

        return GrantExtraction(statements=statements, unrepresentable=unrepresentable)

    # ------------------------------------------------------------------ #
    # pglast readers                                                      #
    # ------------------------------------------------------------------ #

    def _creates_pglast(self, sql: str) -> list[tuple[str, str]]:

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
                schema = stmt.relation.schemaname or DEFAULT_SCHEMA
                out.append((schema, stmt.relation.relname))
            elif kind == "CreateTableAsStmt":
                # CREATE TABLE … AS SELECT — same shape for ACL purposes.
                rel = stmt.into.rel
                if rel.relpersistence == "t":
                    continue
                schema = rel.schemaname or DEFAULT_SCHEMA
                out.append((schema, rel.relname))
        return out

    def _drops_pglast(self, sql: str) -> list[tuple[str, str]]:

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

        out: list[tuple[str, str, str, frozenset[str]]] = []
        for raw in pglast.parse_sql(sql):
            stmt = raw.stmt
            if type(stmt).__name__ != "GrantStmt":
                continue
            if not stmt.is_grant:  # REVOKE
                continue
            if stmt.objtype != ObjectType.OBJECT_TABLE:
                continue
            # ACL_TARGET_ALL_IN_SCHEMA → outside this reader's scope.  Skip.
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
            # one shape for it.
            roles: list[str] = []
            for g in stmt.grantees or []:
                if g.roletype == RoleSpecType.ROLESPEC_PUBLIC:
                    roles.append("PUBLIC")
                elif g.rolename:
                    roles.append(g.rolename)
            for obj in stmt.objects or []:
                # obj is a RangeVar for table grants.
                schema = obj.schemaname or DEFAULT_SCHEMA
                table = obj.relname
                out.extend((schema, table, role, privs) for role in roles)
        return out

    def _statements_pglast(
        self,
        sql: str,
        statements: list[GrantStatement],
        unrepresentable: list[UnrepresentableGrant],
    ) -> None:
        """The pglast reader behind :meth:`extract_grant_statements` (issue #162)."""

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
            rejection = _unrepresentable_grant(stmt, action, modeled)
            if rejection is not None:
                unrepresentable.append(rejection)
                continue
            assert modeled is not None  # rejected above otherwise
            privs = _grant_privileges(stmt, modeled)
            grant_option = bool(stmt.grant_option)
            grantees = _grantees(stmt, RoleSpecType)

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
            statements.extend(
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
                for priv in sorted(privs)
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
        schema = getattr(obj, "schemaname", None) or DEFAULT_SCHEMA
        relname = getattr(obj, "relname", None)
        if not relname:
            return ("", None, "unmodeled_objtype")
        return (schema, relname, None)


__all__ = [
    "_ALL_FUNCTION_PRIVILEGES",
    "_ALL_SCHEMA_PRIVILEGES",
    "_ALL_SEQUENCE_PRIVILEGES",
    "_ALL_TABLE_PRIVILEGES",
    "GrantExtraction",
    "GrantStatement",
    "MigrationGrantExtractor",
    "UnrepresentableGrant",
]
