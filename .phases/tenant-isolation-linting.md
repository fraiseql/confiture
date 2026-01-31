# Tenant Isolation Linting for INSERT Statements

**Issue**: #14
**Status**: [x] Complete
**Estimated Effort**: Medium-High (8 phases, ~15 TDD cycles)

## Objective

Add a linting rule that detects INSERT statements in PostgreSQL functions that are missing FK columns required for tenant filtering. This catches a subtle but critical bug where data is persisted but becomes invisible via tenant-filtered views.

## The Problem

In multi-tenant systems using FK-derived tenant filtering, views JOIN on FK columns to derive `tenant_id`:

```sql
-- View derives tenant_id from FK join
CREATE VIEW v_item AS
SELECT
    i.id,
    i.name,
    org.id AS tenant_id
FROM tb_item i
LEFT JOIN tv_organization org ON i.fk_org = org.pk_organization;

-- Function accidentally omits fk_org
CREATE FUNCTION fn_create_item(p_name TEXT)
RETURNS BIGINT AS $$
DECLARE
    v_id BIGINT;
BEGIN
    INSERT INTO tb_item (id, name)  -- ❌ Missing fk_org!
    VALUES (nextval('seq_item'), p_name)
    RETURNING id INTO v_id;
    RETURN v_id;
END;
$$ LANGUAGE plpgsql;
```

**What happens:**
1. ✅ INSERT succeeds (no constraint violation)
2. ✅ Data exists in `tb_item`
3. ❌ `SELECT * FROM v_item WHERE tenant_id = 123` returns nothing
4. 🔥 Customer reports "data disappeared"

This bug is insidious because:
- No error is raised at insert time
- Data exists but is invisible
- Debugging requires understanding the view→table→FK relationship
- Often discovered in production by end users

## Success Criteria

- [ ] Lint rule detects INSERT statements missing tenant FK columns
- [ ] Auto-detects multi-tenant configuration (no manual config required)
- [ ] Supports explicit configuration for complex setups
- [ ] Integrates with existing `confiture lint` command
- [ ] Reports clear error messages with fix suggestions
- [ ] Handles edge cases (CTEs, RETURNING, multi-table inserts)
- [ ] Unit tests cover all detection logic (>90% coverage)
- [ ] Integration tests with realistic schemas
- [ ] Documentation with examples

## Architecture Overview

### Detection Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                    TENANT ISOLATION LINTING                      │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  1. SCHEMA ANALYSIS                                              │
│     ┌──────────────┐    ┌──────────────┐    ┌──────────────┐   │
│     │ Parse Views  │───▶│ Extract JOIN │───▶│ Identify     │   │
│     │              │    │ Conditions   │    │ Tenant FKs   │   │
│     └──────────────┘    └──────────────┘    └──────────────┘   │
│                                                    │             │
│                                                    ▼             │
│  2. BUILD REQUIREMENTS MAP                                       │
│     ┌────────────────────────────────────────────────────┐      │
│     │  { "tb_item": ["fk_org"], "tb_order": ["fk_cust"] } │      │
│     └────────────────────────────────────────────────────┘      │
│                                                    │             │
│                                                    ▼             │
│  3. FUNCTION ANALYSIS                                            │
│     ┌──────────────┐    ┌──────────────┐    ┌──────────────┐   │
│     │ Parse        │───▶│ Extract      │───▶│ Compare to   │   │
│     │ Functions    │    │ INSERTs      │    │ Requirements │   │
│     └──────────────┘    └──────────────┘    └──────────────┘   │
│                                                    │             │
│                                                    ▼             │
│  4. REPORT VIOLATIONS                                            │
│     ┌────────────────────────────────────────────────────┐      │
│     │ fn_create_item:15 - INSERT missing fk_org          │      │
│     │   Required for tenant filtering in view: v_item     │      │
│     └────────────────────────────────────────────────────┘      │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### File Structure

```
python/confiture/
├── core/
│   └── linting/
│       ├── libraries/
│       │   ├── __init__.py
│       │   └── tenant_isolation.py    # TenantIsolationRule class
│       └── tenant/
│           ├── __init__.py
│           ├── models.py              # TenantRelationship, TenantViolation
│           ├── detector.py            # Auto-detection logic
│           ├── view_parser.py         # VIEW SQL parsing
│           ├── function_parser.py     # Function body parsing
│           └── insert_analyzer.py     # INSERT statement analysis

tests/unit/linting/tenant/
├── __init__.py
├── test_models.py
├── test_detector.py
├── test_view_parser.py
├── test_function_parser.py
├── test_insert_analyzer.py
└── test_tenant_isolation_rule.py

tests/integration/
└── test_tenant_isolation_workflow.py
```

### Configuration Schema

```yaml
# confiture.yaml - Automatic mode (default)
linting:
  rules:
    tenant_isolation:
      enabled: true
      # Auto-detection uses these patterns to find tenant relationships
      tenant_column_patterns:
        - "tenant_id"
        - "organization_id"
        - "org_id"
      fk_patterns:
        - "fk_tenant*"
        - "fk_org*"
        - "fk_organization*"
        - "*_tenant_id"
        - "*_organization_id"

# confiture.yaml - Explicit mode (for complex schemas)
linting:
  rules:
    tenant_isolation:
      enabled: true
      mode: explicit
      relationships:
        - view: v_item
          table: tb_item
          required_fk: fk_org
          tenant_column: tenant_id
        - view: v_order
          table: tb_order
          required_fk: fk_customer
          tenant_column: tenant_id

# confiture.yaml - Disabled
linting:
  rules:
    tenant_isolation:
      enabled: false
```

