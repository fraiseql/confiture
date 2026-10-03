"""``tree_003`` reads a directory's numbering as the build orders it: files and
subdirectories alike (#556).

A numbered subdirectory takes its value in the sequence: between ``01_a.sql`` and
``03_b.sql`` it fills ``02``, and a level of directories alone has a numbering of
its own to keep. A file and a directory sharing a value are one value here (the
collision is ``tree_005``'s), and a directory the build excludes takes none.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from confiture.core.linting.libraries.generate import Tree003GapPolicy


def _tree(root: Path, entries: list[str]) -> list[Path]:
    """The files the build reads for *entries*: a name ending ``/`` is a directory holding one file."""
    files = []
    for entry in entries:
        if entry.endswith("/"):
            directory = root / entry.rstrip("/")
            directory.mkdir(parents=True)
            (directory / "01_inner.sql").touch()
            files.append(directory / "01_inner.sql")
        else:
            (root / entry).touch()
            files.append(root / entry)
    return files


def _gaps(root: Path, entries: list[str], excluded: frozenset[str] = frozenset()) -> list[str]:
    files = [f for f in _tree(root, entries) if not any(x in f.parts for x in excluded)]
    files.sort()
    return [v.message for v in Tree003GapPolicy().check(files, [root])]


@pytest.mark.parametrize(
    ("entries", "gaps"),
    [
        (["01_a.sql", "02_dir/", "03_b.sql"], 0),
        (["01_a.sql", "03_dir/", "04_b.sql"], 1),
        (["01_x/", "02_y/", "05_z/"], 1),
        (["01_a.sql", "02_a.sql", "03_dir/"], 0),
        (["01_a.sql", "01_dir/", "02_b.sql"], 0),
        (["009_a.sql", "00a_dir/", "00b_b.sql"], 0),
    ],
)
def test_every_numbered_entry_takes_its_value(
    tmp_path: Path, entries: list[str], gaps: int
) -> None:
    assert len(_gaps(tmp_path, entries)) == gaps


def test_a_directory_level_reports_its_own_gap(tmp_path: Path) -> None:
    (message,) = _gaps(tmp_path, ["01_x/", "02_y/", "05_z/"])
    assert "2 → 5" in message


def test_the_gap_names_what_is_on_either_side(tmp_path: Path) -> None:
    (message,) = _gaps(tmp_path, ["01_a.sql", "03_dir/", "04_b.sql"])
    assert "01_a.sql" in message and "03_dir/" in message


def test_a_directory_the_build_excludes_leaves_its_slot_empty(tmp_path: Path) -> None:
    assert (
        len(_gaps(tmp_path, ["01_a.sql", "02_excluded/", "03_b.sql"], frozenset({"02_excluded"})))
        == 1
    )


@pytest.mark.parametrize(
    ("entries", "gaps"),
    [
        (["10_tables/", "20_views/", "30_functions/"], 0),
        (["10_tables/", "20_views/", "40_functions/"], 1),
        (["001_a.sql", "002_b.sql", "004_c.sql"], 1),
    ],
)
def test_a_directory_s_step_is_read_from_its_own_numbering(
    tmp_path: Path, entries: list[str], gaps: int
) -> None:
    """``10_tables``, ``20_views``: a numbering stepped by ten leaves room, it lacks nothing."""
    assert len(_gaps(tmp_path, entries)) == gaps
