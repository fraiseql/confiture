"""Lint rules for the SQL function file tree (``tree_001``–``tree_008``).

These rules enforce structural consistency in the ``db/schema/`` directory
tree managed by ``confiture generate alloc / scaffold / renumber``.

Rules
-----
tree_001  Prefix uniqueness — no two files in the same directory share a
          numeric prefix.  Severity: ERROR.
tree_002  Verb suffix — every prefixed file must include a verb after the
          underscore (e.g. ``00001_create.sql`` not ``00001.sql``).
          Severity: WARNING.
tree_003  Gap policy — consecutive prefix values within a directory must be
          contiguous (step 1).  Severity: WARNING.
tree_004  Orphaned overrides — every file in the ``overrides/`` mirror must
          have a matching file in the schema tree.  Severity: WARNING.
tree_005  Sibling collision — two entries in one directory share a numeric
          prefix, where at least one of them is a directory.  Severity:
          WARNING.
tree_006  Parent extension — an entry's prefix does not extend its parent's,
          in a directory whose own prefix extends *its* parent's.  Severity:
          WARNING.
tree_007  Unnumbered sibling — an entry carries no numeric prefix while its
          siblings do.  Severity: WARNING.
tree_008  Status word — a file or directory name says the work is not
          finished.  Severity: INFO.

``tree_001`` compares files within one directory, so a pair of colliding
*directories* was invisible to it; ``tree_005`` is about the entries it does
not compare, and ``tree_002`` looks only at files that already carry a prefix,
which is why ``tree_007`` exists. The last four are the shapes #249 found by
hand in one tree, 54 times between them.

Every rule but ``tree_004`` reads *the files the build reads*, handed to it as
a list — none of them walks the filesystem. A rule that rglobbed its own tree
reported files the environment's ``exclude_dirs`` and per-directory ``exclude``
globs keep out of the build, i.e. files whose numbering decides nothing.
``tree_004``'s subject is the overrides mirror, which the build never reads, so
it walks that tree and asks the schema roots whether a counterpart exists.

None of them opens a file. These are findings about names, and the filename
patterns here are filename patterns: no rule in this module reads SQL text, so
none of it goes near ``core.sql_lexer``.

Usage (via SchemaLinter)::

    from pathlib import Path
    from confiture.core.linting.schema_linter import SchemaLinter

    report = SchemaLinter().lint_tree(
        schema_dir=Path("db/schema"),
        overrides_dir=Path("db/schema/overrides"),
    )
    for v in report.errors + report.warnings:
        print(v)

Usage (one rule directly)::

    from confiture.core.linting.libraries.generate import Tree001PrefixUnique

    violations = Tree001PrefixUnique().check(sorted(Path("db/schema").rglob("*.sql")))
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from pathlib import Path

from confiture.config.environment import DEFAULT_STATUS_WORDS
from confiture.core.linting.schema_linter import LintViolation, RuleSeverity
from confiture.core.tree_prefix import is_hex_group, prefix_value
from confiture.core.tree_prefix import prefix_text as _raw_prefix

#: Every code this module emits, in registry order.
TREE_RULE_CODES: tuple[str, ...] = (
    "tree_001",
    "tree_002",
    "tree_003",
    "tree_004",
    "tree_005",
    "tree_006",
    "tree_007",
    "tree_008",
)


@dataclass(frozen=True)
class _Entry:
    """One thing the build reads, or a directory on the way to one.

    Attributes:
        path: Where the entry is.
        is_dir: Whether it is a directory. A finding about a file points at its
            first line; a directory has none.
        order: The position of the first file the build reads at or under this
            entry, so a collision can report the order it produces — which is
            the thing only confiture knows, because it computes it.
    """

    path: Path
    is_dir: bool
    order: int

    @property
    def label(self) -> str:
        """The entry's name, with a trailing slash when it is a directory."""
        return f"{self.path.name}/" if self.is_dir else self.path.name