---

## Phase 1: Core Models

### Cycle 1.1: TenantRelationship Model

**Objective:** Create a model to represent the relationship between a view, its source table, and the FK column required for tenant filtering.

**RED - Test First:**
```python
# tests/unit/linting/tenant/test_models.py
from confiture.core.linting.tenant.models import TenantRelationship

class TestTenantRelationship:
    def test_create_tenant_relationship(self):
        """TenantRelationship stores view-table-FK relationship."""
        rel = TenantRelationship(
            view_name="v_item",
            source_table="tb_item",
            required_fk="fk_org",
            tenant_column="tenant_id",
            fk_target_table="tv_organization",
            fk_target_column="pk_organization",
        )

        assert rel.view_name == "v_item"
        assert rel.source_table == "tb_item"
        assert rel.required_fk == "fk_org"
        assert rel.tenant_column == "tenant_id"

    def test_tenant_relationship_str(self):
        """TenantRelationship has readable string representation."""
        rel = TenantRelationship(
            view_name="v_item",
            source_table="tb_item",
            required_fk="fk_org",
            tenant_column="tenant_id",
        )

        result = str(rel)
        assert "v_item" in result
        assert "tb_item" in result
        assert "fk_org" in result

    def test_tenant_relationship_equality(self):
        """Two TenantRelationships with same values are equal."""
        rel1 = TenantRelationship(view_name="v_item", source_table="tb_item", required_fk="fk_org")
        rel2 = TenantRelationship(view_name="v_item", source_table="tb_item", required_fk="fk_org")

        assert rel1 == rel2
```

**GREEN - Implementation:**
```python
# python/confiture/core/linting/tenant/models.py
from dataclasses import dataclass

@dataclass
class TenantRelationship:
    """Represents a tenant filtering relationship.

    Captures the relationship between a view that derives tenant_id
    and the source table's FK column required for the join.
    """
    view_name: str
    source_table: str
    required_fk: str
    tenant_column: str = "tenant_id"
    fk_target_table: str | None = None
    fk_target_column: str | None = None

    def __str__(self) -> str:
        return f"{self.view_name} → {self.source_table}.{self.required_fk}"
```

**REFACTOR:** Add validation, hash method for use in sets.

**CLEANUP:** Run `ruff check`, `ruff format`, commit.

---

### Cycle 1.2: TenantViolation Model

**Objective:** Create a model to represent a detected tenant isolation violation.

**RED - Test First:**
```python
# tests/unit/linting/tenant/test_models.py
class TestTenantViolation:
    def test_create_tenant_violation(self):
        """TenantViolation captures violation details."""
        violation = TenantViolation(
            function_name="fn_create_item",
            file_path="functions/fn_create_item.sql",
            line_number=15,
            table_name="tb_item",
            missing_columns=["fk_org"],
            affected_views=["v_item"],
            insert_sql="INSERT INTO tb_item (id, name) VALUES (...)",
        )

        assert violation.function_name == "fn_create_item"
        assert violation.missing_columns == ["fk_org"]
        assert violation.affected_views == ["v_item"]

    def test_violation_suggestion(self):
        """TenantViolation provides actionable suggestion."""
        violation = TenantViolation(
            function_name="fn_create_item",
            file_path="functions/fn_create_item.sql",
            line_number=15,
            table_name="tb_item",
            missing_columns=["fk_org"],
            affected_views=["v_item"],
        )

        suggestion = violation.suggestion
        assert "fk_org" in suggestion
        assert "INSERT" in suggestion or "parameter" in suggestion.lower()

    def test_violation_severity_is_warning(self):
        """TenantViolation default severity is WARNING."""
        violation = TenantViolation(
            function_name="fn_create_item",
            file_path="test.sql",
            line_number=1,
            table_name="tb_item",
            missing_columns=["fk_org"],
            affected_views=["v_item"],
        )

        assert violation.severity == "warning"
```

**GREEN - Implementation:**
```python
# python/confiture/core/linting/tenant/models.py
@dataclass
class TenantViolation:
    """Represents a tenant isolation violation.

    Captures details about an INSERT statement that is missing
    columns required for tenant filtering.
    """
    function_name: str
    file_path: str
    line_number: int
    table_name: str
    missing_columns: list[str]
    affected_views: list[str]
    insert_sql: str | None = None
    severity: str = "warning"

    @property
    def suggestion(self) -> str:
        cols = ", ".join(self.missing_columns)
        views = ", ".join(self.affected_views)
        return (
            f"Add {cols} to INSERT statement. "
            f"Required for tenant filtering in: {views}"
        )

    def __str__(self) -> str:
        return (
            f"{self.function_name}:{self.line_number} - "
            f"INSERT INTO {self.table_name} missing: {', '.join(self.missing_columns)}"
        )
```

**CLEANUP:** Lint, commit.

---

### Cycle 1.3: TenantConfig Model

**Objective:** Create a configuration model for tenant isolation settings.

**RED - Test First:**
```python
class TestTenantConfig:
    def test_default_config(self):
        """Default config enables auto-detection."""
        config = TenantConfig()

        assert config.enabled is True
        assert config.mode == "auto"
        assert "tenant_id" in config.tenant_column_patterns

    def test_explicit_mode_requires_relationships(self):
        """Explicit mode requires relationships to be defined."""
        config = TenantConfig(mode="explicit", relationships=[])

        # Should be valid but empty
        assert config.relationships == []

    def test_config_from_dict(self):
        """Config can be loaded from dictionary (YAML parsing)."""
        data = {
            "enabled": True,
            "mode": "explicit",
            "relationships": [
                {"view": "v_item", "table": "tb_item", "required_fk": "fk_org"}
            ]
        }

        config = TenantConfig.from_dict(data)

        assert config.mode == "explicit"
        assert len(config.relationships) == 1
```

