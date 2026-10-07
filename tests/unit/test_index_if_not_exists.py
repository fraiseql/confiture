"""A ``CREATE INDEX IF NOT EXISTS`` on a name already taken is a no-op (#638).

An index's name lives in its schema's relation namespace: PostgreSQL 18 skips
``CREATE INDEX IF NOT EXISTS i ON s.t2 (…)`` when ``s.i`` is already an index on
``s.t``, or a table, and keeps the first. The model keeps what PostgreSQL keeps.
"""

from __future__ import annotations

from confiture.platform import parse_schema

_TABLES = "CREATE SCHEMA s;\nCREATE TABLE s.t (id bigint PRIMARY KEY, a bigint, b bigint);\n"


def _indexes(sql: str) -> dict[str, list[tuple[str, tuple[str, ...]]]]:
    model = parse_schema(_TABLES + sql)
    return {
        f"{table.schema}.{table.name}": [(index.name, index.columns) for index in table.indexes]
        for table in model.tables.values()
    }


def test_a_later_if_not_exists_on_the_same_table_keeps_the_first() -> None:
    indexes = _indexes(
        "CREATE INDEX IF NOT EXISTS idx_t_a ON s.t (a);\n"
        "CREATE INDEX IF NOT EXISTS idx_t_a ON s.t (b);\n"
    )
    assert indexes["s.t"] == [("idx_t_a", ("a",))]


def test_a_later_if_not_exists_on_another_table_of_the_schema_is_skipped() -> None:
    indexes = _indexes(
        "CREATE TABLE s.t2 (a bigint);\n"
        "CREATE INDEX IF NOT EXISTS i ON s.t (a);\n"
        "CREATE INDEX IF NOT EXISTS i ON s.t2 (a);\n"
    )
    assert indexes["s.t"] == [("i", ("a",))]
    assert indexes["s.t2"] == []


def test_an_if_not_exists_named_like_a_table_is_skipped() -> None:
    indexes = _indexes("CREATE TABLE s.t2 (a bigint);\nCREATE INDEX IF NOT EXISTS t2 ON s.t (a);\n")
    assert indexes["s.t"] == []


def test_the_same_name_in_another_schema_is_another_index() -> None:
    indexes = _indexes(
        "CREATE SCHEMA r;\nCREATE TABLE r.t (a bigint);\n"
        "CREATE INDEX IF NOT EXISTS i ON s.t (a);\n"
        "CREATE INDEX IF NOT EXISTS i ON r.t (a);\n"
    )
    assert indexes["s.t"] == [("i", ("a",))]
    assert indexes["r.t"] == [("i", ("a",))]


def test_a_dropped_name_is_free_again() -> None:
    indexes = _indexes(
        "CREATE INDEX IF NOT EXISTS i ON s.t (a);\nDROP INDEX s.i;\n"
        "CREATE INDEX IF NOT EXISTS i ON s.t (b);\n"
    )
    assert indexes["s.t"] == [("i", ("b",))]


def test_a_name_a_key_s_index_holds_is_taken() -> None:
    indexes = _indexes(
        "ALTER TABLE s.t ADD CONSTRAINT uq_t_a UNIQUE (a);\n"
        "CREATE INDEX IF NOT EXISTS uq_t_a ON s.t (b);\n"
    )
    assert indexes["s.t"] == []


def test_an_unnamed_index_never_collides() -> None:
    indexes = _indexes("CREATE INDEX ON s.t (a);\nCREATE INDEX ON s.t (a);\n")
    assert indexes["s.t"] == [(None, ("a",)), (None, ("a",))]


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


def test_lint_names_the_statement_that_creates_nothing_and_the_one_that_took_the_name(
    tmp_path, monkeypatch
) -> None:
    (found,) = _lint(
        tmp_path,
        monkeypatch,
        {
            "010.sql": _TABLES + "CREATE INDEX IF NOT EXISTS idx_t_a ON s.t (a);\n",
            "020.sql": "\nCREATE INDEX IF NOT EXISTS idx_t_a ON s.t (b);\n",
        },
    )
    assert found.rule_id == "build_005"
    assert found.file_path.endswith("020.sql")
    assert found.line_number == 2
    assert "010.sql (line 3)" in found.message


def test_lint_reports_a_plain_create_on_a_taken_name_as_a_failed_build(
    tmp_path, monkeypatch
) -> None:
    (found,) = _lint(
        tmp_path,
        monkeypatch,
        {"010.sql": _TABLES + "CREATE INDEX t ON s.t (a);\n"},
    )
    assert found.rule_id == "build_006"
    assert "already holds a table of that name" in found.message