def _entries_by_parent(files: Sequence[Path], roots: Sequence[Path]) -> dict[Path, list[_Entry]]:
    """Every entry the build reads, grouped by the directory it sits in.

    Derived from the file list rather than walked, so a directory the
    environment's ``exclude_dirs`` or per-directory ``exclude`` globs keep out
    of the build contributes no entry and is judged by nothing (LINT-08).
    Groups are in build order, and so is *files*.

    Args:
        files: The SQL files the build reads, in the order it reads them.
        roots: The include directories they were found under. An entry above a
            root is not part of the tree and is never judged.
    """
    deepest_first = sorted(roots, key=lambda root: len(root.parts), reverse=True)
    entries: dict[Path, _Entry] = {}
    children: dict[Path, list[Path]] = defaultdict(list)
    for index, sql_file in enumerate(files):
        root = next((r for r in deepest_first if sql_file.is_relative_to(r)), None)
        if root is None:
            continue
        relative = sql_file.relative_to(root).parts
        for depth in range(1, len(relative) + 1):
            path = root.joinpath(*relative[:depth])
            if path not in entries:
                entries[path] = _Entry(path=path, is_dir=depth < len(relative), order=index)
                children[path.parent].append(path)
    return {parent: [entries[child] for child in kids] for parent, kids in children.items()}


#: A collision needs two entries, and a gap needs two numbers, to exist at all.
_A_PAIR = 2


def _extends(child: str, parent: str) -> bool:
    """Whether *child* continues *parent*'s numbering rather than restarting it."""
    return len(child) > len(parent) and child.casefold().startswith(parent.casefold())


def _enforced_prefix(directory: Path) -> str | None:
    """The prefix *directory*'s children must extend, or ``None``.

    The convention is read out of the tree, never assumed: a directory requires
    its children to extend its prefix only when its own prefix extends *its*
    parent's. ``10_tables/01_users.sql`` — the layout
    ``docs/organizing-sql-files.md`` calls Pattern 2, where each directory
    numbers its contents from 1 — therefore reports nothing, while
    ``034_dim/0341_geo/03452_odd`` reports, because ``0341`` continuing ``034``
    is the tree saying which convention it keeps.
    """
    own = _raw_prefix(directory.name)
    if own is None:
        return None
    above = _raw_prefix(directory.parent.name)
    if above is None or not _extends(own, above):
        return None
    return own


def _by_directory(files: Sequence[Path]) -> dict[Path, list[Path]]:
    """Group SQL files by the directory they sit in, each group name-sorted."""
    grouped: dict[Path, list[Path]] = defaultdict(list)
    for sql_file in files:
        if sql_file.suffix == ".sql":
            grouped[sql_file.parent].append(sql_file)
    return {directory: sorted(group, key=lambda f: f.name) for directory, group in grouped.items()}


class Tree001PrefixUnique:
    """``tree_001`` — no two files in the same directory share a numeric prefix.

    Emits one ERROR for each file beyond the first that shares a prefix value
    with a sibling: the build reads all of them, in an order the prefix no
    longer decides.
    """

    def check(self, files: Sequence[Path]) -> list[LintViolation]:
        """Run the check and return all violations found.

        Args:
            files: The SQL files the build reads.

        Returns:
            List of :class:`~confiture.core.linting.schema_linter.LintViolation`.
        """
        violations: list[LintViolation] = []

        for directory, group in _by_directory(files).items():
            prefix_to_files: dict[str, list[Path]] = defaultdict(list)
            for sql_file in group:
                raw = _raw_prefix(sql_file.name)
                if raw is not None:
                    prefix_to_files[raw].append(sql_file)

            for raw_prefix, sharing in prefix_to_files.items():
                if len(sharing) <= 1:
                    continue
                # First file is the "winner"; every subsequent file is a duplicate.
                violations.extend(
                    LintViolation(
                        rule_id="tree_001",
                        rule_name="Prefix Uniqueness",
                        severity=RuleSeverity.ERROR,
                        object_type="file",
                        object_name=dup.name,
                        message=(
                            f"Prefix '{raw_prefix}' is shared by multiple files "
                            f"in {directory.name}/: "
                            f"{', '.join(f.name for f in sharing)}"
                        ),
                        file_path=str(dup),
                    )
                    for dup in sharing[1:]
                )

        return violations


class Tree002VerbSuffix:
    """``tree_002`` — every prefixed file must carry a verb after the underscore.

    A file whose stem is entirely digits (or hex digits) with no underscore
    is a prefixed file with no verb — ``00001.sql`` rather than the expected
    ``00001_create.sql``.

    Files with no numeric prefix (e.g. ``helpers.sql``) are ignored.
    """

    def check(self, files: Sequence[Path]) -> list[LintViolation]:
        """Run the check and return all violations found.

        Args:
            files: The SQL files the build reads.

        Returns:
            List of :class:`~confiture.core.linting.schema_linter.LintViolation`.
        """
        return [
            LintViolation(
                rule_id="tree_002",
                rule_name="Verb Suffix",
                severity=RuleSeverity.WARNING,
                object_type="file",
                object_name=sql_file.name,
                message=(
                    f"'{sql_file.name}' has a numeric prefix but no verb suffix. "
                    f"Expected format: <prefix>_<verb>.sql"
                ),
                file_path=str(sql_file),
            )
            # Stem starts with a digit AND has no underscore → prefixed, no verb.
            for sql_file in files
            if sql_file.suffix == ".sql"
            and sql_file.stem[:1].isdigit()
            and "_" not in sql_file.stem
        ]


