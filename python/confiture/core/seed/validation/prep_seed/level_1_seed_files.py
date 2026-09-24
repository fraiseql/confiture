"""Level 1: each seed statement, read by PostgreSQL's parser, against the prep-seed pattern.

Every ``INSERT … VALUES`` and every ``COPY … FROM stdin`` block is read
(``seed_rows``), every row of it, and checked for:

- its target: the prep-seed schema, not a final table;
- FK column naming: ``fk_*`` ends in ``_id``;
- UUID format, in the columns that hold a UUID — the columns the schema types
  ``uuid`` when a schema is given, else ``id`` and ``fk_*_id`` by the prep-seed
  convention — as PostgreSQL's ``uuid`` input reads it;
- rows as wide as the statement's column list;
- ``UNION`` branches: the same width, and a ``NULL`` typed alike in each.

A statement level 1 cannot read is a finding saying so, never a pass.
"""

from __future__ import annotations

from typing import Literal

from pglast import ast

from confiture.core.ddl_walk import type_name
from confiture.core.model_facts import NotInModelError, table_ref
from confiture.core.schema_model import SchemaModel
from confiture.core.seed.validation.prep_seed.models import (
    PrepSeedPattern,
    PrepSeedViolation,
    ViolationSeverity,
)
from confiture.core.seed.validation.prep_seed.seed_rows import (
    Computed,
    SeedParseError,
    SeedStatements,
    SeedWrite,
    UnionQuery,
    read_seed_statements,
)
from confiture.core.type_lattice import canonical_type

#: What decided which columns hold a UUID: the schema's types, or the convention.
UuidBasis = Literal["schema", "convention"]

_HEX = frozenset("0123456789abcdefABCDEF")
_UUID_BYTES = 16


def is_uuid_text(text: str) -> bool:
    """Whether PostgreSQL's ``uuid`` input accepts *text*.

    Its reader (``string_to_uuid``): an optional pair of braces around 32 hex
    digits, a hyphen allowed after any group of four. That is a superset of
    RFC 4122's 8-4-4-4-12 and reads no version or variant nibble, so any layout
    of 128 bits written that way is a UUID here — a structured id convention is
    fraiseql-uuid's to check, not confiture's.
    """
    braces = text.startswith("{")
    i = 1 if braces else 0
    for byte in range(_UUID_BYTES):
        pair = text[i : i + 2]
        if len(pair) != 2 or not set(pair) <= _HEX:  # noqa: PLR2004 - two hex digits a byte
            return False
        i += 2
        if byte % 2 == 1 and byte < _UUID_BYTES - 1 and text[i : i + 1] == "-":
            i += 1
    if braces:
        if text[i : i + 1] != "}":
            return False
        i += 1
    return i == len(text)


def _by_convention(column: str) -> bool:
    """The prep-seed convention's UUID columns: ``id`` and ``fk_*_id``."""
    return column == "id" or (column.startswith("fk_") and column.endswith("_id"))


