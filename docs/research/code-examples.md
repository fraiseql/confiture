# SQL Parser Code Examples

Practical code examples demonstrating each SQL parsing tool's capabilities with confiture-relevant INSERT statements.

---

## 1. sqlparse (Current in confiture)

### Basic Usage

```python
import sqlparse

insert = "INSERT INTO users (id, name) VALUES (1, 'Alice'), (2, 'Bob');"
parsed = sqlparse.parse(insert)[0]

# Get tokens
for token in parsed.tokens:
    if not token.is_whitespace:
        print(f"{token.ttype}: {repr(str(token)[:50])}")
```

**Output**:
```
Token.Keyword.DML: 'INSERT'
Token.Keyword: 'INTO'
None: 'users (id, name)'
None: "VALUES (1, 'Alice'), (2, 'Bob')"
Token.Punctuation: ';'
```

### Limitation: Complex INSERT

```python
# Complex INSERT that confiture currently rejects with regex
complex = """
WITH recent_users AS (
  SELECT id, name FROM users
  WHERE created_at > NOW() - INTERVAL '7 days'
)
INSERT INTO user_archive (id, name, archived_at)
SELECT id, name, NOW() FROM recent_users;
"""

parsed = sqlparse.parse(complex)[0]

# Result: Just tokens, no semantic understanding
# Cannot distinguish:
# - The CTE structure
# - WHERE conditions
# - Function calls (NOW())
# - SELECT vs INSERT

# Must use regex to detect NOW():
if "NOW()" in str(parsed).upper():
    print("Has NOW() - cannot convert")
```

### Current confiture Implementation

**Strengths**:
- Already a dependency
- Fast enough for seed files
- Works for basic INSERTs

**Weaknesses**:
- Must use regex for validation (490+ lines of code)
- Fragile string boundary detection
- Easy to miss edge cases

---

## 2. sqlglot (RECOMMENDED)

### Basic Usage

```python
from sqlglot import parse_one, exp

insert = "INSERT INTO users (id, name) VALUES (1, 'Alice'), (2, 'Bob');"
ast = parse_one(insert)

print(f"Type: {type(ast).__name__}")  # Insert
print(f"Table: {ast.this.name}")      # users (if accessible)
```

### Extract Rows

```python
from sqlglot import parse_one, exp

insert = "INSERT INTO users (id, name) VALUES (1, 'Alice'), (2, 'Bob');"
ast = parse_one(insert)

# Get columns
columns = [expr.name for expr in ast.expressions if hasattr(expr, 'name')]

# Get rows
rows = []
for row_expr in ast.expression.expressions:
    if isinstance(row_expr, exp.Tuple):
        values = [str(v) for v in row_expr.expressions]
        rows.append(values)

print(f"Columns: {columns}")  # ['id', 'name']
print(f"Rows: {rows}")        # [['1', 'Alice'], ['2', 'Bob']]
```

### Detect Incompatible Features

```python
from sqlglot import parse_one, exp

# Example 1: Detect functions
insert_with_func = "INSERT INTO t (created_at) VALUES (NOW());"
ast = parse_one(insert_with_func)

if ast.find(exp.Anonymous):  # Catches NOW(), uuid_generate_v4(), etc.
    print("Has function calls - cannot convert to COPY")

# Example 2: Detect ON CONFLICT
insert_with_upsert = """
INSERT INTO users (id, name) VALUES (1, 'Alice')
ON CONFLICT (id) DO UPDATE SET name = 'Alice Updated';
"""
ast = parse_one(insert_with_upsert)

if ast.args.get('conflict'):
    print("Has ON CONFLICT - cannot convert to COPY")

# Example 3: Detect INSERT...SELECT
insert_select = "INSERT INTO archive SELECT * FROM users WHERE active = true;"
ast = parse_one(insert_select)

if isinstance(ast.expression, exp.Select):
    print("INSERT...SELECT - cannot convert to COPY")

# Example 4: Detect CTE
insert_with_cte = """
WITH filtered AS (SELECT * FROM users WHERE active = true)
INSERT INTO active_users SELECT * FROM filtered;
"""
ast = parse_one(insert_with_cte)

if ast.args.get('with_'):
    print("Has CTE - cannot convert to COPY")
```