**GREEN - Implementation:**
```python
@dataclass
class TenantConfig:
    """Configuration for tenant isolation linting."""
    enabled: bool = True
    mode: str = "auto"  # "auto", "explicit", "hybrid"
    relationships: list[TenantRelationship] = field(default_factory=list)
    tenant_column_patterns: list[str] = field(default_factory=lambda: [
        "tenant_id", "organization_id", "org_id"
    ])
    fk_patterns: list[str] = field(default_factory=lambda: [
        "fk_tenant*", "fk_org*", "fk_organization*", "*_tenant_id"
    ])

    @classmethod
    def from_dict(cls, data: dict) -> "TenantConfig":
        relationships = [
            TenantRelationship(
                view_name=r["view"],
                source_table=r["table"],
                required_fk=r["required_fk"],
                tenant_column=r.get("tenant_column", "tenant_id"),
            )
            for r in data.get("relationships", [])
        ]
        return cls(
            enabled=data.get("enabled", True),
            mode=data.get("mode", "auto"),
            relationships=relationships,
            tenant_column_patterns=data.get("tenant_column_patterns", cls.tenant_column_patterns),
            fk_patterns=data.get("fk_patterns", cls.fk_patterns),
        )
```

---

## Phase 2: View Parsing

### Cycle 2.1: Extract Table Aliases from VIEW

**Objective:** Parse a VIEW definition and extract table aliases used in FROM/JOIN clauses.

**RED - Test First:**
```python
# tests/unit/linting/tenant/test_view_parser.py
from confiture.core.linting.tenant.view_parser import ViewParser

class TestViewParser:
    def test_extract_table_aliases_simple(self):
        """Extract table and alias from simple FROM clause."""
        sql = """
        CREATE VIEW v_item AS
        SELECT i.id, i.name
        FROM tb_item i;
        """

        parser = ViewParser()
        aliases = parser.extract_table_aliases(sql)

        assert aliases == {"i": "tb_item"}

    def test_extract_table_aliases_with_join(self):
        """Extract tables from FROM and JOIN clauses."""
        sql = """
        CREATE VIEW v_item AS
        SELECT i.id, o.name AS org_name
        FROM tb_item i
        LEFT JOIN tv_organization o ON i.fk_org = o.pk_organization;
        """

        parser = ViewParser()
        aliases = parser.extract_table_aliases(sql)

        assert aliases == {"i": "tb_item", "o": "tv_organization"}

    def test_extract_table_aliases_no_alias(self):
        """Handle tables without aliases."""
        sql = """
        CREATE VIEW v_item AS
        SELECT id, name FROM tb_item;
        """

        parser = ViewParser()
        aliases = parser.extract_table_aliases(sql)

        assert aliases == {"tb_item": "tb_item"}

    def test_extract_table_aliases_schema_qualified(self):
        """Handle schema-qualified table names."""
        sql = """
        CREATE VIEW v_item AS
        SELECT i.* FROM myschema.tb_item i;
        """

        parser = ViewParser()
        aliases = parser.extract_table_aliases(sql)

        assert aliases == {"i": "myschema.tb_item"}
```

**GREEN - Implementation:**
```python
# python/confiture/core/linting/tenant/view_parser.py
import re

class ViewParser:
    """Parses PostgreSQL VIEW definitions."""

    # Pattern: FROM table [AS] alias or FROM table
    FROM_PATTERN = re.compile(
        r'\bFROM\s+((?:\w+\.)?(\w+))(?:\s+(?:AS\s+)?(\w+))?',
        re.IGNORECASE
    )

    # Pattern: JOIN table [AS] alias ON ...
    JOIN_PATTERN = re.compile(
        r'\b(?:LEFT|RIGHT|INNER|OUTER|CROSS)?\s*JOIN\s+((?:\w+\.)?(\w+))(?:\s+(?:AS\s+)?(\w+))?\s+ON',
        re.IGNORECASE
    )

    def extract_table_aliases(self, sql: str) -> dict[str, str]:
        """Extract table aliases from VIEW definition.

        Returns:
            Dict mapping alias -> table_name
        """
        aliases = {}

        # Extract FROM clause
        for match in self.FROM_PATTERN.finditer(sql):
            full_name = match.group(1)  # schema.table or table
            table_name = match.group(2)  # just table
            alias = match.group(3) or full_name
            aliases[alias] = full_name

        # Extract JOIN clauses
        for match in self.JOIN_PATTERN.finditer(sql):
            full_name = match.group(1)
            table_name = match.group(2)
            alias = match.group(3) or full_name
            aliases[alias] = full_name

        return aliases
```

---

### Cycle 2.2: Extract JOIN Conditions

**Objective:** Parse JOIN conditions to identify FK relationships.

