"""The destructive gate: who may generate, and who may apply, a migration that loses data.

A change at tier ``destructive`` or ``irreversible`` (the change set's words:
a dropped table or column, a narrowed type) is generated under a policy —
``migration.destructive`` in the environment config, overridden per run by
``--allow-destructive`` / ``--forbid-destructive`` on ``migrate diff``:

* ``gated`` (the default) writes the DDL and marks the up file with a
  ``-- confiture:destructive`` directive; ``migrate up`` refuses such a file
  (``VALID_002``, exit 5) unless it runs with ``--allow-destructive``.
* ``allow`` writes the DDL unmarked.
* ``forbid`` refuses to generate (``DIFFER_401``, exit 5).

The tiers that gate are named here, not derived from the tier ordering: the
ordering picks the worst of a set, policy maps each tier to an action.
"""

from __future__ import annotations

from typing import Literal

from confiture.core.risk_tier import RiskTier
from confiture.core.sql_lexer import DIRECTIVE_PREFIX, directives
from confiture.exceptions import ValidationError
from confiture.models.schema import SchemaChange

Policy = Literal["gated", "allow", "forbid"]

POLICIES: tuple[Policy, ...] = ("gated", "allow", "forbid")
GATE_DIRECTIVE = "destructive"
GATE_LINE = f"-- {DIRECTIVE_PREFIX}{GATE_DIRECTIVE}"
GATED_TIERS = frozenset({RiskTier.DESTRUCTIVE, RiskTier.IRREVERSIBLE})


def resolve_policy(configured: str, *, allow: bool = False, forbid: bool = False) -> Policy:
    """The policy for this run: a flag overrides the configured value."""
    if allow and forbid:
        raise ValidationError(
            "--allow-destructive and --forbid-destructive cannot both be given",
            resolution_hint="Pass one of them, or neither to use migration.destructive from the config",
        )
    if allow:
        return "allow"
    if forbid:
        return "forbid"
    for policy in POLICIES:
        if configured == policy:
            return policy
    raise ValidationError(
        f"migration.destructive must be one of {', '.join(POLICIES)}; got {configured!r}",
    )


def gates(tier: RiskTier | None) -> bool:
    """Whether a statement at ``tier`` falls under the gate."""
    return tier in GATED_TIERS


def is_gated(sql: str) -> bool:
    """Whether a SQL migration carries the ``-- confiture:destructive`` directive."""
    return any(d.name == GATE_DIRECTIVE for d in directives(sql))


IRREVERSIBLE_DIRECTIVE = "irreversible"
DATA_LOSS_TYPES = frozenset({"DROP_TABLE", "DROP_COLUMN"})


def irreversible_line(reason: str) -> str:
    """The ``-- confiture:irreversible <reason>`` directive line."""
    return f"-- {DIRECTIVE_PREFIX}{IRREVERSIBLE_DIRECTIVE} {reason}"


def no_rollback(change: SchemaChange) -> str:
    """The reason written when no down statement can be derived for ``change``."""
    target = ".".join(part for part in (change.table, change.column) if part)
    return f"no rollback derived for {change.type} {target}".rstrip()


def irreversible_reason(change: SchemaChange, *, has_down: bool) -> str | None:
    """Why ``change`` cannot be fully undone, or ``None`` when it can.

    ``data``: the down file recreates the table or column, never its rows.
    Otherwise, the down file has nothing for it at all.
    """
    if (reason := data_loss_reason(change)) is not None:
        return reason
    if not has_down:
        return no_rollback(change)
    return None


def data_loss_reason(change: SchemaChange) -> str | None:
    """``data`` for a change whose rows no down file can bring back; ``None`` otherwise."""
    return "data" if change.type in DATA_LOSS_TYPES else None


def irreversible_reasons(sql: str) -> list[str]:
    """The distinct ``-- confiture:irreversible <reason>`` reasons a SQL migration declares, in order."""
    seen: list[str] = []
    for d in directives(sql):
        if d.name == IRREVERSIBLE_DIRECTIVE and d.argument and d.argument not in seen:
            seen.append(d.argument)
    return seen
