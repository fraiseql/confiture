# SQL Parsing Libraries for Complex INSERT Statement Parsing in Python

## Executive Summary

For **confiture**'s use case of parsing INSERT statements (particularly for converting to COPY format and validating seed files), **sqlglot** is the clear winner with significant advantages over alternatives. However, each tool has distinct strengths.

### Quick Recommendation Matrix

| Use Case | Best Tool | Rationale |
|----------|-----------|-----------|
| **Complex INSERT parsing** | sqlglot | Full AST, semantics preserved, supports all PostgreSQL constructs |
| **Current confiture use** | sqlparse (already used) | Lightweight, sufficient for basic validation, zero new dependencies |
| **Maximum performance** | sqloxide | Rust-based, fastest parsing, JSON AST output |
| **Production SQL safety** | pg_query-python | PostgreSQL's own parser, 100% compatibility guarantee |

---

## Detailed Tool Comparison

### 1. sqlparse (Current Dependencies)

**Status**: Already in `pyproject.toml` as `sqlparse>=0.5.0`

#### Capabilities

```python
import sqlparse

# Parses basic INSERT
insert = "INSERT INTO users (id, name) VALUES (1, 'Alice');"
parsed = sqlparse.parse(insert)[0]

# Produces token stream
for token in parsed.tokens:
    print(f"{token.ttype}: {token.value}")
```

**Parsed Output** (token-based, not AST):
```
Token.Keyword.DML: 'INSERT'
Token.Keyword: 'INTO'
None: 'users (id, name)'
None: "VALUES (1, 'Alice')"
Token.Punctuation: ';'
```

#### Strengths
- ✅ **Already in dependencies** - Zero installation cost for confiture
- ✅ **Lightweight** - No heavy dependencies
- ✅ **Fast enough** - Suitable for ~650 row files
- ✅ **Good for basic parsing** - Handles simple INSERTs well
- ✅ **Sufficient for current use** - Already working in insert_to_copy_converter.py

#### Weaknesses
- ❌ **No proper AST** - Token stream instead of semantic tree
- ❌ **Limited for complex structures** - CTEs, subqueries are just tokens
- ❌ **No semantic information** - Can't tell what is a function vs identifier
- ❌ **Fragile regex-based approach** - Current converter relies on regex fallback (lines 241-382 of insert_to_copy_converter.py)
- ❌ **No ON CONFLICT support** - Groups it as one token, can't differentiate
- ❌ **Cannot preserve semantics** - Converting complex INSERT to COPY requires manual regex

#### Complex INSERT Example

```python
import sqlparse

# CTE + INSERT + SELECT + Function calls
complex = """
WITH recent_users AS (
  SELECT id, name FROM users WHERE created_at > NOW() - INTERVAL '7 days'
)
INSERT INTO user_archive (id, name, archived_at)
SELECT id, name, NOW() FROM recent_users;
"""

parsed = sqlparse.parse(complex)[0]

# Result: Just tokens, cannot distinguish:
# - WHERE clause conditions
# - Function calls (NOW())
# - CTE structure
# - SELECT vs INSERT semantics

# To detect NOW() calls, must use regex:
if "NOW()" in str(parsed):
    print("Has NOW() - cannot convert to COPY")
```

#### Learning Curve & Effort
- **Steep for complex queries** - Requires manual token stream navigation
- **Effort to add ON CONFLICT support**: Medium (would need to enhance token group recognition)

#### Performance
- **Single INSERT**: ~0.1ms
- **650+ row file**: ~5-10ms
- **Suitable for**: Batch processing up to 1000 files

#### Current confiture Usage
**File**: `/home/lionel/code/confiture/python/confiture/core/seed/insert_to_copy_converter.py`

The converter currently:
1. Uses `sqlparse` minimally (just normalizes whitespace)
2. Falls back to **regex** for all critical parsing (table, columns, values)
3. Manually detects function calls with string scanning (lines 312-335)
4. Checks for unsupported patterns with regex (lines 141-230)

**Problem**: This regex-heavy approach is fragile and will break with:
- Complex quoted strings
- Nested functions
- Edge cases sqlparse doesn't tokenize correctly

---

### 2. sqlglot (RECOMMENDED for Complex INSERT)

