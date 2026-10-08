"""A create on a relation name another kind already holds creates nothing (#648).

A schema's relation names are one namespace across tables, views, materialized
views, sequences, indexes and composite types, and each row-typed relation also
takes the name in the schema's type namespace. Measured on PostgreSQL 18.4:
a later ``CREATE … IF NOT EXISTS`` on a name a relation holds is skipped, a
later plain ``CREATE`` fails the build (``42P07``/``42809``/``42710``), and a
name an enum or a domain holds refuses every later relation, ``IF NOT EXISTS``
or not (``42710``). Either way the schema keeps the first holder, and so does
the model. Two definitions of one *kind* stay ``build_001``'s.
"""

import pytest

from confiture.platform import parse_schema

_SCHEMA = "CREATE SCHEMA s;\nCREATE TABLE s.other (a bigint);\n"

#: How each kind is created first, holding the name ``s.x``. A plain
#: ``CREATE TABLE … AS`` is data to the model, not a table it holds.
HOLDERS = {
    "table": "CREATE TABLE s.x (a bigint);",
    "view": "CREATE VIEW s.x AS SELECT 1 AS a;",
    "matview": "CREATE MATERIALIZED VIEW s.x AS SELECT 1 AS a;",
    "sequence": "CREATE SEQUENCE s.x;",
    "index": "CREATE INDEX x ON s.other (a);",
    "composite": "CREATE TYPE s.x AS (a bigint);",
    "enum": "CREATE TYPE s.x AS ENUM ('a');",
    "domain": "CREATE DOMAIN s.x AS bigint;",
}

#: The later statements, and the kind each would add to the model.
LATER = {
    "table_ine": ("CREATE TABLE IF NOT EXISTS s.x (b text);", "table"),
    "table": ("CREATE TABLE s.x (b text);", "table"),
    "ctas_ine": ("CREATE TABLE IF NOT EXISTS s.x AS SELECT 'b'::text AS b;", "table"),
    "view": ("CREATE VIEW s.x AS SELECT 2 AS b;", "view"),
    "or_replace_view": ("CREATE OR REPLACE VIEW s.x AS SELECT 2 AS b;", "view"),
    "matview_ine": ("CREATE MATERIALIZED VIEW IF NOT EXISTS s.x AS SELECT 2 AS b;", "view"),
    "sequence_ine": ("CREATE SEQUENCE IF NOT EXISTS s.x;", "sequence"),
    "sequence": ("CREATE SEQUENCE s.x;", "sequence"),
    "enum": ("CREATE TYPE s.x AS ENUM ('b');", "enum"),
}

#: What the model holds of ``s.x`` before the later statement, per holder.
FIRST = {
    "table": {"table"},
    "view": {"view"},
    "matview": {"view"},
    "sequence": {"sequence"},
    "index": set(),
    "composite": set(),
    "enum": {"enum"},
    "domain": set(),
}

#: Measured on 18.4: the pairs where both survive — an enum beside a name only
#: a sequence or an index holds, neither of which has a row type.
COEXIST = {("sequence", "enum"), ("index", "enum")}

#: The same kind twice is build_001's (``duplicates.wins``), not this rule's.
SAME_KIND = {
    ("table", "table_ine"),
    ("table", "table"),
    ("table", "ctas_ine"),
    ("view", "view"),
    ("view", "or_replace_view"),
    ("matview", "matview_ine"),
    ("sequence", "sequence_ine"),
    ("sequence", "sequence"),
    ("enum", "enum"),
}


def _kinds_of_x(sql: str) -> set[str]:
    model = parse_schema(_SCHEMA + sql)
    kinds = set()
    for kind, objects in (
        ("table", model.tables),
        ("view", model.views),
        ("sequence", model.sequences),
        ("enum", model.enum_types),
        ("tview", model.tviews),
    ):
        if any(ref.schema == "s" and ref.name == "x" for ref in objects):
            kinds.add(kind)
    return kinds


@pytest.mark.parametrize(
    ("holder", "later"),
    [(h, later) for h in HOLDERS for later in LATER if (h, later) not in SAME_KIND],
)
def test_the_first_holder_keeps_the_name(holder: str, later: str) -> None:
    statement, adds = LATER[later]
    kinds = _kinds_of_x(f"{HOLDERS[holder]}\n{statement}\n")
    expected = FIRST[holder] | ({adds} if (holder, later) in COEXIST else set())
    assert kinds == expected


def test_the_issue_s_trees() -> None:
    assert _kinds_of_x(
        "CREATE VIEW s.x AS SELECT 1 AS a;\nCREATE TABLE IF NOT EXISTS s.x (a int);"
    ) == {"view"}
    model = parse_schema(
        "CREATE SCHEMA s;\nCREATE TABLE s.t (a int);\nCREATE SEQUENCE IF NOT EXISTS s.t;\n"
    )
    assert [ref.name for ref in model.tables] == ["t"]
    assert list(model.sequences) == []


def test_a_dropped_name_is_free_again() -> None:
    assert _kinds_of_x(
        "CREATE VIEW s.x AS SELECT 1 AS a;\nDROP VIEW s.x;\nCREATE TABLE IF NOT EXISTS s.x (a int);"
    ) == {"table"}


def test_a_renamed_holder_frees_its_old_name() -> None:
    assert _kinds_of_x(
        "CREATE VIEW s.x AS SELECT 1 AS a;\nALTER VIEW s.x RENAME TO y;\n"
        "CREATE TABLE IF NOT EXISTS s.x (a int);"
    ) == {"table"}


