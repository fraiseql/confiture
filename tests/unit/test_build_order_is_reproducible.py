"""The build order does not depend on the order the filesystem hands files back.

``SchemaBuilder.find_sql_files`` discovers with ``Path.rglob``, which returns
directory entries in whatever order the filesystem stores them, and then sorts.
A sort is only reproducible if its key is total: any two files whose keys tie
keep their discovery order, because Python's sort is stable. Under
``sort_mode: hex`` the key was ``(prefix_value, rest_of_stem)`` — the directory
was absent from it — so the ``00001_create.sql`` that ``confiture generate
alloc`` writes into every directory tied with every other one, and the build
order of a numbered tree was whatever the machine's filesystem happened to say.

The other half of the same problem is that "is this a numbered prefix" had two
answers: the builder demanded upper case, while the tree rules and the
allocator accepted either. A ``0a_*.sql`` tree was therefore ordered by one
definition and linted by another.
"""

from __future__ import annotations

import random
from pathlib import Path

import pytest

from confiture.core.builder import SchemaBuilder

_REAL_RGLOB = Path.rglob


@pytest.fixture
def shuffle_discovery(monkeypatch):
    """Make ``Path.rglob`` return its entries in a seeded random order."""

    def apply(seed: int) -> None:
        def rglob(self: Path, pattern: str, *args: object, **kwargs: object):
            found = list(_REAL_RGLOB(self, pattern, *args, **kwargs))
            random.Random(seed).shuffle(found)
            return iter(found)

        monkeypatch.setattr(Path, "rglob", rglob)

    return apply


def _alloc_shaped_tree(tmp_path: Path, sort_mode: str) -> Path:
    """A tree shaped the way ``confiture generate alloc`` numbers one.

    Every directory restarts at ``00001``, so the filename alone cannot order
    two files from different directories.
    """
    schema = tmp_path / "db" / "schema"
    for directory in ("0248_configurator", "0248_flag", "0250_widget"):
        (schema / directory).mkdir(parents=True)
        for stem in ("00001_create", "00002_index"):
            (schema / directory / f"{stem}.sql").write_text("SELECT 1;\n")
    env = tmp_path / "db" / "environments" / "test.yaml"
    env.parent.mkdir(parents=True)
    env.write_text(
        "database_url: postgresql://localhost/test\n"
        "include_dirs:\n  - db/schema\n"
        f"build:\n  sort_mode: {sort_mode}\n"
    )
    return tmp_path


@pytest.mark.parametrize("sort_mode", ["hex", "alphabetical"])
def test_discovery_order_does_not_reach_the_build(tmp_path, shuffle_discovery, sort_mode):
    """Ten shuffles of the same tree produce one build order."""
    project = _alloc_shaped_tree(tmp_path, sort_mode)

    orders = []
    for seed in range(10):
        shuffle_discovery(seed)
        builder = SchemaBuilder(env="test", project_dir=project)
        orders.append([f.relative_to(project).as_posix() for f in builder.find_sql_files()])

    assert len({tuple(order) for order in orders}) == 1, (
        f"{sort_mode} build order depends on discovery order: {sorted({tuple(o) for o in orders})}"
    )


def test_hex_order_reads_the_directory_prefix_not_only_the_filename(tmp_path, shuffle_discovery):
    """Under hex sorting the directory's own number decides, as it does alphabetically."""
    project = _alloc_shaped_tree(tmp_path, "hex")
    shuffle_discovery(3)

    order = [
        f.relative_to(project / "db" / "schema").as_posix()
        for f in SchemaBuilder(env="test", project_dir=project).find_sql_files()
    ]

    assert order == [
        "0248_configurator/00001_create.sql",
        "0248_configurator/00002_index.sql",
        "0248_flag/00001_create.sql",
        "0248_flag/00002_index.sql",
        "0250_widget/00001_create.sql",
        "0250_widget/00002_index.sql",
    ]


