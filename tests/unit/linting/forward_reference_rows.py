"""What PostgreSQL resolves when an object is created: the rows ``build_004`` is held to.

Each row is a schema tree, its files in build order, and whether PostgreSQL
refuses the bundle the build writes from it. The integration oracle
(``tests/integration/test_forward_reference_oracle.py``) applies each bundle to
an empty database and checks the verdict; the unit test
(``tests/unit/linting/test_build_004.py``) checks that ``build_004`` reports a
row exactly when PostgreSQL refuses it. The rule and PostgreSQL agree on every
row, or the row is wrong.
"""

from __future__ import annotations

from dataclasses import dataclass, field

SCHEMA = "CREATE SCHEMA app;\n"
TABLE = "CREATE TABLE app.tb_x (id int PRIMARY KEY, name text);\n"
FUNCTION = "CREATE FUNCTION app.fn_one() RETURNS int LANGUAGE sql IMMUTABLE AS $$ SELECT 1 $$;\n"
PLPGSQL_TRIGGER_FN = (
    "CREATE FUNCTION app.fn_touch() RETURNS trigger LANGUAGE plpgsql AS $$\n"
    "BEGIN RETURN NEW; END;\n"
    "$$;\n"
)


@dataclass(frozen=True)
class Row:
    """A tree in build order, and PostgreSQL's verdict on the bundle built from it.

    Attributes:
        name: The test id.
        files: ``(file name, SQL)`` in the order the build emits them.
        refused: Whether PostgreSQL refuses the bundle.
        needs: The object a finding names, when *refused*.
        two_pass: ``build.two_pass``: the builder moves foreign keys to the end.
    """

    name: str
    files: tuple[tuple[str, str], ...]
    refused: bool
    needs: str | None = None
    two_pass: bool = False
    tags: tuple[str, ...] = field(default=())


def _tree(*body: str) -> tuple[tuple[str, str], ...]:
    return (
        ("00_schema.sql", SCHEMA),
        *((f"{10 * (i + 1):02d}_{i}.sql", sql) for i, sql in enumerate(body)),
    )


