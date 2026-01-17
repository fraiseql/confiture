"""Rule Library System.

Provides:
- Rule versioning with deprecation paths
- Conflict detection and resolution
- Compliance libraries (HIPAA, SOX, GDPR, PCI-DSS, General)
- Transparent audit trails
"""
from __future__ import annotations

from .composer import (
    ComposedRuleSet,
    ConflictResolution,
    ConflictType,
    RuleConflict,
    RuleConflictError,
    RuleLibrary,
    RuleLibraryComposer,
)
from .libraries import (
    GDPRLibrary,
    GeneralLibrary,
    HIPAALibrary,
    PCI_DSSLibrary,
    SOXLibrary,
)
from .schema_linter import (
    LintConfig,
    LintReport,
    LintViolation,
    RuleSeverity,
    SchemaLinter,
)
from .versioning import (
    LintSeverity,
    Rule,
    RuleRemovedError,
    RuleVersion,
    RuleVersionManager,
)

__all__ = [
    # Versioning
    "RuleVersion",
    "Rule",
    "LintSeverity",
    "RuleVersionManager",
    "RuleRemovedError",
    # Composition
    "RuleLibrary",
    "RuleLibraryComposer",
    "ComposedRuleSet",
    "RuleConflict",
    "RuleConflictError",
    "ConflictResolution",
    "ConflictType",
    # Libraries
    "GeneralLibrary",
    "HIPAALibrary",
    "SOXLibrary",
    "GDPRLibrary",
    "PCI_DSSLibrary",
    # Schema Linter
    "SchemaLinter",
    "LintConfig",
    "LintReport",
    "LintViolation",
    "RuleSeverity",
]
