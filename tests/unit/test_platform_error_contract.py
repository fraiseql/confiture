"""What ``confiture.platform`` raises: confiture's own errors, each naming what it refused.

A consumer catches :class:`~confiture.exceptions.ConfiturError` and reads a code
and a hint. A ``KeyError`` from a dict, an ``AttributeError`` from a ``str`` taken
for a ``Path`` or a driver exception is none of those, and a typo that returns an
empty result reads as success. Two errors are Python's own on purpose: a
``TypeError`` for an argument of the wrong type, and the ``ValueError`` the
docstrings promise for an argument combination that cannot run.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import psycopg
import pytest

from confiture import platform
from confiture.platform import ConfigurationError, SchemaError

MODEL = platform.parse_schema(
    "CREATE TABLE app_parent (id INT PRIMARY KEY);\n"
    "CREATE TABLE app_child (id INT, parent_id INT REFERENCES app_parent);\n"
)

LOOKUPS: dict[str, Callable[[], object]] = {
    "writable_columns": lambda: platform.writable_columns(MODEL, "nope"),
    "column_facts-table": lambda: platform.column_facts(MODEL, "nope", "id"),
    "column_facts-column": lambda: platform.column_facts(MODEL, "app_child", "nope"),
    "naming_hints": lambda: platform.naming_hints(MODEL, "nope"),
    "dependency_order": lambda: platform.dependency_order(MODEL, tables=["nope"]),
}


@pytest.mark.parametrize("lookup", sorted(LOOKUPS))
def test_a_name_the_model_lacks_is_a_schema_error_and_a_key_error(lookup: str) -> None:
    with pytest.raises(KeyError) as caught:
        LOOKUPS[lookup]()
    assert isinstance(caught.value, SchemaError), type(caught.value)
    assert isinstance(caught.value, platform.NotInModelError)
    assert str(caught.value).startswith("no "), str(caught.value)
    assert "'nope'" in str(caught.value)


@pytest.mark.parametrize("writer", [platform.write_copy_seed, platform.write_insert_seed])
def test_a_writer_refuses_a_table_the_model_lacks_as_a_seed_error(writer, tmp_path: Path) -> None:
    """The writers' documented refusal is a ``SeedError``; the lookup it failed is its cause."""
    with pytest.raises(platform.SeedError, match="nope") as caught:
        writer(tmp_path / "s.sql", "nope", ["id"], [{"id": 1}], model=MODEL)
    assert isinstance(caught.value.__cause__, platform.NotInModelError)
    assert not (tmp_path / "s.sql").exists()


def test_a_bare_name_is_one_table_to_order() -> None:
    """``tables="ab"`` is the table ``ab``, not the tables ``a`` and ``b``."""
    model = platform.parse_schema(
        "CREATE TABLE ab (id INT PRIMARY KEY);\nCREATE TABLE a (id INT);\nCREATE TABLE b (id INT);\n"
    )
    assert [ref.name for ref in platform.dependency_order(model, tables="ab")] == ["ab"]


def test_a_list_of_path_strings_is_a_list_of_paths(tmp_path: Path) -> None:
    """A ``str`` alone is DDL text; a ``str`` in a list of paths is a path."""
    (tmp_path / "a.sql").write_text("CREATE TABLE a (x INT);\n")
    (tmp_path / "b.sql").write_text("CREATE TABLE a (x INT, y INT);\n")
    model = platform.parse_schema([str(tmp_path / "a.sql")])
    assert [ref.name for ref in model.tables] == ["a"]
    changes = platform.diff([str(tmp_path / "a.sql")], [tmp_path / "b.sql"]).changes
    assert [type(change).__name__ for change in changes] == ["ColumnAdded"]


def test_a_seeds_string_is_a_path(tmp_path: Path) -> None:
    """A path spelled as a ``str`` is read as the path it spells, and refused by name when absent."""
    missing = str(tmp_path / "seedz")
    with pytest.raises(platform.SeedError, match="seedz"):
        platform.apply_seeds("postgresql://localhost:1/unreachable", missing)
    with pytest.raises(platform.SeedError, match="seedz"):
        platform.apply_seeds("postgresql://localhost:1/unreachable", [missing])


