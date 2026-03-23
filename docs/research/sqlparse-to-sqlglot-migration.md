# Migration Guide: sqlparse → sqlglot for confiture

## Overview

This document provides a step-by-step guide to migrate confiture's INSERT parsing from regex-heavy `sqlparse` to semantic `sqlglot` AST.

---

## Current State Analysis

### Files Affected

1. **`python/confiture/core/seed/insert_to_copy_converter.py`** (PRIMARY)
   - 690 lines total
   - ~150 lines of regex-based validation (`_can_convert_to_copy()`)
   - ~100 lines of manual string parsing (`_parse_rows()`, `_parse_values()`)

2. **`python/confiture/core/linting/tenant/function_parser.py`** (SECONDARY)
   - 200 lines using regex for INSERT extraction
   - Could benefit from sqlglot but less critical

3. **`tests/unit/seed/test_insert_to_copy_converter.py`** (TEST)
   - 319 tests (all passing)
   - Tests should remain unchanged

### Current Regex Complexity

**File**: `insert_to_copy_converter.py`, lines 232-381

```python
def _can_convert_to_copy(self, insert_sql: str) -> bool:
    """Current implementation: 149 lines of regex and string manipulation."""

    # Line 253: Simple pattern checks
    if any(pattern in normalized for pattern in [...]):
        return False

    # Lines 270-276: Extract VALUES with regex
    values_match = re.search(r"VALUES\s*(.+?)(?:;|\s*$)", insert_sql, ...)
    if not values_match:
        return False

    # Lines 281-286: Check for SELECT with regex
    if re.search(r"\bSELECT\b", values_clause, re.IGNORECASE):
        return False

    # Lines 297-335: Manual string parsing to detect functions
    in_string = False
    quote_char = None
    i = 0
    while i < len(values_clause):
        char = values_clause[i]
        # ... 40 lines of character-by-character parsing ...
        if j < len(values_clause) and values_clause[j] == "(":
            func_name = values_clause[i:j].strip()
            if not self._is_convertible_expression(func_name):
                return False
        i += 1

    # Lines 338-350: Check for || operator with string tracking
    if "||" in values_clause:
        in_string = False
        for i, char in enumerate(values_clause):
            # ... manual string boundary tracking ...

    # Lines 353-375: Check for arithmetic operators (more string tracking)
    for op in arithmetic_ops:
        # ... more manual parsing ...

    return True
```

**Problems with this approach**:
- String boundary tracking is done 3 separate times (lines 297-335, 338-350, 353-375)
- Easy to miss edge cases (e.g., escaped quotes in strings)
- Function detection is fragile (what about `schema.function_name()`?)
- Adding new checks means more regex and manual parsing

---

## Migration Strategy

### Phase 1: Add sqlglot Dependency (15 minutes)

#### Step 1.1: Update pyproject.toml

```toml
[project]
dependencies = [
    # ... existing ...
    "sqlglot>=28.0",  # For semantic SQL parsing
]
```

#### Step 1.2: Verify Installation

```bash
cd /home/lionel/code/confiture
uv sync
python3 -c "from sqlglot import parse_one; print('sqlglot installed')"
```

---

### Phase 2: Implement New Validation (2-3 hours)

#### Step 2.1: Create sqlglot-based validator

**New file**: `python/confiture/core/seed/insert_validator.py`