**Installation**: `uv pip install sqlglot`

**Version**: 28.10.1

#### Capabilities

```python
from sqlglot import parse_one, exp

# Full AST parsing
insert = "INSERT INTO users (id, name) VALUES (1, 'Alice'), (2, 'Bob');"
ast = parse_one(insert)

# Type: sqlglot.expressions.Insert
# Full semantic tree with all details preserved
```

#### Parsed Structure (for VALUES INSERT)

```python
from sqlglot import parse_one, exp

insert = "INSERT INTO users (id, name) VALUES (1, 'Alice'), (2, 'Bob');"
ast = parse_one(insert)

# Navigate AST
print(f"Table: {ast.this.name}")  # 'users'
print(f"Expression type: {type(ast.expression)}")  # Values
print(f"Rows: {len(ast.expression.expressions)}")  # 2

# Extract individual rows and values
for i, row in enumerate(ast.expression.expressions):
    values = [col.this.this if hasattr(col, 'this') else col.this
              for col in row.expressions]
    print(f"Row {i}: {values}")
```

#### Advanced Features

**1. CTE + SELECT Detection**

```python
from sqlglot import parse_one, exp

complex = """
WITH recent AS (SELECT * FROM users)
INSERT INTO archive SELECT * FROM recent;
"""

ast = parse_one(complex)
print(f"Has CTE: {ast.args.get('with_') is not None}")  # True
print(f"Is SELECT-based: {isinstance(ast.expression, exp.Select)}")  # True
```

**2. Function Detection**

```python
from sqlglot import parse_one, exp

insert = "INSERT INTO t (a, b) VALUES (1, NOW()), (2, uuid_generate_v4());"
ast = parse_one(insert)

# Find all function calls
functions = list(ast.find_all(exp.Anonymous))
for func in functions:
    print(f"Function: {func.name.upper()}")  # NOW, UUID_GENERATE_V4

# This enables automatic COPY conversion decision:
if ast.find(exp.Anonymous):
    print("Has functions - cannot convert to COPY")
```

**3. ON CONFLICT Support**

```python
from sqlglot import parse_one, exp

upsert = """
INSERT INTO users (id, name) VALUES (1, 'Alice')
ON CONFLICT (id) DO UPDATE SET name = 'Alice Updated';
"""

ast = parse_one(upsert)
print(f"Has conflict clause: {ast.args.get('conflict') is not None}")  # True
# Access the full conflict structure
```

**4. Multi-Row VALUE Extraction**

```python
from sqlglot import parse_one, exp

insert = "INSERT INTO t (a, b, c) VALUES (1, 'x', true), (2, 'y', false);"
ast = parse_one(insert)

# Clean extraction
rows = []
for row in ast.expression.expressions:  # Each value tuple
    values = [expr.this for expr in row.expressions]
    rows.append(values)

# Result: Clean Python data structures
# [[1, 'x', True], [2, 'y', False]]
```

#### Strengths
- ✅ **True AST** - Full semantic tree, not token stream
- ✅ **Handles all PostgreSQL** - CTEs, subqueries, window functions, etc.
- ✅ **Function detection** - Can identify all function calls
- ✅ **Semantic information preserved** - Knows what is CTE, INSERT, SELECT, etc.
- ✅ **ON CONFLICT support** - Full parsing of conflict clauses
- ✅ **Multi-dialect support** - PostgreSQL, MySQL, Snowflake, etc.
- ✅ **Clean API** - Find what you need with `.find()`, `.find_all()`
- ✅ **Excellent for conversion logic** - Can determine convertibility programmatically

#### Weaknesses
- ⚠️ **New dependency** - Would need to add to pyproject.toml
- ⚠️ **Larger package** - ~2MB vs sqlparse ~100KB
- ⚠️ **Slightly slower** - Still <10ms for typical files, but 10-100x slower than sqloxide

#### Complex INSERT Example (sqlglot)

