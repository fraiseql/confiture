"""Lint rule: replica-aware forward-compatibility (REPLICA001, issue #139).

Classifies each DDL operation in the migrations tree and flags those that are
not forward-compatible under streaming replication, with the multi-step
remediation. Severity follows the #139 policy (warn by default, error when the
project declares replicas; a config bypass downgrades errors to warnings).

One engine (`_iter_findings`) feeds two surfaces: the `confiture lint` rule
(`Replica001ForwardCompat`, LintViolations) and `migrate preflight`
(`replica_preflight_issues`, the #148 PreflightIssue / PFLIGHT_REPLICA_* shape).
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from confiture.core.linting.schema_linter import LintViolation, RuleSeverity
from confiture.core.replica.classifier import DdlOperation, OperationClassifier
from confiture.core.replica.safety import (
    ReplicaVerdict,
    classify_replica_safety,
    replica_severity,
)

if TYPE_CHECKING:
    from confiture.models.results import PreflightIssue

RULE_ID = "replica_001"
RULE_NAME = "replica-forward-compat"

# Operation class name → stable PFLIGHT_REPLICA_* code for the preflight surface.
REPLICA_CODE_BY_OP = {
    "AddColumn": "PFLIGHT_REPLICA_ADD_COLUMN",
    "DropColumn": "PFLIGHT_REPLICA_DROP_COLUMN",
    "RenameColumn": "PFLIGHT_REPLICA_RENAME_COLUMN",
    "ChangeColumnType": "PFLIGHT_REPLICA_CHANGE_TYPE",
    "AddConstraint": "PFLIGHT_REPLICA_ADD_CONSTRAINT",
    "CreateIndex": "PFLIGHT_REPLICA_CREATE_INDEX",
    "Other": "PFLIGHT_REPLICA_UNCLASSIFIED",
}


def replica_lint_codes() -> frozenset[str]:
    """The exact set of ``PFLIGHT_REPLICA_*`` codes the replica lint can emit.

    fraisier's blue-green **window-safety gate** keys on the *presence* of any of
    these in ``migrate preflight``'s ``issues[]`` to decide whether a migration is
    forward-compatible for a two-version shared-DB cutover window. This set is a
    **cross-repo stability commitment** (issue #154): renames/removals are
    breaking and require a major version bump; additions are allowed. It is the
    single source for that namespace — derived from :data:`REPLICA_CODE_BY_OP`, so
    there is no second copy of the code strings to drift. The contract test in
    ``tests/contract/test_fraisier_adapter_surface.py`` pins it.
    """
    return frozenset(REPLICA_CODE_BY_OP.values())


@dataclass(frozen=True)
class ReplicaFinding:
    """A single replica-unsafe (or unclassifiable) operation in a migration."""

    op: DdlOperation
    verdict: ReplicaVerdict
    severity: str  # "error" | "warning"
    migration_file: Path

    @property
    def code(self) -> str:
        return REPLICA_CODE_BY_OP.get(type(self.op).__name__, "PFLIGHT_REPLICA_UNCLASSIFIED")

    @property
    def message(self) -> str:
        msg = self.verdict.reason or "Operation is not replica-forward-compatible."
        if self.verdict.multi_step:
            msg += f" Multi-step fix: {self.verdict.multi_step}."
        return msg


def _iter_findings(
    migrations_dir: Path, *, has_replicas: bool, bypass: bool
) -> Iterator[ReplicaFinding]:
    """Yield one finding per replica-unsafe / unclassifiable operation."""
    if not migrations_dir.exists():
        return
    classifier = OperationClassifier()
    for migration in sorted(migrations_dir.glob("*.up.sql")):
        text = migration.read_text()
        for op in classifier.classify(text):
            verdict = classify_replica_safety(op)
            if verdict.safety == "safe":
                continue
            severity = replica_severity(verdict, has_replicas=has_replicas, bypass=bypass)
            yield ReplicaFinding(
                op=op, verdict=verdict, severity=severity, migration_file=migration
            )


class Replica001ForwardCompat:
    """Flag replica-unsafe single-step DDL with multi-step guidance (`confiture lint`)."""

    category = "replica"  # rule-selection tag for `confiture lint --replica-safe`

    def __init__(self, *, has_replicas: bool = False, bypass: bool = False) -> None:
        self.has_replicas = has_replicas
        self.bypass = bypass

    def check(self, migrations_dir: Path) -> list[LintViolation]:
        """Return one LintViolation per replica-unsafe / unclassifiable operation."""
        return [
            LintViolation(
                rule_id=RULE_ID,
                rule_name=RULE_NAME,
                severity=RuleSeverity(f.severity),
                object_type="migration",
                object_name=f.op.table or f.migration_file.name,
                message=f.message,
                file_path=str(f.migration_file),
                line_number=f.op.line,
            )
            for f in _iter_findings(
                migrations_dir, has_replicas=self.has_replicas, bypass=self.bypass
            )
        ]


def _unreadable_migrations(migrations_dir: Path) -> Iterator[Path]:
    """Yield migration files the SQL replica classifier cannot read.

    Mirrors ``run_preflight``'s Python-migration discovery filter (skip
    ``__init__.py`` and ``_``-prefixed helpers). A ``.py`` migration is opaque to
    the SQL classifier, so its forward-compatibility cannot be certified.
    """
    if not migrations_dir.exists():
        return
    yield from sorted(
        (
            f
            for f in migrations_dir.glob("*.py")
            if f.name != "__init__.py" and not f.name.startswith("_")
        ),
        key=lambda f: f.name,
    )


def replica_preflight_issues(
    migrations_dir: Path, *, has_replicas: bool, bypass: bool
) -> list[PreflightIssue]:
    """Return replica findings as PreflightIssues (#148 shape) for preflight.

    Covers both the SQL operations the classifier reads (``*.up.sql``) and, per
    issue #154, the migrations it *cannot* read (``*.py``) — the latter surface as
    ``PFLIGHT_REPLICA_UNCLASSIFIED`` warnings so "no replica issue" can never
    silently mean "never inspected". UNCLASSIFIED is always a warning (opacity
    never hard-blocks).
    """
    from confiture.models.results import PreflightIssue

    issues = [
        PreflightIssue(
            severity=f.severity,
            code=f.code,
            message=f.message,
            migration=f.op.table,
            file=f.migration_file.name,
            actionable=f.verdict.multi_step,
            details={"operation": type(f.op).__name__},
        )
        for f in _iter_findings(migrations_dir, has_replicas=has_replicas, bypass=bypass)
    ]
    issues.extend(
        PreflightIssue(
            severity="warning",
            code="PFLIGHT_REPLICA_UNCLASSIFIED",
            message=(
                "non-SQL (.py) migration: the replica forward-compatibility "
                "classifier cannot inspect it, so window-safety cannot be "
                "certified automatically; review manually"
            ),
            migration=None,
            file=py.name,
            actionable=(
                "review the migration's DDL by hand for replica "
                "forward-compatibility, or express the schema change as a "
                ".up.sql so it can be classified"
            ),
            details={"operation": "NonSqlMigration"},
        )
        for py in _unreadable_migrations(migrations_dir)
    )
    return issues


def is_window_safe(issues: Iterable[PreflightIssue]) -> bool:
    """Whether a preflight issue set certifies blue-green window safety (#154).

    The typed form of fraisier's gate: ``True`` iff no replica forward-compat
    finding is present. Reuses :func:`replica_lint_codes` so the verdict tracks the
    pinned namespace exactly. With the ``*.py`` coverage above this is total — a
    ``False`` means "blocked or uninspected", a ``True`` means "inspected and
    forward-compatible for a two-version shared-DB window".
    """
    codes = replica_lint_codes()
    return not any(issue.code in codes for issue in issues)