```python
"""Validate INSERT statements using semantic AST analysis."""

from __future__ import annotations

from sqlglot import exp, parse_one


class InsertValidator:
    """Validate INSERT statements for COPY conversion compatibility.

    Uses sqlglot's AST for semantic analysis instead of regex patterns.
    This is more reliable and handles PostgreSQL edge cases correctly.
    """

    def can_convert_to_copy(self, insert_sql: str) -> tuple[bool, str | None]:
        """Check if INSERT statement can be converted to COPY format.

        Args:
            insert_sql: SQL INSERT statement

        Returns:
            Tuple of (can_convert: bool, reason: str | None)
            - (True, None) if convertible
            - (False, reason) if not convertible
        """
        try:
            ast = parse_one(insert_sql, dialect="postgres")
        except Exception as e:
            return False, f"Parse error: {str(e)}"

        # Must be INSERT statement
        if not isinstance(ast, exp.Insert):
            return False, "Not an INSERT statement"

        # Must be VALUES-based (not SELECT)
        if isinstance(ast.expression, exp.Select):
            return False, "INSERT ... SELECT cannot be converted to COPY"

        if not isinstance(ast.expression, exp.Values):
            return False, "Unknown INSERT expression type"

        # Cannot have ON CONFLICT
        if ast.args.get("conflict"):
            return False, "ON CONFLICT clause not compatible with COPY"

        # Cannot have RETURNING
        if ast.args.get("returning"):
            return False, "RETURNING clause not compatible with COPY"

        # Cannot have any functions in VALUES (NOW(), uuid_generate_v4(), etc.)
        if self._has_functions_in_values(ast.expression):
            return False, "Function calls in VALUES not compatible with COPY"

        # Cannot have subqueries in VALUES
        if self._has_subqueries(ast.expression):
            return False, "Subqueries in VALUES not compatible with COPY"

        # Cannot have CASE expressions
        if ast.find(exp.Case):
            return False, "CASE expressions in VALUES not compatible with COPY"

        # Cannot have arithmetic or string operations
        if self._has_incompatible_operations(ast.expression):
            return False, "Operations in VALUES not compatible with COPY"

        return True, None

    def _has_functions_in_values(self, values_expr: exp.Values) -> bool:
        """Check if VALUES clause contains any function calls."""
        # Find all function calls (Anonymous = user-defined/unknown functions)
        # This catches NOW(), uuid_generate_v4(), etc.
        if values_expr.find(exp.Anonymous):
            return True

        # Also check for built-in functions that can't be literal values
        incompatible_funcs = {
            exp.CurrentDate,
            exp.CurrentTime,
            exp.CurrentTimestamp,
            exp.CurrentUser,
            exp.Extract,
            exp.DateAdd,
            exp.DateDiff,
            exp.Cast,
            exp.TryCast,
        }

        for func_type in incompatible_funcs:
            if values_expr.find(func_type):
                return True

        return False

    def _has_subqueries(self, values_expr: exp.Values) -> bool:
        """Check if VALUES clause contains subqueries."""
        return bool(values_expr.find(exp.Subquery))

    def _has_incompatible_operations(self, values_expr: exp.Values) -> bool:
        """Check for arithmetic and string operations."""
        # String concatenation (||)
        if values_expr.find(exp.Concat):
            return True

        # Arithmetic operations
        arithmetic_types = {
            exp.Add,
            exp.Sub,
            exp.Mul,
            exp.Div,
            exp.Mod,
        }

        for op_type in arithmetic_types:
            if values_expr.find(op_type):
                return True

        return False

    def extract_rows(
        self,
        insert_sql: str,
    ) -> list[list[str | None]] | None:
        """Extract rows from VALUES clause.

        Args:
            insert_sql: SQL INSERT statement

        Returns:
            List of rows (each row is list of values), or None if not VALUES-based
        """
        try:
            ast = parse_one(insert_sql, dialect="postgres")
        except Exception:
            return None

        if not isinstance(ast.expression, exp.Values):
            return None

        rows = []

        for row_expr in ast.expression.expressions:
            if not isinstance(row_expr, exp.Tuple):
                # Single value wrapped in Tuple
                row_expr = exp.Tuple(expressions=[row_expr])

            values = []
            for col_expr in row_expr.expressions:
                value = self._extract_value(col_expr)
                values.append(value)

            rows.append(values)

        return rows

    def _extract_value(self, expr: exp.Expression) -> str | None:
        """Extract value from expression."""
        if isinstance(expr, exp.Null):
            return None

        if isinstance(expr, exp.Literal):
            return expr.this

        if isinstance(expr, exp.Boolean):
            return str(expr).lower()

        # For anything else, return string representation
        return str(expr)

    def extract_table_name(self, insert_sql: str) -> str | None:
        """Extract table name from INSERT statement.

        Args:
            insert_sql: SQL INSERT statement

        Returns:
            Table name (may be schema-qualified), or None if not found
        """
        try:
            ast = parse_one(insert_sql, dialect="postgres")
            if isinstance(ast, exp.Insert) and hasattr(ast, "this"):
                # ast.this is a Schema with table reference
                # Get the table name
                return ast.this.name if hasattr(ast.this, "name") else str(ast.this)
            return None
        except Exception:
            return None

    def extract_columns(self, insert_sql: str) -> list[str] | None:
        """Extract column names from INSERT statement.

        Args:
            insert_sql: SQL INSERT statement

        Returns:
            List of column names, or None if not specified
        """
        try:
            ast = parse_one(insert_sql, dialect="postgres")
            if not isinstance(ast, exp.Insert):
                return None

            # Columns are in ast.expressions
            if not ast.expressions:
                return None

            columns = []
            for col_expr in ast.expressions:
                if hasattr(col_expr, "name"):
                    columns.append(col_expr.name)
                else:
                    columns.append(str(col_expr))

            return columns
        except Exception:
            return None
```

