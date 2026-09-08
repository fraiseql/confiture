"""Lint rules for the SQL function file tree (``tree_001``–``tree_004``).

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

The first three read *the files the build reads*, handed to them as a list —
they do not walk the filesystem themselves. A rule that rglobbed its own tree
reported files the environment's ``exclude_dirs`` and per-directory ``exclude``
globs keep out of the build, i.e. files whose numbering decides nothing.
``tree_004``'s subject is the overrides mirror, which the build never reads, so
it walks that tree and asks the schema roots whether a counterpart exists.

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
from pathlib import Path

from confiture.core.linting.schema_linter import LintViolation, RuleSeverity
from confiture.core.tree_prefix import is_hex_group, prefix_value
from confiture.core.tree_prefix import prefix_text as _raw_prefix

#: Every code this module emits, in registry order.
TREE_RULE_CODES: tuple[str, ...] = ("tree_001", "tree_002", "tree_003", "tree_004")


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
            if len(values) < 2:
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


def tree_violations(
    files: Sequence[Path],
    *,
    selected: Collection[str] = TREE_RULE_CODES,
    schema_dirs: Sequence[Path] = (),
    overrides_dir: Path | None = None,
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
    return violations
