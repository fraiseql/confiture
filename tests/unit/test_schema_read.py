"""The one read of a tree: each file parsed once, every position a line of a file."""

from __future__ import annotations

from pathlib import Path

import pytest

from confiture.core.schema_read import Segment, read_segments
from confiture.exceptions import SchemaError
from confiture.platform import parse_schema


def _project(root: Path, files: dict[str, str]) -> Path:
    for name, text in files.items():
        path = root / "db" / "schema" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    (root / "db" / "environments").mkdir(parents=True)
    (root / "db" / "environments" / "local.yaml").write_text(
        "database_url: postgresql://localhost/test\ninclude_dirs:\n  - db/schema\n"
    )
    return root


def test_an_environment_s_rejected_statement_is_named_by_its_file(tmp_path: Path) -> None:
    project = _project(
        tmp_path,
        {"10_ok.sql": "CREATE TABLE a (id int);\n", "20_bad.sql": "\nCREATE TABEL b (id int);\n"},
    )

    with pytest.raises(SchemaError) as caught:
        parse_schema(env="local", project_dir=project)

    assert caught.value.error_code == "DIFFER_400"
    assert caught.value.context == {"file": str(project / "db/schema/20_bad.sql"), "line": 2}


def test_an_environment_s_columns_are_named_relative_to_the_project(tmp_path: Path) -> None:
    project = _project(tmp_path, {"10_t.sql": "CREATE TABLE t (\n    id int\n);\n"})

    (table,) = parse_schema(env="local", project_dir=project).tables.values()

    assert [(c.file, c.line) for c in table.columns] == [("db/schema/10_t.sql", 2)]


def test_positions_take_no_part_in_what_a_schema_is() -> None:
    one = read_segments([Segment(None, "CREATE TABLE t (id int);\n", "a.sql")]).model
    other = read_segments([Segment(None, "\n\nCREATE TABLE t (\n  id int\n);\n", "b.sql")]).model

    assert one == other


def test_order_across_files_is_the_order_they_are_read() -> None:
    # A drop in a later file reaches a table an earlier one created; a create
    # after it declares the table again.
    read = read_segments(
        [
            Segment(None, "CREATE TABLE t (id int);\n", "1.sql"),
            Segment(None, "DROP TABLE t;\n", "2.sql"),
            Segment(None, "CREATE TABLE t (id bigint);\n", "3.sql"),
        ]
    )

    (table,) = read.model.tables.values()
    assert [c.type_key for c in table.columns] == ["bigint"]
