"""Level 2: Schema consistency validation.

Validates schema mapping, FK types, trinity pattern, self-references — over the
tables of the one schema model (``core/schema_model.py``) the whole tree reads
into.
"""

from __future__ import annotations

from collections.abc import Callable

from confiture.core.schema_model import Table
from confiture.core.seed.validation.prep_seed.models import (
    PrepSeedPattern,
    PrepSeedViolation,
    ViolationSeverity,
)


def _column_names(table: Table) -> list[str]:
    return [column.folded for column in table.columns]


class Level2SchemaValidator:
    """Validates schema consistency between prep_seed and final tables.

    Checks:
    - Final table exists for each prep_seed table
    - FK columns map correctly (UUID -> BIGINT)
    - Trinity pattern in final tables (id UUID, pk_* BIGINT, fk_* BIGINT)
    - Self-references handled correctly

    Example:
        >>> validator = Level2SchemaValidator()
        >>> violations = validator.validate_schema_mapping(prep_table)
    """

    def __init__(
        self,
        get_final_table: Callable[[str], Table | None] | None = None,
        *,
        locate: Callable[[Table], tuple[str, int]] | None = None,
        locate_resolver: Callable[[Table], tuple[str, int] | None] | None = None,
        prep_seed_schema: str = "prep_seed",
        catalog_schema: str = "catalog",
    ) -> None:
        """Initialize the validator.

        Args:
            get_final_table: Optional function to look up final table by name.
            locate: ``(file, line)`` a table is created on, for a finding about
                it; without one a finding names the table itself.
            locate_resolver: ``(file, line)`` of the resolver that fills a prep
                table, when the schema defines one.
            prep_seed_schema: The schema seeds are loaded into.
            catalog_schema: The schema the resolvers fill.
        """
        self.get_final_table = get_final_table
        self._locate = locate
        self._locate_resolver = locate_resolver
        self.prep_seed_schema = prep_seed_schema
        self.catalog_schema = catalog_schema

    def _at(self, table: Table) -> tuple[str, int]:
        """Where a finding about *table* points."""
        if self._locate is not None:
            return self._locate(table)
        return (f"{table.schema}.{table.name}" if table.schema else table.name), 1

    def _resolver_or(self, table: Table) -> tuple[str, int]:
        """The resolver that fills *table*, where the schema defines one; else *table*."""
        found = self._locate_resolver(table) if self._locate_resolver is not None else None
        return found or self._at(table)

    def validate_schema_mapping(
        self,
        prep_table: Table,
    ) -> list[PrepSeedViolation]:
        """Validate schema mapping for a prep_seed table.

        Args:
            prep_table: The prep_seed table definition

        Returns:
            List of violations found
        """
        violations: list[PrepSeedViolation] = []

        # Check if final table exists
        if not self.get_final_table:
            return violations

        final_table = self.get_final_table(prep_table.name)
        if not final_table:
            violations.append(
                PrepSeedViolation(
                    pattern=PrepSeedPattern.MISSING_FK_MAPPING,
                    severity=ViolationSeverity.ERROR,
                    message=(
                        f"{self.prep_seed_schema}.{prep_table.name} has no corresponding "
                        f"final table {self.catalog_schema}.{prep_table.name}"
                    ),
                    file_path=self._at(prep_table)[0],
                    line_number=self._at(prep_table)[1],
                    impact="Final table must exist for data resolution",
                    fix_available=False,
                )
            )
            return violations

        # Validate trinity pattern
        violations.extend(self._validate_trinity_pattern(final_table))

        # Validate FK mappings
        violations.extend(self._validate_fk_mappings(prep_table, final_table))

        # Detect self-references
        violations.extend(self.detect_self_references(prep_table))

        return violations

    def _validate_trinity_pattern(
        self,
        final_table: Table,
    ) -> list[PrepSeedViolation]:
        """Validate trinity pattern in final table.

        Expected pattern:
        - id UUID (external identifier)
        - pk_* BIGINT (internal PK)
        - fk_* BIGINT (foreign keys)
        """
        violations: list[PrepSeedViolation] = []

        # Check for id UUID
        if final_table.column("id") is None:
            violations.append(
                PrepSeedViolation(
                    pattern=PrepSeedPattern.MISSING_FK_MAPPING,
                    severity=ViolationSeverity.WARNING,
                    message=f"Table {final_table.name} missing 'id UUID' column",
                    file_path=self._at(final_table)[0],
                    line_number=self._at(final_table)[1],
                    impact="Trinity pattern incomplete",
                )
            )

        # Check for pk_* BIGINT
        pk_col = f"pk_{final_table.name[3:]}"  # Remove tb_ prefix
        if final_table.column(pk_col) is None:
            violations.append(
                PrepSeedViolation(
                    pattern=PrepSeedPattern.MISSING_FK_MAPPING,
                    severity=ViolationSeverity.WARNING,
                    message=(
                        f"Table {final_table.name} missing '{pk_col} BIGINT' "
                        f"(trinity pattern requires pk_* column)"
                    ),
                    file_path=self._at(final_table)[0],
                    line_number=self._at(final_table)[1],
                    impact="Trinity pattern incomplete",
                )
            )

        return violations

    def _validate_fk_mappings(
        self,
        prep_table: Table,
        final_table: Table,
    ) -> list[PrepSeedViolation]:
        """Validate FK column mappings between prep_seed and final."""
        violations: list[PrepSeedViolation] = []

        # Find all FK columns in prep_seed
        for col_name in _column_names(prep_table):
            if col_name.startswith("fk_") and col_name.endswith("_id"):
                # Expected final column name (without _id suffix)
                final_col = col_name[:-3]  # Remove _id

                # Check if final column exists
                if final_table.column(final_col) is None:
                    violations.append(
                        PrepSeedViolation(
                            pattern=PrepSeedPattern.MISSING_FK_MAPPING,
                            severity=ViolationSeverity.ERROR,
                            message=(
                                f"{self.prep_seed_schema}.{prep_table.name}.{col_name} has no "
                                f"corresponding column "
                                f"{self.catalog_schema}.{final_table.name}.{final_col}"
                            ),
                            file_path=self._at(prep_table)[0],
                            line_number=self._at(prep_table)[1],
                            impact="FK transformation will fail",
                            fix_available=True,
                        )
                    )

        return violations

    def detect_self_references(
        self,
        table: Table,
    ) -> list[PrepSeedViolation]:
        """Detect self-referencing FK columns.

        Self-references need two-pass resolution:
        1. INSERT all rows with NULL fk_*
        2. UPDATE fk_* columns with resolved PKs
        """
        violations: list[PrepSeedViolation] = []

        table_basename = table.name[3:]  # Remove tb_ prefix

        for col_name in _column_names(table):
            if col_name.startswith("fk_") and col_name.endswith("_id"):
                # Extract referenced table from column name
                # fk_parent_product_id -> parent_product
                fk_target = col_name[3:-3]  # Remove fk_ and _id

                # Check if it references the same table
                if fk_target == table_basename or fk_target.endswith("_" + table_basename):
                    violations.append(
                        PrepSeedViolation(
                            pattern=PrepSeedPattern.MISSING_SELF_REFERENCE_HANDLING,
                            severity=ViolationSeverity.WARNING,
                            message=(
                                f"Table {table.name} has self-referencing FK "
                                f"'{col_name}' that requires two-pass resolution"
                            ),
                            file_path=self._resolver_or(table)[0],
                            line_number=self._resolver_or(table)[1],
                            impact=(
                                "Self-references must use two-pass resolution (INSERT then UPDATE)"
                            ),
                            fix_available=True,
                            suggestion=(
                                "Ensure resolution function handles self-references: "
                                "1) INSERT with NULL fk_*, "
                                "2) UPDATE fk_* from same table"
                            ),
                        )
                    )

        return violations
