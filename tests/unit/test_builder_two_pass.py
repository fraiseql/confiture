"""Tests for two-pass FK emission in SchemaBuilder (issue #94)."""

from __future__ import annotations

from confiture.core.builder import SchemaBuilder


def _make_project(tmp_path, files: dict[str, str], *, two_pass: bool = True):
    """Create a minimal project with the given schema files.

    Args:
        tmp_path: pytest tmp_path fixture
        files: dict mapping relative path (e.g., "01_identity/order.sql") to SQL content
        two_pass: whether to enable two-pass FK emission

    Returns:
        SchemaBuilder instance
    """
    schema_dir = tmp_path / "db" / "schema"

    for rel_path, content in files.items():
        full_path = schema_dir / rel_path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(content)

    config_dir = tmp_path / "db" / "environments"
    config_dir.mkdir(parents=True)
    config_file = config_dir / "test.yaml"
    config_file.write_text(
        f"name: test\n"
        f"include_dirs:\n"
        f"  - {schema_dir}\n"
        f"exclude_dirs: []\n"
        f"database_url: postgresql://localhost/test\n"
        f"build:\n"
        f"  two_pass: {'true' if two_pass else 'false'}\n"
    )

    return SchemaBuilder(env="test", project_dir=tmp_path)


class TestTwoPassBuild:
    def test_cross_schema_fk_stripped_and_emitted(self, tmp_path):
        """FKs referencing tables in later files should be deferred to pass 2."""
        builder = _make_project(
            tmp_path,
            {
                "01_identity/order.sql": (
                    "CREATE TABLE crm.tb_order (\n"
                    "    pk_order BIGINT PRIMARY KEY,\n"
                    "    fk_product BIGINT REFERENCES product.tb_product(pk_product)\n"
                    ");\n"
                ),
                "02_domain/product.sql": (
                    "CREATE TABLE product.tb_product (\n"
                    "    pk_product BIGINT PRIMARY KEY,\n"
                    "    name TEXT NOT NULL\n"
                    ");\n"
                ),
            },
        )

        schema = builder.build()

        # Pass 1: no REFERENCES in CREATE TABLE
        # Find the CREATE TABLE blocks and check they don't contain REFERENCES
        lines = schema.split("\n")
        in_create = False
        for line in lines:
            if "CREATE TABLE" in line:
                in_create = True
            if in_create and line.strip().startswith(");"):
                in_create = False
            if in_create:
                assert "REFERENCES" not in line

        # Pass 2: ALTER TABLE with FK constraint
        assert "ALTER TABLE crm.tb_order" in schema
        assert "REFERENCES product.tb_product (pk_product)" in schema
        assert "Pass 2" in schema or "Foreign Key" in schema

    def test_no_fks_no_pass2_section(self, tmp_path):
        """When no FK constraints exist, pass 2 section should not appear."""
        builder = _make_project(
            tmp_path,
            {
                "tables.sql": (
                    "CREATE TABLE users (\n    id BIGINT PRIMARY KEY,\n    name TEXT NOT NULL\n);\n"
                ),
            },
        )

        schema = builder.build()
        assert "Pass 2" not in schema
        assert "ALTER TABLE" not in schema

    def test_two_pass_disabled_preserves_inline_fks(self, tmp_path):
        """With two_pass=False, FK constraints stay inline."""
        builder = _make_project(
            tmp_path,
            {
                "tables.sql": (
                    "CREATE TABLE orders (\n"
                    "    id BIGINT PRIMARY KEY,\n"
                    "    customer_id BIGINT REFERENCES customers(id)\n"
                    ");\n"
                ),
            },
            two_pass=False,
        )

        schema = builder.build()
        assert "REFERENCES customers(id)" in schema
        assert "ALTER TABLE" not in schema

    def test_multiple_tables_with_fks(self, tmp_path):
        """Multiple tables with FKs — all extracted and emitted."""
        builder = _make_project(
            tmp_path,
            {
                "01/customers.sql": (
                    "CREATE TABLE customers (\n"
                    "    id BIGINT PRIMARY KEY,\n"
                    "    name TEXT NOT NULL\n"
                    ");\n"
                ),
                "02/orders.sql": (
                    "CREATE TABLE orders (\n"
                    "    id BIGINT PRIMARY KEY,\n"
                    "    customer_id BIGINT NOT NULL REFERENCES customers(id) ON DELETE CASCADE,\n"
                    "    product_id BIGINT REFERENCES products(id)\n"
                    ");\n"
                ),
                "03/products.sql": (
                    "CREATE TABLE products (\n"
                    "    id BIGINT PRIMARY KEY,\n"
                    "    name TEXT NOT NULL\n"
                    ");\n"
                ),
            },
        )

        schema = builder.build()

        # Both FKs should be in pass 2
        assert schema.count("ALTER TABLE") == 2
        assert "ON DELETE CASCADE" in schema

    def test_named_constraints_preserved(self, tmp_path):
        """Named FK constraints should keep their name in ALTER TABLE."""
        builder = _make_project(
            tmp_path,
            {
                "tables.sql": (
                    "CREATE TABLE orders (\n"
                    "    id BIGINT PRIMARY KEY,\n"
                    "    customer_id BIGINT,\n"
                    "    CONSTRAINT fk_order_customer FOREIGN KEY (customer_id) REFERENCES customers (id)\n"
                    ");\n"
                ),
            },
        )

        schema = builder.build()
        assert "fk_order_customer" in schema
        assert "ALTER TABLE orders" in schema

    def test_non_fk_content_preserved(self, tmp_path):
        """Indexes, views, and other non-FK SQL should be untouched."""
        builder = _make_project(
            tmp_path,
            {
                "schema.sql": (
                    "CREATE TABLE orders (\n"
                    "    id BIGINT PRIMARY KEY,\n"
                    "    customer_id BIGINT REFERENCES customers(id),\n"
                    "    amount NUMERIC(10,2) CHECK (amount > 0)\n"
                    ");\n"
                    "\n"
                    "CREATE INDEX idx_orders_customer ON orders (customer_id);\n"
                ),
            },
        )

        schema = builder.build()
        assert "CHECK (amount > 0)" in schema
        assert "CREATE INDEX idx_orders_customer" in schema

    def test_output_file_written(self, tmp_path):
        """Two-pass output should be written to file correctly."""
        builder = _make_project(
            tmp_path,
            {
                "tables.sql": (
                    "CREATE TABLE orders (\n"
                    "    id BIGINT PRIMARY KEY,\n"
                    "    customer_id BIGINT REFERENCES customers(id)\n"
                    ");\n"
                ),
            },
        )

        output = tmp_path / "output.sql"
        schema = builder.build(output_path=output)

        assert output.exists()
        content = output.read_text()
        assert content == schema
        assert "ALTER TABLE" in content


