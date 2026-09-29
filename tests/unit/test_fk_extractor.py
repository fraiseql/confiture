"""Two-pass foreign keys: every FK moves out of its ``CREATE TABLE`` and nothing else changes.

The oracle is the schema model. The tree a two-pass build writes — the tables
without their foreign keys, then one ``ALTER TABLE … ADD`` per key — declares
the same schema as the tree it was built from, so both read into the same
model. A row that reads into a different model is a build that applies a
different schema than the author wrote (#511).
"""

from __future__ import annotations

import pglast
import pytest

from confiture.core.ddl_walk import read_column_constraints, read_constraint
from confiture.core.fk_extractor import extract_and_strip_fks, generate_alter_statements
from confiture.core.linting.inventory import build_model
from confiture.core.schema_model import Constraint, SchemaModel

ROWS: dict[str, str] = {
    "inline": """\
CREATE TABLE orders (
    id BIGINT PRIMARY KEY,
    customer_id BIGINT REFERENCES customers(id)
);
""",
    "inline_with_actions": """\
CREATE TABLE orders (
    id BIGINT PRIMARY KEY,
    customer_id BIGINT NOT NULL REFERENCES customers(id) ON DELETE CASCADE ON UPDATE SET NULL
);
""",
    "inline_no_column_list": """\
CREATE TABLE b (
    id int PRIMARY KEY,
    org_fk bigint REFERENCES org
);
""",
    "inline_named_deferrable_then_not_null": """\
CREATE TABLE b (
    id int PRIMARY KEY,
    org_fk bigint CONSTRAINT b_org REFERENCES org (id) DEFERRABLE INITIALLY DEFERRED NOT NULL
);
""",
    "inline_schema_qualified": """\
CREATE TABLE crm.tb_order (
    pk_order BIGINT PRIMARY KEY,
    fk_product BIGINT REFERENCES product.tb_product(pk_product),
    fk_quote BIGINT REFERENCES billing.tb_quote(pk_quote) ON DELETE SET NULL
);
""",
    "table_level_named_multiline": """\
CREATE TABLE orders (
    id BIGINT PRIMARY KEY,
    customer_id BIGINT,
    CONSTRAINT fk_customer
        FOREIGN KEY (customer_id)
        REFERENCES customers (id)
        ON DELETE CASCADE
        DEFERRABLE INITIALLY IMMEDIATE
);
""",
    "table_level_no_ref_columns": """\
CREATE TABLE b (
    id int PRIMARY KEY,
    org_id bigint,
    FOREIGN KEY (org_id) REFERENCES org
);
""",
    "table_level_first_element": """\
CREATE TABLE b (
    FOREIGN KEY (org_id) REFERENCES org (id),
    org_id bigint
);
""",
    "table_level_between_constraints": """\
CREATE TABLE orders (
    id BIGINT PRIMARY KEY,
    customer_id BIGINT,
    amount NUMERIC(10,2),
    CHECK (amount > 0),
    CONSTRAINT fk_customer FOREIGN KEY (customer_id) REFERENCES customers (id),
    UNIQUE (customer_id, amount)
);
""",
    "table_level_all_last": """\
CREATE TABLE catalog.tb_industry (
    pk_industry BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    fk_parent_industry BIGINT,
    fk_info BIGINT,
    label TEXT NOT NULL,
    CONSTRAINT tb_industry_fk_info_fkey
        FOREIGN KEY (fk_info) REFERENCES catalog.tb_industry_info(pk_industry_info),
    CONSTRAINT tb_industry_fk_parent_fkey
        FOREIGN KEY (fk_parent_industry) REFERENCES catalog.tb_industry(pk_industry)
);
""",
    "multi_column": """\
CREATE TABLE line (
    order_id bigint,
    line_no int,
    FOREIGN KEY (order_id, line_no) REFERENCES order_line (order_id, line_no)
);
""",
    "string_literal_is_not_a_reference": """\
CREATE TABLE b (
    id int PRIMARY KEY,
    note text DEFAULT 'see REFERENCES manual (note)',
    org_id bigint REFERENCES org
);
""",
    "comments_between_elements": """\
CREATE TABLE orders (
    id BIGINT PRIMARY KEY,
    -- the customer
    customer_id BIGINT REFERENCES customers(id), -- trailing note
    /* the product */
    product_id BIGINT,
    CONSTRAINT fk_product FOREIGN KEY (product_id) REFERENCES products (id)
    -- closing note
);
""",
    "several_tables_and_other_statements": """\
CREATE SCHEMA domain;
CREATE TABLE identity.tb_contact (
    pk_contact BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    fk_org BIGINT NOT NULL,
    CONSTRAINT tb_contact_fk_org_fkey FOREIGN KEY (fk_org) REFERENCES identity.tb_org(pk_org)
);
CREATE TABLE IF NOT EXISTS domain.tb_order (
    pk_order BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    fk_contact BIGINT NOT NULL REFERENCES identity.tb_contact(pk_contact),
    amount NUMERIC(10,2) CHECK (amount >= 0)
);
CREATE INDEX idx_order_contact ON domain.tb_order (fk_contact);
CREATE VIEW domain.v_order AS SELECT pk_order FROM domain.tb_order;
""",
    "multibyte_before_the_key": """\
COMMENT ON SCHEMA public IS 'café — déjà';
CREATE TABLE b (
    label text DEFAULT 'naïve',
    org_id bigint REFERENCES org (id)
);
""",
}