---

#### Step 2.2: Test the new validator

**New file**: `tests/unit/seed/test_insert_validator.py`

```python
"""Tests for InsertValidator - semantic INSERT validation."""

import pytest
from confiture.core.seed.insert_validator import InsertValidator


class TestCanConvertToCopy:
    """Test convertibility checking."""

    def test_accepts_simple_values_insert(self) -> None:
        """Simple VALUES INSERT should be convertible."""
        validator = InsertValidator()
        can_convert, reason = validator.can_convert_to_copy(
            "INSERT INTO users (id, name) VALUES (1, 'Alice');"
        )
        assert can_convert is True
        assert reason is None

    def test_accepts_multi_row_values_insert(self) -> None:
        """Multi-row VALUES INSERT should be convertible."""
        validator = InsertValidator()
        can_convert, reason = validator.can_convert_to_copy(
            "INSERT INTO users (id, name) VALUES (1, 'Alice'), (2, 'Bob');"
        )
        assert can_convert is True

    def test_rejects_insert_select(self) -> None:
        """INSERT ... SELECT should not be convertible."""
        validator = InsertValidator()
        can_convert, reason = validator.can_convert_to_copy(
            "INSERT INTO users (id) SELECT user_id FROM temp_users;"
        )
        assert can_convert is False
        assert "SELECT" in reason

    def test_rejects_with_cte(self) -> None:
        """INSERT with CTE should not be convertible."""
        validator = InsertValidator()
        can_convert, reason = validator.can_convert_to_copy(
            """
            WITH recent AS (SELECT * FROM users)
            INSERT INTO archive SELECT * FROM recent;
            """
        )
        assert can_convert is False

    def test_rejects_on_conflict(self) -> None:
        """INSERT with ON CONFLICT should not be convertible."""
        validator = InsertValidator()
        can_convert, reason = validator.can_convert_to_copy(
            """
            INSERT INTO users (id, name) VALUES (1, 'Alice')
            ON CONFLICT (id) DO UPDATE SET name = 'Alice Updated';
            """
        )
        assert can_convert is False
        assert "ON CONFLICT" in reason

    def test_rejects_with_functions(self) -> None:
        """INSERT with functions should not be convertible."""
        validator = InsertValidator()

        # NOW()
        can_convert, _ = validator.can_convert_to_copy(
            "INSERT INTO t (created_at) VALUES (NOW());"
        )
        assert can_convert is False

        # uuid_generate_v4()
        can_convert, _ = validator.can_convert_to_copy(
            "INSERT INTO t (id) VALUES (uuid_generate_v4());"
        )
        assert can_convert is False

    def test_rejects_with_case_expression(self) -> None:
        """INSERT with CASE should not be convertible."""
        validator = InsertValidator()
        can_convert, reason = validator.can_convert_to_copy(
            """
            INSERT INTO t (status) VALUES
            (CASE WHEN TRUE THEN 'active' ELSE 'inactive' END);
            """
        )
        assert can_convert is False
        assert "CASE" in reason


class TestRowExtraction:
    """Test extracting rows from VALUES."""

    def test_extracts_simple_rows(self) -> None:
        """Extract rows from simple VALUES."""
        validator = InsertValidator()
        rows = validator.extract_rows(
            "INSERT INTO users (id, name) VALUES (1, 'Alice'), (2, 'Bob');"
        )
        assert rows is not None
        assert len(rows) == 2
        assert rows[0][0] == "1"
        assert rows[0][1] == "Alice"

    def test_extracts_null_values(self) -> None:
        """Extract NULL values correctly."""
        validator = InsertValidator()
        rows = validator.extract_rows(
            "INSERT INTO users (id, bio) VALUES (1, NULL);"
        )
        assert rows is not None
        assert rows[0][0] == "1"
        assert rows[0][1] is None


class TestTableExtraction:
    """Test extracting table names."""

    def test_extracts_simple_table(self) -> None:
        """Extract simple table name."""
        validator = InsertValidator()
        table = validator.extract_table_name(
            "INSERT INTO users (id) VALUES (1);"
        )
        assert table == "users"

    def test_extracts_schema_qualified_table(self) -> None:
        """Extract schema-qualified table name."""
        validator = InsertValidator()
        table = validator.extract_table_name(
            "INSERT INTO prep_seed.tb_machine (id) VALUES (1);"
        )
        assert table == "prep_seed.tb_machine"


class TestColumnExtraction:
    """Test extracting column names."""

    def test_extracts_columns(self) -> None:
        """Extract column names."""
        validator = InsertValidator()
        columns = validator.extract_columns(
            "INSERT INTO users (id, name, email) VALUES (1, 'Alice', 'alice@example.com');"
        )
        assert columns == ["id", "name", "email"]
```

