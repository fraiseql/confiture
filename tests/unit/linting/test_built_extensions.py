"""What extensions a build creates, where each lands, and where it is written (#741).

``build_003`` asks this to know which schemas an extension's routines may live
in. *Which* extensions the tree keeps is ``ddl_objects.declared_objects``'
answer, so a later ``DROP EXTENSION`` and a repeated name fold as they do for
every other object; *what* each one says is read off the statement that kept it.
"""

from confiture.core.linting.extensions import (
    BuiltExtension,
    built_extensions,
    extension_schemas,
)
from confiture.core.schema_identity import DEFAULT_SCHEMA
from confiture.core.sql_lexer import parse_file


def _built(*files: tuple[str, str]) -> list[BuiltExtension]:
    parsed = []
    base = 0
    for label, text in files:
        parsed.append(parse_file(text, label, base))
        base += len(text) + 1
    return built_extensions(parsed)


class TestNameAndWrittenSchema:
    def test_a_written_schema_is_kept(self) -> None:
        [ext] = _built(("001.sql", "CREATE EXTENSION IF NOT EXISTS ltree SCHEMA public;\n"))

        assert (ext.name, ext.schema, ext.schema_written) == ("ltree", "public", True)

    def test_the_line_is_the_statement_s_own(self) -> None:
        exts = _built(
            (
                "001.sql",
                "CREATE EXTENSION IF NOT EXISTS ltree SCHEMA public;\n"
                "\n"
                "CREATE EXTENSION IF NOT EXISTS unaccent SCHEMA public;\n",
            )
        )

        assert [(e.name, e.file, e.line) for e in exts] == [
            ("ltree", "001.sql", 1),
            ("unaccent", "001.sql", 3),
        ]

    def test_a_second_file_names_itself_and_its_own_line(self) -> None:
        exts = _built(
            ("001.sql", "CREATE SCHEMA app;\nCREATE TABLE app.t (a int);\n"),
            ("002.sql", "-- the extensions\nCREATE EXTENSION ltree SCHEMA app;\n"),
        )

        assert [(e.file, e.line) for e in exts] == [("002.sql", 2)]

    def test_build_order_is_kept(self) -> None:
        exts = _built(
            ("001.sql", "CREATE EXTENSION unaccent SCHEMA public;\n"),
            ("002.sql", "CREATE EXTENSION ltree SCHEMA public;\n"),
        )

        assert [e.name for e in exts] == ["unaccent", "ltree"]


class TestDefaultsAndEdgeShapes:
    def test_no_schema_clause_lands_in_the_default_schema_unwritten(self) -> None:
        [ext] = _built(("001.sql", "CREATE EXTENSION pgcrypto;\n"))

        assert (ext.schema, ext.schema_written) == (DEFAULT_SCHEMA, False)

    def test_the_schema_alone_cannot_stand_in_for_whether_it_was_written(self) -> None:
        """``schema`` is always filled in, so only ``schema_written`` tells the two apart."""
        [unwritten] = _built(("001.sql", "CREATE EXTENSION pgcrypto;\n"))
        [written] = _built(("001.sql", f"CREATE EXTENSION pgcrypto SCHEMA {DEFAULT_SCHEMA};\n"))

        assert unwritten.schema == written.schema
        assert unwritten.schema_written != written.schema_written

    def test_version_and_cascade_are_kept_in_the_statement(self) -> None:
        [ext] = _built(("001.sql", "CREATE EXTENSION x WITH SCHEMA app VERSION '1.1' CASCADE;\n"))

        assert ext.schema == "app"
        assert ext.cascade
        assert "VERSION '1.1'" in ext.create_sql
        assert "CASCADE" in ext.create_sql
        assert "IF NOT EXISTS" in ext.create_sql

    def test_a_quoted_schema_keeps_the_parser_s_spelling(self) -> None:
        [ext] = _built(("001.sql", 'CREATE EXTENSION x SCHEMA "Ext";\n'))

        assert ext.schema == "Ext"

    def test_a_repeated_name_is_one_extension_the_first(self) -> None:
        exts = _built(
            (
                "001.sql",
                "CREATE EXTENSION IF NOT EXISTS ltree SCHEMA public;\n"
                "CREATE EXTENSION IF NOT EXISTS ltree SCHEMA app;\n",
            )
        )

        assert [(e.name, e.schema, e.line) for e in exts] == [("ltree", "public", 1)]

    def test_a_dropped_extension_is_not_created(self) -> None:
        exts = _built(("001.sql", "CREATE EXTENSION x SCHEMA public;\nDROP EXTENSION x;\n"))

        assert exts == []

    def test_a_parameterless_create_language_is_the_extension_postgresql_makes_of_it(
        self,
    ) -> None:
        exts = _built(
            (
                "001.sql",
                "CREATE LANGUAGE plpgsql;\nCREATE OR REPLACE TRUSTED LANGUAGE plperl;\n",
            )
        )

        assert [(e.name, e.schema, e.schema_written) for e in exts] == [
            ("plpgsql", DEFAULT_SCHEMA, False),
            ("plperl", DEFAULT_SCHEMA, False),
        ]

    def test_a_language_with_a_handler_is_not_an_extension(self) -> None:
        assert _built(("001.sql", "CREATE LANGUAGE foo HANDLER foo_handler;\n")) == []


class TestSchemasForTheScratch:
    def test_a_schema_the_tree_creates_and_an_extension_names(self) -> None:
        """Names only: the tree's ``AUTHORIZATION`` and schema elements are not replayed."""
        text = (
            "CREATE SCHEMA app AUTHORIZATION some_role CREATE TABLE app.t (a int);\n"
            "CREATE SCHEMA other;\n"
            "CREATE EXTENSION ltree SCHEMA app;\n"
        )
        parsed = [parse_file(text, "001.sql")]

        assert extension_schemas(built_extensions(parsed), parsed) == frozenset({"app"})

    def test_a_schema_the_tree_never_creates_is_not_named(self) -> None:
        text = "CREATE EXTENSION ltree SCHEMA nowhere;\n"
        parsed = [parse_file(text, "001.sql")]

        assert extension_schemas(built_extensions(parsed), parsed) == frozenset()