**RED - Test First:**
```python
class TestExtractJoinConditions:
    def test_extract_join_on_fk(self):
        """Extract FK column from JOIN ON condition."""
        sql = """
        CREATE VIEW v_item AS
        SELECT i.*, o.id AS tenant_id
        FROM tb_item i
        LEFT JOIN tv_organization o ON i.fk_org = o.pk_organization;
        """

        parser = ViewParser()
        joins = parser.extract_join_conditions(sql)

        assert len(joins) == 1
        assert joins[0].left_table == "i"
        assert joins[0].left_column == "fk_org"
        assert joins[0].right_table == "o"
        assert joins[0].right_column == "pk_organization"

    def test_extract_multiple_joins(self):
        """Extract conditions from multiple JOINs."""
        sql = """
        CREATE VIEW v_order AS
        SELECT o.*, c.name AS customer_name, org.id AS tenant_id
        FROM tb_order o
        JOIN tb_customer c ON o.fk_customer = c.id
        JOIN tv_organization org ON c.fk_org = org.pk_organization;
        """

        parser = ViewParser()
        joins = parser.extract_join_conditions(sql)

        assert len(joins) == 2

    def test_extract_join_with_and_conditions(self):
        """Handle JOIN with multiple AND conditions."""
        sql = """
        CREATE VIEW v_item AS
        SELECT *
        FROM tb_item i
        JOIN tv_organization o ON i.fk_org = o.pk_organization AND o.active = true;
        """

        parser = ViewParser()
        joins = parser.extract_join_conditions(sql)

        # Should extract the FK condition, ignore the boolean
        assert len(joins) >= 1
        assert any(j.left_column == "fk_org" for j in joins)
```

**GREEN - Implementation:**
```python
@dataclass
class JoinCondition:
    """Represents a JOIN condition."""
    left_table: str
    left_column: str
    right_table: str
    right_column: str
    join_type: str = "JOIN"

class ViewParser:
    # ... previous code ...

    JOIN_CONDITION_PATTERN = re.compile(
        r'(\w+)\.(\w+)\s*=\s*(\w+)\.(\w+)',
        re.IGNORECASE
    )

    def extract_join_conditions(self, sql: str) -> list[JoinCondition]:
        """Extract JOIN conditions from VIEW definition."""
        conditions = []

        # Find all equality conditions in JOIN clauses
        # This is simplified - real impl needs to track which JOIN each belongs to
        for match in self.JOIN_CONDITION_PATTERN.finditer(sql):
            conditions.append(JoinCondition(
                left_table=match.group(1),
                left_column=match.group(2),
                right_table=match.group(3),
                right_column=match.group(4),
            ))

        return conditions
```

---

### Cycle 2.3: Detect Tenant Column in SELECT

**Objective:** Identify which column in the SELECT clause represents the tenant identifier.

**RED - Test First:**
```python
class TestDetectTenantColumn:
    def test_detect_tenant_id_alias(self):
        """Detect column aliased as tenant_id."""
        sql = """
        CREATE VIEW v_item AS
        SELECT i.id, i.name, o.id AS tenant_id
        FROM tb_item i
        JOIN tv_organization o ON i.fk_org = o.pk_organization;
        """

        parser = ViewParser()
        tenant_col = parser.detect_tenant_column(sql, patterns=["tenant_id", "organization_id"])

        assert tenant_col is not None
        assert tenant_col.alias == "tenant_id"
        assert tenant_col.source_table == "o"
        assert tenant_col.source_column == "id"

    def test_detect_organization_id_alias(self):
        """Detect column aliased as organization_id."""
        sql = """
        CREATE VIEW v_item AS
        SELECT i.*, o.pk_organization AS organization_id
        FROM tb_item i
        JOIN tv_organization o ON i.fk_org = o.pk_organization;
        """

        parser = ViewParser()
        tenant_col = parser.detect_tenant_column(sql, patterns=["tenant_id", "organization_id"])

        assert tenant_col.alias == "organization_id"

    def test_no_tenant_column_returns_none(self):
        """Return None if no tenant column detected."""
        sql = """
        CREATE VIEW v_item AS
        SELECT i.id, i.name FROM tb_item i;
        """

        parser = ViewParser()
        tenant_col = parser.detect_tenant_column(sql, patterns=["tenant_id"])

        assert tenant_col is None
```

---

### Cycle 2.4: Build TenantRelationship from VIEW

**Objective:** Combine parsing results to create a TenantRelationship.

**RED - Test First:**
```python
class TestBuildTenantRelationship:
    def test_build_relationship_from_view(self):
        """Build complete TenantRelationship from VIEW SQL."""
        sql = """
        CREATE VIEW v_item AS
        SELECT i.id, i.name, o.id AS tenant_id
        FROM tb_item i
        LEFT JOIN tv_organization o ON i.fk_org = o.pk_organization;
        """

        parser = ViewParser()
        relationship = parser.build_tenant_relationship(sql, view_name="v_item")

        assert relationship is not None
        assert relationship.view_name == "v_item"
        assert relationship.source_table == "tb_item"
        assert relationship.required_fk == "fk_org"
        assert relationship.tenant_column == "tenant_id"
        assert relationship.fk_target_table == "tv_organization"

    def test_build_relationship_returns_none_for_non_tenant_view(self):
        """Return None for views without tenant pattern."""
        sql = """
        CREATE VIEW v_counts AS
        SELECT COUNT(*) as total FROM tb_item;
        """

        parser = ViewParser()
        relationship = parser.build_tenant_relationship(sql, view_name="v_counts")

        assert relationship is None
```

---

## Phase 3: Function Parsing

### Cycle 3.1: Extract Function Body

**Objective:** Extract the body (between $$ delimiters) from a CREATE FUNCTION statement.

