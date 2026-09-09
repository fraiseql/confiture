"""The matcher takes a pattern from a config file: it must not hang, and must not escape.

A glob is user input that becomes a regex. Two things can go wrong with that —
the regex backtracks forever, or the pattern reaches outside the directory it
is relative to — and both are cheap to make impossible.
"""

from __future__ import annotations

import time
from pathlib import Path, PurePosixPath

import pytest

from confiture.core.builder import SchemaBuilder
from confiture.core.path_globs import compile_pattern, matches
from confiture.exceptions import ConfigurationError

# Six `**/` runs and a suffix that cannot match, against a very long path: the
# shape that goes exponential the moment the translation emits one unbounded
# quantifier inside another.
PATHOLOGICAL = "**/" * 6 + "*.nomatch"
LONG_PATH = PurePosixPath("/".join(f"d{i}" for i in range(200)) + "/x.sql")


def test_a_pathological_pattern_cannot_backtrack() -> None:
    """Consecutive ``**`` collapse, so the regex holds one unbounded quantifier, not six."""
    assert compile_pattern(PATHOLOGICAL).pattern == compile_pattern("**/*.nomatch").pattern
    assert compile_pattern(PATHOLOGICAL).pattern.count("(?:[^/]+/)*") == 1


def test_a_pathological_pattern_answers_in_bounded_time() -> None:
    """The non-matching case is the expensive one; it returns immediately."""
    start = time.perf_counter()

    assert matches(LONG_PATH, PATHOLOGICAL) is False

    assert time.perf_counter() - start < 2.0


def test_a_deep_wide_tree_is_selected_in_bounded_time(tmp_path: Path) -> None:
    """And the same pattern over a real tree, where every file is tested against it."""
    schema_dir = tmp_path / "db" / "schema"
    for first in range(4):
        for second in range(4):
            directory = schema_dir / f"a{first}" / f"b{second}" / "c" / "d" / "e"
            directory.mkdir(parents=True)
            for index in range(4):
                (directory / f"{index}_t.sql").write_text("SELECT 1;\n")
    env_dir = tmp_path / "db" / "environments"
    env_dir.mkdir(parents=True)
    (env_dir / "test.yaml").write_text(
        "database_url: postgresql://localhost/test\n"
        f"include_dirs:\n  - path: {schema_dir}\n"
        f'    include:\n      - "{"**/" * 6}*.sql"\n'
    )

    start = time.perf_counter()
    files = SchemaBuilder(env="test", project_dir=tmp_path).find_sql_files()

    assert len(files) == 64
    assert time.perf_counter() - start < 5.0


@pytest.mark.parametrize("pattern", ["../*.sql", "a/../../*.sql", "..", "**/../x.sql"])
def test_a_pattern_that_climbs_out_is_rejected(pattern: str) -> None:
    """``..`` in a pattern is always a mistake: it can only ever match nothing."""
    with pytest.raises(ConfigurationError) as raised:
        compile_pattern(pattern)

    assert pattern in str(raised.value)


def test_the_build_reports_a_climbing_pattern_clearly(tmp_path: Path) -> None:
    """And it reaches the user as a configuration error, not a mysterious empty build."""
    schema_dir = tmp_path / "db" / "schema"
    schema_dir.mkdir(parents=True)
    (schema_dir / "keep.sql").write_text("SELECT 1;\n")
    env_dir = tmp_path / "db" / "environments"
    env_dir.mkdir(parents=True)
    (env_dir / "test.yaml").write_text(
        "database_url: postgresql://localhost/test\n"
        f"include_dirs:\n  - path: {schema_dir}\n"
        '    exclude:\n      - "../*.sql"\n'
    )

    with pytest.raises(ConfigurationError) as raised:
        SchemaBuilder(env="test", project_dir=tmp_path).find_sql_files()

    assert "../*.sql" in str(raised.value)


def test_the_walk_does_not_follow_a_symlink_out_of_the_entry(tmp_path: Path) -> None:
    """A directory symlink is not descended into, so nothing outside the entry is built.

    This matches 1.4.0 rather than changing it: ``rglob``'s ``**`` does not
    descend symlinked directories on the Python versions confiture supports, so
    the hand-rolled walk keeps that deliberately.
    """
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.sql").write_text("SELECT 'do not build me';\n")

    schema_dir = tmp_path / "db" / "schema"
    schema_dir.mkdir(parents=True)
    (schema_dir / "keep.sql").write_text("SELECT 1;\n")
    (schema_dir / "escape").symlink_to(outside, target_is_directory=True)

    env_dir = tmp_path / "db" / "environments"
    env_dir.mkdir(parents=True)
    (env_dir / "test.yaml").write_text(
        f"database_url: postgresql://localhost/test\ninclude_dirs:\n  - path: {schema_dir}\n"
    )

    files = SchemaBuilder(env="test", project_dir=tmp_path).find_sql_files()

    assert [p.name for p in files] == ["keep.sql"]
    assert all("secret" not in p.name for p in files)
