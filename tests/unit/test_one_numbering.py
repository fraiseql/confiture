"""One module reads and writes a tree's numbering: ``core/tree_prefix.py``.

Parsing a prefix, formatting one, deciding whether siblings count in hex and
at what width: the allocator, ``renumber`` and the ``tree_*`` rules each did
some of it themselves, and ``tree_002`` decided "numbered" by the first
character being a decimal digit, so a hex prefix that starts with a letter was
never numbered. This test pins the module's answers and fails on a tree tool
that parses or formats a prefix itself.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from confiture.core.linting.libraries.generate import Tree002VerbSuffix
from confiture.core.tree_prefix import bare_prefix, format_prefix, numbering, prefix_value

REPO = Path(__file__).resolve().parents[2]
#: The tools that act on a tree's numbering: none of them reads or writes one itself.
TREE_TOOLS = (
    "python/confiture/core/tree_allocator.py",
    "python/confiture/core/tree_renumber.py",
    "python/confiture/core/linting/libraries/generate.py",
)


@pytest.mark.parametrize(
    ("value", "width", "hexadecimal"),
    [(0, 3, False), (42, 5, False), (26, 4, True), (4094, 4, True), (7, 1, False)],
)
def test_a_prefix_written_reads_back(value: int, width: int, hexadecimal: bool) -> None:
    written = format_prefix(value, width=width, hexadecimal=hexadecimal)
    assert len(written) == width
    assert prefix_value(f"{written}_x.sql", hex_group=hexadecimal) == value


@pytest.mark.parametrize(
    ("names", "expected"),
    [
        (["001_a.sql", "002_b.sql", "0003_c.sql"], (False, 3)),
        (["009_a.sql", "00a_b.sql"], (True, 3)),
        (["readme.sql"], None),
    ],
)
def test_siblings_say_how_they_are_numbered(names: list[str], expected: object) -> None:
    assert numbering(names) == expected


@pytest.mark.parametrize(
    ("stem", "bare"),
    [("0042", True), ("a001", True), ("00a1", True), ("0042_create", False), ("abc", False)],
)
def test_a_stem_that_is_only_a_prefix(stem: str, bare: bool) -> None:
    assert bare_prefix(stem) is bare


def test_a_hex_prefix_starting_with_a_letter_is_numbered(tmp_path: Path) -> None:
    (tmp_path / "a001.sql").touch()
    found = Tree002VerbSuffix().check([tmp_path / "a001.sql"])
    assert [v.object_name for v in found] == ["a001.sql"]


def _parses_or_formats(path: Path) -> list[int]:
    found = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if not isinstance(node, ast.Call):
            continue
        name = ast.unparse(node.func)
        if (name == "int" and len(node.args) == 2) or name == "format" or name.endswith(".isdigit"):
            found.append(node.lineno)
    return found


@pytest.mark.parametrize("module", TREE_TOOLS)
def test_a_tree_tool_leaves_numbering_to_tree_prefix(module: str) -> None:
    assert _parses_or_formats(REPO / module) == []


def test_the_allocator_never_writes_a_prefix_that_reads_as_a_word(tmp_path: Path) -> None:
    # After `ab9` comes `aba` — all letters, which no reader takes for a number.
    from confiture.core.tree_allocator import TreeAllocator

    (tmp_path / "ab9_create.sql").touch()
    allocated = TreeAllocator(schema_dir=tmp_path).alloc(tmp_path, "next")

    assert prefix_value(allocated.name) is not None
    assert allocated.name == "ac0_next.sql"


def test_the_allocator_counts_a_directory_s_number_as_taken(tmp_path: Path) -> None:
    """``02_helpers/`` holds 02 in the build's order: the next file is 03, not a collision."""
    from confiture.core.tree_allocator import TreeAllocator

    (tmp_path / "01_a.sql").touch()
    (tmp_path / "02_helpers").mkdir()
    (tmp_path / "02_helpers" / "01_inner.sql").touch()

    allocated = TreeAllocator(schema_dir=tmp_path).alloc(tmp_path, "next")

    assert allocated.name == "03_next.sql"


def test_compaction_numbers_in_build_order_not_name_order(tmp_path: Path) -> None:
    """``9_y`` builds before ``10_x``; a name sort puts ``10_x`` first and reorders the build."""
    from confiture.core.tree_renumber import TreeRenumber

    for name in ("9_y.sql", "10_x.sql", "12_z.sql"):
        (tmp_path / name).write_text("SELECT 1;\n")
    plans = TreeRenumber(tmp_path).build_compact_plans(tmp_path)

    assert [(p.old_path.name, p.new_path.name) for p in plans] == [
        ("9_y.sql", "01_y.sql"),
        ("10_x.sql", "02_x.sql"),
        ("12_z.sql", "03_z.sql"),
    ]