def _by_table(model: SchemaModel) -> dict[tuple[str | None, str], frozenset[Constraint]]:
    return {(t.schema, t.name): frozenset(t.constraints) for t in model.tables.values()}


def _two_pass(sql: str) -> tuple[str, str, int]:
    stripped, fks = extract_and_strip_fks(sql)
    return stripped, generate_alter_statements(fks), len(fks)


def _foreign_keys_in_tables(sql: str) -> list[Constraint]:
    """Every foreign key a ``CREATE TABLE`` in *sql* still declares."""
    found: list[Constraint] = []
    for raw in pglast.parse_sql(sql):
        if type(raw.stmt).__name__ != "CreateStmt":
            continue
        for element in raw.stmt.tableElts or ():
            if type(element).__name__ == "ColumnDef":
                found.extend(read_column_constraints(element)[1])
            else:
                found.append(read_constraint(element))
    return [c for c in found if isinstance(c, Constraint) and c.kind == "foreign_key"]


@pytest.mark.parametrize("name", ROWS)
def test_the_two_pass_tree_declares_the_schema_the_tree_declares(name: str) -> None:
    sql = ROWS[name]
    stripped, alters, _moved = _two_pass(sql)
    assert _by_table(build_model(stripped + "\n" + alters)) == _by_table(build_model(sql))


@pytest.mark.parametrize("name", ROWS)
def test_every_foreign_key_leaves_its_create_table(name: str) -> None:
    sql = ROWS[name]
    stripped, _alters, moved = _two_pass(sql)
    assert moved == len(_foreign_keys_in_tables(sql))
    assert _foreign_keys_in_tables(stripped) == []


@pytest.mark.parametrize("name", ROWS)
def test_one_alter_per_moved_key(name: str) -> None:
    _stripped, alters, moved = _two_pass(ROWS[name])
    statements = [raw.stmt for raw in pglast.parse_sql(alters)]
    assert len(statements) == moved
    assert all(type(stmt).__name__ == "AlterTableStmt" for stmt in statements)


@pytest.mark.parametrize("name", ROWS)
def test_a_second_pass_moves_nothing(name: str) -> None:
    stripped, _alters, _moved = _two_pass(ROWS[name])
    again, fks = extract_and_strip_fks(stripped)
    assert (again, fks) == (stripped, [])


