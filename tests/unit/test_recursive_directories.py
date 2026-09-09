"""Tests for recursive directory support in SchemaBuilder."""

import pytest

from confiture.core.builder import SchemaBuilder
from confiture.exceptions import SchemaError

"""Tests for recursive directory support feature.

This module tests the SchemaBuilder's ability to recursively discover SQL files
in nested directory structures while maintaining deterministic ordering.

Key features tested:
- Recursive discovery of files in subdirectories
- Non-recursive discovery (current directory only)
- Mixed recursive and non-recursive configurations
- Directory ordering for consistent builds
- Backward compatibility with string-based configurations
"""


def test_recursive_directory_discovery(tmp_path):
    """Test recursive discovery finds nested files."""
    schema_dir = tmp_path / "schema"
    (schema_dir / "level1" / "level2" / "level3").mkdir(parents=True)

    file1 = schema_dir / "level1" / "file1.sql"
    file2 = schema_dir / "level1" / "level2" / "file2.sql"
    file3 = schema_dir / "level1" / "level2" / "level3" / "file3.sql"

    file1.write_text("SELECT 1;")
    file2.write_text("SELECT 2;")
    file3.write_text("SELECT 3;")

    # Create config with recursive: true
    config_path = tmp_path / "db" / "environments" / "test.yaml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(f"""
database_url: postgresql://localhost/test
include_dirs:
  - path: {schema_dir}
    recursive: true
""")

    builder = SchemaBuilder(env="test", project_dir=tmp_path)
    files = builder.find_sql_files()

    assert len(files) == 3
    assert any("file1.sql" in str(f) for f in files)
    assert any("file2.sql" in str(f) for f in files)
    assert any("file3.sql" in str(f) for f in files)


def test_non_recursive_discovery(tmp_path):
    """Test non-recursive only finds immediate children."""
    schema_dir = tmp_path / "schema"
    (schema_dir / "subdirectory").mkdir(parents=True)

    root_file = schema_dir / "root.sql"
    nested_file = schema_dir / "subdirectory" / "nested.sql"

    root_file.write_text("SELECT 1;")
    nested_file.write_text("SELECT 2;")

    config_path = tmp_path / "db" / "environments" / "test.yaml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(f"""
database_url: postgresql://localhost/test
include_dirs:
  - path: {schema_dir}
    recursive: false
""")

    builder = SchemaBuilder(env="test", project_dir=tmp_path)
    files = builder.find_sql_files()

    assert len(files) == 1
    assert "root.sql" in str(files[0])


def test_mixed_recursive_and_non_recursive(tmp_path):
    """Test mixing recursive and non-recursive directories."""
    schema_dir = tmp_path / "schema"
    recursive_dir = schema_dir / "recursive"
    non_recursive_dir = schema_dir / "non_recursive"

    # Create directory structure
    (recursive_dir / "subdir").mkdir(parents=True)
    (non_recursive_dir / "subdir").mkdir(parents=True)

    # Files in recursive directory
    (recursive_dir / "root.sql").write_text("SELECT 1;")
    (recursive_dir / "subdir" / "nested.sql").write_text("SELECT 2;")

    # Files in non-recursive directory
    (non_recursive_dir / "root.sql").write_text("SELECT 3;")
    (non_recursive_dir / "subdir" / "nested.sql").write_text("SELECT 4;")

    config_path = tmp_path / "db" / "environments" / "test.yaml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(f"""
database_url: postgresql://localhost/test
include_dirs:
  - path: {recursive_dir}
    recursive: true
    order: 10
  - path: {non_recursive_dir}
    recursive: false
    order: 20
""")

    builder = SchemaBuilder(env="test", project_dir=tmp_path)
    files = builder.find_sql_files()

    # Should find 3 files: 2 from recursive dir, 1 from non-recursive dir
    assert len(files) == 3

    # Check that recursive dir files are found
    recursive_files = [f for f in files if str(recursive_dir) in str(f)]
    assert len(recursive_files) == 2

    # Check that only root file from non-recursive dir is found
    non_recursive_files = [f for f in files if str(non_recursive_dir) in str(f)]
    assert len(non_recursive_files) == 1
    assert "root.sql" in str(non_recursive_files[0])


def test_directory_ordering(tmp_path):
    """The entry at ``order: 10`` is built before the one at ``order: 20``.

    The two directories also sort that way alphabetically, so this passed
    while ``order`` decided nothing. What it pins now is the ``order`` key —
    :mod:`tests.unit.test_include_dirs_order` is where the two disagree.
    """
    schema_dir = tmp_path / "schema"
    dir1 = schema_dir / "01_first"
    dir2 = schema_dir / "02_second"

    dir1.mkdir(parents=True)
    dir2.mkdir(parents=True)

    (dir1 / "file1.sql").write_text("SELECT 1;")
    (dir2 / "file2.sql").write_text("SELECT 2;")

    config_path = tmp_path / "db" / "environments" / "test.yaml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(f"""
