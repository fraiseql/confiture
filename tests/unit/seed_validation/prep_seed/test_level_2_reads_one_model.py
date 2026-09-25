"""Level 2 reads the schema tree as one model, the way the build reads it (#374).

It parsed each file on its own into a partial model of its own, so an ``ALTER``
in one file on a table another file creates was lost, and a file it could not
read or parse was skipped without a word. It now reads ``parse_schema``'s model
of the whole tree once: a file the parser rejects is a finding naming its file
and line, and a file it cannot read is the seam's error naming it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from confiture.core.seed.validation.prep_seed.models import ViolationSeverity
from confiture.core.seed.validation.prep_seed.orchestrator import (
    OrchestrationConfig,
    PrepSeedOrchestrator,
)
from confiture.exceptions import SchemaError

PREP = "CREATE TABLE prep_seed.tb_x (id UUID, fk_y_id UUID);\n"
CATALOG = "CREATE TABLE catalog.tb_x (id UUID, pk_x BIGINT);\n"


def _run(tmp_path: Path, **files: bytes | str) -> list[str]:
    schema = tmp_path / "schema"
    for name, content in files.items():
        path = schema / name.replace("__", "/")
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_text(content)
    seeds = tmp_path / "seeds"
    seeds.mkdir()
    config = OrchestrationConfig(max_level=2, seeds_dir=seeds, schema_dir=schema)
    return [v.message for v in PrepSeedOrchestrator(config).run().violations]


def test_an_alter_in_another_file_is_part_of_the_table(tmp_path: Path) -> None:
    messages = _run(
        tmp_path,
        **{
            "10_tables.sql": PREP + CATALOG,
            "20_alter.sql": "ALTER TABLE catalog.tb_x ADD COLUMN fk_y BIGINT;\n",
        },
    )
    assert not [m for m in messages if "fk_y" in m], messages


def test_a_nested_file_is_read(tmp_path: Path) -> None:
    messages = _run(tmp_path, **{"10_prep.sql": PREP, "sub__10_catalog.sql": CATALOG})
    assert not [m for m in messages if "no corresponding final table" in m], messages


def test_a_file_that_is_not_utf8_is_an_error_naming_it(tmp_path: Path) -> None:
    """Not read is not passed: the seam's error, as at levels 1 and 3."""
    with pytest.raises(SchemaError, match=r"20_latin1\.sql") as caught:
        _run(
            tmp_path,
            **{"10_tables.sql": PREP + CATALOG, "20_latin1.sql": "-- café\n".encode("latin-1")},
        )
    assert isinstance(caught.value.__cause__, UnicodeDecodeError)


def test_a_file_the_parser_rejects_is_a_finding_naming_its_file_and_line(tmp_path: Path) -> None:
    messages = _run(
        tmp_path,
        **{"10_tables.sql": PREP + CATALOG, "20_broken.sql": "\n\nCREATE TABLE (;\n"},
    )
    assert [m for m in messages if "20_broken.sql:3" in m], messages


def test_what_level_2_cannot_read_is_critical(tmp_path: Path) -> None:
    schema = tmp_path / "schema"
    schema.mkdir()
    (schema / "broken.sql").write_text("CREATE TABLE (;\n")
    seeds = tmp_path / "seeds"
    seeds.mkdir()
    report = PrepSeedOrchestrator(
        OrchestrationConfig(max_level=2, seeds_dir=seeds, schema_dir=schema)
    ).run()
    assert [v.severity for v in report.violations] == [ViolationSeverity.CRITICAL]


def test_a_resolver_file_is_not_skipped_by_its_name(tmp_path: Path) -> None:
    """What a file defines decides, not what it is called."""
    messages = _run(tmp_path, **{"10_prep.sql": PREP, "fn_resolve_tb_x.sql": CATALOG})
    assert not [m for m in messages if "no corresponding final table" in m], messages


def _findings(tmp_path: Path, **files: str) -> list:
    schema = tmp_path / "schema"
    for name, content in files.items():
        path = schema / name.replace("__", "/")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    seeds = tmp_path / "seeds"
    seeds.mkdir()
    config = OrchestrationConfig(max_level=2, seeds_dir=seeds, schema_dir=schema)
    return PrepSeedOrchestrator(config).run().violations


def test_a_finding_names_the_file_and_line_the_table_is_created_on(tmp_path: Path) -> None:
    """The file a table is in is what the schema read says, never ``db/schema/<table>.sql``."""
    found = _findings(
        tmp_path,
        **{
            "prep__tables.sql": "-- prep\n\n" + PREP,
            "catalog__all.sql": "CREATE SCHEMA catalog;\n"
            + "CREATE TABLE catalog.tb_x (id UUID);\n",
        },
    )
    by_message = {v.message.split(" ", 2)[1]: v for v in found}
    places = {
        (Path(v.file_path).relative_to(tmp_path / "schema").as_posix(), v.line_number)
        for v in found
    }
    assert places == {("prep/tables.sql", 3), ("catalog/all.sql", 2)}, by_message


def test_a_prep_table_without_a_final_table_is_found_where_it_is_created(tmp_path: Path) -> None:
    (missing,) = _findings(tmp_path, **{"a__b.sql": "\n" + PREP})
    assert "no corresponding final table catalog.tb_x" in missing.message
    assert (Path(missing.file_path).name, missing.line_number) == ("b.sql", 2)


def test_a_self_reference_names_the_resolver_that_must_handle_it(tmp_path: Path) -> None:
    found = _findings(
        tmp_path,
        **{
            "10.sql": "CREATE TABLE prep_seed.tb_node (id UUID, fk_parent_node_id UUID);\n"
            "CREATE TABLE catalog.tb_node (id UUID, pk_node BIGINT, fk_parent_node BIGINT);\n",
            "fn__resolve.sql": "\n\nCREATE FUNCTION catalog.fn_resolve_tb_node() RETURNS void "
            "LANGUAGE sql AS $$ SELECT 1 $$;\n",
        },
    )
    (self_ref,) = [v for v in found if "self-referencing" in v.message]
    assert (Path(self_ref.file_path).name, self_ref.line_number) == ("resolve.sql", 3)
