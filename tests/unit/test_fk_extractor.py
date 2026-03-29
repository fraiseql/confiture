"""Tests for two-pass FK extraction from CREATE TABLE statements."""

from __future__ import annotations

from confiture.core.fk_extractor import (
    ForeignKeyInfo,
    extract_and_strip_fks,
    generate_alter_statements,
)

# ── ForeignKeyInfo ──────────────────────────────────────────────────────


class TestForeignKeyInfo:
    def test_fields(self):
        fk = ForeignKeyInfo(
            source_table="crm.tb_order",
            source_columns=["fk_product"],
            target_table="product.tb_product",
            target_columns=["pk_product"],
        )
        assert fk.source_table == "crm.tb_order"
        assert fk.source_columns == ["fk_product"]
        assert fk.target_table == "product.tb_product"
        assert fk.target_columns == ["pk_product"]
        assert fk.constraint_name is None
        assert fk.on_delete is None
        assert fk.on_update is None
        assert fk.deferrable is None

    def test_with_all_options(self):
        fk = ForeignKeyInfo(
            constraint_name="fk_order_product",
            source_table="crm.tb_order",
            source_columns=["fk_product"],
            target_table="product.tb_product",
            target_columns=["pk_product"],
            on_delete="CASCADE",
            on_update="SET NULL",
            deferrable="DEFERRABLE INITIALLY DEFERRED",
        )
        assert fk.constraint_name == "fk_order_product"
        assert fk.on_delete == "CASCADE"
        assert fk.on_update == "SET NULL"
        assert fk.deferrable == "DEFERRABLE INITIALLY DEFERRED"


# ── Inline REFERENCES extraction ────────────────────────────────────────


class TestInlineReferences:
    def test_simple_inline_reference(self):
        sql = """\
CREATE TABLE orders (
    id BIGINT PRIMARY KEY,
    customer_id BIGINT REFERENCES customers(id)
);
"""
        stripped, fks = extract_and_strip_fks(sql)
        assert len(fks) == 1
        assert fks[0].source_table == "orders"
        assert fks[0].source_columns == ["customer_id"]
        assert fks[0].target_table == "customers"
        assert fks[0].target_columns == ["id"]
        assert fks[0].constraint_name is None
        # REFERENCES clause should be removed from output
        assert "REFERENCES" not in stripped
        # Column definition should remain
        assert "customer_id BIGINT" in stripped

    def test_inline_reference_with_on_delete(self):
        sql = """\
CREATE TABLE orders (
    id BIGINT PRIMARY KEY,
    customer_id BIGINT NOT NULL REFERENCES customers(id) ON DELETE CASCADE
);
"""
        stripped, fks = extract_and_strip_fks(sql)
        assert len(fks) == 1
        assert fks[0].on_delete == "CASCADE"
        assert "REFERENCES" not in stripped
        assert "customer_id BIGINT NOT NULL" in stripped

    def test_inline_reference_with_on_update(self):
        sql = """\
CREATE TABLE orders (
    id BIGINT PRIMARY KEY,
    customer_id BIGINT REFERENCES customers(id) ON UPDATE SET NULL
);
"""
        stripped, fks = extract_and_strip_fks(sql)
        assert len(fks) == 1
        assert fks[0].on_update == "SET NULL"

    def test_inline_reference_with_both_on_actions(self):
        sql = """\
CREATE TABLE orders (
    id BIGINT PRIMARY KEY,
    customer_id BIGINT REFERENCES customers(id) ON DELETE CASCADE ON UPDATE SET DEFAULT
);
"""
        stripped, fks = extract_and_strip_fks(sql)
        assert len(fks) == 1
        assert fks[0].on_delete == "CASCADE"
        assert fks[0].on_update == "SET DEFAULT"

    def test_inline_reference_schema_qualified(self):
        sql = """\
CREATE TABLE crm.tb_order (
    pk_order BIGINT PRIMARY KEY,
    fk_product BIGINT REFERENCES product.tb_product(pk_product)
);
"""
        stripped, fks = extract_and_strip_fks(sql)
        assert len(fks) == 1
        assert fks[0].source_table == "crm.tb_order"
        assert fks[0].target_table == "product.tb_product"

    def test_inline_reference_no_target_column(self):
        """REFERENCES table without explicit column should use source column name."""
        sql = """\
CREATE TABLE orders (
    id BIGINT PRIMARY KEY,
    customer_id BIGINT REFERENCES customers
);
"""
        stripped, fks = extract_and_strip_fks(sql)
        assert len(fks) == 1
        assert fks[0].target_table == "customers"
        # When no target column specified, default to source column name
        assert fks[0].target_columns == ["customer_id"]

    def test_named_inline_constraint(self):
        sql = """\
CREATE TABLE orders (
    id BIGINT PRIMARY KEY,
    customer_id BIGINT CONSTRAINT fk_orders_customer REFERENCES customers(id)
);
"""
        stripped, fks = extract_and_strip_fks(sql)
        assert len(fks) == 1
        assert fks[0].constraint_name == "fk_orders_customer"

    def test_multiple_inline_references(self):
        sql = """\
CREATE TABLE orders (
    id BIGINT PRIMARY KEY,
    customer_id BIGINT REFERENCES customers(id),
    product_id BIGINT REFERENCES products(id)
);
"""
        stripped, fks = extract_and_strip_fks(sql)
        assert len(fks) == 2
        assert fks[0].source_columns == ["customer_id"]
        assert fks[1].source_columns == ["product_id"]

    def test_inline_reference_with_not_null_and_default(self):
        sql = """\
CREATE TABLE orders (
    id BIGINT PRIMARY KEY,
    status_id BIGINT NOT NULL DEFAULT 1 REFERENCES statuses(id)
);
"""
        stripped, fks = extract_and_strip_fks(sql)
        assert len(fks) == 1
        assert fks[0].source_columns == ["status_id"]
        assert "status_id BIGINT NOT NULL DEFAULT 1" in stripped


