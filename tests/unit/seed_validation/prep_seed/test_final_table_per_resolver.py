"""Each staging table's final table is found, not built from one schema name (#458).

Levels 2-5 assumed every ``prep_seed.<table>`` resolves into
``<catalog_schema>.<table>``. A tree whose resolvers fill tables in several
schemas — shared reference data in one, per-tenant tables in another — got a
false ``MISSING_FK_MAPPING`` for every table outside ``catalog_schema``, and
the level 3 join check never looked at those tables.

The final table is decided once: the ``INSERT`` target of the resolver that
reads ``prep_seed.<table>``; otherwise the one schema the tree declares
``<table>`` in (outside the prep-seed schema); otherwise ``catalog_schema``.
"""

from __future__ import annotations

from pathlib import Path

from confiture import platform
from confiture.core.seed.validation.prep_seed.models import PrepSeedPattern

TABLES = """
CREATE SCHEMA catalog; CREATE SCHEMA tenant; CREATE SCHEMA prep_seed;
CREATE TABLE catalog.tb_color (
    pk_color BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id UUID NOT NULL UNIQUE,
    name TEXT NOT NULL
);
CREATE TABLE tenant.tb_widget (
    pk_widget BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id UUID NOT NULL UNIQUE,
    fk_color BIGINT REFERENCES catalog.tb_color (pk_color)
);
CREATE TABLE prep_seed.tb_color (id UUID NOT NULL, name TEXT NOT NULL);
CREATE TABLE prep_seed.tb_widget (id UUID NOT NULL, fk_color_id UUID);
"""

COLOR_RESOLVER = """
CREATE FUNCTION catalog.fn_resolve_tb_color() RETURNS void LANGUAGE plpgsql AS $$
BEGIN INSERT INTO catalog.tb_color (id, name) SELECT id, name FROM prep_seed.tb_color; END $$;
"""

WIDGET_RESOLVER = """
CREATE FUNCTION tenant.fn_resolve_tb_widget() RETURNS void LANGUAGE plpgsql AS $$
BEGIN INSERT INTO tenant.tb_widget (id, fk_color)
      SELECT w.id, c.pk_color FROM prep_seed.tb_widget w
      LEFT JOIN catalog.tb_color c ON c.id = w.fk_color_id; END $$;
"""


def _validate(tmp_path: Path, ddl: str, **kwargs: object) -> platform.PrepSeedReport:
    schema = tmp_path / "schema"
    schema.mkdir()
    (schema / "10_tables.sql").write_text(ddl)
    seeds = tmp_path / "seeds"
    seeds.mkdir()
    return platform.validate_seeds(seeds, schema_dir=schema, max_level=3, **kwargs)  # ty: ignore[invalid-argument-type]


def _messages(report: platform.PrepSeedReport, pattern: PrepSeedPattern) -> list[str]:
    return [v.message for v in report.violations if v.pattern == pattern]