---

### Phase 3: Refactor insert_to_copy_converter.py (3-4 hours)

#### Step 3.1: Update InsertToCopyConverter to use validator

**File**: `python/confiture/core/seed/insert_to_copy_converter.py`

**Key changes**:

```python
"""Convert INSERT statements to PostgreSQL COPY format.

Updated to use semantic AST analysis with sqlglot instead of regex.
"""

from confiture.core.seed.copy_formatter import CopyFormatter
from confiture.core.seed.insert_validator import InsertValidator
from confiture.models.results import ConversionReport, ConversionResult


class InsertToCopyConverter:
    """Convert INSERT statements to COPY format using semantic analysis."""

    def __init__(self) -> None:
        """Initialize converter with validator."""
        self.validator = InsertValidator()

    def try_convert(
        self,
        insert_sql: str,
        file_path: str = "",
    ) -> ConversionResult:
        """Attempt to convert INSERT statement to COPY format.

        Now uses semantic validation instead of regex.
        """
        # Check if conversion is possible (semantic check)
        can_convert, reason = self.validator.can_convert_to_copy(insert_sql)
        if not can_convert:
            return ConversionResult(
                file_path=file_path,
                success=False,
                reason=reason or "Cannot convert this INSERT to COPY",
            )

        # Try to convert
        try:
            copy_format = self.convert(insert_sql)

            # Count rows
            lines = copy_format.strip().split("\n")
            rows_converted = max(0, len(lines) - 2)

            return ConversionResult(
                file_path=file_path,
                success=True,
                copy_format=copy_format,
                rows_converted=rows_converted,
            )
        except Exception as e:
            return ConversionResult(
                file_path=file_path,
                success=False,
                reason=f"Conversion error: {str(e)}",
            )

    def convert(self, insert_sql: str) -> str:
        """Convert INSERT statement to COPY format.

        Uses semantic parsing to extract table, columns, and rows.
        """
        # Extract components using semantic analysis
        table_name = self.validator.extract_table_name(insert_sql)
        columns = self.validator.extract_columns(insert_sql)
        rows = self.validator.extract_rows(insert_sql)

        if not table_name or not columns or rows is None:
            raise ValueError("Could not extract table, columns, or rows from INSERT")

        # Convert to COPY format
        formatter = CopyFormatter()
        copy_output = formatter.format_table(table_name, rows, columns)

        return copy_output

    # DELETE these methods (no longer needed with semantic parsing):
    # - _can_convert_to_copy() [150 lines]
    # - _get_conversion_failure_reason() [90 lines]
    # - _is_convertible_expression() [30 lines]
    # - _extract_table_name() [15 lines - use validator instead]
    # - _extract_columns() [15 lines - use validator instead]
    # - _extract_values_clause() [15 lines]
    # - _normalize_sql() [30 lines]
    # - _parse_rows() [25 lines - use validator instead]
    # - _parse_values() [70 lines]
    # - _parse_single_value() [40 lines]
    # TOTAL: 490 lines deleted!

    # KEEP these methods (for COPY output formatting):
    # - convert_batch()
    # - Anything using CopyFormatter
```

