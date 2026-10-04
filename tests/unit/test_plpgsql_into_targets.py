"""A multi-target ``INTO`` with a variable of a type the compiler cannot see (#558).

libpg_query's PL/pgSQL compiler has no catalogue. On pglast 8 it resolves a
built-in type for real and **any other type name to ``record``** — ``ltree``,
``citext``, an unqualified domain — and a record is legal as a lone ``INTO``
target but not in a list, so ``SELECT … INTO a, b`` with ``b ltree`` is
refused; ``b s.my_domain`` is refused before that. PostgreSQL accepts both.
Blanking cannot fix it: the type name itself is what is wrong. So the oracle
may also *substitute* a declared variable's type with ``text``; it is still the
compiler that decides, one substitution at a time, which are needed.
"""

import pglast
import pytest

from confiture.core.plpgsql_fragments import fragments
from confiture.core.plpgsql_parse import parse_body


def _function(declare: str, body: str) -> str:
    return (
        "CREATE FUNCTION s.f() RETURNS void LANGUAGE plpgsql AS $$\n"
        f"DECLARE\n    {declare}\nBEGIN\n    {body}\nEND;\n$$;"
    )


@pytest.mark.parametrize(
    "declare",
    [
        "a bigint; b ltree;",
        "a bigint; b citext;",
        "a bigint; b hstore;",
        "a bigint; b s.my_domain;",
        "a bigint; b ltree[];",
        "a bigint; b s.my_domain[];",
        "a bigint; b t;",
        "a bigint; b id;",
        "a bigint; b ltree NOT NULL := 'x';",
    ],
)
@pytest.mark.parametrize("targets", ["a, b", "b, a"])
def test_a_multi_target_into_compiles(declare: str, targets: str) -> None:
    statement = _function(declare, f"SELECT id, label INTO {targets} FROM s.t;")
    compiled = parse_body(statement)
    assert compiled.tree


def test_the_lines_and_the_fragments_are_the_author_s() -> None:
    """What the body holds, and on which line, is what it holds written with a type it reads."""

    def read(type_name: str) -> list[tuple[str, int]]:
        statement = _function(
            f"a bigint;\n    b {type_name}\n        := s.fn_default();",
            "SELECT id, label INTO a, b FROM s.t;\n    PERFORM s.fn_after(a);",
        )
        return [(f.text, f.line) for f in fragments(parse_body(statement))]

    assert read("ltree") == read("text")


def test_a_type_the_compiler_reads_is_left_alone() -> None:
    statement = _function("a bigint; b text;", "SELECT id, label INTO a, b FROM s.t;")
    assert parse_body(statement).text == statement


def test_a_record_in_a_multi_target_into_is_still_refused() -> None:
    """``record`` is never substituted: PostgreSQL refuses this body too."""
    statement = _function("a bigint; r record;", "SELECT id, label INTO a, r FROM s.t;")
    with pytest.raises(pglast.parser.ParseError):
        parse_body(statement)


def test_a_type_copied_from_a_column_is_not_a_candidate() -> None:
    statement = _function("a bigint; b s.t.label%TYPE;", "SELECT id, label INTO a, b FROM s.t;")
    compiled = parse_body(statement)
    assert "%TYPE" in compiled.text


def test_lint_reads_the_body_it_used_to_report_unread(tmp_path, monkeypatch) -> None:
    """#558's report: ``build_003 ran on less than the whole schema: could not read N bodies``."""
    from confiture.core.linting.schema_linter import LintConfig, SchemaLinter

    schema = tmp_path / "db" / "schema"
    schema.mkdir(parents=True)
    (tmp_path / "db" / "environments").mkdir()
    (tmp_path / "db" / "environments" / "local.yaml").write_text(
        "database_url: postgresql://localhost/test\ninclude_dirs:\n  - db/schema\n"
    )
    (schema / "10.sql").write_text(
        "CREATE SCHEMA s;\nCREATE TABLE s.t (id bigint, label text);\n"
        + _function("a bigint; b ltree;", "SELECT id, label INTO a, b FROM s.t;")
        + "\n"
    )
    monkeypatch.chdir(tmp_path)

    report = SchemaLinter(env="local", config=LintConfig(check_references=True)).lint()

    assert not [d for d in report.degraded if "could not read" in (d.reason or "")]