class TestTheResolverSaysWhereItWrites:
    def test_a_table_resolved_outside_catalog_schema_has_its_final_table(
        self, tmp_path: Path
    ) -> None:
        """The issue's repro: level 2 reported ``catalog.tb_widget`` missing."""
        report = _validate(tmp_path, TABLES + COLOR_RESOLVER + WIDGET_RESOLVER)
        assert _messages(report, PrepSeedPattern.MISSING_FK_MAPPING) == []

    def test_the_control_tree_all_in_catalog_is_still_clean(self, tmp_path: Path) -> None:
        ddl = (TABLES + COLOR_RESOLVER + WIDGET_RESOLVER).replace("tenant.", "catalog.")
        report = _validate(tmp_path, ddl)
        assert _messages(report, PrepSeedPattern.MISSING_FK_MAPPING) == []

    def test_level_2_compares_the_table_the_resolver_fills(self, tmp_path: Path) -> None:
        """``tenant.tb_widget`` has no ``fk_color``: the finding names that table."""
        ddl = (TABLES + COLOR_RESOLVER + WIDGET_RESOLVER).replace(
            ",\n    fk_color BIGINT REFERENCES catalog.tb_color (pk_color)", ""
        )
        report = _validate(tmp_path, ddl)
        assert _messages(report, PrepSeedPattern.MISSING_FK_MAPPING) == [
            "prep_seed.tb_widget.fk_color_id has no corresponding column tenant.tb_widget.fk_color"
        ]

    def test_level_3_checks_the_joins_of_a_resolver_filling_another_schema(
        self, tmp_path: Path
    ) -> None:
        """Level 3 checked joins only for inserts into ``catalog_schema``."""
        unjoined = """
CREATE FUNCTION tenant.fn_resolve_tb_widget() RETURNS void LANGUAGE plpgsql AS $$
BEGIN INSERT INTO tenant.tb_widget (id) SELECT w.id FROM prep_seed.tb_widget w; END $$;
"""
        report = _validate(tmp_path, TABLES + COLOR_RESOLVER + unjoined)
        (message,) = _messages(report, PrepSeedPattern.MISSING_FK_TRANSFORMATION)
        assert "fills tenant.tb_widget" in message
        assert "LEFT JOIN catalog.tb_color" in (
            next(
                v.suggestion
                for v in report.violations
                if v.pattern == PrepSeedPattern.MISSING_FK_TRANSFORMATION
            )
            or ""
        )

    def test_an_unqualified_target_is_the_default_schema(self, tmp_path: Path) -> None:
        """``INSERT INTO tb_widget`` writes ``public.tb_widget``, even when
        ``catalog`` holds a table of that name too: the resolver decides. The
        finding spells the table as its ``CREATE`` does, with no invented
        ``public.``."""
        ddl = (
            TABLES.replace("tenant.tb_widget", "catalog.tb_widget")
            + "CREATE TABLE tb_widget (pk_widget BIGINT PRIMARY KEY, id UUID NOT NULL);\n"
            + COLOR_RESOLVER
            + """
CREATE FUNCTION fn_resolve_tb_widget() RETURNS void LANGUAGE plpgsql AS $$
BEGIN INSERT INTO tb_widget (id) SELECT w.id FROM prep_seed.tb_widget w; END $$;
"""
        )
        report = _validate(tmp_path, ddl)
        assert _messages(report, PrepSeedPattern.MISSING_FK_MAPPING) == [
            "prep_seed.tb_widget.fk_color_id has no corresponding column tb_widget.fk_color"
        ]


class TestWithoutAResolverTheSchemaDecides:
    def test_a_name_declared_in_one_schema_is_that_table(self, tmp_path: Path) -> None:
        report = _validate(tmp_path, TABLES + COLOR_RESOLVER)
        assert _messages(report, PrepSeedPattern.MISSING_FK_MAPPING) == []

    def test_a_name_declared_in_two_schemas_is_an_ambiguity_never_a_guess(
        self, tmp_path: Path
    ) -> None:
        ddl = (
            TABLES
            + COLOR_RESOLVER
            + (
                "CREATE SCHEMA archive;\n"
                "CREATE TABLE archive.tb_widget (pk_widget BIGINT PRIMARY KEY, id UUID NOT NULL);\n"
            )
        )
        report = _validate(tmp_path, ddl)
        assert _messages(report, PrepSeedPattern.MISSING_FK_MAPPING) == []
        (message,) = _messages(report, PrepSeedPattern.AMBIGUOUS_FINAL_TABLE)
        assert "archive.tb_widget" in message
        assert "tenant.tb_widget" in message

    def test_a_name_declared_nowhere_falls_back_to_catalog_schema(self, tmp_path: Path) -> None:
        ddl = TABLES + COLOR_RESOLVER + "CREATE TABLE prep_seed.tb_gadget (id UUID NOT NULL);\n"
        report = _validate(tmp_path, ddl)
        assert _messages(report, PrepSeedPattern.MISSING_FK_MAPPING) == [
            "prep_seed.tb_gadget has no corresponding final table catalog.tb_gadget"
        ]