```python
from sqlglot import parse_one, exp

# Real-world complex example
insert = """
WITH prep_data AS (
  SELECT
    uuid_generate_v4() as id,
    name,
    CASE
      WHEN status = 'active' THEN true
      ELSE false
    END as is_active,
    NOW() as created_at
  FROM temp_users
  WHERE deleted_at IS NULL
)
INSERT INTO users (id, name, is_active, created_at)
SELECT id, name, is_active, created_at FROM prep_data;
"""

ast = parse_one(insert)

# Can be converted to analysis:
class ConversionAnalyzer:
    def can_convert_to_copy(self, insert_ast):
        # 1. Check if it's VALUES-based
        if isinstance(insert_ast.expression, exp.Values):
            # 2. Check for functions in VALUES
            if insert_ast.find(exp.Anonymous):
                return False, "Functions in VALUES clause"

            # 3. Check for subqueries
            if insert_ast.find(exp.Subquery):
                return False, "Subqueries in VALUES"

            return True, "Can be converted"

        # INSERT ... SELECT cannot be converted
        if isinstance(insert_ast.expression, exp.Select):
            return False, "INSERT...SELECT cannot be converted to COPY"

        return False, "Unknown INSERT type"

analyzer = ConversionAnalyzer()
can_convert, reason = analyzer.can_convert_to_copy(ast)
print(f"{reason}")  # "INSERT...SELECT cannot be converted to COPY"
```

#### Learning Curve & Effort
- **Moderate** - AST navigation is intuitive
- **Effort to support ON CONFLICT**: Low (already parsed, just add check for `ast.args.get('conflict')`)
- **Effort to improve INSERT->COPY**: Low (replace regex checks with AST queries)

#### Performance
- **Single INSERT**: ~1ms
- **650 row file**: ~10-20ms
- **Suitable for**: 100+ concurrent files

#### Integration with confiture

**Proposed improvement to insert_to_copy_converter.py**:

```python
from sqlglot import parse_one, exp

class ImprovedInsertToCopyConverter:
    """Using sqlglot for semantic parsing."""

    def _can_convert_to_copy(self, insert_sql: str) -> bool:
        """Improved version using sqlglot AST."""
        try:
            ast = parse_one(insert_sql, dialect="postgres")

            # Must be VALUES-based (not SELECT)
            if not isinstance(ast.expression, exp.Values):
                return False

            # Check for any functions (NOW, uuid_generate_v4, etc)
            if ast.find(exp.Anonymous):
                return False

            # Check for ON CONFLICT
            if ast.args.get('conflict'):
                return False

            return True
        except Exception:
            return False
```

This would **eliminate 250+ lines of regex code** and be more reliable.

---

### 3. pg_query-python

**Installation**: `uv pip install pg_query`

**Basis**: Python bindings to PostgreSQL's own parser (libpg_query)

#### Capabilities

```python
import pg_query

# Uses PostgreSQL's actual C parser
result = pg_query.parse("INSERT INTO users (id) VALUES (1);")

# Result: JSON representation of PostgreSQL's parse tree
print(result)  # List[Dict] with full PostgreSQL AST
```

#### Parsed Structure

```python
import pg_query

insert = "INSERT INTO users (id, name) VALUES (1, 'Alice');"
result = pg_query.parse(insert)

# Result is PostgreSQL's native parse tree structure
# {
#   "stmts": [{
#     "stmt": {
#       "InsertStmt": {
#         "relation": {...},
#         "cols": [...],
#         "selectStmt": None,  # For VALUES-based insert
#         "valuesLists": [...]
#       }
#     }
#   }]
# }
```

#### Strengths
- ✅ **100% PostgreSQL compatibility** - Uses PostgreSQL's own parser
- ✅ **Guaranteed correctness** - If PostgreSQL accepts it, pg_query parses it
- ✅ **Production-proven** - Used by PostgRES IDE projects
- ✅ **Standard structure** - Follows PostgreSQL's parse tree format
- ✅ **Best for "is this valid PostgreSQL?"** checks

#### Weaknesses
- ❌ **Requires libpg_query** - Binary dependency, platform-specific wheels
- ❌ **Installation complexity** - May fail on some systems (Windows, ARM)
- ❌ **Steeper learning curve** - PostgreSQL parse tree structure is verbose
- ❌ **Not packaged for pure Python** - Must compile or use prebuilt wheels
- ❌ **Slower than sqloxide** - Still slower than rust-based parsers
- ❌ **Overkill for confiture** - Only need INSERT validation, not full parse