**RED - Test First:**
```python
# tests/unit/linting/tenant/test_function_parser.py
from confiture.core.linting.tenant.function_parser import FunctionParser

class TestFunctionParser:
    def test_extract_function_body_dollar_quote(self):
        """Extract body from $$ quoted function."""
        sql = """
        CREATE FUNCTION fn_test() RETURNS VOID AS $$
        BEGIN
            INSERT INTO tb_item (id) VALUES (1);
        END;
        $$ LANGUAGE plpgsql;
        """

        parser = FunctionParser()
        body = parser.extract_function_body(sql)

        assert "INSERT INTO tb_item" in body
        assert "BEGIN" in body

    def test_extract_function_body_tagged_dollar_quote(self):
        """Extract body from $tag$ quoted function."""
        sql = """
        CREATE FUNCTION fn_test() RETURNS VOID AS $fn$
        BEGIN
            INSERT INTO tb_item (id) VALUES (1);
        END;
        $fn$ LANGUAGE plpgsql;
        """

        parser = FunctionParser()
        body = parser.extract_function_body(sql)

        assert "INSERT INTO tb_item" in body

    def test_extract_function_body_single_quote(self):
        """Extract body from single-quoted function."""
        sql = """
        CREATE FUNCTION fn_add(a INT, b INT) RETURNS INT AS '
            SELECT a + b;
        ' LANGUAGE sql;
        """

        parser = FunctionParser()
        body = parser.extract_function_body(sql)

        assert "SELECT a + b" in body

    def test_extract_function_name(self):
        """Extract function name from CREATE FUNCTION."""
        sql = "CREATE FUNCTION myschema.fn_create_item(p_name TEXT) RETURNS BIGINT AS $$ ..."

        parser = FunctionParser()
        name = parser.extract_function_name(sql)

        assert name == "myschema.fn_create_item"
```

---

### Cycle 3.2: Extract INSERT Statements

**Objective:** Find all INSERT statements within a function body.

**RED - Test First:**
```python
class TestExtractInsertStatements:
    def test_extract_single_insert(self):
        """Extract single INSERT from function body."""
        body = """
        BEGIN
            INSERT INTO tb_item (id, name, fk_org)
            VALUES (nextval('seq'), p_name, p_org_id);
        END;
        """

        parser = FunctionParser()
        inserts = parser.extract_insert_statements(body)

        assert len(inserts) == 1
        assert inserts[0].table_name == "tb_item"
        assert inserts[0].columns == ["id", "name", "fk_org"]

    def test_extract_multiple_inserts(self):
        """Extract multiple INSERTs from function body."""
        body = """
        BEGIN
            INSERT INTO tb_item (id, name) VALUES (1, 'test');
            INSERT INTO tb_audit_log (action) VALUES ('created');
        END;
        """

        parser = FunctionParser()
        inserts = parser.extract_insert_statements(body)

        assert len(inserts) == 2
        assert inserts[0].table_name == "tb_item"
        assert inserts[1].table_name == "tb_audit_log"

    def test_extract_insert_with_returning(self):
        """Handle INSERT with RETURNING clause."""
        body = """
        INSERT INTO tb_item (id, name)
        VALUES (1, 'test')
        RETURNING id INTO v_id;
        """

        parser = FunctionParser()
        inserts = parser.extract_insert_statements(body)

        assert len(inserts) == 1
        assert inserts[0].columns == ["id", "name"]

    def test_extract_insert_without_column_list(self):
        """Handle INSERT without explicit column list."""
        body = """
        INSERT INTO tb_item VALUES (1, 'test', 123);
        """

        parser = FunctionParser()
        inserts = parser.extract_insert_statements(body)

        assert len(inserts) == 1
        assert inserts[0].columns is None  # Unknown columns

    def test_extract_insert_in_cte(self):
        """Extract INSERT from CTE (WITH clause)."""
        body = """
        WITH new_item AS (
            INSERT INTO tb_item (id, name)
            VALUES (1, 'test')
            RETURNING *
        )
        SELECT * FROM new_item;
        """

        parser = FunctionParser()
        inserts = parser.extract_insert_statements(body)

        assert len(inserts) == 1

    def test_skip_dynamic_sql_insert(self):
        """Mark EXECUTE with INSERT as unanalyzable."""
        body = """
        EXECUTE format('INSERT INTO %I (id) VALUES ($1)', tbl_name) USING p_id;
        """

        parser = FunctionParser()
        inserts = parser.extract_insert_statements(body)

        # Either empty or marked as dynamic
        assert len(inserts) == 0 or inserts[0].is_dynamic
```

**GREEN - Implementation:**
```python
@dataclass
class InsertStatement:
    """Represents a parsed INSERT statement."""
    table_name: str
    columns: list[str] | None  # None if columns not specified
    line_number: int
    raw_sql: str
    is_dynamic: bool = False

class FunctionParser:
    """Parses PostgreSQL function definitions."""

    INSERT_PATTERN = re.compile(
        r'INSERT\s+INTO\s+((?:\w+\.)?(\w+))\s*'
        r'(?:\(([^)]+)\))?\s*'
        r'(?:VALUES|SELECT|DEFAULT\s+VALUES)',
        re.IGNORECASE | re.DOTALL
    )

    def extract_insert_statements(self, body: str) -> list[InsertStatement]:
        """Extract all INSERT statements from function body."""
        statements = []

        for match in self.INSERT_PATTERN.finditer(body):
            table_full = match.group(1)
            columns_str = match.group(3)

            columns = None
            if columns_str:
                columns = [c.strip() for c in columns_str.split(',')]

            # Calculate line number
            line_num = body[:match.start()].count('\n') + 1

            statements.append(InsertStatement(
                table_name=table_full,
                columns=columns,
                line_number=line_num,
                raw_sql=match.group(0),
            ))

        return statements
```

---

## Phase 4: Insert Analysis

### Cycle 4.1: Check for Missing Tenant Columns

