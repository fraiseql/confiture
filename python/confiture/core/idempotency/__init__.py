"""Idempotency validation for SQL migrations.

This module provides tools to validate that SQL migrations are idempotent,
meaning they can be safely re-run without causing errors.
"""

from confiture.core.idempotency.fixer import FixChange, IdempotencyFixer
from confiture.core.idempotency.models import (
    IdempotencyPattern,
    IdempotencyReport,
    IdempotencyViolation,
)
from confiture.core.idempotency.patterns import PatternMatch, detect_non_idempotent_patterns
from confiture.core.idempotency.validator import IdempotencyValidator

__all__ = [
    "FixChange",
    "IdempotencyFixer",
    "IdempotencyPattern",
    "IdempotencyReport",
    "IdempotencyValidator",
    "IdempotencyViolation",
    "PatternMatch",
    "detect_non_idempotent_patterns",
]