BASIC = Path(__file__).resolve().parents[2] / "examples" / "basic"


def test_diff_reads_an_environments_build_for_the_side_left_none() -> None:
    """``diff`` takes what ``parse_schema`` takes: a side given as ``None`` is *env*'s build."""
    built = platform.parse_schema(env="local", project_dir=BASIC)
    added = platform.diff("", None, env="local", project_dir=BASIC).changes
    assert {c.table.name for c in added if isinstance(c, platform.TableAdded)} == {
        t.name for t in built.tables.values()
    }
    dropped = platform.diff(None, "", env="local", project_dir=BASIC).changes
    assert {type(c).__name__ for c in dropped} >= {"TableDropped"}


@pytest.mark.parametrize(
    ("old", "new", "env"),
    [("", "", "local"), (None, None, "local"), (None, "", None)],
    ids=["two-sources-and-an-env", "no-source-for-either-side", "a-side-with-nothing"],
)
def test_diff_takes_an_environment_for_exactly_one_side(old, new, env) -> None:
    with pytest.raises(ValueError, match="exactly one"):
        platform.diff(old, new, env=env, project_dir=BASIC)


UNREACHABLE = "postgresql://localhost:1/unreachable"


@pytest.mark.parametrize("url", [UNREACHABLE, "not a url"], ids=["refused", "garbled"])
def test_a_url_that_does_not_connect_is_a_configuration_error(url: str, tmp_path: Path) -> None:
    calls = {
        "introspect": lambda: platform.introspect(url),
        "apply_seeds": lambda: platform.apply_seeds(url, tmp_path),
    }
    for name, call in calls.items():
        with pytest.raises(ConfigurationError) as caught:
            call()
        assert caught.value.error_code == "CONFIG_006", name
        assert isinstance(caught.value.__cause__, psycopg.Error), name


def test_a_database_that_is_neither_a_url_nor_a_connection_is_a_type_error(tmp_path: Path) -> None:
    for call in (
        lambda: platform.introspect(tmp_path),  # type: ignore[arg-type]
        lambda: platform.apply_seeds(tmp_path, tmp_path),  # type: ignore[arg-type]
    ):
        with pytest.raises(TypeError, match=r"URL .* or a connection .*PosixPath"):
            call()


@pytest.mark.parametrize(
    "seeds",
    [Path("seedz"), Path("seedz/01_a.sql"), [Path("seedz/01_a.sql")]],
    ids=["directory", "file", "file-in-a-list"],
)
def test_a_seed_path_that_does_not_exist_is_refused_before_connecting(
    seeds, tmp_path: Path
) -> None:
    """A misspelt path has no files to apply, and zero files applied would read as success."""
    anchored = [tmp_path / p for p in seeds] if isinstance(seeds, list) else tmp_path / seeds
    with pytest.raises(platform.SeedError, match="seedz") as caught:
        platform.apply_seeds(UNREACHABLE, anchored)
    assert caught.value.error_code == "SEED_001"


def test_a_seed_the_writer_cannot_write_is_a_seed_error(tmp_path: Path) -> None:
    (tmp_path / "a_file").write_text("")
    with pytest.raises(platform.SeedError, match="a_file") as caught:
        platform.write_copy_seed(
            tmp_path / "a_file" / "s.sql", "app_parent", ["id"], [{"id": 1}], model=MODEL
        )
    assert isinstance(caught.value.__cause__, OSError)


def _tree(tmp_path: Path) -> tuple[Path, Path]:
    seeds, schema = tmp_path / "seeds", tmp_path / "schema"
    seeds.mkdir()
    schema.mkdir()
    (seeds / "01_a.sql").write_text("INSERT INTO prep_seed.tb_a (id) VALUES (1);\n")
    (schema / "tb_a.sql").write_text("CREATE TABLE prep_seed.tb_a (id INT);\n")
    return seeds, schema


