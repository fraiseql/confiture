"""Phase 6 Rule Library System.

Provides:
- Rule versioning with deprecation paths
- Conflict detection and resolution
- Compliance libraries (HIPAA, SOX, GDPR, PCI-DSS, General)
- Transparent audit trails
"""
from __future__ import annotations

import sys
from pathlib import Path

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
    GeneralLibrary,
    GDPRLibrary,
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

# Import from parent linting.py (the old module) for backward compatibility
try:
    # Add parent directory to path temporarily to import the linting.py file
    import importlib.util
    linting_py_path = Path(__file__).parent.parent / "linting.py"
    spec = importlib.util.spec_from_file_location("_linting_legacy", linting_py_path)
    _linting_legacy = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(_linting_legacy)

    LintRule = _linting_legacy.LintRule
    NamingConventionRule = _linting_legacy.NamingConventionRule
    PrimaryKeyRule = _linting_legacy.PrimaryKeyRule
    DocumentationRule = _linting_legacy.DocumentationRule
    MultiTenantRule = _linting_legacy.MultiTenantRule
    MissingIndexRule = _linting_legacy.MissingIndexRule
    SecurityRule = _linting_legacy.SecurityRule
    # Also expose the legacy SchemaLinter and its dependencies for mocking in tests
    SchemaBuilder = _linting_legacy.SchemaBuilder
    SchemaDiffer = _linting_legacy.SchemaDiffer
except Exception:
    # If legacy import fails, try direct import (shouldn't happen in normal usage)
    pass

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
    # Legacy LintRule classes
    "LintRule",
    "NamingConventionRule",
    "PrimaryKeyRule",
    "DocumentationRule",
    "MultiTenantRule",
    "MissingIndexRule",
    "SecurityRule",
    # Legacy dependencies for testing
    "SchemaBuilder",
    "SchemaDiffer",
]
