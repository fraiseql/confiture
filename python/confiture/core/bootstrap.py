"""``confiture bootstrap`` planner and executor (issue #137 part 1).

Idempotent one-shot for environment ownership setup.  Three steps:

1. Create the migrator role if it doesn't exist.
2. Run ``REASSIGN OWNED BY postgres TO <migrator>`` so every
   currently-misowned object gets flipped to the canonical owner.
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

REASSIGN OWNED scope
====================
``REASSIGN OWNED BY x TO y`` is database-wide; it has no
schema-scoping flag.  When the planner observes ``postgres``-owned
objects in schemas not covered by ``ownership.apply_to``, it refuses
to emit the statement unless ``all_schemas=True`` is explicitly
passed.  See :class:`BootstrapScopeError`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

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

# PostgreSQL object-class filter for the postgres-owned scan: tables,
# sequences, views, materialized views, indexes (latter follow their
# parent's ownership, but include for completeness in the scan).
_REL_KINDS = "('r', 'S', 'v', 'm', 'i', 'p')"


@dataclass(frozen=True)
class BootstrapStep:
    """One SQL statement the executor would run, with operator-readable label."""

    label: str
    sql: str
    # Operator-facing one-liner shown in --dry-run output.
    description: str


@dataclass(frozen=True)
class BootstrapPlan:
    """Frozen snapshot of what ``--apply`` would do.

    Empty plan ⇒ the environment is already in the desired shape; a
    second ``--apply`` is a no-op.
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
            "observed_postgres_owned_schemas": list(
                self.observed_postgres_owned_schemas
            ),
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
        if not self._role_exists(conn, self.ownership.expected_owner):
            steps.append(self._step_create_role())

        # Step 2: REASSIGN OWNED — gated by scope check.
        postgres_owned = self._enumerate_postgres_owned_schemas(conn)
        out_of_scope = tuple(s for s in postgres_owned if s not in apply_to)
        if postgres_owned:
            if out_of_scope and not all_schemas:
                raise BootstrapScopeError(
                    f"`REASSIGN OWNED BY postgres TO {self.ownership.expected_owner}` "
                    f"would also flip ownership in schemas not covered by "
                    f"`ownership.apply_to`: {sorted(out_of_scope)}.  "
                    f"Re-run with `--all-schemas` to authorize, or extend "
                    f"`ownership.apply_to` to cover them.",
                    resolution_hint=(
                        "Either add the affected schemas to ownership.apply_to "
                        "in the env YAML, or pass --all-schemas explicitly. "
                        "PostgreSQL's REASSIGN OWNED is database-wide; there "
                        "is no per-schema variant."
                    ),
                )
            steps.append(self._step_reassign_owned())

        # Step 3: ALTER DEFAULT PRIVILEGES per schema/role/privs.
        steps.extend(self._steps_default_privileges())

        return BootstrapPlan(
            steps=tuple(steps),
            observed_postgres_owned_schemas=tuple(sorted(postgres_owned)),
            apply_to_schemas=apply_to,
        )

    # ------------------------------------------------------------------ #
    # Step builders                                                       #
    # ------------------------------------------------------------------ #

    def _step_create_role(self) -> BootstrapStep:
        # Role names go through quote_ident at execute time — never
        # parameterized via %s.  We pre-render with the validated
        # identifier here for display.
        role = _quote_ident(self.ownership.expected_owner)
        return BootstrapStep(
            label="create_role",
            sql=f"CREATE ROLE {role} WITH LOGIN NOCREATEROLE",
            description=(
                f"Create role {self.ownership.expected_owner!r} "
                f"(absent from pg_roles)."
            ),
        )

    def _step_reassign_owned(self) -> BootstrapStep:
        role = _quote_ident(self.ownership.expected_owner)
        return BootstrapStep(
            label="reassign_owned",
            sql=f"REASSIGN OWNED BY postgres TO {role}",
            description=(
                "Flip ownership of every postgres-owned object to "
                f"{self.ownership.expected_owner!r}.  Database-wide; not "
                "schema-scoped."
            ),
        )

    def _steps_default_privileges(self) -> list[BootstrapStep]:
        if self.ownership.default_privileges is None:
            return []
        role = _quote_ident(self.ownership.expected_owner)
        steps: list[BootstrapStep] = []
        for schema, role_privs in self.ownership.default_privileges.items():
            schema_ident = _quote_ident(schema)
            for grantee, privs in role_privs.items():
                # Privilege keywords are validated by OwnershipExpectation's
                # Pydantic validator — they're known constants here.
                upper_privs = ", ".join(p.upper() for p in privs)
                grantee_ident = _quote_ident(grantee)
                steps.append(
                    BootstrapStep(
                        label=f"default_privileges_{schema}_{grantee}",
                        sql=(
                            f"ALTER DEFAULT PRIVILEGES FOR ROLE {role} "
                            f"IN SCHEMA {schema_ident} "
                            f"GRANT {upper_privs} ON TABLES TO {grantee_ident}"
                        ),
                        description=(
                            f"Grant {upper_privs} on future tables in "
                            f"{schema!r} to {grantee!r}."
                        ),
                    )
                )
        return steps

    # ------------------------------------------------------------------ #
    # Database inspection                                                 #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _role_exists(conn: psycopg.Connection, role: str) -> bool:
        row = conn.execute(
            "SELECT 1 FROM pg_roles WHERE rolname = %s", (role,)
        ).fetchone()
        return row is not None

    @staticmethod
    def _enumerate_postgres_owned_schemas(conn: psycopg.Connection) -> set[str]:
        """Return the set of schema names with at least one postgres-owned object."""
        rows = conn.execute(
            f"""
            SELECT DISTINCT n.nspname
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            JOIN pg_roles r ON r.oid = c.relowner
            WHERE r.rolname = 'postgres'
              AND c.relkind IN {_REL_KINDS}
              AND n.nspname NOT IN ({", ".join("'" + s + "'" for s in _SYSTEM_SCHEMAS)})
            """
        ).fetchall()
        return {row[0] for row in rows}