class TestTwoPassConfig:
    def test_config_default_is_false(self, tmp_path):
        """two_pass should default to False."""
        schema_dir = tmp_path / "db" / "schema"
        schema_dir.mkdir(parents=True)
        (schema_dir / "test.sql").write_text("CREATE TABLE t (id INT);")

        config_dir = tmp_path / "db" / "environments"
        config_dir.mkdir(parents=True)
        (config_dir / "test.yaml").write_text(
            f"name: test\n"
            f"include_dirs:\n"
            f"  - {schema_dir}\n"
            f"database_url: postgresql://localhost/test\n"
        )

        builder = SchemaBuilder(env="test", project_dir=tmp_path)
        assert builder.env_config.build.two_pass is False

    def test_config_enabled(self, tmp_path):
        """two_pass can be enabled via config."""
        schema_dir = tmp_path / "db" / "schema"
        schema_dir.mkdir(parents=True)
        (schema_dir / "test.sql").write_text("CREATE TABLE t (id INT);")

        config_dir = tmp_path / "db" / "environments"
        config_dir.mkdir(parents=True)
        (config_dir / "test.yaml").write_text(
            f"name: test\n"
            f"include_dirs:\n"
            f"  - {schema_dir}\n"
            f"database_url: postgresql://localhost/test\n"
            f"build:\n"
            f"  two_pass: true\n"
        )

        builder = SchemaBuilder(env="test", project_dir=tmp_path)
        assert builder.env_config.build.two_pass is True