def test_a_later_drop_of_the_holder_does_not_revive_the_skipped_create() -> None:
    assert (
        _kinds_of_x(
            "CREATE VIEW s.x AS SELECT 1 AS a;\nCREATE TABLE IF NOT EXISTS s.x (a int);\nDROP VIEW s.x;"
        )
        == set()
    )


def test_another_schema_holds_another_name() -> None:
    model = parse_schema(
        "CREATE SCHEMA a;\nCREATE SCHEMA b;\nCREATE VIEW a.x AS SELECT 1 AS a;\n"
        "CREATE TABLE IF NOT EXISTS b.x (a int);"
    )
    assert [ref.name for ref in model.tables] == ["x"]
    assert [ref.name for ref in model.views] == ["x"]


def test_an_unqualified_create_is_in_the_default_schema() -> None:
    model = parse_schema(
        "CREATE VIEW x AS SELECT 1 AS a;\nCREATE TABLE IF NOT EXISTS public.x (a int);"
    )
    assert list(model.tables) == []


def test_a_tview_holds_its_name() -> None:
    model = parse_schema(
        "CREATE TABLE tb_post (pk_post bigint PRIMARY KEY, id uuid);\n"
        "CREATE TABLE tv_post AS SELECT pk_post, id FROM tb_post;\n"
        "CREATE TABLE IF NOT EXISTS tv_post (a int);\n"
    )
    assert [ref.name for ref in model.tviews] == ["tv_post"]
    assert [ref.name for ref in model.tables] == ["tb_post"]


def _lint(tmp_path, monkeypatch, files: dict[str, str]):
    from confiture.core.linting.schema_linter import LintConfig, SchemaLinter

    schema = tmp_path / "db" / "schema"
    schema.mkdir(parents=True)
    (tmp_path / "db" / "environments").mkdir()
    (tmp_path / "db" / "environments" / "local.yaml").write_text(
        "database_url: postgresql://localhost/test\ninclude_dirs:\n  - db/schema\n"
    )
    for name, text in files.items():
        (schema / name).write_text(text)
    monkeypatch.chdir(tmp_path)
    report = SchemaLinter(env="local", config=LintConfig()).lint()
    return [v for v in report.errors + report.warnings if v.rule_id in {"build_005", "build_006"}]


def test_lint_names_a_table_postgresql_skips_and_the_view_that_took_its_name(
    tmp_path, monkeypatch
) -> None:
    (found,) = _lint(
        tmp_path,
        monkeypatch,
        {
            "010.sql": "CREATE SCHEMA s;\nCREATE VIEW s.x AS SELECT 1 AS a;\n",
            "020.sql": "\nCREATE TABLE IF NOT EXISTS s.x (a int);\n",
        },
    )
    assert (found.rule_id, found.object_type, found.object_name) == ("build_005", "table", "x")
    assert (found.file_path, found.line_number) == ("db/schema/020.sql", 2)
    assert found.message == (
        "Table 'x': its schema already holds a view of that name (db/schema/010.sql (line 2)) "
        "— PostgreSQL skips this statement, so the table it describes is never built"
    )


@pytest.mark.parametrize(
    ("first", "later", "sqlstate", "held_by"),
    [
        ("CREATE TABLE s.x (a int);", "CREATE SEQUENCE s.x;", "42P07", "a table"),
        (
            "CREATE TABLE s.x (a int);",
            "CREATE OR REPLACE VIEW s.x AS SELECT 1 AS a;",
            "42809",
            "a table",
        ),
        (
            "CREATE TYPE s.x AS ENUM ('a');",
            "CREATE TABLE IF NOT EXISTS s.x (a int);",
            "42710",
            "a type",
        ),
        ("CREATE VIEW s.x AS SELECT 1 AS a;", "CREATE DOMAIN s.x AS int;", "42710", "a view"),
    ],
)
def test_lint_reports_a_create_postgresql_refuses_as_a_failed_build(
    tmp_path, monkeypatch, first: str, later: str, sqlstate: str, held_by: str
) -> None:
    (found,) = _lint(tmp_path, monkeypatch, {"010.sql": f"CREATE SCHEMA s;\n{first}\n{later}\n"})
    assert found.rule_id == "build_006"
    assert f"already holds {held_by} of that name" in found.message
    assert f"PostgreSQL refuses this statement ({sqlstate})" in found.message


def test_an_enum_beside_a_sequence_of_its_name_is_no_finding(tmp_path, monkeypatch) -> None:
    assert (
        _lint(
            tmp_path,
            monkeypatch,
            {"010.sql": "CREATE SCHEMA s;\nCREATE SEQUENCE s.x;\nCREATE TYPE s.x AS ENUM ('a');\n"},
        )
        == []
    )


def test_the_object_list_agrees_with_the_model() -> None:
    from confiture.core.ddl_objects import objects_in
    from confiture.core.sql_lexer import parse_file

    files = [
        parse_file(
            "CREATE SCHEMA s;\nCREATE TABLE s.x (a int);\n"
            "CREATE MATERIALIZED VIEW IF NOT EXISTS s.x AS SELECT 1 AS a;\n"
            "CREATE VIEW s.y AS SELECT 1 AS a;\n"
            "CREATE MATERIALIZED VIEW IF NOT EXISTS s.y AS SELECT 2 AS b;\n",
            "010.sql",
            0,
        )
    ]
    declared = {(ref.kind, ref.name) for ref in objects_in(files)}
    assert ("matview", "x") not in declared
    assert ("view", "y") in declared
    assert ("matview", "y") not in declared
