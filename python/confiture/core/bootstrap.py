"""``confiture bootstrap`` planner and executor (issue #137 part 1).

Idempotent one-shot for environment ownership setup.  Three steps:

1. Create the migrator role if it doesn't exist.
2. Hand every object a superuser owns in the target schemas to the
   migrator, one ``ALTER … OWNER TO`` per object.
3. Run ``ALTER DEFAULT PRIVILEGES`` per schema/role pair so newly-created
   objects automatically receive the configured grants.

``bootstrap`` is the operator-explicit alternative to the doomed pattern
of stuffing ``ALTER … OWNER TO migrator`` inside a migration that itself
runs as ``migrator`` (which lacks ``ALTER OWNER`` privilege).  See
``docs/guides/bootstrap.md`` for the operational walkthrough.

Connection requirement
======================
Every step needs superuser, so the planner and executor expect a
connection opened against ``ownership.bootstrap_connection_url``.  We
never silently reuse the env's main URL — if the operator hasn't set
the explicit override, we surface a :class:`BootstrapError`.

Ownership scope
===============
Objects are handed over one at a time, never with ``REASSIGN OWNED``: that
statement is database-wide, and where ``postgres`` is the cluster's bootstrap
superuser — the default everywhere, Docker included — it also owns objects the
system needs, and PostgreSQL refuses the whole statement ("required by the
database system").  A superuser owns what a migration applied as a superuser
creates, whatever the role is called, so the scan is by ``rolsuper``, not by the
name ``postgres``.  Extension members are the extension's, and a sequence owned
by a column moves with its table.

When superuser-owned objects exist in schemas not covered by
``ownership.apply_to``, the planner refuses unless ``all_schemas=True`` is
passed, so a run never silently hands over less, or more, than the operator
meant.  See :class:`BootstrapScopeError`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import psycopg

from confiture.core.schema_identity import identifier_identity, quote_identifier
from confiture.exceptions import BootstrapError, BootstrapScopeError

if TYPE_CHECKING:
    import psycopg

    from confiture.config.environment import OwnershipExpectation

# Catalog schemas that ``REASSIGN OWNED`` must NEVER touch.  These are
# always owned by ``postgres`` (or another superuser); flipping them
# breaks the cluster.  When the planner enumerates postgres-owned
# objects it strips these out before deciding whether the
# ``--all-schemas`` gate applies.
_SYSTEM_SCHEMAS: frozenset[str] = frozenset(
    {
        "pg_catalog",
        "pg_toast",
        "information_schema",
    }
)

# Every object a superuser (other than the expected owner) owns, with the
# ALTER that hands it over, schema-qualified by the catalog's own quoting.
_SUPERUSER_OWNED = """
WITH su AS (SELECT oid FROM pg_roles WHERE rolsuper AND rolname <> %(owner)s),
     ext AS (SELECT classid, objid FROM pg_depend WHERE deptype = 'e')
SELECT n.nspname, 'ALTER ' || CASE c.relkind WHEN 'v' THEN 'VIEW'
                                             WHEN 'm' THEN 'MATERIALIZED VIEW'
                                             WHEN 'S' THEN 'SEQUENCE'
                                             WHEN 'f' THEN 'FOREIGN TABLE'
                                             ELSE 'TABLE' END
       || format(' %%I.%%I', n.nspname, c.relname)
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE c.relowner IN (SELECT oid FROM su)
  AND c.relkind IN ('r', 'p', 'v', 'm', 'S', 'f')
  AND NOT (c.relkind = 'S' AND EXISTS (
        SELECT 1 FROM pg_depend d
        WHERE d.classid = 'pg_class'::regclass AND d.objid = c.oid AND d.deptype IN ('a', 'i')))
  AND NOT EXISTS (SELECT 1 FROM ext WHERE classid = 'pg_class'::regclass AND objid = c.oid)
UNION ALL
SELECT n.nspname, 'ALTER ' || CASE p.prokind WHEN 'a' THEN 'AGGREGATE'
                                             WHEN 'p' THEN 'PROCEDURE'
                                             ELSE 'FUNCTION' END
       || format(' %%I.%%I(%%s)', n.nspname, p.proname, pg_get_function_identity_arguments(p.oid))
FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
WHERE p.proowner IN (SELECT oid FROM su)
  AND NOT EXISTS (SELECT 1 FROM ext WHERE classid = 'pg_proc'::regclass AND objid = p.oid)
UNION ALL
SELECT n.nspname, 'ALTER ' || CASE t.typtype WHEN 'd' THEN 'DOMAIN' ELSE 'TYPE' END
       || format(' %%I.%%I', n.nspname, t.typname)
FROM pg_type t JOIN pg_namespace n ON n.oid = t.typnamespace
LEFT JOIN pg_class tc ON tc.oid = t.typrelid
WHERE t.typowner IN (SELECT oid FROM su)
  AND t.typtype IN ('e', 'd', 'r', 'c')
  AND (t.typtype <> 'c' OR tc.relkind = 'c')
  AND NOT EXISTS (SELECT 1 FROM ext WHERE classid = 'pg_type'::regclass AND objid = t.oid)
UNION ALL
SELECT n.nspname, format('ALTER SCHEMA %%I', n.nspname)
FROM pg_namespace n
WHERE n.nspowner IN (SELECT oid FROM su)
  AND NOT EXISTS (SELECT 1 FROM ext WHERE classid = 'pg_namespace'::regclass AND objid = n.oid)
"""


@dataclass(frozen=True)
class BootstrapStep:
    """One SQL statement the executor would run, with operator-readable label."""

    label: str
    sql: str
    # Operator-facing one-liner shown in --dry-run output.
    description: str


@dataclass(frozen=True)
class BootstrapPlan:
    """Frozen snapshot of what ``--mode apply`` would do.

    Empty plan ⇒ the environment is already in the desired shape; a
    second ``--mode apply`` is a no-op.
    """

    steps: tuple[BootstrapStep, ...] = ()
    # Schemas with postgres-owned objects that the planner observed.
    # Populated even when steps is empty (e.g. when --all-schemas was
    # required but missing — used in error messages).
    observed_postgres_owned_schemas: tuple[str, ...] = ()
    # Schemas configured in ownership.apply_to, for display in
    # --dry-run output.
    apply_to_schemas: tuple[str, ...] = ()

    @property
    def is_empty(self) -> bool:
        return not self.steps

    def to_dict(self) -> dict[str, object]:
        return {
            "steps": [
                {
                    "label": s.label,
                    "sql": s.sql,
                    "description": s.description,
                }
                for s in self.steps
            ],
            "observed_postgres_owned_schemas": list(self.observed_postgres_owned_schemas),
            "apply_to_schemas": list(self.apply_to_schemas),
            "is_empty": self.is_empty,
        }


@dataclass(frozen=True)
class BootstrapResult:
    """Outcome of ``BootstrapExecutor.apply``."""

    plan: BootstrapPlan
    applied_steps: tuple[str, ...] = field(default_factory=tuple)
    success: bool = True
    error: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "success": self.success,
            "error": self.error,
            "applied_steps": list(self.applied_steps),
            "plan": self.plan.to_dict(),
        }


class BootstrapPlanner:
    """Build a :class:`BootstrapPlan` from the live database + config.

    The planner is read-only: it inspects ``pg_roles`` / ``pg_class`` /
    ``pg_namespace`` to decide which steps are needed and never modifies
    state.  Idempotency is achieved by emitting only the steps that
    would actually change something — running the planner twice in a
    row produces an empty plan the second time.
    """

    def __init__(self, ownership: OwnershipExpectation) -> None:
        self.ownership = ownership

    # ------------------------------------------------------------------ #
    # Public API                                                          #
    # ------------------------------------------------------------------ #

    def plan(
        self,
        conn: psycopg.Connection,
        *,
        all_schemas: bool = False,
    ) -> BootstrapPlan:
        """Return the bootstrap plan for *conn*.

        Args:
            conn: Open psycopg connection.  MUST authenticate as a
                superuser — every step that ``apply`` would run requires
                superuser.
            all_schemas: Authorize ``REASSIGN OWNED`` across schemas
                outside ``ownership.apply_to``.  Raises
                :class:`BootstrapScopeError` when False and out-of-scope
                postgres-owned objects exist.
        """
        apply_to = tuple(entry.schema_ for entry in self.ownership.apply_to)
        steps: list[BootstrapStep] = []

        # Step 1: role creation.
        if not self._role_exists(conn, self.ownership.owner_identity):
            steps.append(self._step_create_role())

        # Step 2: hand superuser-owned objects over — gated by scope check.
        handovers = self._superuser_owned(conn)
        postgres_owned = {schema for schema, _ in handovers}
        out_of_scope = tuple(s for s in postgres_owned if s not in apply_to)
        if postgres_owned:
            if out_of_scope and not all_schemas:
                raise BootstrapScopeError(
                    f"Objects owned by a superuser also sit in schemas not covered by "
                    f"`ownership.apply_to`: {sorted(out_of_scope)}.  Re-run with "
                    f"`--all-schemas` to hand them to {self.ownership.expected_owner!r} "
                    f"too, or extend `ownership.apply_to` to cover them.",
                    resolution_hint=(
                        "Either add the affected schemas to ownership.apply_to "
                        "in the env YAML, or pass --all-schemas explicitly."
                    ),
                )
            steps.append(self._step_reassign_owned(handovers))

        # Step 3: ALTER DEFAULT PRIVILEGES per schema/role/privs.
        steps.extend(self._steps_default_privileges(conn))

        return BootstrapPlan(
            steps=tuple(steps),
            observed_postgres_owned_schemas=tuple(sorted(postgres_owned)),
            apply_to_schemas=apply_to,
        )

    # ------------------------------------------------------------------ #
    # Step builders                                                       #
    # ------------------------------------------------------------------ #

    def _step_create_role(self) -> BootstrapStep:
        # A role cannot be a %s parameter: the statement carries the role's
        # identity, quoted by the one identifier quoter.
        role = quote_identifier(self.ownership.owner_identity)
        return BootstrapStep(
            label="create_role",
            sql=f"CREATE ROLE {role} WITH LOGIN NOCREATEROLE",
            description=(f"Create role {self.ownership.expected_owner!r} (absent from pg_roles)."),
        )

    def _step_reassign_owned(self, handovers: list[tuple[str, str]]) -> BootstrapStep:
        role = quote_identifier(self.ownership.owner_identity)
        return BootstrapStep(
            label="reassign_owned",
            sql="\n".join(f"{alter} OWNER TO {role};" for _, alter in handovers),
            description=(
                f"Hand {len(handovers)} superuser-owned object(s) in "
                f"{sorted({schema for schema, _ in handovers})} to "
                f"{self.ownership.expected_owner!r}, one ALTER … OWNER TO each."
            ),
        )

    def _steps_default_privileges(self, conn: psycopg.Connection) -> list[BootstrapStep]:
        if self.ownership.default_privileges is None:
            return []
        role = quote_identifier(self.ownership.owner_identity)
        steps: list[BootstrapStep] = []
        for schema, role_privs in self.ownership.default_privileges.items():
            schema_ident = quote_identifier(_key_name(schema))
            for grantee, privs in role_privs.items():
                # Privilege keywords are validated by OwnershipExpectation's
                # Pydantic validator — they're known constants here.
                upper_privs = ", ".join(p.upper() for p in privs)
                grantee_ident = quote_identifier(_key_name(grantee))
                if self._default_privileges_present(conn, schema, grantee, privs):
                    continue
                steps.append(
                    BootstrapStep(
                        label=f"default_privileges_{schema}_{grantee}",
                        sql=(
                            f"ALTER DEFAULT PRIVILEGES FOR ROLE {role} "
                            f"IN SCHEMA {schema_ident} "
                            f"GRANT {upper_privs} ON TABLES TO {grantee_ident}"
                        ),
                        description=(
                            f"Grant {upper_privs} on future tables in {schema!r} to {grantee!r}."
                        ),
                    )
                )
        return steps

    # ------------------------------------------------------------------ #
    # Database inspection                                                 #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _role_exists(conn: psycopg.Connection, role: str) -> bool:
        row = conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,)).fetchone()
        return row is not None

    def _superuser_owned(self, conn: psycopg.Connection) -> list[tuple[str, str]]:
        """``(schema, ALTER statement stem)`` per superuser-owned object outside the system."""
        rows = conn.execute(_SUPERUSER_OWNED, {"owner": self.ownership.owner_identity}).fetchall()
        return sorted(
            (schema, alter)
            for schema, alter in rows
            if schema not in _SYSTEM_SCHEMAS and not schema.startswith("pg_")
        )

    def _default_privileges_present(
        self, conn: psycopg.Connection, schema: str, grantee: str, privs: list[str]
    ) -> bool:
        """Whether the owner's default privileges in *schema* already grant *privs* to *grantee*."""
        row = conn.execute(
            """
            SELECT count(DISTINCT a.privilege_type)
            FROM pg_default_acl d
            JOIN pg_namespace n ON n.oid = d.defaclnamespace,
                 aclexplode(d.defaclacl) a
            WHERE d.defaclrole = to_regrole(%s)
              AND n.nspname = %s
              AND d.defaclobjtype = 'r'
              AND a.grantee = to_regrole(%s)
              AND a.privilege_type = ANY(%s)
            """,
            (
                quote_identifier(self.ownership.owner_identity),
                _key_name(schema),
                quote_identifier(_key_name(grantee)),
                [p.upper() for p in privs],
            ),
        ).fetchone()
        return row is not None and row[0] == len({p.upper() for p in privs})


