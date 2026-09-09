"""``order`` decides the sequence files are concatenated in.

The key was read once — ``include_configs`` was sorted by it — and then
discarded: every entry's matches were flattened into one list and sorted
globally, so a directory's ``order`` decided nothing a reader could observe.
"""

from __future__ import annotations

from pathlib import Path

from confiture.core.builder import SchemaBuilder


def _two_entry_project(tmp_path: Path, *, first_order: int, second_order: int) -> Path:
    """``db/b`` holding a late-sorting file, ``db/a`` holding an early-sorting one."""
    (tmp_path / "db" / "a").mkdir(parents=True)
    (tmp_path / "db" / "b").mkdir(parents=True)
    (tmp_path / "db" / "a" / "00_first.sql").write_text("SELECT 1;\n")
    (tmp_path / "db" / "b" / "99_last.sql").write_text("SELECT 2;\n")

    env_dir = tmp_path / "db" / "environments"
    env_dir.mkdir(parents=True)
    (env_dir / "test.yaml").write_text(f"""
database_url: postgresql://localhost/test
include_dirs:
  - path: {tmp_path / "db" / "b"}
    order: {first_order}
  - path: {tmp_path / "db" / "a"}
    order: {second_order}
""")
    return tmp_path


def _built_order(project: Path) -> list[str]:
    builder = SchemaBuilder(env="test", project_dir=project)
    return [str(path.relative_to(project)) for path in builder.find_sql_files()]


def test_order_decides_concatenation(tmp_path: Path) -> None:
    """The lower ``order`` is built first, whatever the filenames sort like."""
    project = _two_entry_project(tmp_path, first_order=10, second_order=20)

    assert _built_order(project) == ["db/b/99_last.sql", "db/a/00_first.sql"]


def test_order_decides_concatenation_the_other_way_round(tmp_path: Path) -> None:
    """Swapping the two ``order`` values swaps the build.

    This half agrees with the alphabetical sort, so it held while ``order``
    decided nothing; it is here so that the pair reads as one statement.
    """
    project = _two_entry_project(tmp_path, first_order=20, second_order=10)

    assert _built_order(project) == ["db/a/00_first.sql", "db/b/99_last.sql"]
