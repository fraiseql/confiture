"""The one answer to "does this name carry a number, and what number is it".

The builder orders the tree, the tree rules judge it and ``generate alloc``
writes it. Before 1.4.0 each had its own answer, so ``0a_x.sql`` was a number
to two of them and a word to the third (LINT-07), and the base a prefix was
read in was a property of the filename rather than of the directory.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from confiture.core import tree_prefix


@pytest.mark.parametrize(
    ("name", "raw"),
    [
        ("0248_flag", "0248"),
        ("0248_flag.sql", "0248"),
        ("000a_middle.sql", "000a"),
        ("000A_middle.sql", "000A"),
        ("1_x.sql", "1"),
        ("add_column.sql", None),
        ("abc_alpha.sql", None),
        ("face_it.sql", None),
        ("helpers.sql", None),
        ("_leading.sql", None),
        ("00001.sql", None),
        ("", None),
    ],
)
def test_what_counts_as_a_prefix(name, raw):
    """Either case, and at least one decimal digit so a word stays a word."""
    assert tree_prefix.prefix_text(name) == raw


def test_the_base_belongs_to_the_directory():
    """One hex-lettered sibling makes the whole group hex.

    Read per name instead, ``0100`` beside ``009a`` is 100 beside 154 — the
    author wrote 256 after 154.
    """
    decimal = ["0009_a.sql", "0010_b.sql"]
    hexadecimal = ["009a_a.sql", "0100_b.sql"]

    assert not tree_prefix.is_hex_group(decimal)
    assert tree_prefix.is_hex_group(hexadecimal)

    assert [tree_prefix.prefix_value(n, hex_group=False) for n in decimal] == [9, 10]
    assert [tree_prefix.prefix_value(n, hex_group=True) for n in hexadecimal] == [154, 256]


def test_order_reads_every_component(tmp_path):
    """A directory's number decides before its children's do."""
    paths = [
        Path("0250_widget/00001_create.sql"),
        Path("0248_flag/00002_index.sql"),
        Path("0248_flag/00001_create.sql"),
        Path("0248_configurator/00001_create.sql"),
        Path("unnumbered/00001_create.sql"),
    ]

    assert [p.as_posix() for p in tree_prefix.order(paths)] == [
        "0248_configurator/00001_create.sql",
        "0248_flag/00001_create.sql",
        "0248_flag/00002_index.sql",
        "0250_widget/00001_create.sql",
        "unnumbered/00001_create.sql",
    ]


def test_order_does_not_depend_on_input_order():
    """Every permutation of the same set produces the same order."""
    import itertools

    paths = [
        Path("a/00001_create.sql"),
        Path("b/00001_create.sql"),
        Path("c/0001_create.sql"),
    ]
    results = {
        tuple(p.as_posix() for p in tree_prefix.order(perm))
        for perm in itertools.permutations(paths)
    }

    assert len(results) == 1