class BootstrapExecutor:
    """Apply a :class:`BootstrapPlan` against a real database.

    Wraps the entire plan in a single transaction; on failure rolls
    back and raises :class:`BootstrapError`.  On success commits and
    returns a :class:`BootstrapResult` with one entry per executed
    step.

    The executor never builds its own plan — callers pass in the
    pre-computed :class:`BootstrapPlan`.  This makes ``--mode plan`` and
    ``--mode apply`` share the same plan object so plan output and the
    actual statements can never drift.
    """

    def apply(
        self,
        plan: BootstrapPlan,
        conn: psycopg.Connection,
    ) -> BootstrapResult:
        applied: list[str] = []
        current = "<role check>"
        try:
            with conn.transaction():
                for step in plan.steps:
                    current = step.label
                    conn.execute(step.sql)
                    applied.append(step.label)
            # The `with conn.transaction()` block is a SAVEPOINT when the
            # caller already initiated an implicit transaction (which the
            # planner's read queries do).  An explicit commit() promotes
            # the released savepoint into a durable change — without it
            # the next conn.close() would discard the work.
            conn.commit()
        except psycopg.Error as exc:
            conn.rollback()
            raise BootstrapError(
                f"Bootstrap failed during step {current}: {exc}",
                resolution_hint=(
                    "Inspect the database state, fix the underlying issue, "
                    "and re-run `confiture bootstrap` (`--mode check`) to see what "
                    "remains."
                ),
            ) from exc
        return BootstrapResult(
            plan=plan,
            applied_steps=tuple(applied),
            success=True,
        )


def _key_name(key: str) -> str:
    """A ``default_privileges`` key's name: ``"Name"`` is ``Name``, anything else the name itself.

    The keys are not validated as identifiers before they reach here: only a key
    that is exactly one quoted identifier — no quote inside it but a doubled one —
    is read as one. Any other key, a bare one included, is taken as written.
    """
    inner = key[1:-1]
    one_quoted = len(key) > 1 and key[0] == key[-1] == '"' and '"' not in inner.replace('""', "")
    return identifier_identity(key) if one_quoted else key


__all__ = [
    "BootstrapExecutor",
    "BootstrapPlan",
    "BootstrapPlanner",
    "BootstrapResult",
    "BootstrapStep",
]