class Tree003GapPolicy:
    """``tree_003`` — consecutive prefix values within a directory are contiguous.

    Detects gaps in prefix sequences (step > 1 between adjacent values) and
    emits one WARNING per gap found.  A single-file or empty directory is
    always valid.

    This rule assumes a step of 1 between consecutive allocations, which is
    the default for :class:`~confiture.core.tree_allocator.TreeAllocator`.
    """

    def check(self, files: Sequence[Path]) -> list[LintViolation]:
        """Run the check and return all violations found.

        Args:
            files: The SQL files the build reads.

        Returns:
            List of :class:`~confiture.core.linting.schema_linter.LintViolation`.
        """
        violations: list[LintViolation] = []

        for directory, group in _by_directory(files).items():
            # One numbering per directory, as TreeAllocator allocates it: a
            # decimal tree read in base 16 turns 0009 → 0010 into a gap of six.
            hex_group = is_hex_group(f.name for f in group)
            values = sorted(
                value
                for value in (prefix_value(f.name, hex_group=hex_group) for f in group)
                if value is not None
            )
            if len(values) < _A_PAIR:
                continue

            violations.extend(
                LintViolation(
                    rule_id="tree_003",
                    rule_name="Prefix Gap",
                    severity=RuleSeverity.WARNING,
                    object_type="directory",
                    object_name=directory.name,
                    message=(
                        f"Gap in prefix sequence in {directory.name}/: "
                        f"{values[i - 1]} → {values[i]} "
                        f"(missing {values[i] - values[i - 1] - 1} value(s))"
                    ),
                    file_path=str(directory),
                )
                for i in range(1, len(values))
                if values[i] - values[i - 1] > 1
            )

        return violations


class Tree004OrphanedOverride:
    """``tree_004`` — every file in the overrides mirror matches a schema file.

    When a file exists in ``overrides_dir`` but its counterpart is absent
    from every schema root, it is an orphaned override — the generated file
    was deleted or moved without cleaning up the override.
    """

    def check(self, schema_dirs: Sequence[Path], overrides_dir: Path) -> list[LintViolation]:
        """Run the check and return all violations found.

        Args:
            schema_dirs: The roots of the schema tree the overrides mirror.
            overrides_dir: Root of the overrides mirror directory.

        Returns:
            List of :class:`~confiture.core.linting.schema_linter.LintViolation`.
        """
        violations: list[LintViolation] = []

        if not overrides_dir.exists():
            return violations

        for override_file in sorted(overrides_dir.rglob("*.sql")):
            if not override_file.is_file():
                continue
            try:
                rel = override_file.relative_to(overrides_dir)
            except ValueError:
                continue
            if any((root / rel).exists() for root in schema_dirs):
                continue
            violations.append(
                LintViolation(
                    rule_id="tree_004",
                    rule_name="Orphaned Override",
                    severity=RuleSeverity.WARNING,
                    object_type="file",
                    object_name=override_file.name,
                    message=(
                        f"Override '{rel}' has no matching file in schema tree. "
                        f"Delete the override or restore the schema file."
                    ),
                    file_path=str(override_file),
                )
            )

        return violations


