"""Rule versioning and compatibility management - Phase 6."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class LintSeverity(Enum):
    """Severity levels for linting rules."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass
class RuleVersion:
    """Semantic version for rules."""

    major: int
    minor: int
    patch: int

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"

    def is_compatible_with(self, other: RuleVersion) -> bool:
        """Check if compatible (major version must match)."""
        return self.major == other.major

    def __le__(self, other: RuleVersion) -> bool:
        return (self.major, self.minor, self.patch) <= (
            other.major,
            other.minor,
            other.patch,
        )

    def __ge__(self, other: RuleVersion) -> bool:
        return (self.major, self.minor, self.patch) >= (
            other.major,
            other.minor,
            other.patch,
        )

    def __lt__(self, other: RuleVersion) -> bool:
        return (self.major, self.minor, self.patch) < (
            other.major,
            other.minor,
            other.patch,
        )

    def __gt__(self, other: RuleVersion) -> bool:
        return (self.major, self.minor, self.patch) > (
            other.major,
            other.minor,
            other.patch,
        )

    def __eq__(self, other: RuleVersion) -> bool:
        return (self.major, self.minor, self.patch) == (
            other.major,
            other.minor,
            other.patch,
        )


@dataclass
class Rule:
    """Individual linting rule with versioning."""

    rule_id: str
    name: str
    description: str
    version: RuleVersion
    deprecated_in: RuleVersion | None = None
    removed_in: RuleVersion | None = None
    migration_path: str | None = None  # Docs URL or replacement rule ID
    severity: LintSeverity = LintSeverity.WARNING
    enabled_by_default: bool = True

    def is_deprecated(self, target_version: RuleVersion | None = None) -> bool:
        """Check if rule is deprecated."""
        if not self.deprecated_in:
            return False
        if target_version:
            return self.deprecated_in <= target_version
        return True

    def is_removed(self, target_version: RuleVersion | None = None) -> bool:
        """Check if rule is removed."""
        if not self.removed_in:
            return False
        if target_version:
            return self.removed_in <= target_version
        return True


class RuleRemovedError(Exception):
    """Exception raised when accessing a removed rule."""

    pass


class RuleVersionManager:
    """Manage rule versions and compatibility."""

    def __init__(self, rules: list[Rule]):
        self.rules = {r.rule_id: r for r in rules}

    def get_rule(
        self,
        rule_id: str,
        target_version: RuleVersion | None = None,
    ) -> Rule | None:
        """Get rule compatible with target version."""
        rule = self.rules.get(rule_id)
        if not rule:
            return None

        if rule.is_removed(target_version):
            raise RuleRemovedError(
                f"Rule {rule_id} was removed in {rule.removed_in}. "
                f"Migration path: {rule.migration_path}"
            )

        if rule.is_deprecated(target_version):
            logger.warning(
                f"Rule {rule_id} is deprecated since {rule.deprecated_in}. "
                f"Migration path: {rule.migration_path}"
            )

        return rule

    def validate_compatibility(
        self,
        library_version: RuleVersion,
        min_rule_version: RuleVersion,
    ) -> list[str]:
        """Check if all rules are compatible with version."""
        incompatible = []
        for rule in self.rules.values():
            if not rule.version.is_compatible_with(min_rule_version):
                incompatible.append(rule.rule_id)
        return incompatible