**Objective:** Compare INSERT columns against required FK columns.

**RED - Test First:**
```python
# tests/unit/linting/tenant/test_insert_analyzer.py
from confiture.core.linting.tenant.insert_analyzer import InsertAnalyzer

class TestInsertAnalyzer:
    def test_detect_missing_fk_column(self):
        """Detect when INSERT is missing required FK column."""
        insert = InsertStatement(
            table_name="tb_item",
            columns=["id", "name"],
            line_number=15,
            raw_sql="INSERT INTO tb_item (id, name) VALUES (...)",
        )

        requirements = {"tb_item": ["fk_org"]}

        analyzer = InsertAnalyzer()
        missing = analyzer.find_missing_columns(insert, requirements)

        assert missing == ["fk_org"]

    def test_no_missing_when_fk_present(self):
        """No missing columns when FK is included."""
        insert = InsertStatement(
            table_name="tb_item",
            columns=["id", "name", "fk_org"],
            line_number=15,
            raw_sql="INSERT INTO tb_item (id, name, fk_org) VALUES (...)",
        )

        requirements = {"tb_item": ["fk_org"]}

        analyzer = InsertAnalyzer()
        missing = analyzer.find_missing_columns(insert, requirements)

        assert missing == []

    def test_no_requirements_for_table(self):
        """No violations for tables without tenant requirements."""
        insert = InsertStatement(
            table_name="tb_audit_log",
            columns=["id", "action"],
            line_number=15,
            raw_sql="INSERT INTO tb_audit_log (id, action) VALUES (...)",
        )

        requirements = {"tb_item": ["fk_org"]}  # Different table

        analyzer = InsertAnalyzer()
        missing = analyzer.find_missing_columns(insert, requirements)

        assert missing == []

    def test_unknown_columns_returns_warning(self):
        """INSERT without column list cannot be analyzed."""
        insert = InsertStatement(
            table_name="tb_item",
            columns=None,  # No column list
            line_number=15,
            raw_sql="INSERT INTO tb_item VALUES (...)",
        )

        requirements = {"tb_item": ["fk_org"]}

        analyzer = InsertAnalyzer()
        result = analyzer.find_missing_columns(insert, requirements)

        # Should return special marker or empty with warning flag
        assert result is None or insert.table_name in requirements
```

---

### Cycle 4.2: Build Violation from Analysis

**Objective:** Create TenantViolation when missing columns detected.

**RED - Test First:**
```python
class TestBuildViolation:
    def test_build_violation_from_analysis(self):
        """Create TenantViolation from analysis results."""
        analyzer = InsertAnalyzer()

        violation = analyzer.build_violation(
            function_name="fn_create_item",
            file_path="functions/fn_create_item.sql",
            insert=InsertStatement(
                table_name="tb_item",
                columns=["id", "name"],
                line_number=15,
                raw_sql="INSERT INTO tb_item (id, name) VALUES (...)",
            ),
            missing_columns=["fk_org"],
            affected_views=["v_item"],
        )

        assert violation.function_name == "fn_create_item"
        assert violation.table_name == "tb_item"
        assert violation.missing_columns == ["fk_org"]
        assert violation.affected_views == ["v_item"]
        assert "fk_org" in violation.suggestion
```

---

## Phase 5: Auto-Detection

### Cycle 5.1: Detect Multi-Tenant Schema

**Objective:** Automatically detect if a schema has multi-tenant patterns.

**RED - Test First:**
```python
# tests/unit/linting/tenant/test_detector.py
from confiture.core.linting.tenant.detector import TenantDetector

class TestTenantDetector:
    def test_detect_multi_tenant_schema(self):
        """Detect schema with tenant patterns."""
        schema_sql = """
        CREATE TABLE tv_organization (pk_organization BIGINT PRIMARY KEY);

        CREATE TABLE tb_item (
            id BIGINT PRIMARY KEY,
            name TEXT,
            fk_org BIGINT REFERENCES tv_organization(pk_organization)
        );

        CREATE VIEW v_item AS
        SELECT i.*, o.pk_organization AS tenant_id
        FROM tb_item i
        JOIN tv_organization o ON i.fk_org = o.pk_organization;
        """

        detector = TenantDetector()
        is_multi_tenant = detector.is_multi_tenant_schema(schema_sql)

        assert is_multi_tenant is True

    def test_detect_single_tenant_schema(self):
        """Detect schema without tenant patterns."""
        schema_sql = """
        CREATE TABLE tb_item (
            id BIGINT PRIMARY KEY,
            name TEXT
        );

        CREATE VIEW v_item AS SELECT * FROM tb_item;
        """

        detector = TenantDetector()
        is_multi_tenant = detector.is_multi_tenant_schema(schema_sql)

        assert is_multi_tenant is False

    def test_extract_tenant_relationships(self):
        """Extract all tenant relationships from schema."""
        schema_sql = """
        CREATE VIEW v_item AS
        SELECT i.*, o.pk_organization AS tenant_id
        FROM tb_item i
        JOIN tv_organization o ON i.fk_org = o.pk_organization;

        CREATE VIEW v_order AS
        SELECT ord.*, c.fk_org AS tenant_id
        FROM tb_order ord
        JOIN tb_customer c ON ord.fk_customer = c.id;
        """

        detector = TenantDetector()
        relationships = detector.extract_relationships(schema_sql)

        assert len(relationships) == 2

        item_rel = next(r for r in relationships if r.view_name == "v_item")
        assert item_rel.source_table == "tb_item"
        assert item_rel.required_fk == "fk_org"
```

