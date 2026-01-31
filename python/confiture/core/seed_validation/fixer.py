"""Auto-fix functionality for seed data validation issues.

This module provides automated corrections for common seed data issues.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass
class FixResult:
    """Result of an auto-fix operation.

    Attributes:
        fixes_applied: Number of fixes applied
        dry_run: Whether this was a dry-run
        modified_content: The modified SQL content (if dry-run=True)
    """

    fixes_applied: int
    dry_run: bool
    modified_content: str | None = None


class SeedFixer:
    """Auto-fix for seed data validation issues.

    Provides automatic corrections for common issues found by
    SeedValidator, such as adding missing ON CONFLICT clauses.

    Example:
        >>> fixer = SeedFixer()
        >>> result = fixer.fix_file(Path("seeds.sql"), dry_run=True)
        >>> if result.fixes_applied > 0:
        ...     print(f"Would fix {result.fixes_applied} issues")
    """

    def fix_missing_on_conflict(self, sql: str) -> str:
        """Add ON CONFLICT DO NOTHING to INSERT statements without it.

        Args:
            sql: SQL content to fix

        Returns:
            Fixed SQL with ON CONFLICT clauses added
        """
        # Pattern: INSERT ... VALUES ... ; (without ON CONFLICT)
        # This regex finds INSERT statements that end with ); but don't have ON CONFLICT
        pattern = r"(INSERT\s+INTO\s+\w+\s*\([^)]*\)\s+VALUES\s*\([^)]*\))\s*;"

        def replacer(match: re.Match[str]) -> str:
            statement = match.group(1)
            # Check if it already has ON CONFLICT
            if "ON CONFLICT" in statement:
                return match.group(0)
            return f"{statement} ON CONFLICT DO NOTHING;"

        return re.sub(pattern, replacer, sql, flags=re.IGNORECASE | re.MULTILINE)

    def fix_file(
        self,
        file_path: Path,
        dry_run: bool = False,
        patterns: list[str] | None = None,
    ) -> FixResult:
        """Auto-fix issues in a seed file.

        Args:
            file_path: Path to the seed file
            dry_run: If True, don't modify the file
            patterns: List of patterns to fix (default: all)

        Returns:
            FixResult with details of fixes applied
        """
        if not file_path.exists():
            return FixResult(fixes_applied=0, dry_run=dry_run)

        original_content = file_path.read_text(encoding="utf-8")
        modified_content = original_content

        # Apply fixes
        fixes_count = 0

        # Fix missing ON CONFLICT
        if patterns is None or "on_conflict" in patterns:
            fixed_once = modified_content
            modified_content = self.fix_missing_on_conflict(modified_content)
            if fixed_once != modified_content:
                fixes_count += 1

        # Write back if not dry-run
        if not dry_run and fixes_count > 0:
            file_path.write_text(modified_content, encoding="utf-8")

        return FixResult(
            fixes_applied=fixes_count,
            dry_run=dry_run,
            modified_content=modified_content if dry_run else None,
        )