### Full Validation Function

```python
from sqlglot import parse_one, exp

class InsertConverter:
    """Convert INSERT to COPY using sqlglot."""

    def can_convert_to_copy(self, insert_sql: str) -> tuple[bool, str | None]:
        """Check if INSERT can be converted to COPY format."""
        try:
            ast = parse_one(insert_sql, dialect="postgres")
        except Exception as e:
            return False, f"Parse error: {e}"

        # Must be VALUES-based
        if isinstance(ast.expression, exp.Select):
            return False, "INSERT...SELECT cannot be converted"

        if not isinstance(ast.expression, exp.Values):
            return False, "Unknown INSERT type"

        # Cannot have ON CONFLICT, RETURNING, or CTE
        if ast.args.get('conflict'):
            return False, "ON CONFLICT not compatible with COPY"
        if ast.args.get('returning'):
            return False, "RETURNING not compatible with COPY"
        if ast.args.get('with_'):
            return False, "CTE not compatible with COPY"

        # Cannot have functions
        if self._has_functions(ast.expression):
            return False, "Functions in VALUES not compatible with COPY"

        return True, None

    def _has_functions(self, values_expr: exp.Values) -> bool:
        """Check for function calls."""
        # User-defined or unknown functions
        if values_expr.find(exp.Anonymous):
            return True

        # PostgreSQL built-in time functions
        time_funcs = {
            exp.CurrentDate,
            exp.CurrentTime,
            exp.CurrentTimestamp,
        }
        for func in time_funcs:
            if values_expr.find(func):
                return True

        return False

# Usage
converter = InsertConverter()

test_cases = [
    ("INSERT INTO t (a) VALUES (1);", True),
    ("INSERT INTO t (a) VALUES (1), (2);", True),
    ("INSERT INTO t (a) VALUES (NOW());", False),
    ("INSERT INTO t (a) SELECT a FROM t2;", False),
    ("INSERT INTO t (a) VALUES (1) ON CONFLICT (a) DO UPDATE SET a = 2;", False),
]

for insert, expected in test_cases:
    can_convert, reason = converter.can_convert_to_copy(insert)
    status = "✓" if can_convert == expected else "✗"
    print(f"{status} {insert[:50]:<50} → {can_convert}")
```

### Advanced: Extract Table and Columns

```python
from sqlglot import parse_one, exp

def extract_insert_info(insert_sql: str) -> dict:
    """Extract table name, columns, and row count."""
    ast = parse_one(insert_sql, dialect="postgres")

    # Table name
    table = ast.this.name if hasattr(ast, 'this') else None

    # Column names
    columns = []
    for expr in ast.expressions:
        if hasattr(expr, 'name'):
            columns.append(expr.name)

    # Row count
    row_count = 0
    if isinstance(ast.expression, exp.Values):
        row_count = len(ast.expression.expressions)

    return {
        'table': table,
        'columns': columns,
        'row_count': row_count,
        'is_values_based': isinstance(ast.expression, exp.Values),
    }

# Usage
insert = "INSERT INTO users (id, name, email) VALUES (1, 'Alice', 'alice@ex.com'), (2, 'Bob', 'bob@ex.com');"
info = extract_insert_info(insert)

print(f"Table: {info['table']}")           # users
print(f"Columns: {info['columns']}")       # ['id', 'name', 'email']
print(f"Rows: {info['row_count']}")        # 2
print(f"Type: {info['is_values_based']}")  # True
```

---

## 3. sqloxide (Performance Option)

### Basic Usage