# ── Table-level FOREIGN KEY extraction ──────────────────────────────────


class TestTableLevelForeignKey:
    def test_named_table_level_fk(self):
        sql = """\
CREATE TABLE orders (
    id BIGINT PRIMARY KEY,
    customer_id BIGINT,
    CONSTRAINT fk_customer FOREIGN KEY (customer_id) REFERENCES customers (id)
);
"""
        stripped, fks = extract_and_strip_fks(sql)
        assert len(fks) == 1
        assert fks[0].constraint_name == "fk_customer"
        assert fks[0].source_columns == ["customer_id"]
        assert fks[0].target_table == "customers"
        assert fks[0].target_columns == ["id"]
        assert "FOREIGN KEY" not in stripped

    def test_multiline_named_table_level_fk(self):
        """CONSTRAINT name on separate line from FOREIGN KEY (issue #95)."""
        sql = """\
CREATE TABLE catalog.tb_industry (
    pk_industry BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    fk_parent_industry BIGINT,
    fk_info BIGINT,
    CONSTRAINT tb_industry_fk_info_fkey
        FOREIGN KEY (fk_info) REFERENCES catalog.tb_industry_info(pk_industry_info),
    CONSTRAINT tb_industry_fk_parent_fkey
        FOREIGN KEY (fk_parent_industry) REFERENCES catalog.tb_industry(pk_industry)
);
"""
        stripped, fks = extract_and_strip_fks(sql)
        assert len(fks) == 2
        assert fks[0].constraint_name == "tb_industry_fk_info_fkey"
        assert fks[1].constraint_name == "tb_industry_fk_parent_fkey"
        # No leftover CONSTRAINT or FOREIGN KEY in stripped output
        assert "CONSTRAINT" not in stripped
        assert "FOREIGN KEY" not in stripped
        # No trailing comma before closing paren
        assert ",\n);" not in stripped
        # Column definitions should remain
        assert "fk_parent_industry BIGINT" in stripped
        assert "fk_info BIGINT" in stripped

    def test_multiline_fk_with_actions(self):
        """Multi-line FK with ON DELETE/ON UPDATE on separate lines."""
        sql = """\
CREATE TABLE orders (
    id BIGINT PRIMARY KEY,
    customer_id BIGINT,
    CONSTRAINT fk_customer
        FOREIGN KEY (customer_id)
        REFERENCES customers (id)
        ON DELETE CASCADE
);
"""
        stripped, fks = extract_and_strip_fks(sql)
        assert len(fks) == 1
        assert fks[0].constraint_name == "fk_customer"
        assert fks[0].on_delete == "CASCADE"
        assert "CONSTRAINT" not in stripped
        assert "FOREIGN KEY" not in stripped

    def test_unnamed_table_level_fk(self):
        sql = """\
CREATE TABLE orders (
    id BIGINT PRIMARY KEY,
    customer_id BIGINT,
    FOREIGN KEY (customer_id) REFERENCES customers (id)
);
"""
        stripped, fks = extract_and_strip_fks(sql)
        assert len(fks) == 1
        assert fks[0].constraint_name is None

    def test_table_level_fk_with_actions(self):
        sql = """\
CREATE TABLE orders (
    id BIGINT PRIMARY KEY,
    customer_id BIGINT,
    CONSTRAINT fk_customer FOREIGN KEY (customer_id) REFERENCES customers (id) ON DELETE CASCADE ON UPDATE NO ACTION
);
"""
        stripped, fks = extract_and_strip_fks(sql)
        assert len(fks) == 1
        assert fks[0].on_delete == "CASCADE"
        assert fks[0].on_update == "NO ACTION"

    def test_multi_column_fk(self):
        sql = """\
CREATE TABLE order_items (
    id BIGINT PRIMARY KEY,
    order_id BIGINT,
    product_id BIGINT,
    CONSTRAINT fk_order_product FOREIGN KEY (order_id, product_id) REFERENCES order_products (order_id, product_id)
);
"""
        stripped, fks = extract_and_strip_fks(sql)
        assert len(fks) == 1
        assert fks[0].source_columns == ["order_id", "product_id"]
        assert fks[0].target_columns == ["order_id", "product_id"]

    def test_table_level_fk_with_deferrable(self):
        sql = """\
CREATE TABLE orders (
    id BIGINT PRIMARY KEY,
    customer_id BIGINT,
    CONSTRAINT fk_customer FOREIGN KEY (customer_id) REFERENCES customers (id) DEFERRABLE INITIALLY DEFERRED
);
"""
        stripped, fks = extract_and_strip_fks(sql)
        assert len(fks) == 1
        assert fks[0].deferrable == "DEFERRABLE INITIALLY DEFERRED"

    def test_table_level_fk_not_deferrable(self):
        sql = """\
CREATE TABLE orders (
    id BIGINT PRIMARY KEY,
    customer_id BIGINT,
    CONSTRAINT fk_customer FOREIGN KEY (customer_id) REFERENCES customers (id) NOT DEFERRABLE
);
"""
        stripped, fks = extract_and_strip_fks(sql)
        assert len(fks) == 1
        assert fks[0].deferrable == "NOT DEFERRABLE"