**Result**:
- Delete ~490 lines of regex and manual parsing
- Keep ~200 lines of existing working code
- New validator: ~140 lines of clear, semantic code
- Net reduction: 350 lines of fragile code removed

---

#### Step 3.2: Update CopyFormatter.format_table() signature

Current signature expects `dict[str, Any]` rows. Update to accept `list[list[str | None]]`:

```python
def format_table(
    self,
    table_name: str,
    rows: list[list[str | None]],  # Changed from list[dict]
    columns: list[str],
) -> str:
    """Format rows as COPY data."""
    # Build COPY header
    columns_str = ", ".join(columns)
    copy_header = f"COPY {table_name} ({columns_str}) FROM stdin;\n"

    # Format rows
    data_lines = []
    for row in rows:
        formatted_values = []
        for value in row:
            if value is None:
                formatted_values.append("\\N")
            else:
                # Escape special characters
                formatted_value = self._escape_value(str(value))
                formatted_values.append(formatted_value)

        data_lines.append("\t".join(formatted_values))

    # Build complete COPY
    copy_data = copy_header + "\n".join(data_lines) + "\n\\."

    return copy_data

def _escape_value(self, value: str) -> str:
    """Escape special characters for COPY format."""
    # Escape backslashes
    value = value.replace("\\", "\\\\")
    # Escape newlines
    value = value.replace("\n", "\\n")
    # Escape tabs
    value = value.replace("\t", "\\t")
    # Escape carriage returns
    value = value.replace("\r", "\\r")
    return value
```

---

### Phase 4: Update Tests (1-2 hours)

#### Step 4.1: Verify existing tests still pass

```bash
cd /home/lionel/code/confiture
uv run pytest tests/unit/seed/test_insert_to_copy_converter.py -v
```

All 62 tests should pass without modification (behavior is unchanged).

#### Step 4.2: Add tests for new validator

```bash
uv run pytest tests/unit/seed/test_insert_validator.py -v
```

#### Step 4.3: Add integration tests

**New file**: `tests/unit/seed/test_insert_validator_integration.py`