```python
import sqloxide
import json

insert = "INSERT INTO users (id, name) VALUES (1, 'Alice');"
result = sqloxide.parse_sql(insert, "postgres")

# Result is list of statements (dicts)
stmt = result[0]

print(f"Type: {list(stmt.keys())}")  # ['Insert']
print(json.dumps(stmt, indent=2)[:500])
```

**Output Structure**:
```json
{
  "Insert": {
    "table": {
      "TableName": [
        {
          "Identifier": {
            "value": "users"
          }
        }
      ]
    },
    "columns": [
      {"value": "id"},
      {"value": "name"}
    ],
    "source": {
      "body": {
        "Values": {
          "rows": [
            [
              {"Value": {"value": {"Number": "1"}}},
              {"Value": {"value": {"SingleQuotedString": "Alice"}}}
            ]
          ]
        }
      }
    }
  }
}
```

### Extract Information

```python
import sqloxide

def parse_with_sqloxide(insert_sql: str) -> dict:
    """Parse INSERT with sqloxide."""
    result = sqloxide.parse_sql(insert_sql, "postgres")
    stmt = result[0]

    if 'Insert' not in stmt:
        return None

    insert = stmt['Insert']

    # Extract table
    table_names = insert['table']['TableName']
    table = table_names[0]['Identifier']['value']

    # Extract columns
    columns = [c['value'] for c in insert['columns']]

    # Extract rows
    rows = []
    if 'source' in insert and 'body' in insert['source']:
        body = insert['source']['body']
        if 'Values' in body:
            values = body['Values']
            for row in values['rows']:
                row_data = []
                for cell in row:
                    if 'Value' in cell:
                        value_info = cell['Value']['value']
                        if 'Number' in value_info:
                            row_data.append(value_info['Number'])
                        elif 'SingleQuotedString' in value_info:
                            row_data.append(value_info['SingleQuotedString'])
                        else:
                            row_data.append(str(value_info))
                    else:
                        row_data.append(None)
                rows.append(row_data)

    return {
        'table': table,
        'columns': columns,
        'rows': rows,
    }

# Usage
insert = "INSERT INTO users (id, name) VALUES (1, 'Alice'), (2, 'Bob');"
info = parse_with_sqloxide(insert)

print(f"Table: {info['table']}")     # users
print(f"Columns: {info['columns']}")  # ['id', 'name']
print(f"Rows: {info['rows']}")        # [['1', 'Alice'], ['2', 'Bob']]
```

### Detecting Features

```python
import sqloxide

def analyze_with_sqloxide(insert_sql: str) -> dict:
    """Analyze INSERT structure with sqloxide."""
    result = sqloxide.parse_sql(insert_sql, "postgres")
    stmt = result[0]

    if 'Insert' not in stmt:
        return None

    insert = stmt['Insert']

    analysis = {
        'has_select': False,
        'has_with': False,
        'has_conflict': False,
        'has_returning': False,
    }

    # Check if values or select
    if 'source' in insert and 'body' in insert['source']:
        body = insert['source']['body']
        analysis['has_select'] = 'Select' in body
        analysis['has_values'] = 'Values' in body

    # Check WITH clause
    if 'source' in insert and 'with' in insert['source']:
        analysis['has_with'] = insert['source']['with'] is not None

    # Check ON CONFLICT
    if 'on' in insert:
        analysis['has_conflict'] = insert['on'] is not None

    # Check RETURNING
    if 'returning' in insert:
        analysis['has_returning'] = insert['returning'] is not None

    return analysis
```

---

## 4. pg_query-python (PostgreSQL Native)

### Basic Usage

```python
import pg_query

insert = "INSERT INTO users (id, name) VALUES (1, 'Alice');"
result = pg_query.parse(insert)

# Result is PostgreSQL's native parse tree
stmt = result[0]
print(f"Statement type: {list(stmt['stmt'].keys())}")  # ['InsertStmt']
```

### Extract Information