# ── Trailing comma cleanup ──────────────────────────────────────────────


class TestTrailingCommaCleanup:
    def test_fk_is_last_entry(self):
        """When FK constraint is the last item before ), trailing comma must be removed."""
        sql = """\
CREATE TABLE orders (
    id BIGINT PRIMARY KEY,
    customer_id BIGINT,
    CONSTRAINT fk_customer FOREIGN KEY (customer_id) REFERENCES customers (id)
);
"""
        stripped, fks = extract_and_strip_fks(sql)
        assert len(fks) == 1
        # Should not have trailing comma before )
        assert ",\n);" not in stripped
        # Should still be valid SQL structure
        assert "customer_id BIGINT\n);" in stripped or "customer_id BIGINT\n)" in stripped

    def test_fk_is_not_last_entry(self):
        """When FK is followed by other constraints, no comma issue."""
        sql = """\
CREATE TABLE orders (
    id BIGINT PRIMARY KEY,
    customer_id BIGINT,
    CONSTRAINT fk_customer FOREIGN KEY (customer_id) REFERENCES customers (id),
    CONSTRAINT uq_something UNIQUE (customer_id)
);
"""
        stripped, fks = extract_and_strip_fks(sql)
        assert len(fks) == 1
        # UNIQUE constraint should remain
        assert "UNIQUE" in stripped

    def test_multiple_fks_last_entries(self):
        """Multiple FK constraints at the end of table — all removed, comma cleaned."""
        sql = """\
CREATE TABLE orders (
    id BIGINT PRIMARY KEY,
    customer_id BIGINT,
    product_id BIGINT,
    FOREIGN KEY (customer_id) REFERENCES customers (id),
    FOREIGN KEY (product_id) REFERENCES products (id)
);
"""
        stripped, fks = extract_and_strip_fks(sql)
        assert len(fks) == 2
        assert "FOREIGN KEY" not in stripped
        assert ",\n);" not in stripped


