"""SQL function tree file allocation.

Provides :class:`TreeAllocator`, which scans a directory of SQL files
and returns the next sort-stable filename for a given subtree.  The
numbering scheme (decimal or hex), prefix width, and step size are
auto-detected from existing files or supplied explicitly via
:class:`PrefixConfig`.

The module is intentionally pure-Python with no external dependencies
beyond the standard library so it can be imported and tested without a
database connection.

Example::

    from pathlib import Path
    from confiture.core.tree_allocator import TreeAllocator

    allocator = TreeAllocator(Path("db/schema"))
    path = allocator.alloc(
        Path("db/schema/functions/catalog/manufacturer"),
        verb="create",
    )
    # → Path("db/schema/functions/catalog/manufacturer/03323_create.sql")
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class PrefixScheme(Enum):
    """Numeric base used for file prefix allocation."""

    DECIMAL = "decimal"
    HEX = "hex"


@dataclass
class PrefixConfig:
    """Configuration for the prefix numbering scheme.

    Attributes:
        scheme: Numeric base for prefix digits.
        width: Zero-padded digit count (e.g. ``5`` → ``"00001"``).
        step: Increment applied to the current maximum to produce the next
            available prefix.
        start: First prefix value used when the target directory contains
            no recognised SQL files.
    """

    scheme: PrefixScheme = PrefixScheme.DECIMAL
    width: int = 5
    step: int = 1
    start: int = 1


# Matches a run of hex chars followed by '_' at the start of a filename.
# This is intentionally broad so the caller can decide whether the chars
# are hex-only or decimal-only.
_HEX_PREFIX_RE = re.compile(r"^([0-9a-fA-F]+)_")
# Matches a run of *decimal* digits followed by '_'.
_DECIMAL_PREFIX_RE = re.compile(r"^(\d+)_")
# Detects at least one letter (a-f/A-F) that makes a prefix truly hex.
_HEX_LETTER_RE = re.compile(r"[a-fA-F]")
# Allowed characters in a verb: ASCII letters, digits, underscore, hyphen, dot.
# Rejects path separators (``/``, ``\``) and ``..`` sequences that would let a
# verb escape the target directory via ``Path.mkdir(parents=True)``.
_SAFE_VERB_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]*$")


def _parse_prefix(filename: str, base: int = 10) -> int | None:
    """Parse the numeric prefix from *filename*, or return *None*.

    Args:
        filename: Bare filename (not a full path), e.g. ``"00042_create.sql"``.
        base: Numeric base — ``10`` for decimal, ``16`` for hex.

    Returns:
        Integer value of the prefix, or *None* if the filename does not
        start with a recognisable prefix in the requested base.
    """
    pattern = _HEX_PREFIX_RE if base == 16 else _DECIMAL_PREFIX_RE
    m = pattern.match(filename)
    if not m:
        return None
    try:
        return int(m.group(1), base)
    except ValueError:
        return None


class TreeAllocator:
    """Allocates sort-stable filenames within a SQL function subtree.

    Scans *target_dir* for ``.sql`` files whose names begin with a
    numeric prefix followed by an underscore (e.g. ``00042_create.sql``).
    :meth:`alloc` returns the :class:`~pathlib.Path` to the next
    available file, without writing anything to disk.

    The allocation is **stateless and deterministic**: given the same
    directory contents, :meth:`alloc` always returns the same answer.
    Parallel-branch prefix collisions are therefore resolved at
    rebase/merge time — use :command:`confiture generate renumber` to
    fix them after the fact.

    Args:
        schema_dir: Root of the schema tree (e.g. ``Path("db/schema")``).
            Used to validate that *target_dir* is a subdirectory.  The
            path is resolved to an absolute path on construction.
        config: Explicit prefix configuration.  When *None*, the
            configuration is auto-detected from the files already present
            in *target_dir* at the time :meth:`alloc` is called.
    """

    def __init__(
        self,
        schema_dir: Path,
        config: PrefixConfig | None = None,
    ) -> None:
        self.schema_dir = schema_dir.resolve()
        self._explicit_config = config

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def alloc(self, target_dir: Path, verb: str | None = None) -> Path:
        """Return the path to the next available file in *target_dir*.

        The returned path does **not** exist yet; the caller is
        responsible for creating it.

        Args:
            target_dir: Directory in which to allocate the next filename.
                Must exist, must be a directory, and must be within
                :attr:`schema_dir` (inclusive).
            verb: Optional verb suffix appended after an underscore, e.g.
                ``"create"`` produces ``"<prefix>_create.sql"``.  When
                omitted the filename is simply ``"<prefix>.sql"``.

        Returns:
            :class:`~pathlib.Path` pointing to the (not-yet-created) file.

        Raises:
            ValueError: If *target_dir* does not exist, is not a
                directory, or lies outside :attr:`schema_dir`.
        """
        resolved = target_dir.resolve()
        self._validate_target(resolved)
        if verb is not None:
            self._validate_verb(verb)

        config = self._explicit_config or self._detect_config(resolved)
        existing = self._collect_prefixes(resolved, config.scheme)
        next_value = (max(existing) + config.step) if existing else config.start
        prefix_str = self._format_prefix(next_value, config)
        stem = f"{prefix_str}_{verb}" if verb else prefix_str
        output_path = resolved / f"{stem}.sql"

        # Defence in depth: confirm the final path is still inside schema_dir
        # after resolution.  Catches symlink tricks and any verb-validation
        # bypass that might slip through.
        try:
            output_path.resolve().relative_to(self.schema_dir)
        except ValueError:
            raise ValueError(
                f"allocated path {output_path!s} escapes schema root {self.schema_dir!s}"
            ) from None
        return output_path

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _validate_target(self, target_dir: Path) -> None:
        """Raise ValueError if *target_dir* is invalid."""
        if not target_dir.exists():
            raise ValueError(f"Directory does not exist: {target_dir}")
        if not target_dir.is_dir():
            raise ValueError(f"Path is not a directory: {target_dir}")
        try:
            target_dir.relative_to(self.schema_dir)
        except ValueError:
            raise ValueError(f"{target_dir} is not within schema root {self.schema_dir}") from None

    @staticmethod
    def _validate_verb(verb: str) -> None:
        """Reject verbs that could escape the target directory.

        A verb is interpolated into the output filename as
        ``{prefix}_{verb}.sql``.  Allowing path separators or ``..`` segments
        would let an emitter write outside ``schema_dir`` via
        ``Path.mkdir(parents=True)`` / ``write_text``.
        """
        if not _SAFE_VERB_RE.match(verb):
            raise ValueError(
                f"invalid verb {verb!r}: must match {_SAFE_VERB_RE.pattern} "
                "(letters, digits, underscore, hyphen, dot; no path separators)"
            )

    def _detect_config(self, directory: Path) -> PrefixConfig:
        """Auto-detect :class:`PrefixConfig` from files in *directory*.

        Examines each ``.sql`` filename, collects widths and whether any
        prefix contains a hex letter (``a``–``f``), then returns a
        :class:`PrefixConfig` whose ``width`` is the modal prefix width
        and whose ``scheme`` is :attr:`PrefixScheme.HEX` if any prefix
        letter was found.

        Falls back to :class:`PrefixConfig` defaults when the directory
        is empty or contains no recognisable prefixed files.
        """
        widths: list[int] = []
        has_hex_letter = False

        for child in directory.iterdir():
            if child.suffix != ".sql":
                continue
            m = _HEX_PREFIX_RE.match(child.name)
            if not m:
                continue
            raw = m.group(1)
            widths.append(len(raw))
            if _HEX_LETTER_RE.search(raw):
                has_hex_letter = True

        if not widths:
            return PrefixConfig()

        scheme = PrefixScheme.HEX if has_hex_letter else PrefixScheme.DECIMAL
        # Modal width — most common length among existing prefixes.
        width = max(set(widths), key=widths.count)
        return PrefixConfig(scheme=scheme, width=width)

    def _collect_prefixes(self, directory: Path, scheme: PrefixScheme) -> list[int]:
        """Return all existing numeric prefix values in *directory*.

        Only ``.sql`` files whose names begin with a recognisable prefix
        (decimal or hex, depending on *scheme*) are included.

        Args:
            directory: Directory to scan.
            scheme: Numeric base to use when parsing prefixes.

        Returns:
            List of integer prefix values (may be empty, may be unsorted).
        """
        base = 16 if scheme == PrefixScheme.HEX else 10
        result: list[int] = []
        for child in directory.iterdir():
            if child.suffix != ".sql":
                continue
            value = _parse_prefix(child.name, base)
            if value is not None:
                result.append(value)
        return result

    @staticmethod
    def _format_prefix(value: int, config: PrefixConfig) -> str:
        """Format *value* as a zero-padded prefix string.

        Args:
            value: Integer to format.
            config: Provides ``scheme`` (decimal/hex) and ``width``.

        Returns:
            Zero-padded string, e.g. ``"00042"`` or ``"0001a"``.
        """
        if config.scheme == PrefixScheme.HEX:
            return format(value, f"0{config.width}x")
        return format(value, f"0{config.width}d")