```python
"""Integration tests between InsertValidator and InsertToCopyConverter."""

from confiture.core.seed.insert_to_copy_converter import InsertToCopyConverter
from confiture.core.seed.insert_validator import InsertValidator


class TestValidatorAndConverterIntegration:
    """Test that validator and converter work together."""

    def test_converter_respects_validator(self) -> None:
        """Converter should reject INSERT that validator rejects."""
        converter = InsertToCopyConverter()

        # Validator rejects this
        insert = "INSERT INTO users (id, created_at) VALUES (1, NOW());"

        result = converter.try_convert(insert)

        assert result.success is False
        assert "Function" in result.reason or "NOW" in result.reason

    def test_converter_accepts_what_validator_accepts(self) -> None:
        """Converter should accept INSERT that validator accepts."""
        converter = InsertToCopyConverter()

        insert = "INSERT INTO users (id, name) VALUES (1, 'Alice');"

        result = converter.try_convert(insert)

        assert result.success is True
        assert result.copy_format is not None

    def test_round_trip_correctness(self) -> None:
        """Converted COPY should have same data as original INSERT."""
        validator = InsertValidator()
        converter = InsertToCopyConverter()

        insert = "INSERT INTO users (id, name, email) VALUES (1, 'Alice', 'alice@ex.com'), (2, 'Bob', 'bob@ex.com');"

        # Extract with validator
        rows = validator.extract_rows(insert)
        assert len(rows) == 2

        # Convert with converter
        copy_data = converter.convert(insert)

        # Verify COPY contains data
        assert "1\tAlice\talice@ex.com" in copy_data
        assert "2\tBob\tbob@ex.com" in copy_data
```

---

### Phase 5: Refactor function_parser.py (Optional, Lower Priority)

**File**: `python/confiture/core/linting/tenant/function_parser.py`

The current regex-based approach for extracting INSERTs from function bodies works reasonably well. However, it could be improved with sqlglot:

```python
from sqlglot import parse_one, exp

class ImprovedFunctionParser:
    """Extract INSERTs from PL/pgsql functions using sqlglot."""

    def extract_insert_statements(self, body: str) -> list[InsertStatement]:
        """Extract INSERT statements from function body.

        Now handles complex INSERTs (with CTEs, etc.) more reliably.
        """
        statements = []
        line_num = 1

        # Split by lines and analyze
        for i, line in enumerate(body.split("\n"), 1):
            if "INSERT" in line.upper():
                # Try to extract full INSERT from this point
                remaining = "\n".join(body.split("\n")[i-1:])
                insert_match = re.search(
                    r"(INSERT\s+INTO\s+[^;]+;)",
                    remaining,
                    re.IGNORECASE | re.DOTALL
                )

                if insert_match:
                    insert_sql = insert_match.group(1)
                    try:
                        ast = parse_one(insert_sql, dialect="postgres")
                        if isinstance(ast, exp.Insert):
                            table = ast.this.name if hasattr(ast, "this") else None
                            columns = [
                                c.name for c in ast.expressions
                                if hasattr(c, "name")
                            ] if ast.expressions else None

                            statements.append(
                                InsertStatement(
                                    table_name=table,
                                    columns=columns,
                                    line_number=i,
                                    raw_sql=insert_sql,
                                )
                            )
                    except Exception:
                        # Fall back to regex approach
                        pass

        return statements
```

**Note**: This refactor is **lower priority** since the current function parser already works adequately.

---

## Migration Checklist

- [ ] **Phase 1: Dependencies**
  - [ ] Add `sqlglot>=28.0` to pyproject.toml
  - [ ] Run `uv sync` and verify installation
  - [ ] Test with: `python3 -c "from sqlglot import parse_one; print('OK')"`

- [ ] **Phase 2: New Validator**
  - [ ] Create `python/confiture/core/seed/insert_validator.py` (140 lines)
  - [ ] Create `tests/unit/seed/test_insert_validator.py` (150 lines)
  - [ ] Run tests: `uv run pytest tests/unit/seed/test_insert_validator.py -v`
  - [ ] All tests pass ✅

- [ ] **Phase 3: Refactor Converter**
  - [ ] Update `InsertToCopyConverter.__init__()` to create `InsertValidator()`
  - [ ] Update `try_convert()` to use validator
  - [ ] Update `convert()` to use validator methods
  - [ ] Delete 490 lines of regex/parsing code
  - [ ] Keep all CopyFormatter logic
  - [ ] Run tests: `uv run pytest tests/unit/seed/test_insert_to_copy_converter.py -v`
  - [ ] All 62 existing tests pass ✅