# ── Mixed content (non-FK SQL preserved) ────────────────────────────────


class TestMixedContent:
    def test_create_index_preserved(self):
        sql = """\
CREATE TABLE orders (
    id BIGINT PRIMARY KEY,
    customer_id BIGINT REFERENCES customers(id)
);

CREATE INDEX idx_orders_customer ON orders (customer_id);
"""
        stripped, fks = extract_and_strip_fks(sql)
        assert len(fks) == 1
        assert "CREATE INDEX" in stripped

    def test_create_view_preserved(self):
        sql = """\
CREATE TABLE orders (
    id BIGINT PRIMARY KEY,
    customer_id BIGINT REFERENCES customers(id)
);

CREATE VIEW orders_view AS SELECT * FROM orders;
"""
        stripped, fks = extract_and_strip_fks(sql)
        assert "CREATE VIEW" in stripped

    def test_non_fk_constraints_preserved(self):
        sql = """\
CREATE TABLE orders (
    id BIGINT PRIMARY KEY,
    customer_id BIGINT REFERENCES customers(id),
    amount NUMERIC(10,2) CHECK (amount > 0),
    email TEXT UNIQUE
);
"""
        stripped, fks = extract_and_strip_fks(sql)
        assert len(fks) == 1
        assert "CHECK" in stripped
        assert "UNIQUE" in stripped

    def test_no_fks_returns_unchanged(self):
        sql = """\
CREATE TABLE orders (
    id BIGINT PRIMARY KEY,
    name TEXT NOT NULL,
    amount NUMERIC(10,2)
);
"""
        stripped, fks = extract_and_strip_fks(sql)
        assert len(fks) == 0
        assert stripped == sql

    def test_multiple_tables(self):
        sql = """\
CREATE TABLE customers (
    id BIGINT PRIMARY KEY,
    name TEXT NOT NULL
);

CREATE TABLE orders (
    id BIGINT PRIMARY KEY,
    customer_id BIGINT REFERENCES customers(id)
);

CREATE TABLE order_items (
    id BIGINT PRIMARY KEY,
    order_id BIGINT REFERENCES orders(id),
    product_id BIGINT REFERENCES products(id)
);
"""
        stripped, fks = extract_and_strip_fks(sql)
        assert len(fks) == 3
        assert fks[0].source_table == "orders"
        assert fks[1].source_table == "order_items"
        assert fks[2].source_table == "order_items"

    def test_create_table_if_not_exists(self):
        sql = """\
CREATE TABLE IF NOT EXISTS orders (
    id BIGINT PRIMARY KEY,
    customer_id BIGINT REFERENCES customers(id)
);
"""
        stripped, fks = extract_and_strip_fks(sql)
        assert len(fks) == 1
        assert fks[0].source_table == "orders"


# ── Quoted identifiers ──────────────────────────────────────────────────


