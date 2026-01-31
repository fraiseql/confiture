"""Seed data validation for consistent seed files.

This module provides tools to validate that seed files contain correct SQL
and don't have common issues like double semicolons or missing ON CONFLICT
clauses.
"""

from confiture.core.seed_validation.database_validator import (
    DatabaseSeedValidator,
)
from confiture.core.seed_validation.fixer import FixResult, SeedFixer
from confiture.core.seed_validation.models import (
    SeedValidationPattern,
    SeedValidationReport,
    SeedViolation,
)
from confiture.core.seed_validation.patterns import (
    PatternMatch,
    detect_seed_issues,
)
from confiture.core.seed_validation.validator import SeedValidator

__all__ = [
    "DatabaseSeedValidator",
    "FixResult",
    "PatternMatch",
    "SeedFixer",
    "SeedValidator",
    "SeedValidationPattern",
    "SeedValidationReport",
    "SeedViolation",
    "detect_seed_issues",
]