def _two_block_tree(tmp_path: Path) -> Path:
    """Two ``order`` blocks; only the second's *filenames* carry numeric prefixes.

    The first block's numbers are on its directories, so the predicate that
    decides whether numbers are read at all — which looks at file stems — is
    false for that block on its own and true over the selection as a whole.
    """
    first = tmp_path / "db" / "first"
    (first / "9_beta").mkdir(parents=True)
    (first / "10_alpha").mkdir(parents=True)
    (first / "9_beta" / "x.sql").write_text("SELECT 1;\n")
    (first / "10_alpha" / "y.sql").write_text("SELECT 2;\n")
    second = tmp_path / "db" / "second"
    second.mkdir(parents=True)
    (second / "00001_create.sql").write_text("SELECT 3;\n")

    env = tmp_path / "db" / "environments" / "test.yaml"
    env.parent.mkdir(parents=True)
    env.write_text(
        "database_url: postgresql://localhost/test\n"
        "include_dirs:\n"
        f"  - path: {first}\n    order: 10\n"
        f"  - path: {second}\n    order: 20\n"
        "build:\n  sort_mode: hex\n"
    )
    return tmp_path


_TWO_BLOCK_ORDER = [
    "db/first/9_beta/x.sql",
    "db/first/10_alpha/y.sql",
    "db/second/00001_create.sql",
]


def test_hex_predicate_is_global_not_per_block(tmp_path):
    """Both blocks read their numbers, because one selected file carries one.

    Deciding it per block would sort the first block alphabetically —
    ``10_alpha`` before ``9_beta`` — which is neither what the tree says nor
    what the same files sorted as one flat list gave before blocks existed.
    """
    project = _two_block_tree(tmp_path)

    order = [
        f.relative_to(project).as_posix()
        for f in SchemaBuilder(env="test", project_dir=project).find_sql_files()
    ]

    assert order == _TWO_BLOCK_ORDER


def test_discovery_order_does_not_reach_a_blocked_build(tmp_path, shuffle_discovery):
    """Ten shuffles of a two-block tree produce one build order."""
    project = _two_block_tree(tmp_path)

    orders = []
    for seed in range(10):
        shuffle_discovery(seed)
        builder = SchemaBuilder(env="test", project_dir=project)
        orders.append([f.relative_to(project).as_posix() for f in builder.find_sql_files()])

    assert orders == [_TWO_BLOCK_ORDER] * 10


def _hex_tree(tmp_path: Path) -> Path:
    """A tree numbered the way ``TreeAllocator`` writes hex prefixes: lower case."""
    schema = tmp_path / "db" / "schema"
    schema.mkdir(parents=True)
    for stem in ("0009_early", "000a_middle", "000b_late"):
        (schema / f"{stem}.sql").write_text("SELECT 1;\n")
    env = tmp_path / "db" / "environments" / "test.yaml"
    env.parent.mkdir(parents=True)
    env.write_text(
        "database_url: postgresql://localhost/test\ninclude_dirs:\n  - db/schema\n"
        "build:\n  sort_mode: hex\n"
    )
    return tmp_path


def test_one_definition_of_a_numeric_prefix(tmp_path):
    """The builder, the allocator and the tree rules classify ``0a_`` the same way.

    ``TreeAllocator`` formats hex prefixes with ``format(value, '0Nx')`` — lower
    case — so a tree confiture generated itself was not hex to the builder that
    orders it.
    """
    from confiture.core.linting.libraries.generate import prefix_value
    from confiture.core.tree_allocator import PrefixScheme, TreeAllocator

    project = _hex_tree(tmp_path)
    schema = project / "db" / "schema"
    builder = SchemaBuilder(env="test", project_dir=project)

    assert builder._is_hex_prefix("000a_middle"), "builder does not see a lower-case hex prefix"
    assert prefix_value("000a_middle.sql") == 10
    detected = TreeAllocator(schema_dir=schema)._detect_config(schema)
    assert detected.scheme is PrefixScheme.HEX

    order = [f.stem for f in builder.find_sql_files()]
    assert order == ["0009_early", "000a_middle", "000b_late"]


def test_a_word_is_not_a_numeric_prefix(tmp_path):
    """``add_column.sql`` and ``abc_alpha.sql`` are words, not numbers.

    Every character of ``add`` is a hex digit. A prefix carries at least one
    decimal digit, which is what ``TreeAllocator`` always writes and what keeps
    an English word out of the numbering.
    """
    from confiture.core.linting.libraries.generate import prefix_value

    project = _hex_tree(tmp_path)
    builder = SchemaBuilder(env="test", project_dir=project)

    assert not builder._is_hex_prefix("add_column")
    assert not builder._is_hex_prefix("abc_alpha")
    assert prefix_value("add_column.sql") is None
    assert prefix_value("abc_alpha.sql") is None
