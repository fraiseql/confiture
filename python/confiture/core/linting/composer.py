"""Rule library composition with explicit conflict handling - Phase 6."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum

from .versioning import LintSeverity, Rule, RuleVersion

logger = logging.getLogger(__name__)


class ConflictResolution(Enum):
    """How to handle rule conflicts."""

    ERROR = "error"  # Raise exception
    WARN = "warn"  # Log warning, continue
    PREFER_FIRST = "prefer_first"  # Use first added library's rule
    PREFER_LAST = "prefer_last"  # Use last added library's rule


class ConflictType(Enum):
    """Type of conflict between rules."""

    DUPLICATE = "duplicate"  # Same rule ID
    INCOMPATIBLE = "incompatible"  # Conflicting requirements
    OVERLAPPING = "overlapping"  # Similar functionality


@dataclass
class RuleConflict:
    """Represents a conflict between rules."""

    rule_id: str
    library_a: str
    library_b: str
    conflict_type: ConflictType
    severity: LintSeverity
    description: str
    suggested_resolution: str


class RuleConflictError(Exception):
    """Exception raised when rule conflicts are detected."""

    pass


class RuleLibrary:
    """Collection of related rules."""

    def __init__(
        self,
        name: str,
        version: RuleVersion,
        rules: list[Rule],
        tags: list[str] | None = None,
    ):
        self.name = name
        self.version = version
        self.rules = {r.rule_id: r for r in rules}
        self.tags = tags or []

    def get_rules(self) -> list[Rule]:
        """Get all rules in this library."""
        return list(self.rules.values())


class RuleLibraryComposer:
    """Compose multiple libraries with explicit conflict handling."""

    def __init__(self):
        self.libraries: list[RuleLibrary] = []
        self.overrides: dict[str, Rule] = {}
        self.disabled_rules: set[str] = set()
        self.conflict_log: list[RuleConflict] = []

    def add_library(
        self,
        library: RuleLibrary,
        on_conflict: ConflictResolution = ConflictResolution.ERROR,
    ) -> RuleLibraryComposer:
        """Add library with conflict handling."""
        conflicts = self._detect_conflicts(library)

        if conflicts:
            self.conflict_log.extend(conflicts)

            if on_conflict == ConflictResolution.ERROR:
                raise RuleConflictError(
                    f"Found {len(conflicts)} rule conflicts in {library.name}"
                )
            elif on_conflict == ConflictResolution.WARN:
                for conflict in conflicts:
                    logger.warning(
                        f"Rule conflict: {conflict.rule_id} in {conflict.library_a} "
                        f"vs {conflict.library_b}. {conflict.suggested_resolution}"
                    )

        self.libraries.append(library)
        return self

    def override_rule(self, rule_id: str, new_rule: Rule) -> RuleLibraryComposer:
        """Override a specific rule."""
        self.overrides[rule_id] = new_rule
        logger.info(f"Overridden rule {rule_id}")
        return self

    def disable_rule(self, rule_id: str) -> RuleLibraryComposer:
        """Disable a rule from any library."""
        self.disabled_rules.add(rule_id)
        logger.info(f"Disabled rule {rule_id}")
        return self

    def build(self) -> ComposedRuleSet:
        """Build final rule set with conflicts resolved."""
        all_rules = {}

        for library in self.libraries:
            for rule_id, rule in library.rules.items():
                if rule_id in self.disabled_rules:
                    continue
                all_rules[rule_id] = rule

        # Apply overrides
        all_rules.update(self.overrides)

        # Create audit trail
        return ComposedRuleSet(
            rules=list(all_rules.values()),
            libraries=[lib.name for lib in self.libraries],
            disabled_rules=list(self.disabled_rules),
            overridden_rules=list(self.overrides.keys()),
            conflicts=self.conflict_log,
        )

    def _detect_conflicts(self, new_library: RuleLibrary) -> list[RuleConflict]:
        """Detect conflicts with existing libraries."""
        conflicts = []
        new_rule_ids = set(new_library.rules.keys())

        for existing_library in self.libraries:
            for existing_rule_id in existing_library.rules.keys():
                if existing_rule_id in new_rule_ids:
                    conflicts.append(
                        RuleConflict(
                            rule_id=existing_rule_id,
                            library_a=existing_library.name,
                            library_b=new_library.name,
                            conflict_type=ConflictType.DUPLICATE,
                            severity=LintSeverity.WARNING,
                            description=f"Rule {existing_rule_id} exists in both libraries",
                            suggested_resolution=(
                                "Use override_rule() to select preferred version"
                            ),
                        )
                    )

        return conflicts


@dataclass
class ComposedRuleSet:
    """Result of composing multiple rule libraries."""

    rules: list[Rule]
    libraries: list[str]  # Which libraries were composed
    disabled_rules: list[str] = field(default_factory=list)  # Which rules were disabled
    overridden_rules: list[str] = field(default_factory=list)  # Which rules were overridden
    conflicts: list[RuleConflict] = field(default_factory=list)

    def get_audit_trail(self) -> str:
        """Get human-readable audit trail."""
        lines = [
            f"Libraries: {', '.join(self.libraries)}",
            f"Total rules: {len(self.rules)}",
            f"Disabled: {len(self.disabled_rules)} ({', '.join(self.disabled_rules)})",
            f"Overridden: {len(self.overridden_rules)}",
            f"Conflicts: {len(self.conflicts)}",
        ]
        return "\n".join(lines)

    def get_rules_by_severity(self, severity: LintSeverity) -> list[Rule]:
        """Get all rules of a specific severity."""
        return [r for r in self.rules if r.severity == severity]

    def get_enabled_rules(self) -> list[Rule]:
        """Get all enabled rules."""
        return [r for r in self.rules if r.enabled_by_default]

    def get_disabled_rules_info(self) -> list[str]:
        """Get info about disabled rules."""
        return self.disabled_rules