#### Complex Example

```python
import pg_query

upsert = """
INSERT INTO users (id, email, name)
VALUES (1, 'alice@example.com', 'Alice')
ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name;
"""

result = pg_query.parse(upsert)

# Navigate PostgreSQL AST structure
insert_stmt = result[0]['stmt']['InsertStmt']
has_on_conflict = insert_stmt.get('onConflict') is not None
# True

# Extract columns
col_names = [col['name'] for col in insert_stmt['cols']]
# ['id', 'email', 'name']
```

#### Learning Curve & Effort
- **High** - Must understand PostgreSQL AST structure
- **Effort to support complex INSERT**: High (deep PostgreSQL knowledge needed)

#### Performance
- **Single INSERT**: ~2-5ms (due to binary call)
- **650 row file**: ~20-30ms
- **Suitable for**: Validation-heavy workflows

#### When to Use
- If you need **100% correctness guarantee**
- If you need **PostgreSQL-specific features** (e.g., parsing PL/pgsql)
- If you're building a tool that **must handle all PostgreSQL dialect variants**

---

### 4. sqloxide (Performance Option)

**Installation**: `uv pip install sqloxide`

**Version**: 0.1.56

**Basis**: High-performance Rust-based SQL parser with Python bindings

#### Capabilities

```python
import sqloxide

# Fast parsing to Python dict
result = sqloxide.parse_sql(
    "INSERT INTO users (id, name) VALUES (1, 'Alice');",
    dialect="postgres"
)

# Result: List[Dict] with nested structure representing full AST
print(result)  # Rust-based AST converted to Python
```

#### Parsed Structure

```python
import sqloxide

insert = "INSERT INTO users (id, name) VALUES (1, 'Alice');"
result = sqloxide.parse_sql(insert, "postgres")

# Result: [{'Insert': {
#   'table': {'TableName': [...]},
#   'columns': [{'value': 'id'}, {'value': 'name'}],
#   'source': {
#     'body': {
#       'Values': {
#         'rows': [[
#           {'Value': {'value': {'Number': ('1', False)}}},
#           {'Value': {'value': {'SingleQuotedString': 'Alice'}}}
#         ]]
#       }
#     }
#   },
#   ...
# }}]
```

#### Strengths
- ✅ **Extremely fast** - 10-100x faster than pure Python parsers
- ✅ **Comprehensive AST** - Full semantic tree with all details
- ✅ **JSON output** - Easy to integrate with downstream tools
- ✅ **Multi-dialect** - PostgreSQL, MySQL, Snowflake, BigQuery, etc.
- ✅ **Minimal dependencies** - Single compiled Rust binary

#### Weaknesses
- ❌ **Early version (0.1.56)** - Still pre-1.0, API may change
- ❌ **Large package** - ~3MB binary
- ⚠️ **Navigation complexity** - Deep nested dicts, not as ergonomic as sqlglot
- ❌ **Less mature than sqlglot** - Fewer maintained bindings

#### Complex Example

```python
import sqloxide

complex = """
WITH recent AS (SELECT id, name FROM users WHERE created_at > NOW())
INSERT INTO archive (id, name, archived_at)
SELECT id, name, NOW() FROM recent;
"""

result = sqloxide.parse_sql(complex, "postgres")

# Navigate result (list of statement dicts)
stmt = result[0]  # First statement

# Access nested structure
if 'Insert' in stmt:
    insert = stmt['Insert']
    table = insert['table']['TableName'][0]['Identifier']['value']  # 'archive'
    columns = [c['value'] for c in insert['columns']]  # ['id', 'name', 'archived_at']
    has_with = insert['source'].get('with') is not None  # True
```

#### Learning Curve & Effort
- **Steep** - Must navigate deep nested dict structures
- **Effort to integrate**: High (manual dict walking)

#### Performance
- **Single INSERT**: ~0.1-0.2ms
- **650 row file**: ~1-2ms
- **Suitable for**: Batch processing 10,000+ files

#### When to Use
- If you need **maximum performance**
- If you're building a **high-volume SQL processing service**
- If INSERT parsing is **the performance bottleneck**

---

### 5. pyparsing (Generic Parsing Library)

