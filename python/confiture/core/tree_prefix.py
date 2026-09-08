"""What a numbered filename's prefix is, and where the file it names sorts.

The DDL tree's numbering decides the build order, and the build order decides
which definition of an object wins and which objects exist when a later file
references them. Three modules used to answer "does this name carry a numeric
prefix, and what is its value" differently:

* :mod:`confiture.core.builder` demanded **upper case** — ``0A_x.sql`` was a
  number, ``0a_x.sql`` was a word — and read every prefix in base 16;
* :mod:`confiture.core.linting.libraries.generate`, which lints the tree,
  accepted either case and read base 16 only when *that name* carried a hex
  letter;
* :class:`confiture.core.tree_allocator.TreeAllocator`, which *writes* the
  names, formats hex with ``format(value, "0Nx")`` — lower case, i.e. a
  numbering confiture generates itself that the builder did not recognise.

So the linter could approve a numbering the builder ordered differently
(LINT-07). This module is the one answer; the others import it.

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

from __future__ import annotations

import re
from collections.abc import Iterable
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


def prefix_value(name: str, *, hex_group: bool | None = None) -> int | None:
    """The integer value of *name*'s prefix, or ``None`` when it carries none.

    Args:
        name: A bare file or directory name, with or without its suffix.
        hex_group: Whether the siblings *name* sits among are numbered in
            hexadecimal, from :func:`is_hex_group`. ``None`` reads the base off
            this name alone, which is all a caller holding one name can do.

    Returns:
        The prefix's value, or ``None``.

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
    return int(raw, 16 if (has_hex_letter(raw) if hex_group is None else hex_group) else 10)


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

    Keying on the filename alone is what made the build order irreproducible
    (LINT-06): ``confiture generate alloc`` restarts numbering in each
    directory, so the ``00001_create.sql`` of one directory tied exactly with
    the ``00001_create.sql`` of the next, and a tie under a stable sort keeps
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
