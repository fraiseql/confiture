"""``migrate up --online``: whether a SQL migration can apply as expand/contract stages.

When the operator asked for ``--online`` and every statement of a pending
``.up.sql`` has a staged plan (:func:`~confiture.core.expand_contract.plannable`),
the apply loop runs it through :class:`~confiture.core._migrator.apply.Online`
— the same pipeline, hooks and preconditions as every other migration.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from confiture.core.expand_contract import StagedPlan, plannable
from confiture.core.schema_facts import server_major


def online_plans(migration_file: Path, connection: Any) -> list[StagedPlan] | None:
    """The staged plans for a ``.up.sql`` file, or ``None`` when it must apply the classic way."""
    if not migration_file.name.endswith(".up.sql"):
        return None
    sql = migration_file.read_text(encoding="utf-8")
    return plannable(sql, server_version=server_major(connection))