---

### Cycle 5.2: Build Requirements Map

**Objective:** Build a map of table → required FK columns.

**RED - Test First:**
```python
class TestBuildRequirementsMap:
    def test_build_requirements_from_relationships(self):
        """Build requirements map from tenant relationships."""
        relationships = [
            TenantRelationship(
                view_name="v_item",
                source_table="tb_item",
                required_fk="fk_org",
            ),
            TenantRelationship(
                view_name="v_order",
                source_table="tb_order",
                required_fk="fk_customer",
            ),
        ]

        detector = TenantDetector()
        requirements = detector.build_requirements_map(relationships)

        assert requirements == {
            "tb_item": ["fk_org"],
            "tb_order": ["fk_customer"],
        }

    def test_multiple_requirements_for_same_table(self):
        """Handle table with multiple tenant FK requirements."""
        relationships = [
            TenantRelationship(view_name="v_item", source_table="tb_item", required_fk="fk_org"),
            TenantRelationship(view_name="v_item_alt", source_table="tb_item", required_fk="fk_dept"),
        ]

        detector = TenantDetector()
        requirements = detector.build_requirements_map(relationships)

        assert set(requirements["tb_item"]) == {"fk_org", "fk_dept"}
```

---

## Phase 6: Lint Rule Integration

### Cycle 6.1: TenantIsolationRule Class

**Objective:** Create the lint rule class that integrates with SchemaLinter.

**RED - Test First:**
```python
# tests/unit/linting/tenant/test_tenant_isolation_rule.py
from confiture.core.linting.libraries.tenant_isolation import TenantIsolationRule

class TestTenantIsolationRule:
    def test_rule_detects_violation(self):
        """Rule detects INSERT missing tenant FK."""
        schema_sql = """
        CREATE VIEW v_item AS
        SELECT i.*, o.pk_organization AS tenant_id
        FROM tb_item i
        JOIN tv_organization o ON i.fk_org = o.pk_organization;

        CREATE FUNCTION fn_create_item(p_name TEXT) RETURNS BIGINT AS $$
        BEGIN
            INSERT INTO tb_item (id, name) VALUES (1, p_name);
            RETURN 1;
        END;
        $$ LANGUAGE plpgsql;
        """

        rule = TenantIsolationRule()
        violations = rule.check(schema_sql)

        assert len(violations) == 1
        assert violations[0].function_name == "fn_create_item"
        assert violations[0].missing_columns == ["fk_org"]

    def test_rule_passes_for_correct_insert(self):
        """Rule passes when INSERT includes tenant FK."""
        schema_sql = """
        CREATE VIEW v_item AS
        SELECT i.*, o.pk_organization AS tenant_id
        FROM tb_item i
        JOIN tv_organization o ON i.fk_org = o.pk_organization;

        CREATE FUNCTION fn_create_item(p_name TEXT, p_org BIGINT) RETURNS BIGINT AS $$
        BEGIN
            INSERT INTO tb_item (id, name, fk_org) VALUES (1, p_name, p_org);
            RETURN 1;
        END;
        $$ LANGUAGE plpgsql;
        """

        rule = TenantIsolationRule()
        violations = rule.check(schema_sql)

        assert len(violations) == 0

    def test_rule_respects_enabled_config(self):
        """Rule is skipped when disabled in config."""
        config = TenantConfig(enabled=False)
        rule = TenantIsolationRule(config=config)

        violations = rule.check("CREATE FUNCTION ...")

        assert violations == []

    def test_rule_name_and_severity(self):
        """Rule has correct name and default severity."""
        rule = TenantIsolationRule()

        assert rule.name == "tenant_isolation"
        assert rule.default_severity == "warning"
```

---

### Cycle 6.2: Integration with SchemaLinter

**Objective:** Register the rule in the linting pipeline.

**RED - Test First:**
```python
# tests/unit/test_schema_linter_tenant.py
from confiture.core.linting import SchemaLinter

class TestSchemaLinterTenantIntegration:
    def test_linter_includes_tenant_rule_when_enabled(self, tmp_path):
        """SchemaLinter runs tenant isolation rule when enabled."""
        # Create schema files
        schema_dir = tmp_path / "db" / "schema"
        schema_dir.mkdir(parents=True)

        (schema_dir / "views.sql").write_text("""
        CREATE VIEW v_item AS
        SELECT i.*, o.pk_organization AS tenant_id
        FROM tb_item i
        JOIN tv_organization o ON i.fk_org = o.pk_organization;
        """)

        (schema_dir / "functions.sql").write_text("""
        CREATE FUNCTION fn_bad() RETURNS VOID AS $$
        BEGIN
            INSERT INTO tb_item (id, name) VALUES (1, 'test');
        END;
        $$ LANGUAGE plpgsql;
        """)

        # Create config enabling tenant isolation
        config = LintConfig(
            tenant_isolation=TenantConfig(enabled=True)
        )

        linter = SchemaLinter(config=config)
        report = linter.lint(schema_dir)

        # Should have tenant isolation violation
        tenant_violations = [v for v in report.warnings if v.rule_name == "tenant_isolation"]
        assert len(tenant_violations) == 1

    def test_linter_skips_tenant_rule_when_disabled(self, tmp_path):
        """SchemaLinter skips tenant rule when disabled."""
        config = LintConfig(
            tenant_isolation=TenantConfig(enabled=False)
        )

        linter = SchemaLinter(config=config)
        report = linter.lint(tmp_path)

        tenant_violations = [v for v in report.all_violations if v.rule_name == "tenant_isolation"]
        assert len(tenant_violations) == 0
```