ROWS: tuple[Row, ...] = (
    Row(
        "view-before-table",
        _tree("CREATE VIEW app.v_x AS SELECT id FROM app.tb_x;\n", TABLE),
        refused=True,
        needs="app.tb_x",
    ),
    Row(
        "view-after-table", _tree(TABLE, "CREATE VIEW app.v_x AS SELECT id FROM app.tb_x;\n"), False
    ),
    Row(
        "matview-before-table",
        _tree("CREATE MATERIALIZED VIEW app.mv_x AS SELECT id FROM app.tb_x;\n", TABLE),
        refused=True,
        needs="app.tb_x",
    ),
    Row(
        "view-calls-a-later-function",
        _tree("CREATE VIEW app.v_one AS SELECT app.fn_one() AS one;\n", FUNCTION),
        refused=True,
        needs="app.fn_one",
    ),
    Row(
        "sql-body-before-table",
        _tree(
            "CREATE FUNCTION app.first_x() RETURNS text LANGUAGE sql STABLE AS $$\n"
            "  SELECT name FROM app.tb_x ORDER BY id LIMIT 1\n"
            "$$;\n",
            TABLE,
        ),
        refused=True,
        needs="app.tb_x",
    ),
    Row(
        "sql-body-calls-a-later-function",
        _tree(
            "CREATE FUNCTION app.fn_two() RETURNS int LANGUAGE sql AS $$ SELECT app.fn_one() + 1 $$;\n",
            FUNCTION,
        ),
        refused=True,
        needs="app.fn_one",
    ),
    Row(
        "sql-begin-atomic-before-table",
        _tree(
            "CREATE FUNCTION app.first_x() RETURNS text LANGUAGE sql STABLE\n"
            "BEGIN ATOMIC\n"
            "  SELECT name FROM app.tb_x ORDER BY id LIMIT 1;\n"
            "END;\n",
            TABLE,
        ),
        refused=True,
        needs="app.tb_x",
    ),
    Row(
        "plpgsql-body-before-table",
        _tree(
            "CREATE FUNCTION app.first_x() RETURNS text LANGUAGE plpgsql STABLE AS $$\n"
            "BEGIN\n"
            "  RETURN (SELECT name FROM app.tb_x ORDER BY id LIMIT 1);\n"
            "END;\n"
            "$$;\n",
            TABLE,
        ),
        refused=False,
    ),
    Row(
        "sql-body-with-check-function-bodies-off",
        _tree(
            "SET check_function_bodies = false;\n",
            "CREATE FUNCTION app.first_x() RETURNS text LANGUAGE sql STABLE AS $$\n"
            "  SELECT name FROM app.tb_x ORDER BY id LIMIT 1\n"
            "$$;\n",
            TABLE,
        ),
        refused=False,
    ),
    Row(
        "trigger-before-its-function",
        _tree(
            TABLE,
            "CREATE TRIGGER tr_touch BEFORE UPDATE ON app.tb_x\n"
            "  FOR EACH ROW EXECUTE FUNCTION app.fn_touch();\n",
            PLPGSQL_TRIGGER_FN,
        ),
        refused=True,
        needs="app.fn_touch",
    ),
    Row(
        "default-calls-a-later-function",
        _tree("CREATE TABLE app.tb_y (id int DEFAULT app.fn_one());\n", FUNCTION),
        refused=True,
        needs="app.fn_one",
    ),
    Row(
        "check-calls-a-later-function",
        _tree("CREATE TABLE app.tb_y (id int CHECK (id > app.fn_one()));\n", FUNCTION),
        refused=True,
        needs="app.fn_one",
    ),
    Row(
        "generated-column-calls-a-later-function",
        _tree(
            "CREATE TABLE app.tb_y (id int, two int GENERATED ALWAYS AS (id + app.fn_one()) STORED);\n",
            FUNCTION,
        ),
        refused=True,
        needs="app.fn_one",
    ),
    Row(
        "index-expression-calls-a-later-function",
        _tree(
            TABLE,
            "CREATE INDEX ix_x ON app.tb_x ((id + app.fn_one()));\n",
            FUNCTION,
        ),
        refused=True,
        needs="app.fn_one",
    ),
    Row(
        "foreign-key-to-a-later-table",
        _tree("CREATE TABLE app.tb_y (id int, x_id int REFERENCES app.tb_x (id));\n", TABLE),
        refused=True,
        needs="app.tb_x",
    ),
    Row(
        "foreign-key-to-a-later-table-two-pass",
        _tree("CREATE TABLE app.tb_y (id int, x_id int REFERENCES app.tb_x (id));\n", TABLE),
        refused=False,
        two_pass=True,
    ),
    Row(
        "index-on-a-later-table",
        _tree("CREATE INDEX ix_x ON app.tb_x (name);\n", TABLE),
        refused=True,
        needs="app.tb_x",
    ),
    Row(
        "alter-a-later-table",
        _tree("ALTER TABLE app.tb_x ADD COLUMN note text;\n", TABLE),
        refused=True,
        needs="app.tb_x",
    ),
    Row(
        "inherits-a-later-table",
        _tree("CREATE TABLE app.tb_child (extra int) INHERITS (app.tb_x);\n", TABLE),
        refused=True,
        needs="app.tb_x",
    ),
    Row(
        "create-table-as-from-a-later-table",
        _tree("CREATE TABLE app.tb_copy AS SELECT id FROM app.tb_x;\n", TABLE),
        refused=True,
        needs="app.tb_x",
    ),
    Row(
        "alter-adds-a-foreign-key-to-a-later-table-two-pass",
        _tree(
            "CREATE TABLE app.tb_y (id int, x_id int);\n",
            "ALTER TABLE app.tb_y ADD FOREIGN KEY (x_id) REFERENCES app.tb_x (id);\n",
            TABLE,
        ),
        refused=True,
        needs="app.tb_x",
        two_pass=True,
    ),
    Row(
        "a-table-referencing-itself",
        _tree(
            "CREATE TABLE app.tb_n (id int PRIMARY KEY, parent_id int REFERENCES app.tb_n (id));\n"
        ),
        refused=False,
    ),
    Row(
        "a-sql-function-calling-itself",
        _tree(
            "CREATE FUNCTION app.fn_r(n int) RETURNS int LANGUAGE sql AS $$\n"
            "  SELECT CASE WHEN n <= 0 THEN 0 ELSE app.fn_r(n - 1) END\n"
            "$$;\n"
        ),
        # The routine's catalogue row exists before its body is checked.
        refused=False,
    ),
    Row(
        "comment-holding-a-line-comment-marker",
        _tree(
            TABLE,
            "COMMENT ON TABLE app.tb_x IS '-- not a comment';\n",
            "CREATE VIEW app.v_x AS SELECT id FROM app.tb_x;\n",
        ),
        refused=False,
    ),
    Row(
        "or-replace-later-is-not-the-first-create",
        _tree(
            FUNCTION,
            "CREATE VIEW app.v_one AS SELECT app.fn_one() AS one;\n",
            FUNCTION.replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION"),
        ),
        refused=False,
    ),
)
