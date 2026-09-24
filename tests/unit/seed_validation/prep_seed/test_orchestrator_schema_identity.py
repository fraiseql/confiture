"""Level 2 reads the qualifier the statement wrote, not the file's path (#317).

Level 2 decided which side a table was on from
``"prep_seed" in str(sql_file)`` and keyed the result on ``table.name``. That is
#313's defect one module over: the schema is a fact the statement carries —
``Table.schema`` has held it since 1.13.0 — and a bare name is not an identity.

It is latent rather than active only because the shipped
``examples/06-prep-seed-validation`` happens to put its two ``tb_manufacturer``
declarations in directories the heuristic separates correctly.
"""

from __future__ import annotations

from pathlib import Path

from confiture.core.seed.validation.prep_seed.orchestrator import (
    OrchestrationConfig,
    PrepSeedOrchestrator,
    SchemaTables,
)


def _orchestrator(schema_dir: Path, **kwargs: object) -> PrepSeedOrchestrator:
    seeds_dir = schema_dir.parent / "seeds"
    seeds_dir.mkdir(exist_ok=True)
    return PrepSeedOrchestrator(
        OrchestrationConfig(
            max_level=2,
            seeds_dir=seeds_dir,
            schema_dir=schema_dir,
            **kwargs,  # ty: ignore[invalid-argument-type]
        )
    )


def _tables(orchestrator: PrepSeedOrchestrator) -> SchemaTables:
    return orchestrator._schema_tables(orchestrator._read_schema()[0])


def _schema_dir(tmp_path: Path, **files: str) -> Path:
    schema_dir = tmp_path / "schema"
    schema_dir.mkdir(parents=True, exist_ok=True)
    for name, sql in files.items():
        path = schema_dir / (name.replace("__", "/") + ".sql")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(sql)
    return schema_dir


class TestTheQualifierDecidesWhichSideATableIsOn:
    def test_one_file_holding_both_sides_separates_them(self, tmp_path: Path) -> None:
        """The heuristic sent the whole file to one side, and the second
        declaration silently overwrote the first."""
        schema_dir = _schema_dir(
            tmp_path,
            tables__all="CREATE TABLE prep_seed.tb_x (id UUID);\n"
            "CREATE TABLE catalog.tb_x (id UUID, pk_x BIGINT);",
        )
        tables = _tables(_orchestrator(schema_dir))
        prep, catalog = tables.prep, tables.catalog
        assert [t.name for t in prep.values()] == ["tb_x"]
        assert [t.name for t in catalog.values()] == ["tb_x"]

    def test_a_path_that_merely_contains_prep_seed_does_not_decide(self, tmp_path: Path) -> None:
        schema_dir = _schema_dir(
            tmp_path,
            prep_seed_archive__tables="CREATE TABLE catalog.tb_y (id UUID, pk_y BIGINT);",
        )
        tables = _tables(_orchestrator(schema_dir))
        prep, catalog = tables.prep, tables.catalog
        assert prep == {}
        assert [t.name for t in catalog.values()] == ["tb_y"]

    def test_a_table_in_neither_configured_schema_is_on_neither_side(self, tmp_path: Path) -> None:
        """``tenant.tb_x`` and ``etl.tb_x`` both landed in ``catalog_tables``
        under one key, so one of them vanished. Neither belongs to level 2."""
        schema_dir = _schema_dir(
            tmp_path,
            tables__twins="CREATE TABLE tenant.tb_x (id UUID);\nCREATE TABLE etl.tb_x (id UUID);",
        )
        tables = _tables(_orchestrator(schema_dir))
        prep, catalog = tables.prep, tables.catalog
        assert (prep, catalog) == ({}, {})

    def test_a_missing_qualifier_folds_to_the_default_schema(self, tmp_path: Path) -> None:
        """``CREATE TABLE tb_z`` is ``public.tb_z``, which is neither side —
        unless the project configured ``public`` as one of them."""
        schema_dir = _schema_dir(tmp_path, tables__bare="CREATE TABLE tb_z (id UUID);")
        tables = _tables(_orchestrator(schema_dir, catalog_schema="public"))
        prep, catalog = tables.prep, tables.catalog
        assert prep == {}
        assert [t.name for t in catalog.values()] == ["tb_z"]

    def test_the_configured_schema_names_are_honoured(self, tmp_path: Path) -> None:
        schema_dir = _schema_dir(
            tmp_path,
            tables__x="CREATE TABLE staging.tb_x (id UUID);\nCREATE TABLE final.tb_x (id UUID);",
        )
        tables = _tables(
            _orchestrator(schema_dir, prep_seed_schema="staging", catalog_schema="final")
        )
        prep, catalog = tables.prep, tables.catalog
        assert [t.schema for t in prep.values()] == ["staging"]
        assert [t.schema for t in catalog.values()] == ["final"]


class TestIdentityIsSchemaAndName:
    def test_two_declarations_of_one_table_are_a_finding_not_a_silence(
        self, tmp_path: Path
    ) -> None:
        """Last-one-wins is what #313 removed from the differ. The same answer
        here: the collapse is reported."""
        schema_dir = _schema_dir(
            tmp_path,
            a__tb_x="CREATE TABLE catalog.tb_x (id UUID, pk_x BIGINT);",
            b__tb_x="CREATE TABLE catalog.tb_x (id UUID, pk_x BIGINT, extra TEXT);",
        )
        report = _orchestrator(schema_dir).run()
        assert any(
            "defined" in v.message and "catalog.tb_x" in v.message for v in report.violations
        )

    def test_the_first_declaration_is_the_one_kept(self, tmp_path: Path) -> None:
        """``confiture build`` concatenates in order and a later plain ``CREATE``
        fails at that statement, so the first is what the database has."""
        schema_dir = _schema_dir(
            tmp_path,
            a__tb_x="CREATE TABLE catalog.tb_x (id UUID, pk_x BIGINT);",
            b__tb_x="CREATE TABLE catalog.tb_x (id UUID, pk_x BIGINT, extra TEXT);",
        )
        catalog = _tables(_orchestrator(schema_dir)).catalog
        assert [sorted(c.folded for c in t.columns) for t in catalog.values()] == [["id", "pk_x"]]


class TestTheSilenceThatWouldHaveReplacedTheHeuristic:
    def test_a_tree_with_no_table_in_either_schema_says_so(self, tmp_path: Path) -> None:
        """The path heuristic used to route unqualified DDL; the qualifier cannot.

        Level 2 returning no violations for a schema it never looked at is the
        silent pass, so it is a finding instead.
        """
        schema_dir = _schema_dir(
            tmp_path, tables__bare="CREATE TABLE tb_a (id UUID);\nCREATE TABLE tb_b (id UUID);"
        )
        report = _orchestrator(schema_dir).run()
        message = " ".join(v.message for v in report.violations)
        assert "prep_seed" in message
        assert "public" in message

    def test_an_empty_schema_tree_says_nothing(self, tmp_path: Path) -> None:
        """Nothing declared is not the same as nothing in the right schema."""
        report = _orchestrator(_schema_dir(tmp_path)).run()
        assert report.violations == []
