"""What a numbered filename's prefix is, and where the file it names sorts.

The DDL tree's numbering decides the build order, and the build order decides
which definition of an object wins and which objects exist when a later file
references them. Three modules ask "does this name carry a numeric prefix, and
what is its value": :mod:`confiture.core.builder`, which orders the build;
:mod:`confiture.core.linting.libraries.generate`, which lints the tree; and
:class:`confiture.core.tree_allocator.TreeAllocator`, which *writes* the names,
in lower-case hex. If they answered differently the linter could approve a
numbering the builder orders differently, or the builder could fail to recognise
a numbering confiture generated itself. This module is the one answer; the
others import it.

**What counts as a prefix.** The run of hex digits before the first ``_``,
either case, carrying at least one *decimal* digit. Without that last clause
every letter of ``add`` and ``face`` is a hex digit, so ``add_column.sql``
would sort as 2781 and ``abc_alpha.sql`` as 2748. ``TreeAllocator`` always
writes a zero-padded number, so nothing confiture generates is excluded.

**What base it is read in.** The base belongs to the *directory*, not to the
name — which is already how :meth:`TreeAllocator._detect_config` decides what
to allocate next. A directory holding one hex-lettered prefix is a hex
directory, and every sibling is read in base 16; a directory of pure digits is
decimal. Deciding per name instead gets both halves wrong: reading a decimal
tree in base 16 turns ``0009`` → ``0010`` into a gap of seven, which
``tree_003`` would report, and reading ``0100`` in base 10 beside ``009a`` in
base 16 puts 100 before 154 when the author wrote 256 after 154.
"""

import re
from collections import defaultdict
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path

#: The run of hex digits before the first underscore.
_PREFIX_RE = re.compile(r"^([0-9a-fA-F]+)_")
#: At least one decimal digit is what separates a number from a word.
_DIGIT_RE = re.compile(r"[0-9]")
#: A hex letter is what makes a directory's numbering base 16 rather than 10.
_HEX_LETTER_RE = re.compile(r"[a-fA-F]")


def prefix_text(name: str) -> str | None:
    """The raw prefix of *name*, or ``None`` when it carries none.

    Args:
        name: A bare file or directory name, with or without its suffix.

    Returns:
        The prefix as written — ``"000a"``, not ``10`` — or ``None``.

    Example:
        >>> prefix_text("0248_flag")
        '0248'
        >>> prefix_text("add_column.sql") is None
        True
    """
    match = _PREFIX_RE.match(name)
    if match is None:
        return None
    raw = match.group(1)
    return raw if _DIGIT_RE.search(raw) else None


def is_numbered(name: str) -> bool:
    """Whether *name* carries a numeric prefix."""
    return prefix_text(name) is not None


def has_hex_letter(raw: str) -> bool:
    """Whether a raw prefix is written in hexadecimal."""
    return _HEX_LETTER_RE.search(raw) is not None


def is_hex_group(names: Iterable[str]) -> bool:
    """Whether a set of sibling names is numbered in hexadecimal.

    One hex-lettered prefix makes the whole group hex, which is the rule
    :meth:`TreeAllocator._detect_config` already applies when it decides what
    to allocate next: a directory has one numbering, not one per file.
    """
    return any(
        has_hex_letter(raw) for raw in (prefix_text(name) for name in names) if raw is not None
    )


def bare_prefix(stem: str) -> bool:
    """Whether *stem* is a prefix and nothing else — ``0042``, ``00a1`` — with no verb after it."""
    return prefix_text(f"{stem}_") == stem


def format_prefix(value: int, *, width: int, hexadecimal: bool) -> str:
    """*value* as a prefix: zero-padded to *width*, in base 16 or 10.

    Example:
        >>> format_prefix(26, width=4, hexadecimal=True)
        '001a'
        >>> format_prefix(26, width=4, hexadecimal=False)
        '0026'
    """
    return format(value, f"0{width}{'x' if hexadecimal else 'd'}")


def prefixes(
    start: int, *, step: int = 1, width: int, hexadecimal: bool
) -> Iterator[tuple[int, str]]:
    """``(value, prefix)`` from *start* on, by *step* — each one a reader takes for a number.

    A hex value written without a decimal digit (``aba``, ``fff``) reads as a word,
    as ``add`` in ``add_column`` must: it is skipped, never written.
    """
    value = start
    while True:
        written = format_prefix(value, width=width, hexadecimal=hexadecimal)
        if prefix_text(f"{written}_") == written:
            yield value, written
        value += step