class TestQuotedIdentifiers:
    def test_quoted_table_names(self):
        sql = """\
CREATE TABLE "MyOrders" (
    id BIGINT PRIMARY KEY,
    customer_id BIGINT REFERENCES "MyCustomers"("customerId")
);
"""
        stripped, fks = extract_and_strip_fks(sql)
        assert len(fks) == 1
        assert fks[0].source_table == '"MyOrders"'
        assert fks[0].target_table == '"MyCustomers"'
        assert fks[0].target_columns == ['"customerId"']

    def test_quoted_schema_qualified(self):
        sql = """\
CREATE TABLE "my_schema"."MyOrders" (
    id BIGINT PRIMARY KEY,
    customer_id BIGINT REFERENCES "other"."Customers"(id)
);
"""
        stripped, fks = extract_and_strip_fks(sql)
        assert len(fks) == 1
        assert fks[0].source_table == '"my_schema"."MyOrders"'
        assert fks[0].target_table == '"other"."Customers"'


# ── Comments ────────────────────────────────────────────────────────────


class TestComments:
    def test_commented_out_references_ignored(self):
        sql = """\
CREATE TABLE orders (
    id BIGINT PRIMARY KEY,
    -- customer_id BIGINT REFERENCES customers(id),
    customer_id BIGINT
);
"""
        stripped, fks = extract_and_strip_fks(sql)
        assert len(fks) == 0
        # Comment should be preserved
        assert "-- customer_id" in stripped

    def test_block_comment_references_ignored(self):
        sql = """\
CREATE TABLE orders (
    id BIGINT PRIMARY KEY,
    /* customer_id BIGINT REFERENCES customers(id), */
    customer_id BIGINT
);
"""
        stripped, fks = extract_and_strip_fks(sql)
        assert len(fks) == 0


# ── generate_alter_statements ───────────────────────────────────────────


class TestGenerateAlterStatements:
    def test_simple_alter(self):
        fks = [
            ForeignKeyInfo(
                source_table="orders",
                source_columns=["customer_id"],
                target_table="customers",
                target_columns=["id"],
            )
        ]
        result = generate_alter_statements(fks)
        assert "ALTER TABLE orders" in result
        assert "ADD CONSTRAINT orders_customer_id_fkey" in result
        assert "FOREIGN KEY (customer_id)" in result
        assert "REFERENCES customers (id)" in result

    def test_named_constraint_preserved(self):
        fks = [
            ForeignKeyInfo(
                constraint_name="fk_my_custom_name",
                source_table="orders",
                source_columns=["customer_id"],
                target_table="customers",
                target_columns=["id"],
            )
        ]
        result = generate_alter_statements(fks)
        assert "ADD CONSTRAINT fk_my_custom_name" in result

    def test_with_on_delete_cascade(self):
        fks = [
            ForeignKeyInfo(
                source_table="orders",
                source_columns=["customer_id"],
                target_table="customers",
                target_columns=["id"],
                on_delete="CASCADE",
            )
        ]
        result = generate_alter_statements(fks)
        assert "ON DELETE CASCADE" in result

    def test_with_on_update(self):
        fks = [
            ForeignKeyInfo(
                source_table="orders",
                source_columns=["customer_id"],
                target_table="customers",
                target_columns=["id"],
                on_update="SET NULL",
            )
        ]
        result = generate_alter_statements(fks)
        assert "ON UPDATE SET NULL" in result

    def test_with_deferrable(self):
        fks = [
            ForeignKeyInfo(
                source_table="orders",
                source_columns=["customer_id"],
                target_table="customers",
                target_columns=["id"],
                deferrable="DEFERRABLE INITIALLY DEFERRED",
            )
        ]
        result = generate_alter_statements(fks)
        assert "DEFERRABLE INITIALLY DEFERRED" in result

    def test_multi_column_alter(self):
        fks = [
            ForeignKeyInfo(
                source_table="order_items",
                source_columns=["order_id", "product_id"],
                target_table="order_products",
                target_columns=["order_id", "product_id"],
            )
        ]
        result = generate_alter_statements(fks)
        assert "FOREIGN KEY (order_id, product_id)" in result
        assert "REFERENCES order_products (order_id, product_id)" in result

    def test_schema_qualified_alter(self):
        fks = [
            ForeignKeyInfo(
                source_table="crm.tb_order",
                source_columns=["fk_product"],
                target_table="product.tb_product",
                target_columns=["pk_product"],
            )
        ]
        result = generate_alter_statements(fks)
        assert "ALTER TABLE crm.tb_order" in result
        assert "REFERENCES product.tb_product (pk_product)" in result

    def test_deterministic_name_for_unnamed_fk(self):
        """Unnamed FKs should get PostgreSQL-convention name: {table}_{column}_fkey."""
        fks = [
            ForeignKeyInfo(
                source_table="crm.tb_order",
                source_columns=["fk_product"],
                target_table="product.tb_product",
                target_columns=["pk_product"],
            )
        ]
        result = generate_alter_statements(fks)
        # Table name without schema prefix for constraint naming
        assert "tb_order_fk_product_fkey" in result

    def test_empty_list_returns_empty(self):
        result = generate_alter_statements([])
        assert result == ""

    def test_multiple_fks_all_emitted(self):
        fks = [
            ForeignKeyInfo(
                source_table="orders",
                source_columns=["customer_id"],
                target_table="customers",
                target_columns=["id"],
            ),
            ForeignKeyInfo(
                source_table="orders",
                source_columns=["product_id"],
                target_table="products",
                target_columns=["id"],
            ),
        ]
        result = generate_alter_statements(fks)
        assert result.count("ALTER TABLE") == 2

    def test_header_comment_present(self):
        fks = [
            ForeignKeyInfo(
                source_table="orders",
                source_columns=["customer_id"],
                target_table="customers",
                target_columns=["id"],
            )
        ]
        result = generate_alter_statements(fks)
        assert "Pass 2" in result or "Foreign Key" in result