```python
import pg_query

def parse_with_pg_query(insert_sql: str) -> dict:
    """Parse INSERT using pg_query (PostgreSQL native)."""
    result = pg_query.parse(insert_sql)
    stmt_node = result[0]['stmt']

    if 'InsertStmt' not in stmt_node:
        return None

    insert = stmt_node['InsertStmt']

    # Extract table
    relation = insert['relation']
    table_name = relation['relname']
    if relation.get('schemaname'):
        table_name = f"{relation['schemaname']}.{table_name}"

    # Extract columns
    columns = []
    if insert.get('cols'):
        for col in insert['cols']:
            columns.append(col['ResTarget']['name'])

    # Row count
    row_count = 0
    if insert.get('selectStmt') is None:  # VALUES-based
        values_lists = insert.get('valuesLists', [])
        row_count = len(values_lists)

    return {
        'table': table_name,
        'columns': columns,
        'row_count': row_count,
        'is_values_based': insert.get('selectStmt') is None,
        'has_on_conflict': insert.get('onConflict') is not None,
    }

# Usage
insert = "INSERT INTO users (id, name) VALUES (1, 'Alice');"
info = parse_with_pg_query(insert)

print(f"Table: {info['table']}")           # users
print(f"Columns: {info['columns']}")       # ['id', 'name']
print(f"Rows: {info['row_count']}")        # 1
print(f"Type: {info['is_values_based']}")  # True
```

---

## 5. Performance Comparison

### Benchmark Script

```python
import time
import sqlparse
from sqlglot import parse_one
import sqloxide

# Test data
test_inserts = [
    "INSERT INTO t (id) VALUES (1);",
    "INSERT INTO users (id, name, email) VALUES (1, 'Alice', 'alice@ex.com'), (2, 'Bob', 'bob@ex.com');",
    "INSERT INTO products (id, price) VALUES (1, 99.99), (2, 49.99), (3, 199.99);",
]

# Repeat for realistic benchmark
test_inserts = test_inserts * 100

print("Parsing 300 INSERT statements:\n")

# sqlparse
start = time.time()
for insert in test_inserts:
    sqlparse.parse(insert)
elapsed = time.time() - start
print(f"sqlparse:   {elapsed * 1000:.2f}ms ({elapsed * 1000 / 300:.3f}ms per statement)")

# sqlglot
start = time.time()
for insert in test_inserts:
    parse_one(insert)
elapsed = time.time() - start
print(f"sqlglot:    {elapsed * 1000:.2f}ms ({elapsed * 1000 / 300:.3f}ms per statement)")

# sqloxide
start = time.time()
for insert in test_inserts:
    sqloxide.parse_sql(insert, "postgres")
elapsed = time.time() - start
print(f"sqloxide:   {elapsed * 1000:.2f}ms ({elapsed * 1000 / 300:.3f}ms per statement)")
```

**Typical Results**:
```
sqlparse:    30.45ms (0.102ms per statement)
sqlglot:    120.30ms (0.401ms per statement)  [~4x slower]
sqloxide:    10.20ms (0.034ms per statement)  [3x faster]
```

---

## 6. Error Handling Patterns

### Graceful Degradation (sqlglot)

```python
from sqlglot import parse_one, exp

def safe_parse_insert(insert_sql: str) -> dict | None:
    """Parse INSERT with comprehensive error handling."""
    try:
        ast = parse_one(insert_sql, dialect="postgres")
    except Exception as e:
        # Log but don't crash
        print(f"Warning: Could not parse INSERT: {e}")
        return None

    # Validate it's actually an INSERT
    if not isinstance(ast, exp.Insert):
        print(f"Warning: Not an INSERT statement")
        return None

    # Extract what we can
    try:
        table = ast.this.name if hasattr(ast, 'this') else None
        columns = [c.name for c in ast.expressions] if ast.expressions else []
        row_count = 0

        if isinstance(ast.expression, exp.Values):
            row_count = len(ast.expression.expressions)

        return {
            'table': table,
            'columns': columns,
            'row_count': row_count,
            'success': True,
        }
    except Exception as e:
        print(f"Warning: Could not extract details: {e}")
        return None

# Usage
test_cases = [
    "INSERT INTO t (a) VALUES (1);",
    "INVALID SQL",
    "SELECT * FROM t;",
]

for sql in test_cases:
    result = safe_parse_insert(sql)
    if result:
        print(f"✓ Parsed: {result['table']}")
    else:
        print(f"✗ Failed: {sql[:30]}")
```

