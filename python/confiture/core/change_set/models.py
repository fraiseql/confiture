"""The change-set wire shape: entries, the set, tier tables and the tier rules."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

from confiture.core.lock_profile import (
    FAST_DEFAULT_SINCE,
    LockProfile,
)
from confiture.core.risk_tier import RiskTier, worst_tier
from confiture.core.type_lattice import (
    TypeChange,
)

if TYPE_CHECKING:
    pass


# Bumped only by a removal, a rename, or a change in what a tier *means*.
# Adding a field to an entry does not bump it.
CONTRACT_VERSION: Final = 1
_DEFAULT_SCHEMA: Final = "public"


@dataclass(frozen=True)
class ChangeEntry:
    """One change, as it crosses the adapter seam."""

    kind: str
    """Stable machine code, ``snake_case``. Rendered verbatim; never parsed for meaning."""

    object: str
    """Fully-qualified target — ``schema.table``, ``schema.table.column``, ``schema.table.index``."""

    migration: str | None = None
    """The migration **version prefix**, matching ``issues[].migration``."""

    tier: RiskTier | None = None
    """``None`` ⇒ unclassified ⇒ the consumer denies. Never inferred from ``kind``."""

    detail: str | None = None
    """One human-readable line for the plan render. Never parsed, never a credential."""

    lock: LockProfile | None = None
    """What the change costs in locking terms (#199), or ``None`` when confiture
    has no statement to cost — a ``.py`` migration.

    **Deliberately not on the wire.** The change-set entry shape is the ratified
    fraisier-core#44 pact, pinned byte-for-byte by golden fixtures in both
    repositories; adding a key there is a co-ordinated change with a
    ``contract_version`` decision, not a free addition. Until that is agreed, the
    lock facts reach an operator through :attr:`detail`, which the contract
    defines as free-form, and reach a library caller through this field."""

    def to_dict(self) -> dict[str, Any]:
        """Wire form. Absent optional fields are omitted, not emitted as ``null``."""
        payload: dict[str, Any] = {"kind": self.kind, "object": self.object}
        if self.migration is not None:
            payload["migration"] = self.migration
        if self.tier is not None:
            payload["tier"] = self.tier.value
        if self.detail is not None:
            payload["detail"] = self.detail
        return payload


@dataclass(frozen=True)
class ChangeSet:
    """The classified change set for a migration tree.

    An **empty** ``changes`` means "looked, nothing to change". A change set that
    is *absent* from the payload means "did not classify". The object wrapper is
    what keeps those two apart, and that distinction is the point of it.
    """

    changes: tuple[ChangeEntry, ...] = ()
    contract_version: int = CONTRACT_VERSION

    @property
    def worst_tier(self) -> RiskTier | None:
        """Most severe tier over the *classifiable* entries (``None`` if none are)."""
        return worst_tier(entry.tier for entry in self.changes)

    @property
    def has_unclassified(self) -> bool:
        """True when any entry carries no tier."""
        return any(entry.tier is None for entry in self.changes)

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_version": self.contract_version,
            "changes": [entry.to_dict() for entry in self.changes],
        }


# kind → tier, for the kinds whose tier does not depend on the statement's own
# attributes. A kind absent from this table is unclassified. Shared by both
# backends, so they cannot disagree about a boundary.
_TIER_BY_KIND: Final[dict[str, RiskTier | None]] = {
    # additive — adds a new object; no existing reader or writer can break
    "create_table": RiskTier.ADDITIVE,
    "create_table_as": RiskTier.ADDITIVE,
    "create_view": RiskTier.ADDITIVE,
    "create_materialized_view": RiskTier.ADDITIVE,
    "create_schema": RiskTier.ADDITIVE,
    "create_sequence": RiskTier.ADDITIVE,
    "create_type": RiskTier.ADDITIVE,
    "create_domain": RiskTier.ADDITIVE,
    "create_extension": RiskTier.ADDITIVE,
    "create_function": RiskTier.ADDITIVE,
    "create_procedure": RiskTier.ADDITIVE,
    "create_trigger": RiskTier.ADDITIVE,
    "create_policy": RiskTier.ADDITIVE,
    "create_rule": RiskTier.ADDITIVE,
    "insert": RiskTier.ADDITIVE,
    # `ALTER TYPE … ADD VALUE` cannot be taken back, but it destroys nothing and
    # breaks no reader — irreversibility in this taxonomy is about data.
    "alter_type": RiskTier.ADDITIVE,
    # reversible — changes existing state, with a down path that restores it
    "rename_column": RiskTier.REVERSIBLE,
    "rename_object": RiskTier.REVERSIBLE,
    "set_column_default": RiskTier.REVERSIBLE,
    "drop_column_default": RiskTier.REVERSIBLE,
    "drop_not_null": RiskTier.REVERSIBLE,
    "replace_view": RiskTier.REVERSIBLE,
    "replace_function": RiskTier.REVERSIBLE,
    "replace_procedure": RiskTier.REVERSIBLE,
    "change_owner": RiskTier.REVERSIBLE,
    "alter_sequence": RiskTier.REVERSIBLE,
    "alter_default_privileges": RiskTier.REVERSIBLE,
    "grant": RiskTier.REVERSIBLE,
    "revoke": RiskTier.REVERSIBLE,
    "comment": RiskTier.REVERSIBLE,
    # lock_risky — semantically safe, but takes a lock that can stall a hot table
    "set_not_null": RiskTier.LOCK_RISKY,
    "cluster": RiskTier.LOCK_RISKY,
    "refresh_materialized_view": RiskTier.LOCK_RISKY,
    "reindex": RiskTier.LOCK_RISKY,
    # destructive — destroys data or an object, restorable from backup
    "drop_index": RiskTier.DESTRUCTIVE,
    "drop_view": RiskTier.DESTRUCTIVE,
    "drop_materialized_view": RiskTier.DESTRUCTIVE,
    "drop_function": RiskTier.DESTRUCTIVE,
    "drop_procedure": RiskTier.DESTRUCTIVE,
    "drop_type": RiskTier.DESTRUCTIVE,
    "drop_domain": RiskTier.DESTRUCTIVE,
    "drop_trigger": RiskTier.DESTRUCTIVE,
    "drop_policy": RiskTier.DESTRUCTIVE,
    "drop_rule": RiskTier.DESTRUCTIVE,
    "drop_extension": RiskTier.DESTRUCTIVE,
    "drop_constraint": RiskTier.DESTRUCTIVE,
    "truncate": RiskTier.DESTRUCTIVE,
    "delete": RiskTier.DESTRUCTIVE,
    "update": RiskTier.DESTRUCTIVE,
    # irreversible — destroys data with no down path that can restore it
    "drop_column": RiskTier.IRREVERSIBLE,
    "drop_table": RiskTier.IRREVERSIBLE,
    "drop_schema": RiskTier.IRREVERSIBLE,
    "drop_sequence": RiskTier.IRREVERSIBLE,
}
# Detail lines that read better than the generic "KIND WITH UNDERSCORES" form.
_DETAIL_BY_KIND: Final[dict[str, str]] = {
    "replace_view": "CREATE OR REPLACE VIEW",
    "replace_function": "CREATE OR REPLACE FUNCTION",
    "replace_procedure": "CREATE OR REPLACE PROCEDURE",
    "create_table_as": "CREATE TABLE AS",
}


def _detail_for(kind: str) -> str:
    """The default one-line detail for ``kind`` — shared by both backends."""
    return _DETAIL_BY_KIND.get(kind, kind.replace("_", " ").upper())


_ALTER_COLUMN_TYPE_DETAIL: Final = (
    "reversible when widening and irreversible when narrowing; preflight cannot "
    "tell without the source and target types"
)
# A narrowing loses data with no down path; a lateral move reinterprets every
# stored value, which is the same loss wearing a different hat. A widening is
# safe for the data but still pays for the rewrite when there is one.
_TIER_BY_DIRECTION: Final[dict[TypeChange, RiskTier]] = {
    TypeChange.NARROWING: RiskTier.IRREVERSIBLE,
    TypeChange.LATERAL: RiskTier.IRREVERSIBLE,
    TypeChange.WIDENING: RiskTier.REVERSIBLE,
    TypeChange.IDENTICAL: RiskTier.REVERSIBLE,
}


def tier_for_add_column(
    *, nullable: bool, has_default: bool, server_version: int | None = None
) -> RiskTier:
    """`ADD COLUMN`: additive when nullable, otherwise a lock risk.

    ``NOT NULL DEFAULT`` rewrites the table on PostgreSQL below 11; ``NOT NULL``
    without a default aborts outright on a non-empty table. Neither destroys
    data.

    With no ``server_version`` — the filesystem-only default — both NOT NULL
    forms take the more severe of the two readings available. When a database has
    said it is PostgreSQL 11 or newer, the ``DEFAULT`` form is a catalog write
    (#199) and drops to additive; the no-default form is a hard failure rather
    than a lock risk on every version, so it does not move.
    """
    if nullable:
        return RiskTier.ADDITIVE
    if has_default and server_version is not None and server_version >= FAST_DEFAULT_SINCE:
        return RiskTier.ADDITIVE
    return RiskTier.LOCK_RISKY


def tier_for_create_index(*, concurrently: bool) -> RiskTier:
    """`CREATE INDEX CONCURRENTLY` is additive; a plain one blocks writes."""
    return RiskTier.ADDITIVE if concurrently else RiskTier.LOCK_RISKY


def tier_for_add_constraint(*, not_valid: bool) -> RiskTier:
    """`NOT VALID` defers the scan; immediate validation locks and can reject rows."""
    return RiskTier.REVERSIBLE if not_valid else RiskTier.LOCK_RISKY