# ── Full round-trip ─────────────────────────────────────────────────────


class TestRoundTrip:
    def test_issue_94_cross_schema_scenario(self):
        """The exact scenario from issue #94."""
        sql = """\
CREATE TABLE product.tb_product (
    pk_product BIGINT PRIMARY KEY,
    name TEXT NOT NULL
);

CREATE TABLE crm.tb_order (
    pk_order BIGINT PRIMARY KEY,
    fk_product BIGINT REFERENCES product.tb_product(pk_product),
    fk_quote BIGINT REFERENCES billing.tb_quote(pk_quote) ON DELETE SET NULL
);

CREATE TABLE billing.tb_quote (
    pk_quote BIGINT PRIMARY KEY,
    amount NUMERIC(10,2)
);
"""
        stripped, fks = extract_and_strip_fks(sql)
        assert len(fks) == 2

        # All CREATE TABLE should remain
        assert "CREATE TABLE product.tb_product" in stripped
        assert "CREATE TABLE crm.tb_order" in stripped
        assert "CREATE TABLE billing.tb_quote" in stripped

        # No REFERENCES in pass 1
        assert "REFERENCES" not in stripped

        # Generate pass 2
        alter_sql = generate_alter_statements(fks)
        assert "ALTER TABLE crm.tb_order" in alter_sql
        assert "product.tb_product" in alter_sql
        assert "billing.tb_quote" in alter_sql
        assert "ON DELETE SET NULL" in alter_sql

    def test_idempotent(self):
        """Running extract twice should produce same result (no FKs on second pass)."""
        sql = """\
CREATE TABLE orders (
    id BIGINT PRIMARY KEY,
    customer_id BIGINT REFERENCES customers(id)
);
"""
        stripped1, fks1 = extract_and_strip_fks(sql)
        stripped2, fks2 = extract_and_strip_fks(stripped1)
        assert len(fks1) == 1
        assert len(fks2) == 0
        assert stripped1 == stripped2

    def test_mixed_inline_and_table_level(self):
        sql = """\
CREATE TABLE orders (
    id BIGINT PRIMARY KEY,
    customer_id BIGINT NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    product_id BIGINT,
    CONSTRAINT fk_product FOREIGN KEY (product_id) REFERENCES products (id)
);
"""
        stripped, fks = extract_and_strip_fks(sql)
        assert len(fks) == 2
        assert "REFERENCES" not in stripped
        assert "FOREIGN KEY" not in stripped
        assert "customer_id BIGINT NOT NULL" in stripped
        assert "product_id BIGINT" in stripped