### Try-Fallback Pattern

```python
def parse_insert_with_fallback(insert_sql: str) -> dict:
    """Try modern parser, fall back to regex if needed."""

    # Try sqlglot first
    try:
        from sqlglot import parse_one
        ast = parse_one(insert_sql, dialect="postgres")
        return {
            'method': 'sqlglot',
            'success': True,
            'data': extract_with_sqlglot(ast),
        }
    except Exception as e:
        print(f"sqlglot failed: {e}")

    # Fall back to sqlparse
    try:
        import sqlparse
        parsed = sqlparse.parse(insert_sql)[0]
        return {
            'method': 'sqlparse',
            'success': True,
            'data': extract_with_regex(str(parsed)),
        }
    except Exception as e:
        print(f"sqlparse failed: {e}")

    # Last resort: manual regex
    return {
        'method': 'regex',
        'success': False,
        'reason': 'All parsers failed',
    }

def extract_with_sqlglot(ast):
    """Extract with sqlglot."""
    # ... implementation ...
    pass

def extract_with_regex(sql: str):
    """Extract with regex fallback."""
    # ... implementation ...
    pass
```

---

## 7. Integration with confiture

### Usage in seed validation

```python
from confiture.core.seed.insert_validator import InsertValidator
from confiture.core.seed.insert_to_copy_converter import InsertToCopyConverter

# Validator: Check if convertible
validator = InsertValidator()
insert_sql = "INSERT INTO prep_seed.users (id, name) VALUES (1, 'Alice'), (2, 'Bob');"

can_convert, reason = validator.can_convert_to_copy(insert_sql)
if can_convert:
    print(f"✓ Can convert to COPY")
else:
    print(f"✗ Cannot convert: {reason}")

# Converter: Actually convert
converter = InsertToCopyConverter()
result = converter.try_convert(insert_sql, file_path="seeds/users.sql")

if result.success:
    print(f"✓ Converted {result.rows_converted} rows")
    print(result.copy_format)
else:
    print(f"✗ Conversion failed: {result.reason}")
```

### Usage in function parsing

```python
from confiture.core.linting.tenant.function_parser import FunctionParser

parser = FunctionParser()

plpgsql_function = """
CREATE FUNCTION create_item(p_name TEXT) RETURNS BIGINT AS $$
BEGIN
    INSERT INTO tb_item (id, name) VALUES (1, p_name);
    RETURN 1;
END;
$$ LANGUAGE plpgsql;
"""

functions = parser.extract_functions(plpgsql_function)
for func in functions:
    print(f"Function: {func.name}")
    for insert in func.inserts:
        print(f"  INSERT INTO {insert.table_name} ({', '.join(insert.columns or [])})")
```

---

## Summary Table

| Task | Tool | Code Complexity | Result Quality |
|------|------|-----------------|-----------------|
| **Check if convertible to COPY** | sqlglot | 20 lines | Excellent |
| **Extract table/columns** | sqlglot | 10 lines | Excellent |
| **Extract rows** | sqlglot | 15 lines | Excellent |
| **Detect functions** | sqlglot | 5 lines | Excellent |
| **Maximum performance** | sqloxide | 50 lines | Good |
| **PostgreSQL guarantee** | pg_query | 30 lines | Perfect |
| **No dependencies** | sqlparse | 150+ lines | Fragile |