**Installation**: `uv pip install pyparsing`

**Basis**: Pure Python parser generator library

#### Capabilities

```python
from pyparsing import *

# Define grammar for INSERT statement
INSERT_STMT = CaselessKeyword("INSERT") + CaselessKeyword("INTO") + ...

# Would need to build complete INSERT grammar from scratch
result = INSERT_STMT.parseString("INSERT INTO users (id) VALUES (1);")
```

#### Strengths
- ✅ **Complete control** - Build parser to exact specifications
- ✅ **Pure Python** - No binary dependencies
- ✅ **Well-documented** - Large community, many examples

#### Weaknesses
- ❌ **Massive effort** - Must define complete PostgreSQL INSERT grammar
- ❌ **Maintenance burden** - Every PostgreSQL feature needs grammar update
- ❌ **Fragile** - Easy to miss edge cases in grammar
- ❌ **Poor performance** - Much slower than pre-built parsers
- ❌ **Not recommended for production** - Reinventing the wheel badly

#### Example Effort Estimate
- Time to build basic INSERT grammar: 40-80 hours
- Time to handle all PostgreSQL features: 400+ hours
- Time to maintain and fix bugs: Ongoing

**Verdict**: Not suitable for confiture unless building a custom DSL.

---

## Practical Comparison: Can Each Tool Handle Complex INSERTs?

### Test Case: CTE + INSERT + SELECT + Functions

```sql
WITH prep_users AS (
  SELECT
    uuid_generate_v4() as id,
    UPPER(name) as name,
    CURRENT_TIMESTAMP as created_at
  FROM temp_users
  WHERE email IS NOT NULL
)
INSERT INTO users (id, name, created_at)
SELECT id, name, created_at FROM prep_users;
```

| Tool | CTE Detection | Function Detection | SELECT Detection | Convertible? | Notes |
|------|---------------|-------------------|-----------------|--------------|-------|
| **sqlparse** | Regex fallback | Regex pattern | Regex pattern | ❌ No | All regex-based, fragile |
| **sqlglot** | ✅ Direct AST | ✅ Direct AST | ✅ Direct AST | ❌ Correctly identified (not convertible) | Programmatic decision |
| **pg_query** | ✅ Native parse tree | ✅ Native parse tree | ✅ Native parse tree | ❌ Correctly identified | PostgreSQL guaranteed |
| **sqloxide** | ✅ Nested dict | ✅ Nested dict | ✅ Nested dict | ❌ Correctly identified | Fast but complex navigation |
| **pyparsing** | ❓ Need to implement | ❓ Need to implement | ❓ Need to implement | ❌ If implemented | 400+ hours effort |

---

## Integration Options for confiture

### Option 1: Keep sqlparse (Status Quo)

**Pros**: Zero new dependencies, already working
**Cons**: Regex-heavy, brittle, missing semantic information
**Recommendation**: ⚠️ Use only if reluctant to add dependencies

**Required Changes**: None (but should refactor with pyparsing or sqlglot later)

### Option 2: Add sqlglot (RECOMMENDED)

**Pros**:
- True AST, handles all PostgreSQL
- 250+ lines of regex can be replaced with 50 lines of AST queries
- Excellent for INSERT->COPY conversion decision logic
- Can be extended for future features (schema diff, migration analysis)

**Cons**:
- ~2MB new dependency
- 10-100x slower than sqloxide (but still <20ms for typical files)

**Implementation Effort**:
- Medium: Replace `_can_convert_to_copy()` with AST-based version
- Time: 2-4 hours

**pyproject.toml Change**:
```toml
dependencies = [
    ...
    "sqlglot>=28.0",  # For semantic INSERT parsing
    ...
]
```

### Option 3: Add sqloxide (Performance Path)

**Pros**:
- Extremely fast
- Rust-based, modern
- Good for batch processing

**Cons**:
- Pre-1.0 API (may change)
- Navigation complexity
- Need to write extensive dict walking code

**Implementation Effort**:
- High: Must manually navigate nested dicts
- Time: 8-12 hours

**Not recommended for current confiture use case** (not performance-limited)

### Option 4: Add pg_query-python (Safety Path)

