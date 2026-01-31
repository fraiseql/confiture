"""Auto-fixer for prep_seed violations.

Implements auto-fixes for schema drift and other correctable issues.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from confiture.core.seed_validation.prep_seed.models import PrepSeedViolation


@dataclass
class FixResult:
    """Result of applying fixes to a file."""

    file_path: Path
    fixes_applied: int
    fixed_violations: list[PrepSeedViolation]


class PrepSeedFixer:
    """Auto-fixes prep_seed validation violations.

    Example:
        >>> fixer = PrepSeedFixer()
        >>> fixed_sql = fixer.fix_schema_drift(
        ...     "INSERT INTO tenant.tb_x",
        ...     "tb_x",
        ...     "catalog"
        ... )
    """

    def fix_violations(
        self,
        violations: list[PrepSeedViolation],
        dry_run: bool = False,
    ) -> dict[str, int]:
        """Fix all auto-fixable violations.

        Groups violations by file and applies fixes where available.
        Returns a summary of fixes applied per file.

        Args:
            violations: List of violations to fix
            dry_run: If True, don't modify files, just return fix count

        Returns:
            Dictionary mapping file paths to number of fixes applied
        """
        # Group violations by file
        violations_by_file: dict[str, list[PrepSeedViolation]] = defaultdict(
            list
        )
        for violation in violations:
            if violation.fix_available:
                violations_by_file[violation.file_path].append(violation)

        # Apply fixes to each file
        fixes_summary: dict[str, int] = {}

        for file_path_str, file_violations in violations_by_file.items():
            file_path = Path(file_path_str)

            try:
                # Read file content
                content = file_path.read_text()
                original_content = content

                # Apply fixes
                for violation in file_violations:
                    if (
                        violation.pattern.name
                        == "SCHEMA_DRIFT_IN_RESOLVER"
                    ):
                        # Extract schema info from violation
                        # This is a simple fix for schema drift
                        content = self.fix_schema_drift_from_message(
                            content, violation.message
                        )

                # Count fixes applied
                fix_count = 0
                if content != original_content:
                    fix_count = len(file_violations)

                    # Write back unless dry_run
                    if not dry_run:
                        file_path.write_text(content)

                    fixes_summary[file_path_str] = fix_count

            except OSError:
                # Skip files that can't be read/written
                pass

        return fixes_summary

    def fix_schema_drift(
        self,
        sql: str,
        table_name: str,
        correct_schema: str,
        wrong_schema: str | None = None,
    ) -> str:
        """Fix schema drift by updating schema references.

        Replaces occurrences of <wrong_schema>.<table_name> with
        <correct_schema>.<table_name> in the SQL.

        Args:
            sql: SQL content to fix
            table_name: Table name being referenced (e.g., "tb_manufacturer")
            correct_schema: Correct schema name (e.g., "catalog")
            wrong_schema: Wrong schema name to replace (e.g., "tenant").
                Required to avoid replacing prep_seed references.

        Returns:
            Fixed SQL with correct schema references
        """
        if not wrong_schema:
            raise ValueError("wrong_schema parameter is required")

        # Pattern to match wrong_schema.table_name (case-insensitive)
        pattern = rf"{re.escape(wrong_schema)}\.{re.escape(table_name)}\b"

        # Replace with correct_schema.table_name
        replacement = rf"{correct_schema}.{table_name}"

        return re.sub(
            pattern,
            replacement,
            sql,
            flags=re.IGNORECASE,
        )

    def fix_schema_drift_from_message(
        self,
        sql: str,
        message: str,
    ) -> str:
        """Fix schema drift based on violation message.

        Attempts to extract schema information from violation message
        and apply fixes. This is a best-effort approach.

        Args:
            sql: SQL content to fix
            message: Violation message describing the drift

        Returns:
            Fixed SQL (or original if fix cannot be determined)
        """
        # Try to parse message like:
        # "Function refs tenant.tb_x but table in catalog.tb_x"
        pattern = r"refs\s+(\w+)\.(\w+)\s+but\s+table\s+in\s+(\w+)\."
        match = re.search(pattern, message, re.IGNORECASE)

        if match:
            wrong_schema = match.group(1)
            table_name = match.group(2)
            correct_schema = match.group(3)

            return self.fix_schema_drift(
                sql,
                table_name,
                correct_schema,
                wrong_schema,
            )

        return sql