def numbering(names: Iterable[str]) -> tuple[bool, int] | None:
    """How sibling *names* are numbered: ``(hexadecimal, width)``, or ``None`` when none is.

    Hexadecimal when any prefix carries a hex letter (:func:`is_hex_group`); the
    width is the one most of them are written at.
    """
    prefixes = [raw for raw in (prefix_text(name) for name in names) if raw is not None]
    if not prefixes:
        return None
    widths = [len(raw) for raw in prefixes]
    return any(has_hex_letter(raw) for raw in prefixes), max(set(widths), key=widths.count)


def prefix_value(name: str, *, hex_group: bool | None = None) -> int | None:
    """The integer value of *name*'s prefix, or ``None`` when it carries none.

    Args:
        name: A bare file or directory name, with or without its suffix.
        hex_group: Whether the siblings *name* sits among are numbered in
            hexadecimal, from :func:`is_hex_group`. ``None`` reads the base off
            this name alone, which is all a caller holding one name can do.

    Returns:
        The prefix's value, or ``None`` — also for a hex prefix among siblings
        numbered in decimal.

    Example:
        >>> prefix_value("000a_middle.sql")
        10
        >>> prefix_value("0010_late.sql")
        10
        >>> prefix_value("0010_late.sql", hex_group=True)
        16
    """
    raw = prefix_text(name)
    if raw is None:
        return None
    hexadecimal = has_hex_letter(raw) if hex_group is None else hex_group
    if not hexadecimal and has_hex_letter(raw):
        return None  # a decimal group cannot read a hex prefix: it is not one of its numbers
    return int(raw, 16 if hexadecimal else 10)


def _component_key(name: str, *, hex_group: bool) -> tuple[int, int, str]:
    """Sort key for one path component: numbered entries first, in value order.

    The leading ``0``/``1`` ranks numbered entries before unnumbered ones, so
    an entry nobody numbered sorts after every entry somebody did rather than
    landing wherever its first character falls.
    """
    raw = prefix_text(name)
    if raw is None:
        return (1, 0, name)
    return (0, int(raw, 16 if hex_group else 10), name[len(raw) + 1 :])


def _hex_parents(paths: Iterable[Path]) -> set[tuple[str, ...]]:
    """The parent directories whose children are numbered in hexadecimal.

    A parent is identified by its own ``parts``, so the answer depends only on
    the set of paths and never on the order they arrive in.
    """
    names_by_parent: dict[tuple[str, ...], list[str]] = {}
    for path in paths:
        parts = path.parts
        for index, name in enumerate(parts):
            names_by_parent.setdefault(parts[:index], []).append(name)
    return {parent for parent, names in names_by_parent.items() if is_hex_group(names)}


def sort_key(
    path: Path, hex_parents: set[tuple[str, ...]]
) -> tuple[tuple[tuple[int, int, str], ...], tuple[str, ...]]:
    """A total order over paths that reads the number on **every** component.

    Keying on the filename alone would make the build order irreproducible:
    ``confiture generate alloc`` restarts numbering in each directory, so the
    ``00001_create.sql`` of one directory ties exactly with the
    ``00001_create.sql`` of the next, and a tie under a stable sort keeps
    whatever order ``Path.rglob`` returned — the filesystem's order, not the
    project's.

    The path's own parts are the last element of the key, so two entries a
    numbering cannot separate (``0001_x`` and ``001_x`` are both 1) are still
    ordered the same way on every machine.

    Args:
        path: The path to key.
        hex_parents: Parent ``parts`` tuples whose children are hex-numbered,
            from :func:`_hex_parents` over the whole set being sorted.
    """
    parts = path.parts
    return (
        tuple(
            _component_key(name, hex_group=parts[:index] in hex_parents)
            for index, name in enumerate(parts)
        ),
        parts,
    )


def order(paths: Iterable[Path]) -> list[Path]:
    """*paths*, in the order a build reads them under numeric sorting.

    Deterministic: the result depends on the set of paths alone, never on the
    order they were discovered in.
    """
    materialised = list(paths)
    hex_parents = _hex_parents(materialised)
    return sorted(materialised, key=lambda path: sort_key(path, hex_parents))