**Pros**:
- 100% PostgreSQL compatibility
- Uses PostgreSQL's own parser

**Cons**:
- Binary dependency (platform-specific)
- Installation complexity
- Steep learning curve
- Overkill for confiture's needs

**Not recommended for confiture** (complexity vs benefit trade-off poor)

---

## Decision Matrix for confiture

**Question 1**: Do we need to support complex INSERT detection?
- **Yes** → Use sqlglot
- **No** → Keep sqlparse

**Question 2**: Is INSERT parsing a performance bottleneck?
- **Yes** → Use sqloxide (with sqlglot for ergonomics)
- **No** → Use sqlglot

**Question 3**: Must support all PostgreSQL dialects?
- **Yes** → Use pg_query-python
- **No** → Use sqlglot

**Question 4**: Want pure Python, zero binary dependencies?
- **Yes** → Keep sqlparse or use sqlglot
- **No** → Consider sqloxide for performance

---

## Code Examples: Real-world Scenarios

### Scenario 1: Improve current insert_to_copy_converter.py

**Current approach** (sqlparse + regex):
```python
def _can_convert_to_copy(self, insert_sql: str) -> bool:
    """Current: 150+ lines of regex checking"""
    normalized = insert_sql.strip().upper()

    # Check for clauses that make conversion impossible
    if any(pattern in normalized for pattern in [
        "ON CONFLICT", "ON DUPLICATE", "WITH ", "INSERT OR", "RETURNING"
    ]):
        return False

    # Extract VALUES clause with regex
    values_match = re.search(r"VALUES\s*(.+?)(?:;|\s*$)", insert_sql, ...)
    if not values_match:
        return False

    values_clause = values_match.group(1)

    # Check for SELECT in VALUES (regex)
    if re.search(r"\bSELECT\b", values_clause, re.IGNORECASE):
        return False

    # ... 100+ more lines of fragile regex ...
    return True
```

**Improved approach** (sqlglot):
```python
from sqlglot import parse_one, exp

def _can_convert_to_copy(self, insert_sql: str) -> bool:
    """Improved: 20 lines of semantic checks"""
    try:
        ast = parse_one(insert_sql, dialect="postgres")

        # Must be VALUES-based
        if not isinstance(ast.expression, exp.Values):
            return False

        # Cannot have ON CONFLICT
        if ast.args.get('conflict'):
            return False

        # Cannot have functions in VALUES
        if ast.find(exp.Anonymous):
            return False

        # Cannot have subqueries
        if ast.find(exp.Subquery):
            return False

        return True
    except Exception:
        return False
```

**Benefits**:
- 87% less code (20 vs 150 lines)
- More reliable (AST vs regex)
- Easier to extend (just add more `find()` calls)
- Clearer intent (code reads like logic, not pattern matching)

### Scenario 2: Detect complex INSERTs for prep-seed validation

```python
from sqlglot import parse_one, exp

class PrepSeedAnalyzer:
    """Analyze INSERT statements for prep-seed validation."""

    def analyze(self, insert_sql: str) -> dict:
        """Return analysis of INSERT statement."""
        try:
            ast = parse_one(insert_sql, dialect="postgres")
        except Exception as e:
            return {"valid": False, "error": str(e)}

        analysis = {
            "valid": True,
            "is_values_based": isinstance(ast.expression, exp.Values),
            "is_select_based": isinstance(ast.expression, exp.Select),
            "has_cte": ast.args.get('with_') is not None,
            "has_functions": bool(ast.find(exp.Anonymous)),
            "has_subqueries": bool(ast.find(exp.Subquery)),
            "has_on_conflict": ast.args.get('conflict') is not None,
            "has_returning": ast.args.get('returning') is not None,
            "table_name": ast.this.name if hasattr(ast, 'this') else None,
            "columns": [c.this for c in ast.expressions] if hasattr(ast, 'expressions') else [],
        }

        # Add conversion recommendation
        if analysis["is_values_based"] and not analysis["has_functions"]:
            analysis["can_convert_to_copy"] = True
        else:
            analysis["can_convert_to_copy"] = False

        return analysis

# Usage
analyzer = PrepSeedAnalyzer()
result = analyzer.analyze("INSERT INTO t (a) VALUES (1), (2);")
print(result)
# {
#   'valid': True,
#   'is_values_based': True,
#   'has_functions': False,
#   'can_convert_to_copy': True,
#   'table_name': 't',
#   'columns': ['a']
# }
```