class Tree005SiblingPrefix:
    """``tree_005`` — two sibling entries share a numeric prefix.

    ``tree_001`` compares the *files* in one directory; this compares every
    entry the build reads, so the shape #249 found 36 times — two sibling
    *directories* numbered ``0248`` — is reported at last. A group of files
    alone stays ``tree_001``'s, which is an ``error`` and already names them.

    The message carries the resulting build order, because confiture is the
    only component that computes it: inserting a file into one of the colliding
    directories silently reorders the other.
    """

    def check(self, files: Sequence[Path], roots: Sequence[Path]) -> list[LintViolation]:
        """Run the check and return all violations found.

        Args:
            files: The SQL files the build reads, in the order it reads them.
            roots: The include directories they were found under.

        Returns:
            List of :class:`~confiture.core.linting.schema_linter.LintViolation`.
        """
        violations: list[LintViolation] = []

        for parent, entries in _entries_by_parent(files, roots).items():
            groups: dict[str, list[_Entry]] = defaultdict(list)
            for entry in entries:
                raw = _raw_prefix(entry.path.name)
                if raw is not None:
                    groups[raw.casefold()].append(entry)

            for sharing in groups.values():
                if len(sharing) < _A_PAIR or not any(entry.is_dir for entry in sharing):
                    continue
                ordered = sorted(sharing, key=lambda entry: entry.order)
                raw = _raw_prefix(ordered[0].path.name)
                violations.extend(
                    LintViolation(
                        rule_id="tree_005",
                        rule_name="Sibling Prefix Collision",
                        severity=RuleSeverity.WARNING,
                        object_type="directory" if dup.is_dir else "file",
                        object_name=dup.path.name,
                        message=(
                            f"Prefix '{raw}' is shared by sibling entries in "
                            f"{parent.name}/: {', '.join(e.label for e in ordered)}. "
                            f"The build reads {ordered[0].label} first; adding a file to "
                            f"either one silently reorders the other."
                        ),
                        file_path=str(dup.path),
                        line_number=None if dup.is_dir else 1,
                    )
                    for dup in ordered[1:]
                )

        return violations


class Tree006ParentPrefix:
    """``tree_006`` — an entry's prefix does not extend its parent's.

    ``0341_geo/03452_odd`` reads as a typo and applies where nobody put it:
    under the default alphabetical sort a prefix of the wrong length reorders
    the whole subtree, because ``0341_geo`` sorts before ``034_dim`` (``1`` <
    ``_``).

    The convention is read out of the tree rather than assumed — see
    :func:`_enforced_prefix` — so a project that numbers each directory from 1
    reports nothing.
    """

    def check(self, files: Sequence[Path], roots: Sequence[Path]) -> list[LintViolation]:
        """Run the check and return all violations found.

        Args:
            files: The SQL files the build reads, in the order it reads them.
            roots: The include directories they were found under.

        Returns:
            List of :class:`~confiture.core.linting.schema_linter.LintViolation`.
        """
        violations: list[LintViolation] = []

        for parent, entries in _entries_by_parent(files, roots).items():
            expected = _enforced_prefix(parent)
            if expected is None:
                continue
            for entry in entries:
                raw = _raw_prefix(entry.path.name)
                if raw is None or _extends(raw, expected):
                    continue
                violations.append(
                    LintViolation(
                        rule_id="tree_006",
                        rule_name="Parent Prefix Extension",
                        severity=RuleSeverity.WARNING,
                        object_type="directory" if entry.is_dir else "file",
                        object_name=entry.path.name,
                        message=(
                            f"Prefix '{raw}' does not extend its parent's '{expected}'. "
                            f"Entries in {parent.name}/ are numbered '{expected}…'; "
                            f"'{raw}' sorts by its own digits, and takes everything "
                            f"under it along."
                        ),
                        file_path=str(entry.path),
                        line_number=None if entry.is_dir else 1,
                    )
                )

        return violations


class Tree007Unnumbered:
    """``tree_007`` — an entry carries no numeric prefix while its siblings do.

    An unnumbered entry sorts by its name against numbered ones, so where it
    lands in the build is decided by its first character rather than by
    anybody. Distinct from ``tree_002``, which asks whether a *prefixed* file
    also carries a verb and never looks at a file with no prefix at all.

    A directory whose entries are all unnumbered reports nothing —
    ``00_common/extensions.sql`` is idiomatic, and it is the mixture that makes
    a position undecided.
    """

    def check(self, files: Sequence[Path], roots: Sequence[Path]) -> list[LintViolation]:
        """Run the check and return all violations found.

        Args:
            files: The SQL files the build reads, in the order it reads them.
            roots: The include directories they were found under.

        Returns:
            List of :class:`~confiture.core.linting.schema_linter.LintViolation`.
        """
        violations: list[LintViolation] = []

        for parent, entries in _entries_by_parent(files, roots).items():
            unnumbered = [e for e in entries if _raw_prefix(e.path.name) is None]
            if not unnumbered or len(unnumbered) == len(entries):
                continue
            violations.extend(
                LintViolation(
                    rule_id="tree_007",
                    rule_name="Unnumbered Entry",
                    severity=RuleSeverity.WARNING,
                    object_type="directory" if entry.is_dir else "file",
                    object_name=entry.path.name,
                    message=(
                        f"'{entry.label}' carries no numeric prefix while its siblings in "
                        f"{parent.name}/ do. It sorts by its name against them, so its "
                        f"position in the build is decided by its first character."
                    ),
                    file_path=str(entry.path),
                    line_number=None if entry.is_dir else 1,
                )
                for entry in unnumbered
            )

        return violations