database_url: postgresql://localhost/test
include_dirs:
  - path: {dir2}
    order: 20
  - path: {dir1}
    order: 10
""")

    builder = SchemaBuilder(env="test", project_dir=tmp_path)
    files = builder.find_sql_files()

    # Files should be in order: dir1 first (order 10), then dir2 (order 20)
    assert len(files) == 2
    assert "01_first" in str(files[0])
    assert "02_second" in str(files[1])


def test_backward_compatibility_string_format(tmp_path):
    """Test backward compatibility with string format for include_dirs."""
    schema_dir = tmp_path / "schema"
    (schema_dir / "subdir").mkdir(parents=True)

    (schema_dir / "root.sql").write_text("SELECT 1;")
    (schema_dir / "subdir" / "nested.sql").write_text("SELECT 2;")

    # Use old string format
    config_path = tmp_path / "db" / "environments" / "test.yaml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(f"""
database_url: postgresql://localhost/test
include_dirs:
  - {schema_dir}
""")

    builder = SchemaBuilder(env="test", project_dir=tmp_path)
    files = builder.find_sql_files()

    # Should find both files (recursive by default)
    assert len(files) == 2
    assert any("root.sql" in str(f) for f in files)
    assert any("nested.sql" in str(f) for f in files)


def test_include_configs_structure(tmp_path):
    """Test that include_configs are properly structured."""
    schema_dir = tmp_path / "schema"
    schema_dir.mkdir()

    (schema_dir / "file.sql").write_text("SELECT 1;")

    config_path = tmp_path / "db" / "environments" / "test.yaml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(f"""
database_url: postgresql://localhost/test
include_dirs:
  - path: {schema_dir}
    recursive: true
    order: 5
""")

    builder = SchemaBuilder(env="test", project_dir=tmp_path)

    # Check that include_configs is properly structured
    assert len(builder.include_configs) == 1
    config = builder.include_configs[0]
    assert config["path"] == schema_dir
    assert config["recursive"] is True
    assert config["order"] == 5


def _entry_project(tmp_path, *, recursive: bool, include: list[str], files: list[str]):
    """A project with one ``include_dirs`` entry, spelled exactly as given."""
    schema_dir = tmp_path / "db" / "schema"
    for relative in files:
        path = schema_dir / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("SELECT 1;\n")

    config_path = tmp_path / "db" / "environments" / "test.yaml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        "database_url: postgresql://localhost/test\n"
        "include_dirs:\n"
        f"  - path: {schema_dir}\n"
        f"    recursive: {str(recursive).lower()}\n"
        "    include:\n" + "".join(f'      - "{pattern}"\n' for pattern in include)
    )
    return tmp_path, schema_dir


def test_a_slash_free_pattern_reaches_depth_when_recursive(tmp_path):
    """``recursive: true`` + ``*.sql`` reaches every depth, as it always has.

    Pinned rather than fixed: ``rglob`` gave this reach before, rule 1 of the
    glob dialect gives it now, and nothing about the release may change it.
    """
    project, schema_dir = _entry_project(
        tmp_path, recursive=True, include=["*.sql"], files=["top.sql", "a/b/deep.sql"]
    )

    selected = sorted(
        str(p.relative_to(schema_dir))
        for p in SchemaBuilder(env="test", project_dir=project).find_sql_files()
    )

    assert selected == ["a/b/deep.sql", "top.sql"]


def test_the_default_include_is_not_rewritten_under_non_recursive(tmp_path):
    """``recursive: false`` + ``**/*.sql`` reads depth 1 — and the pattern is left alone.

    The selection was already right, but for the wrong reason: the entry's
    include list was silently rewritten to ``["*.sql"]`` to stop ``glob`` from
    recursing. ``**`` spans zero components, so the rewrite buys nothing and
    the matcher now sees what the YAML says.
    """
    project, schema_dir = _entry_project(
        tmp_path, recursive=False, include=["**/*.sql"], files=["top.sql", "a/b/deep.sql"]
    )
    builder = SchemaBuilder(env="test", project_dir=project)

    selected = [str(p.relative_to(schema_dir)) for p in builder.find_sql_files()]

    assert selected == ["top.sql"]
    assert builder.include_configs[0]["include"] == ["**/*.sql"]


def test_a_pattern_that_requires_depth_selects_nothing_when_not_recursive(tmp_path):
    """``recursive: false`` + ``**/sub/*.sql`` builds nothing, three levels down included."""
    project, _ = _entry_project(
        tmp_path, recursive=False, include=["**/sub/*.sql"], files=["a/sub/deep.sql"]
    )

    with pytest.raises(SchemaError):
        SchemaBuilder(env="test", project_dir=project).find_sql_files()