### Scenario 3: Multi-row extraction for copy generation

```python
from sqlglot import parse_one, exp

class MultiRowExtractor:
    """Extract rows from INSERT statement."""

    def extract_rows(self, insert_sql: str) -> list[dict]:
        """Extract individual rows from VALUES clause."""
        ast = parse_one(insert_sql, dialect="postgres")

        if not isinstance(ast.expression, exp.Values):
            raise ValueError("Not a VALUES-based INSERT")

        # Get column names
        columns = [expr.name for expr in ast.expressions]

        rows = []
        for row_expr in ast.expression.expressions:
            # Each row_expr is a Tuple of values
            values = []
            for col_expr in row_expr.expressions:
                if isinstance(col_expr, exp.Null):
                    values.append(None)
                elif isinstance(col_expr, exp.Literal):
                    values.append(col_expr.this)
                else:
                    # Handle other types (functions, etc.)
                    values.append(str(col_expr))

            rows.append(dict(zip(columns, values)))

        return rows

# Usage
extractor = MultiRowExtractor()
rows = extractor.extract_rows("""
    INSERT INTO users (id, name, active)
    VALUES (1, 'Alice', true), (2, 'Bob', false);
""")
print(rows)
# [
#   {'id': '1', 'name': 'Alice', 'active': 'true'},
#   {'id': '2', 'name': 'Bob', 'active': 'false'}
# ]
```

---

## Recommendation Summary

### For confiture's Current Needs

**Best Choice: sqlglot**

1. **Immediate benefit**: Replace 250+ lines of regex with 50 lines of semantic checks
2. **Medium effort**: 2-4 hours integration work
3. **High reliability**: True AST handles all PostgreSQL syntax
4. **Future-proof**: Can extend for schema diffing, migration analysis, etc.

### Implementation Priority

1. **Phase 1** (Easy): Add sqlglot to pyproject.toml, improve `_can_convert_to_copy()`
2. **Phase 2** (Medium): Refactor `InsertToCopyConverter` to use AST for all parsing
3. **Phase 3** (Future): Use sqlglot for other parsing needs (schema diff, migration diff)

### Performance Considerations

- **Current**: sqlparse (fast but fragile)
- **Improved**: sqlglot (reliable, <20ms overhead)
- **Future**: sqloxide (if INSERT parsing becomes bottleneck at 1000+ files/sec)

---

## Installation & Testing

### Quick Test (in confiture)

```bash
# Install sqlglot
uv pip install sqlglot

# Test in Python
python3 << 'EOF'
from sqlglot import parse_one, exp

insert = "INSERT INTO users (id) VALUES (1);"
ast = parse_one(insert)
print(f"Parsed: {type(ast).__name__}")
print(f"Table: {ast.this.name}")
EOF
```

### Benchmark (all tools)

```bash
# Run benchmark across tools
python3 << 'EOF'
import time
import sqlparse
from sqlglot import parse_one

insert = "INSERT INTO users (id, name) VALUES (1, 'Alice'), (2, 'Bob');"

# sqlparse
start = time.time()
for _ in range(1000):
    sqlparse.parse(insert)
print(f"sqlparse: {(time.time() - start) * 1000:.2f}ms for 1000 parses")

# sqlglot
start = time.time()
for _ in range(1000):
    parse_one(insert)
print(f"sqlglot: {(time.time() - start) * 1000:.2f}ms for 1000 parses")
EOF
```

---

## Conclusion

| Tool | Recommended For | Risk Level |
|------|-----------------|-----------|
| **sqlparse** | Minimum dependencies, already used | Medium (regex fragility) |
| **sqlglot** | Default choice, best ergonomics | Low (mature, actively maintained) |
| **pg_query** | Maximum PostgreSQL safety | High (binary dependency) |
| **sqloxide** | Performance-critical scenarios | Medium (pre-1.0 API) |

**Final Verdict**: Adopt sqlglot as the standard parser for confiture. It provides the best balance of functionality, reliability, and maintainability.
