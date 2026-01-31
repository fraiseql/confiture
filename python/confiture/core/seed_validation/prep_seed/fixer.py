"""Auto-fixer for prep_seed violations.

Cycle 7: Implements auto-fixes for schema drift and other correctable issues.
"""

from __future__ import annotations

import re


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
