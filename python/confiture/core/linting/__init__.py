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
    "ComposedRuleSet",
    "ConflictResolution",
    "ConflictType",
    "GDPRLibrary",
    # Libraries
    "GeneralLibrary",
    "HIPAALibrary",
    "LintConfig",
    "LintReport",
    "LintSeverity",
    "LintViolation",
    "PCI_DSSLibrary",
    "Rule",
    "RuleConflict",
    "RuleConflictError",
    # Composition
    "RuleLibrary",
    "RuleLibraryComposer",
    "RuleRemovedError",
    "RuleSeverity",
    # Versioning
    "RuleVersion",
    "RuleVersionManager",
    "SOXLibrary",
    # Schema Linter
    "SchemaLinter",
]