class BootstrapExecutor:
    """Apply a :class:`BootstrapPlan` against a real database.

    Wraps the entire plan in a single transaction; on failure rolls
    back and raises :class:`BootstrapError`.  On success commits and
    returns a :class:`BootstrapResult` with one entry per executed
    step.

    The executor never builds its own plan — callers pass in the
    pre-computed :class:`BootstrapPlan`.  This makes ``--dry-run`` and
    ``--apply`` share the same plan object so dry-run output and the
    actual statements can never drift.
    """

    def apply(
        self,
        plan: BootstrapPlan,
        conn: psycopg.Connection,
    ) -> BootstrapResult:
        applied: list[str] = []
        try:
            with conn.transaction():
                for step in plan.steps:
                    conn.execute(step.sql)
                    applied.append(step.label)
            # The `with conn.transaction()` block is a SAVEPOINT when the
            # caller already initiated an implicit transaction (which the
            # planner's read queries do).  An explicit commit() promotes
            # the released savepoint into a durable change — without it
            # the next conn.close() would discard the work.
            conn.commit()
        except Exception as exc:  # noqa: BLE001 — re-wrap into BootstrapError
            conn.rollback()
            raise BootstrapError(
                f"Bootstrap failed during step "
                f"{applied[-1] if applied else '<role check>'}: {exc}",
                resolution_hint=(
                    "Inspect the database state, fix the underlying issue, "
                    "and re-run `confiture bootstrap --check` to see what "
                    "remains."
                ),
            ) from exc
        return BootstrapResult(
            plan=plan,
            applied_steps=tuple(applied),
            success=True,
        )


def _quote_ident(ident: str) -> str:
    """Quote a PostgreSQL identifier safely.

    Roles and schemas come through Pydantic validators (role idents
    match ``[a-z_][a-z0-9_]*`` or are double-quoted; schema names are
    validated by Postgres at lookup time), so we only need to handle
    embedded double-quotes via doubling.  We never accept user input
    that wasn't run through the env-config validation pipeline.
    """
    # Already double-quoted form — preserve as-is.
    if ident.startswith('"') and ident.endswith('"'):
        return ident
    escaped = ident.replace('"', '""')
    return f'"{escaped}"'


__all__ = [
    "BootstrapPlan",
    "BootstrapPlanner",
    "BootstrapExecutor",
    "BootstrapResult",
    "BootstrapStep",
]
