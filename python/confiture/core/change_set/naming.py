"""Object naming for change entries: qualification, quoting, and the safe statement prefix."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from confiture.core.lock_profile import (
    profile_for_kind,
)
from confiture.core.risk_tier import RiskTier
from confiture.core.schema_facts import SchemaFacts
from confiture.core.type_lattice import (
    TypeChange,
    changes_rewrite_table,
    compare_types,
)

if TYPE_CHECKING:
    pass
from confiture.core.change_set.models import (
    _ALTER_COLUMN_TYPE_DETAIL,
    _DEFAULT_SCHEMA,
    _TIER_BY_DIRECTION,
    _TIER_BY_KIND,
    ChangeEntry,
)


@dataclass(frozen=True)
class _Context:
    """What every entry produced from one file gets stamped with."""

    migration: str | None = None
    source: str | None = None
    default_schema: str = _DEFAULT_SCHEMA
    facts: SchemaFacts | None = None
    """What a live database told us, when one was reachable (#199). Absent on the
    filesystem-only path, where every refinement falls back to its static answer."""

    @property
    def server_version(self) -> int | None:
        return self.facts.server_version if self.facts else None

    def entry(
        self,
        kind: str,
        obj: str | None = None,
        *,
        detail: str | None = None,
        tier: RiskTier | None = None,
        **lock_attrs: bool,
    ) -> ChangeEntry:
        """Build an entry, defaulting the tier from :data:`_TIER_BY_KIND`.

        ``lock_attrs`` are the statement attributes the lock table needs for the
        kinds whose cost is not decided by the kind alone (``concurrently``,
        ``not_valid``, ``has_default``).
        """
        return ChangeEntry(
            kind=kind,
            object=obj or self.source or "unknown",
            migration=self.migration,
            tier=tier if tier is not None else _TIER_BY_KIND.get(kind),
            detail=detail,
            lock=profile_for_kind(kind, server_version=self.server_version, **lock_attrs),
        )

    def unclassified(self, kind: str, obj: str | None, detail: str) -> ChangeEntry:
        """An entry confiture will not tier. Explicitly tier-less, never dropped."""
        return ChangeEntry(
            kind=kind,
            object=obj or self.source or "unknown",
            migration=self.migration,
            tier=None,
            detail=detail,
            lock=profile_for_kind(kind, server_version=self.server_version),
        )

    def alter_column_type(
        self, target: str | None, column: str | None, new_type: str | None
    ) -> ChangeEntry:
        """`ALTER COLUMN … TYPE`, tiered only when the *current* type is known.

        SQL states the target and never the source, so the direction is knowable
        only from a live database (or a differ). Without it the entry stays
        tier-less, exactly as it was before #199 — an honest absence rather than a
        confident guess in either direction.
        """
        old_type = self.facts.column_type(target) if self.facts else None
        direction = compare_types(old_type, new_type)
        rewrites = changes_rewrite_table(old_type, new_type) if old_type else None
        lock = profile_for_kind(
            "alter_column_type", rewrites=rewrites, server_version=self.server_version
        )
        label = f"ALTER COLUMN {_ident(column)} TYPE"

        if direction in (TypeChange.UNKNOWN, TypeChange.IDENTICAL) and old_type is None:
            return ChangeEntry(
                kind="alter_column_type",
                object=target or self.source or "unknown",
                migration=self.migration,
                tier=None,
                detail=f"{label} — {_ALTER_COLUMN_TYPE_DETAIL}",
                lock=lock,
            )
        if direction is TypeChange.UNKNOWN:
            return ChangeEntry(
                kind="alter_column_type",
                object=target or self.source or "unknown",
                migration=self.migration,
                tier=None,
                detail=f"{label} {old_type} → {new_type} — confiture does not model one of "
                "these types, so the direction is unknown",
                lock=lock,
            )
        rewrite_note = "rewrites the table" if lock.rewrites_table else "no rewrite"
        tier = _TIER_BY_DIRECTION[direction]
        if tier is RiskTier.REVERSIBLE and lock.rewrites_table:
            # Safe for the data, but an ACCESS EXCLUSIVE heap rewrite all the same.
            tier = RiskTier.LOCK_RISKY
        return ChangeEntry(
            kind="alter_column_type",
            object=target or self.source or "unknown",
            migration=self.migration,
            tier=tier,
            detail=f"{label} {old_type} → {new_type} — {direction.value}, {rewrite_note}",
            lock=lock,
        )

    def qualified(self, schema: str | None, name: str | None, child: str | None = None) -> str:
        """`schema.name[.child]`, defaulting the schema when the DDL omits one."""
        parts = [_ident(schema) or self.default_schema, _ident(name)]
        if child:
            parts.append(_ident(child))
        return ".".join(part for part in parts if part)

    def dotted(self, raw: str | None, child: str | None = None) -> str | None:
        """Qualify an already-dotted identifier such as ``app.tb_user``.

        With a ``child``, ``raw`` is the relation and ``child`` the leaf; without
        one, ``raw`` may itself already carry the leaf (``app.tb_user.nickname``).
        """
        if not raw:
            return None
        parts = _split_dotted(raw)
        if child is None:
            return self.from_parts(parts)
        if len(parts) >= 2:
            return self.qualified(parts[-2], parts[-1], child)
        return self.qualified(None, parts[0], child)

    def bare(self, raw: str | None) -> str | None:
        """A name that is not schema-scoped (a schema, an extension, a role)."""
        if not raw:
            return None
        return _ident(_split_dotted(raw)[-1])

    def from_parts(self, parts: list[str]) -> str | None:
        """Qualify already-split identifier parts.

        Three parts is ``schema.table.child`` — a column, or a trigger/policy
        whose name is scoped to its table. Taking only the last two would report
        the *table* as the schema.
        """
        if not parts:
            return None
        if len(parts) >= 3:
            return self.qualified(parts[-3], parts[-2], parts[-1])
        if len(parts) == 2:
            return self.qualified(parts[0], parts[1])
        return self.qualified(None, parts[0])


def _ident(raw: str | None) -> str | None:
    """An identifier as pglast spells it: quotes stripped, case kept.

    pglast has already folded unquoted identifiers; folding again would turn a
    quoted ``"MyTable"`` into a different relation.
    """
    if raw is None:
        return None
    text = str(raw).strip()
    if text.startswith('"') and text.endswith('"') and len(text) > 1:
        return text[1:-1]
    return text


def _split_dotted(raw: str) -> list[str]:
    """Split ``a.b`` on dots, keeping quoted segments intact."""
    parts: list[str] = []
    buf: list[str] = []
    in_quotes = False
    for char in raw.strip():
        if char == '"':
            in_quotes = not in_quotes
            buf.append(char)
        elif char == "." and not in_quotes:
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(char)
    parts.append("".join(buf))
    return [part for part in parts if part]


def _command_prefix(statement: str, *, words: int = 5) -> str:
    """The leading keywords of a statement, with every literal stripped.

    ``detail`` is rendered to an operator and must never carry a credential, and
    an unclassified statement is exactly the kind that might hold one
    (``CREATE USER … PASSWORD 'x'``). Only bare word tokens survive.
    """
    tokens: list[str] = []
    for token in statement.split():
        if not re.fullmatch(r"[A-Za-z_][\w$.]*", token):
            break
        tokens.append(token)
        if len(tokens) >= words:
            break
    return " ".join(tokens) or "statement"