class Tree008StatusWord:
    """``tree_008`` — a name says the work is not finished.

    ``..._update_TODO.sql`` is in the build and applied on every deploy, and
    its own name says it is not done. Whether that is confiture's business is
    arguable — which is why the rule is ``info`` and opt-in, and why the
    vocabulary is :attr:`LintSettings.status_words` rather than a constant.
    """

    def __init__(self, status_words: Collection[str] = DEFAULT_STATUS_WORDS) -> None:
        """Args:
        status_words: The words to report, matched case-insensitively
            against the underscore-separated parts of a name.
        """
        self._words = {word.casefold() for word in status_words if word}

    def check(self, files: Sequence[Path], roots: Sequence[Path]) -> list[LintViolation]:
        """Run the check and return all violations found.

        Args:
            files: The SQL files the build reads, in the order it reads them.
            roots: The include directories they were found under.

        Returns:
            List of :class:`~confiture.core.linting.schema_linter.LintViolation`.
        """
        violations: list[LintViolation] = []
        if not self._words:
            return violations

        for entries in _entries_by_parent(files, roots).values():
            for entry in entries:
                stem = entry.path.name if entry.is_dir else entry.path.stem
                found = [part for part in stem.split("_") if part.casefold() in self._words]
                if not found:
                    continue
                violations.append(
                    LintViolation(
                        rule_id="tree_008",
                        rule_name="Status Word In Name",
                        severity=RuleSeverity.INFO,
                        object_type="directory" if entry.is_dir else "file",
                        object_name=entry.path.name,
                        message=(
                            f"'{entry.label}' carries the status word '{found[0]}'. "
                            f"The build reads it and every deploy applies it. Finish it, "
                            f"take it out of the build, or set lint.status_words."
                        ),
                        file_path=str(entry.path),
                        line_number=None if entry.is_dir else 1,
                    )
                )

        return violations


def tree_violations(
    files: Sequence[Path],
    *,
    selected: Collection[str] = TREE_RULE_CODES,
    schema_dirs: Sequence[Path] = (),
    overrides_dir: Path | None = None,
    status_words: Collection[str] = DEFAULT_STATUS_WORDS,
) -> list[LintViolation]:
    """Run the selected file-tree rules over *files*.

    The one place the four rules are sequenced: ``confiture lint``,
    ``confiture lint-unified --check tree`` and
    :meth:`~confiture.core.linting.schema_linter.SchemaLinter.lint_tree` all
    arrive here, so selecting, ignoring and baselining a tree rule mean the same
    thing whichever command was typed.

    Args:
        files: The SQL files the build reads, for ``tree_001``–``tree_003``.
        selected: Which codes to run. Anything outside :data:`TREE_RULE_CODES`
            is ignored, so a caller can pass a whole ``--select`` resolution.
        schema_dirs: Schema roots, for ``tree_004``'s counterpart lookup.
        overrides_dir: The overrides mirror. ``tree_004`` is skipped without it —
            there is no conventional location to guess, and guessing wrong would
            report every generated file as an orphan.
        status_words: ``tree_008``'s vocabulary, from ``lint.status_words``.

    Returns:
        Every violation the selected rules found, rule order preserved.
    """
    violations: list[LintViolation] = []
    if "tree_001" in selected:
        violations += Tree001PrefixUnique().check(files)
    if "tree_002" in selected:
        violations += Tree002VerbSuffix().check(files)
    if "tree_003" in selected:
        violations += Tree003GapPolicy().check(files)
    if "tree_004" in selected and overrides_dir is not None:
        violations += Tree004OrphanedOverride().check(schema_dirs, overrides_dir)
    if "tree_005" in selected:
        violations += Tree005SiblingPrefix().check(files, schema_dirs)
    if "tree_006" in selected:
        violations += Tree006ParentPrefix().check(files, schema_dirs)
    if "tree_007" in selected:
        violations += Tree007Unnumbered().check(files, schema_dirs)
    if "tree_008" in selected:
        violations += Tree008StatusWord(status_words).check(files, schema_dirs)
    return violations