---

## Phase 7: CLI Output

### Cycle 7.1: Format Tenant Violations

**Objective:** Format tenant violations for CLI display.

**Expected Output:**
```
$ confiture lint

🔍 Detected multi-tenant patterns:
   • v_item → tb_item (requires: fk_org)
   • v_order → tb_order (requires: fk_customer)

⚠️  TENANT ISOLATION ISSUES

   fn_create_item (functions/items.sql:15)
   ├─ INSERT INTO tb_item missing: fk_org
   ├─ Required for tenant filtering in: v_item
   └─ Suggestion: Add fk_org parameter to function and include in INSERT

   fn_bulk_import (functions/import.sql:42)
   ├─ INSERT INTO tb_order missing: fk_customer
   ├─ Required for tenant filtering in: v_order
   └─ Suggestion: Add fk_customer parameter to function and include in INSERT

Summary: 2 functions checked, 2 tenant isolation issues
```

---

## Phase 8: Integration Tests

### Cycle 8.1: Full Workflow Test

**RED - Test First:**
```python
# tests/integration/test_tenant_isolation_workflow.py
class TestTenantIsolationWorkflow:
    def test_full_lint_workflow(self, tmp_path):
        """Test complete lint workflow with tenant isolation."""
        # Create realistic schema structure
        schema_dir = tmp_path / "db" / "schema"
        (schema_dir / "10_tables").mkdir(parents=True)
        (schema_dir / "20_views").mkdir(parents=True)
        (schema_dir / "30_functions").mkdir(parents=True)

        # Tables
        (schema_dir / "10_tables" / "organization.sql").write_text("""
        CREATE TABLE tv_organization (
            pk_organization BIGINT PRIMARY KEY,
            name TEXT NOT NULL
        );
        """)

        (schema_dir / "10_tables" / "item.sql").write_text("""
        CREATE TABLE tb_item (
            id BIGINT PRIMARY KEY,
            name TEXT NOT NULL,
            fk_org BIGINT REFERENCES tv_organization(pk_organization)
        );
        """)

        # Views
        (schema_dir / "20_views" / "v_item.sql").write_text("""
        CREATE VIEW v_item AS
        SELECT i.id, i.name, o.pk_organization AS tenant_id
        FROM tb_item i
        LEFT JOIN tv_organization o ON i.fk_org = o.pk_organization;
        """)

        # Functions - one good, one bad
        (schema_dir / "30_functions" / "fn_create_item.sql").write_text("""
        CREATE FUNCTION fn_create_item(p_name TEXT) RETURNS BIGINT AS $$
        BEGIN
            INSERT INTO tb_item (id, name) VALUES (nextval('seq'), p_name);
            RETURN 1;
        END;
        $$ LANGUAGE plpgsql;
        """)

        (schema_dir / "30_functions" / "fn_create_item_safe.sql").write_text("""
        CREATE FUNCTION fn_create_item_safe(p_name TEXT, p_org BIGINT) RETURNS BIGINT AS $$
        BEGIN
            INSERT INTO tb_item (id, name, fk_org) VALUES (nextval('seq'), p_name, p_org);
            RETURN 1;
        END;
        $$ LANGUAGE plpgsql;
        """)

        # Run CLI
        result = runner.invoke(app, ["lint", "--project-dir", str(tmp_path)])

        # Should detect violation in fn_create_item
        assert "fn_create_item" in result.stdout
        assert "fk_org" in result.stdout

        # Should NOT flag fn_create_item_safe
        assert "fn_create_item_safe" not in result.stdout or "✅" in result.stdout
```

---

## Phase 9: Finalize

- [ ] Remove all development comments
- [ ] Ensure test coverage > 90% for new code
- [ ] Run full test suite (`uv run pytest`)
- [ ] Run linters (`uv run ruff check`, `uv run ruff format`)
- [ ] Update CHANGELOG.md
- [ ] Update CLI help text
- [ ] Write user documentation in docs/

---

## Appendix: Edge Cases to Handle

| Case | Handling |
|------|----------|
| Dynamic SQL (`EXECUTE format(...)`) | Mark as "cannot analyze", emit INFO |
| INSERT without column list | Mark as "cannot analyze", emit WARNING |
| Multiple INSERTs in one function | Check each independently |
| Schema-qualified table names | Normalize to just table name |
| CTE with INSERT | Extract and analyze |
| INSERT ... SELECT | Analyze SELECT columns |
| Nested functions calling other functions | Out of scope (too complex) |
| Views with multiple JOINs | Track all FK relationships |
| Composite tenant keys | Support multiple required_fk columns |

---

## Appendix: SQL Patterns Reference

```sql
-- Pattern 1: Direct FK join for tenant
CREATE VIEW v_item AS
SELECT i.*, org.id AS tenant_id
FROM tb_item i
JOIN tv_organization org ON i.fk_org = org.pk_organization;
-- Required: tb_item.fk_org

-- Pattern 2: Indirect FK through another table
CREATE VIEW v_order AS
SELECT o.*, cust.fk_org AS tenant_id
FROM tb_order o
JOIN tb_customer cust ON o.fk_customer = cust.id;
-- Required: tb_order.fk_customer (indirect tenant via customer)

-- Pattern 3: Multiple tenant columns
CREATE VIEW v_project AS
SELECT p.*, org.id AS tenant_id
FROM tb_project p
JOIN tv_organization org ON p.fk_org = org.pk_organization
WHERE p.fk_department IS NOT NULL;
-- Required: tb_project.fk_org AND tb_project.fk_department (if both used)
```