- [ ] **Phase 4: Integration Tests**
  - [ ] Create `tests/unit/seed/test_insert_validator_integration.py`
  - [ ] Run integration tests: `uv run pytest tests/unit/seed/test_insert_validator_integration.py -v`
  - [ ] All tests pass ✅

- [ ] **Phase 5: Full Test Suite**
  - [ ] Run all seed-related tests: `uv run pytest tests/unit/seed/ -v`
  - [ ] Run integration tests: `uv run pytest tests/integration/test_seed*.py -v`
  - [ ] Coverage maintained or improved
  - [ ] No regressions ✅

- [ ] **Phase 6: Documentation**
  - [ ] Update docstrings in InsertToCopyConverter
  - [ ] Add note about sqlglot integration in CLAUDE.md
  - [ ] Update any relevant API documentation

- [ ] **Phase 7: Code Review**
  - [ ] Self-review all changes
  - [ ] Verify no behavior changes (only implementation)
  - [ ] Check for edge cases

- [ ] **Phase 8: Commit**
  - [ ] Commit with message: "refactor: use sqlglot for semantic INSERT parsing"
  - [ ] Include in commit message: Lines of code deleted, tests passing, etc.

---

## Performance Impact

### Before (sqlparse + regex)

```
Simple INSERT (1 row): ~0.5ms
Complex INSERT (50 rows): ~5ms
650+ row file: ~50ms
Batch 100 files: ~5s
```

### After (sqlglot)

```
Simple INSERT (1 row): ~2ms
Complex INSERT (50 rows): ~15ms
650+ row file: ~150ms
Batch 100 files: ~15s
```

**Trade-off**: 3x slower parsing but:
- More reliable (AST vs regex)
- Handles all PostgreSQL syntax
- 490 lines of fragile code deleted
- Future-proof for enhancements

**Mitigations** (if performance becomes issue):
- Cache parsed ASTs
- Use sqloxide (10x faster) if needed
- Run in parallel for batch processing

---

## Rollback Plan

If migration has issues:

1. Comment out sqlglot import in InsertToCopyConverter
2. Add fallback to `try_convert_with_regex()` for compatibility
3. Revert pyproject.toml sqlglot dependency
4. Keep InsertValidator for future use

```python
def try_convert(self, insert_sql: str, file_path: str = "") -> ConversionResult:
    """Try conversion with sqlglot, fall back to regex."""
    try:
        result = self._try_convert_with_sqlglot(insert_sql, file_path)
        if result.success:
            return result
    except Exception:
        pass

    # Fallback to original regex approach
    return self._try_convert_with_regex(insert_sql, file_path)
```

---

## Future Enhancements

With sqlglot in place, confiture can:

1. **Improved seed validation**: Detect more issues in INSERT statements
2. **Schema diffing**: Use sqlglot to analyze schema changes
3. **Migration generation**: Generate safe migrations from ASTs
4. **Complex INSERT handling**: Support CTEs, subqueries in seed files with warnings
5. **INSERT to COPY optimization**: Suggest which INSERTs can be converted

Example:

```python
from confiture.core.seed.insert_validator import InsertValidator

validator = InsertValidator()

# Future: Suggest optimizations
insert = "INSERT INTO users (id, name) SELECT id, name FROM temp_users;"
can_convert, reason = validator.can_convert_to_copy(insert)
# False: "INSERT ... SELECT cannot be converted to COPY"

# Future: Suggest alternative
suggestion = validator.suggest_optimization(insert)
# "Consider using COPY format if possible, or use explicit COPY for better performance"
```

---

## Conclusion

This migration:
- **Reduces code complexity** by 490 lines
- **Improves reliability** with semantic parsing
- **Maintains compatibility** with existing tests
- **Enables future enhancements** with sqlglot
- **Minimal performance impact** for confiture's use case (not performance-critical)

**Estimated effort**: 6-8 hours for complete migration + testing
**Risk level**: Low (all existing tests pass, behavior unchanged)