def test_validate_seeds_refuses_a_directory_that_does_not_exist(tmp_path: Path) -> None:
    seeds, schema = _tree(tmp_path)
    with pytest.raises(platform.SeedError, match="seedz") as caught:
        platform.validate_seeds(tmp_path / "seedz", schema_dir=schema)
    assert caught.value.error_code == "SEED_001"
    with pytest.raises(platform.SchemaError, match="schemaz") as schema_caught:
        platform.validate_seeds(seeds, schema_dir=tmp_path / "schemaz", max_level=2)
    assert schema_caught.value.error_code == "SCHEMA_201"


@pytest.mark.parametrize("level", [0, -1, 6])
def test_validate_seeds_refuses_a_level_outside_one_to_five(level: int, tmp_path: Path) -> None:
    seeds, schema = _tree(tmp_path)
    with pytest.raises(ConfigurationError, match=f"max_level {level}"):
        platform.validate_seeds(seeds, schema_dir=schema, max_level=level)


def test_validate_seeds_refuses_a_file_it_cannot_read(tmp_path: Path) -> None:
    """An unread seed is not a clean one: level 1 names it rather than skipping it."""
    seeds, schema = _tree(tmp_path)
    (seeds / "02_latin1.sql").write_bytes(
        "INSERT INTO prep_seed.tb_a VALUES ('é');\n".encode("latin-1")
    )
    with pytest.raises(platform.SeedError, match=r"02_latin1\.sql") as caught:
        platform.validate_seeds(seeds, schema_dir=schema, max_level=1)
    assert isinstance(caught.value.__cause__, UnicodeDecodeError)
    (seeds / "02_latin1.sql").unlink()
    (schema / "fn_resolve_tb_a.sql").write_bytes("-- café\n".encode("latin-1"))
    with pytest.raises(platform.SchemaError, match=r"fn_resolve_tb_a\.sql"):
        platform.validate_seeds(seeds, schema_dir=schema, max_level=3)


def test_a_schema_file_that_is_not_utf8_is_a_schema_error_naming_it(tmp_path: Path) -> None:
    (tmp_path / "00_ok.sql").write_text("CREATE TABLE a (x INT);\n")
    (tmp_path / "10_latin1.sql").write_bytes("COMMENT ON TABLE a IS 'café';\n".encode("latin-1"))
    for call in (
        lambda: platform.parse_schema(tmp_path),
        lambda: platform.parse_schema([tmp_path / "10_latin1.sql"]),
        lambda: platform.diff(tmp_path, ""),
    ):
        with pytest.raises(platform.SchemaError, match=r"10_latin1\.sql") as caught:
            call()
        assert isinstance(caught.value.__cause__, UnicodeDecodeError)


def test_tier_of_something_that_is_not_a_change_is_a_type_error() -> None:
    with pytest.raises(TypeError, match=r"SchemaChange.*str"):
        platform.tier_of("x")  # type: ignore[arg-type]


def test_a_str_path_is_a_path_everywhere_the_seam_takes_one(tmp_path: Path) -> None:
    """``write_*_seed(path=)`` and ``validate_seeds(seeds=, schema_dir=)`` take a
    ``str`` as the path it spells, as ``apply_seeds`` and the schema sources do."""
    rows = [{"id": 1}]
    written = [
        write(str(tmp_path / name), "app_parent", ["id"], rows, model=MODEL)
        for write, name in (
            (platform.write_copy_seed, "copy.sql"),
            (platform.write_insert_seed, "insert.sql"),
        )
    ]
    seeds = tmp_path / "seeds"
    seeds.mkdir()
    report = platform.validate_seeds(str(seeds), schema_dir=str(tmp_path), max_level=1)
    assert [f.path for f in written] == [tmp_path / "copy.sql", tmp_path / "insert.sql"]
    assert report.violations == []