@dataclass(frozen=True)
class NumberedEntry:
    """One entry of a directory: a file the build reads, or a directory on the way to one.

    Attributes:
        path: Where the entry is.
        is_dir: Whether it is a directory. A finding about a file points at its
            first line; a directory has none.
        order: The position of the first file the build reads at or under this
            entry, so a finding can report the order it produces.
    """

    path: Path
    is_dir: bool
    order: int

    @property
    def label(self) -> str:
        """The entry's name, with a trailing slash when it is a directory."""
        return f"{self.path.name}/" if self.is_dir else self.path.name


def build_entries(files: Sequence[Path], roots: Sequence[Path]) -> dict[Path, list[NumberedEntry]]:
    """**The build's view**: every entry the build reads, grouped by its directory.

    Derived from the files the build reads rather than walked, so a directory the
    environment excludes contributes no entry and takes no number. Groups are in
    build order, as *files* is. An entry above a root is not part of the tree.

    Args:
        files: The SQL files the build reads, in the order it reads them.
        roots: The include directories they were found under.
    """
    deepest_first = sorted(roots, key=lambda root: len(root.parts), reverse=True)
    entries: dict[Path, NumberedEntry] = {}
    children: dict[Path, list[Path]] = defaultdict(list)
    for index, sql_file in enumerate(files):
        root = next((r for r in deepest_first if sql_file.is_relative_to(r)), None)
        if root is None:
            continue
        relative = sql_file.relative_to(root).parts
        for depth in range(1, len(relative) + 1):
            path = root.joinpath(*relative[:depth])
            if path not in entries:
                entries[path] = NumberedEntry(path=path, is_dir=depth < len(relative), order=index)
                children[path.parent].append(path)
    return {parent: [entries[child] for child in kids] for parent, kids in children.items()}


def disk_entries(directory: Path) -> list[NumberedEntry]:
    """**The disk's view**: *directory*'s numbered ``.sql`` files and subdirectories, in build order.

    For the tools that act on files the build has not read yet — allocating the
    next number, renumbering — which see a directory as it is on disk.
    """
    found = [
        child
        for child in directory.iterdir()
        if is_numbered(child.name) and (child.is_dir() or child.suffix == ".sql")
    ]
    return [
        NumberedEntry(path=path, is_dir=path.is_dir(), order=index)
        for index, path in enumerate(order(found))
    ]


#: One value of a directory's numbering, and the entries that take it.
Taken = tuple[int, list[NumberedEntry]]


@dataclass(frozen=True)
class Numbering:
    """A directory's numbering: its base, the values its entries take, and its step."""

    hexadecimal: bool
    taken: list[Taken]

    @property
    def step(self) -> int:
        """The step it counts in (:func:`step`)."""
        return step([value for value, _ in self.taken], hexadecimal=self.hexadecimal)

    def gaps(self) -> list[tuple[Taken, Taken]]:
        """Each pair of neighbouring values further apart than the step."""
        every = self.step
        return [(low, high) for low, high in pairwise(self.taken) if high[0] - low[0] > every]


def sequence(entries: Iterable[NumberedEntry]) -> Numbering:
    """How *entries* are numbered: the values they take, ascending, each with its entries.

    One numbering per directory: hexadecimal when any entry's prefix carries a hex
    letter, file and directory alike, as the build orders them. A file and a
    directory sharing a value are one value (their collision is a finding of its
    own, not a gap).
    """
    numbered = [entry for entry in entries if is_numbered(entry.path.name)]
    hexadecimal = is_hex_group(entry.path.name for entry in numbered)
    taken: dict[int, list[NumberedEntry]] = defaultdict(list)
    for entry in numbered:
        value = prefix_value(entry.path.name, hex_group=hexadecimal)
        if value is not None:
            taken[value].append(entry)
    return Numbering(hexadecimal, sorted(taken.items()))


def step(values: Sequence[int], *, hexadecimal: bool) -> int:
    """The step a directory's numbering counts in, read from the numbers themselves.

    A directory numbered ``10_tables``, ``20_views``, ``30_functions`` leaves room
    between its entries on purpose: when every value is a multiple of the base
    (10, or 16 in hex) — or of its square, … — that is its step. Otherwise it is 1,
    the step ``TreeAllocator`` numbers files with. Two numbers cannot say more.
    """
    base = 16 if hexadecimal else 10
    found = 1
    while values and max(values) >= found * base and all(v % (found * base) == 0 for v in values):
        found *= base
    return found