def test_what_is_not_a_foreign_key_is_kept_byte_for_byte() -> None:
    sql = ROWS["several_tables_and_other_statements"]
    stripped, _alters, _moved = _two_pass(sql)
    for kept in (
        "CREATE SCHEMA domain;",
        "CREATE INDEX idx_order_contact ON domain.tb_order (fk_contact);",
        "CREATE VIEW domain.v_order AS SELECT pk_order FROM domain.tb_order;",
        "    amount NUMERIC(10,2) CHECK (amount >= 0)\n);",
        "    fk_contact BIGINT NOT NULL,\n",
    ):
        assert kept in stripped


def test_a_string_literal_is_never_read_as_a_reference() -> None:
    stripped, _alters, moved = _two_pass(ROWS["string_literal_is_not_a_reference"])
    assert moved == 1
    assert "note text DEFAULT 'see REFERENCES manual (note)'," in stripped


def test_comments_stay_where_the_author_wrote_them() -> None:
    stripped, _alters, _moved = _two_pass(ROWS["comments_between_elements"])
    assert (
        stripped
        == """\
CREATE TABLE orders (
    id BIGINT PRIMARY KEY,
    -- the customer
    customer_id BIGINT, -- trailing note
    /* the product */
    product_id BIGINT
    -- closing note
);
"""
    )


def test_a_table_level_key_leaves_no_blank_line_and_no_stray_comma() -> None:
    stripped, _alters, _moved = _two_pass(ROWS["table_level_all_last"])
    assert (
        stripped
        == """\
CREATE TABLE catalog.tb_industry (
    pk_industry BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    fk_parent_industry BIGINT,
    fk_info BIGINT,
    label TEXT NOT NULL
);
"""
    )


def test_an_unnamed_key_is_left_for_postgresql_to_name() -> None:
    """PostgreSQL names ``b_org_id_fkey`` itself, as it would have named the inline key."""
    _stripped, alters, _moved = _two_pass(ROWS["table_level_no_ref_columns"])
    assert "CONSTRAINT" not in alters
    assert "FOREIGN KEY (org_id) REFERENCES org" in alters


@pytest.mark.parametrize(
    "clause",
    [
        "REFERENCES org (x, y) MATCH FULL ON DELETE CASCADE",
        "REFERENCES org (x, y) ON DELETE SET NULL (x)",
    ],
)
def test_a_key_the_model_cannot_hold_stays_where_it_was_written(clause: str) -> None:
    """The model holds no MATCH type and no SET NULL column list: moving it would drop them."""
    sql = f"CREATE TABLE b (\n    x int,\n    y int,\n    FOREIGN KEY (x, y) {clause}\n);\n"
    stripped, fks = extract_and_strip_fks(sql)
    assert (stripped, fks) == (sql, [])


def test_a_statement_the_parser_rejects_costs_only_itself() -> None:
    sql = (
        "CREATE TABLE a (id int REFERENCES org (id));\n"
        "CREATE TABLE broken (id int REFERENCES org (id) oops oops);\n"
        "CREATE TABLE c (id int REFERENCES org (id));\n"
    )
    stripped, fks = extract_and_strip_fks(sql)
    assert [fk.table.name for fk in fks] == ["a", "c"]
    assert "CREATE TABLE broken (id int REFERENCES org (id) oops oops);" in stripped


def test_a_copy_block_is_not_read() -> None:
    sql = (
        "COPY t (a) FROM stdin;\n"
        "x REFERENCES y (z)\n"
        "\\.\n"
        "CREATE TABLE b (org_id bigint REFERENCES org (id));\n"
    )
    stripped, fks = extract_and_strip_fks(sql)
    assert len(fks) == 1
    assert stripped.startswith("COPY t (a) FROM stdin;\nx REFERENCES y (z)\n\\.\n")


def test_no_foreign_key_means_no_alter_block() -> None:
    sql = "CREATE TABLE a (id int PRIMARY KEY);\n"
    assert extract_and_strip_fks(sql) == (sql, [])
    assert generate_alter_statements([]) == ""
