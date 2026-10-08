"""The snapshots a baseline is detected against: model wire, newest first.

How a database is matched against them is the integration suite's
(``tests/integration/test_baseline_detection.py``); this pins what is read.
"""

from pathlib import Path

from confiture.core.baseline_detector import BaselineDetector
from confiture.core.schema_read import read_text

TREE = "CREATE TABLE tb_x (id bigint PRIMARY KEY, name text);"


def _json(directory: Path, stem: str, sql: str = TREE) -> None:
    (directory / f"{stem}.json").write_text(read_text(sql).catalogued.to_json())


def test_no_directory_is_no_snapshot(tmp_path: Path) -> None:
    assert BaselineDetector(tmp_path / "absent").load_snapshots() == []


def test_snapshots_are_read_newest_first(tmp_path: Path) -> None:
    _json(tmp_path, "001_first")
    _json(tmp_path, "010_tenth")
    _json(tmp_path, "002_second")

    found = BaselineDetector(tmp_path).load_snapshots()

    assert [(s.version, s.name) for s in found] == [
        ("010", "tenth"),
        ("002", "second"),
        ("001", "first"),
    ]


def test_a_snapshot_is_the_model_its_wire_holds(tmp_path: Path) -> None:
    _json(tmp_path, "001_first")
    (snapshot,) = BaselineDetector(tmp_path).load_snapshots()
    assert snapshot.model == read_text(TREE).catalogued


def test_a_snapshot_written_as_sql_is_read_as_the_tree_it_holds(tmp_path: Path) -> None:
    (tmp_path / "001_legacy.sql").write_text(TREE)
    (snapshot,) = BaselineDetector(tmp_path).load_snapshots()
    assert snapshot.model == read_text(TREE).catalogued


def test_the_model_wire_wins_over_sql_of_one_version(tmp_path: Path) -> None:
    (tmp_path / "001_both.sql").write_text("CREATE TABLE tb_other (id int);")
    _json(tmp_path, "001_both")
    (snapshot,) = BaselineDetector(tmp_path).load_snapshots()
    assert snapshot.model == read_text(TREE).catalogued


def test_other_files_are_not_snapshots(tmp_path: Path) -> None:
    _json(tmp_path, "001_first")
    (tmp_path / "README.md").write_text("# history")
    (tmp_path / "notes.txt").write_text("x")
    assert len(BaselineDetector(tmp_path).load_snapshots()) == 1


def test_a_snapshot_that_cannot_be_read_is_reported_not_dropped(tmp_path: Path) -> None:
    _json(tmp_path, "001_first")
    (tmp_path / "002_broken.sql").write_text("CREATE TABLE (;")

    detector = BaselineDetector(tmp_path)
    found = detector.load_snapshots()

    assert [s.version for s in found] == ["001"]
    assert [path.name for path, _reason in detector.unreadable] == ["002_broken.sql"]