class Level1SeedValidator:
    """Validates seed files for correct prep_seed patterns.

    Args:
        model: The schema's model. Given, a UUID column is one it types
            ``uuid``, and a statement naming no columns takes the table's; not
            given, the prep-seed convention names the UUID columns.
        prep_seed_schema: The schema seeds are written into.

    Example:
        >>> validator = Level1SeedValidator()
        >>> violations = validator.validate_seed_file(
        ...     sql="INSERT INTO catalog.tb_x (id) VALUES ('not-a-uuid');",
        ...     file_path="db/seeds/prep/test.sql",
        ... )
    """

    def __init__(
        self, model: SchemaModel | None = None, *, prep_seed_schema: str = "prep_seed"
    ) -> None:
        self.model = model
        self.prep_seed_schema = prep_seed_schema
        #: Rows read per table, as the statements name it, across every file validated.
        self.rows_read: dict[str, int] = {}

    @property
    def uuid_basis(self) -> UuidBasis:
        """What decides which columns hold a UUID."""
        return "schema" if self.model is not None else "convention"

    def validate_seed_file(self, sql: str, file_path: str) -> list[PrepSeedViolation]:
        """Every finding in one seed file.

        Args:
            sql: SQL content of the seed file
            file_path: Path to the seed file

        Returns:
            List of violations found
        """
        try:
            statements = read_seed_statements(sql)
        except SeedParseError as exc:
            return [
                PrepSeedViolation(
                    pattern=PrepSeedPattern.SEED_UNPARSEABLE,
                    severity=ViolationSeverity.ERROR,
                    message=f"PostgreSQL's parser rejects this seed file: {exc}",
                    file_path=file_path,
                    line_number=exc.line,
                    impact="Level 1 read nothing in this file, and PostgreSQL will not load it",
                )
            ]
        violations: list[PrepSeedViolation] = []
        for write in statements.writes:
            self.rows_read[write.qualified] = self.rows_read.get(write.qualified, 0) + len(
                write.rows
            )
            violations.extend(self._target(write, file_path))
            violations.extend(self._fk_naming(write, file_path))
            violations.extend(self._rows(write, file_path))
        violations.extend(self._unread(statements, file_path))
        for union in statements.unions:
            violations.extend(_union_findings(union, file_path))
        violations.extend(
            PrepSeedViolation(
                pattern=PrepSeedPattern.UNION_INLINE_COMMENT,
                severity=ViolationSeverity.WARNING,
                message="Inline comment after UNION breaks SQL concatenation",
                file_path=file_path,
                line_number=line,
                fix_available=True,
                suggestion="Move comment to line before UNION or remove it",
            )
            for line in statements.union_comment_lines
        )
        return sorted(violations, key=lambda v: v.line_number)

    def _target(self, write: SeedWrite, file_path: str) -> list[PrepSeedViolation]:
        if write.schema is None or write.schema.lower() == self.prep_seed_schema.lower():
            return []
        verb = "INSERT" if write.form == "insert" else "COPY"
        return [
            PrepSeedViolation(
                pattern=PrepSeedPattern.PREP_SEED_TARGET_MISMATCH,
                severity=ViolationSeverity.ERROR,
                message=(
                    f"Seed {verb} targets {write.schema} schema but should target "
                    f"{self.prep_seed_schema}"
                ),
                file_path=file_path,
                line_number=write.line,
                impact=f"Will not load data into {self.prep_seed_schema} tables",
                fix_available=True,
                suggestion=f"Write {write.table} into {self.prep_seed_schema}.{write.table}",
            )
        ]

    @staticmethod
    def _fk_naming(write: SeedWrite, file_path: str) -> list[PrepSeedViolation]:
        return [
            PrepSeedViolation(
                pattern=PrepSeedPattern.INVALID_FK_NAMING,
                severity=ViolationSeverity.WARNING,
                message=f"FK column '{col}' missing _id suffix (should be '{col}_id')",
                file_path=file_path,
                line_number=write.line,
                impact="FK column naming convention not followed for prep_seed",
                fix_available=True,
                suggestion=f"Rename column to '{col}_id'",
            )
            for col in write.columns or ()
            if col.startswith("fk_") and not col.endswith("_id")
        ]

    def _columns(self, write: SeedWrite) -> tuple[tuple[str, ...] | None, frozenset[str] | None]:
        """The statement's columns, and the ones the schema types ``uuid``.

        The columns are the statement's own, else the table's in the schema;
        ``None`` when neither names them. The typed set is ``None`` when the
        schema does not hold the table — the convention then names the UUID
        columns.
        """
        if self.model is not None:
            try:
                table = self.model.tables[table_ref(self.model, write.qualified)]
            except NotInModelError:
                return write.columns, None
            typed = frozenset(c.folded for c in table.columns if c.type_key == "uuid")
            return write.columns or tuple(c.folded for c in table.columns), typed
        return write.columns, None

    def _rows(self, write: SeedWrite, file_path: str) -> list[PrepSeedViolation]:
        columns, typed = self._columns(write)
        if columns is None:
            return [
                self._not_checked(
                    file_path,
                    write.line,
                    f"{write.qualified}: the statement names no columns and the schema "
                    "does not hold the table, so no value can be matched to its column",
                )
            ]
        basis = (
            "a column typed uuid in the schema"
            if typed is not None
            else "a UUID column by the prep-seed convention (id, fk_*_id)"
        )
        violations: list[PrepSeedViolation] = []
        for row in write.rows:
            if len(row.values) != len(columns):
                violations.append(
                    PrepSeedViolation(
                        pattern=PrepSeedPattern.SEED_ROW_WIDTH,
                        severity=ViolationSeverity.ERROR,
                        message=(
                            f"{write.qualified} row {row.number} holds {len(row.values)} "
                            f"value(s) for {len(columns)} column(s)"
                        ),
                        file_path=file_path,
                        line_number=row.line,
                        impact="PostgreSQL refuses the row, and the statement with it",
                    )
                )
                continue
            for column, value in zip(columns, row.values, strict=True):
                holds_uuid = column in typed if typed is not None else _by_convention(column)
                if not holds_uuid or value is None or isinstance(value, Computed):
                    continue
                if is_uuid_text(value):
                    continue
                violations.append(
                    PrepSeedViolation(
                        pattern=PrepSeedPattern.INVALID_UUID_FORMAT,
                        severity=ViolationSeverity.ERROR,
                        message=(
                            f"Invalid UUID '{value}' in {write.qualified}.{column}, "
                            f"row {row.number} ({basis}): expected 32 hex digits, "
                            "8-4-4-4-12"
                        ),
                        file_path=file_path,
                        line_number=row.line,
                        impact="PostgreSQL's uuid input refuses the value",
                        fix_available=False,
                        suggestion="Use valid UUID format (see RFC 4122)",
                    )
                )
        return violations

    @staticmethod
    def _not_checked(file_path: str, line: int, reason: str) -> PrepSeedViolation:
        return PrepSeedViolation(
            pattern=PrepSeedPattern.SEED_NOT_CHECKED,
            severity=ViolationSeverity.INFO,
            message=f"Not checked: {reason}",
            file_path=file_path,
            line_number=line,
            impact="Level 1 did not check the values this statement writes",
        )

    def _unread(self, statements: SeedStatements, file_path: str) -> list[PrepSeedViolation]:
        return [self._not_checked(file_path, u.line, u.reason) for u in statements.unread]


def _null_type(expr: object) -> tuple[bool, str | None]:
    """Whether *expr* is a NULL, and the type it is cast to (``None`` for a bare one)."""
    if isinstance(expr, ast.A_Const):
        return bool(expr.isnull), None
    if isinstance(expr, ast.TypeCast):
        is_null, _ = _null_type(expr.arg)
        return (True, canonical_type(type_name(expr.typeName))) if is_null else (False, None)
    return False, None


def _union_findings(union: UnionQuery, file_path: str) -> list[PrepSeedViolation]:
    """A UNION's branches against its first: the same width, and each NULL typed alike."""
    violations: list[PrepSeedViolation] = []

    def finding(
        pattern: PrepSeedPattern, message: str, impact: str, suggestion: str, *, fixable: bool
    ) -> None:
        violations.append(
            PrepSeedViolation(
                pattern=pattern,
                severity=ViolationSeverity.ERROR,
                message=message,
                file_path=file_path,
                line_number=union.line,
                impact=impact,
                fix_available=fixable,
                suggestion=suggestion,
            )
        )

    base = union.branches[0]
    for number, branch in enumerate(union.branches, start=1):
        for col, expr in enumerate(branch, start=1):
            if _null_type(expr) == (True, None):
                finding(
                    PrepSeedPattern.UNION_UNCAST_NULL,
                    f"UNION branch {number} column {col}: NULL without type cast",
                    "PostgreSQL cannot infer type for bare NULL in UNION",
                    "Change 'NULL' to 'NULL::type' (e.g., NULL::timestamp)",
                    fixable=True,
                )
        if number == 1:
            continue
        if len(branch) != len(base):
            finding(
                PrepSeedPattern.UNION_TYPE_MISMATCH,
                f"UNION branch {number} has {len(branch)} columns "
                f"but base branch has {len(base)} columns",
                "PostgreSQL will reject: 'each UNION query must have same number of columns'",
                "Ensure all UNION branches have same column count",
                fixable=False,
            )
            continue
        for col, (first, other) in enumerate(zip(base, branch, strict=True), start=1):
            first_null, first_type = _null_type(first)
            other_null, other_type = _null_type(other)
            if not (first_null and other_null) or first_type == other_type:
                continue
            spelled = [f"NULL::{t}" if t else "NULL" for t in (first_type, other_type)]
            finding(
                PrepSeedPattern.UNION_TYPE_MISMATCH,
                f"UNION branch {number} column {col}: NULL type mismatch: "
                f"'{spelled[0]}' vs '{spelled[1]}'",
                "PostgreSQL will reject: 'UNION types cannot be matched'",
                f"Change '{spelled[1]}' to '{spelled[0]}' for type consistency",
                fixable=True,
            )
    return violations
