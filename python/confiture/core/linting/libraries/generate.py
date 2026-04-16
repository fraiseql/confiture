"""Lint rules for the SQL function file tree (GEN001–GEN004).

These rules enforce structural consistency in the ``db/schema/`` directory
tree managed by ``confiture generate alloc / scaffold / renumber``.

Rules
-----
GEN001  Prefix uniqueness — no two files in the same directory share a
        numeric prefix.  Severity: ERROR.
GEN002  Verb suffix — every prefixed file must include a verb after the
        underscore (e.g. ``00001_create.sql`` not ``00001.sql``).
        Severity: WARNING.
GEN003  Gap policy — consecutive prefix values within a directory must be
        contiguous (step 1).  Severity: WARNING.
GEN004  Orphaned overrides — every file in the ``overrides/`` mirror must
        have a matching file in the schema tree.  Severity: WARNING.

Usage (via SchemaLinter)::

    from pathlib import Path
    from confiture.core.linting.schema_linter import SchemaLinter

    report = SchemaLinter().lint_tree(
        schema_dir=Path("db/schema"),
        overrides_dir=Path("db/schema/overrides"),
    )
    for v in report.errors + report.warnings:
        print(v)

Usage (rules directly)::

    from confiture.core.linting.libraries.generate import Gen001PrefixUnique

    violations = Gen001PrefixUnique().check(Path("db/schema"))
"""

from __future__ import annotations

import re
from pathlib import Path

from confiture.core.linting.schema_linter import LintViolation, RuleSeverity

# Matches a leading hex/decimal prefix followed by exactly one underscore.
_PREFIX_CAPTURE_RE = re.compile(r"^([0-9a-fA-F]+)_")
# Distinguishes hex letters from pure-decimal digits.
_HEX_LETTER_RE = re.compile(r"[a-fA-F]")
# Matches a stem that is entirely decimal or hex digits (no underscore).
_PREFIX_ONLY_STEM_RE = re.compile(r"^[0-9][0-9a-fA-F]*$")


def _raw_prefix(filename: str) -> str | None:
    """Return the raw prefix string (digits before first ``_``), or *None*."""
    m = _PREFIX_CAPTURE_RE.match(filename)
    return m.group(1) if m else None


def _parse_prefix_value(filename: str) -> int | None:
    """Return the integer value of the prefix, or *None* if absent."""
    raw = _raw_prefix(filename)
    if raw is None:
        return None
    base = 16 if _HEX_LETTER_RE.search(raw) else 10
    return int(raw, base)


def _sql_files_in(directory: Path) -> list[Path]:
    return [f for f in directory.iterdir() if f.is_file() and f.suffix == ".sql"]


def _all_dirs(schema_dir: Path) -> list[Path]:
    """Return *schema_dir* plus every descendant directory."""
    return [schema_dir, *[d for d in schema_dir.rglob("*") if d.is_dir()]]


class Gen001PrefixUnique:
    """GEN001 — No two files in the same directory share a numeric prefix.

    Scans every directory under ``schema_dir`` and emits one ERROR for
    each extra file beyond the first that shares a prefix value.
    """

    def check(self, schema_dir: Path) -> list[LintViolation]:
        """Run the check and return all violations found.

        Args:
            schema_dir: Root of the schema tree to scan.

        Returns:
            List of :class:`~confiture.core.linting.schema_linter.LintViolation`.
        """
        violations: list[LintViolation] = []

        for directory in _all_dirs(schema_dir):
            prefix_to_files: dict[str, list[Path]] = {}
            for sql_file in _sql_files_in(directory):
                raw = _raw_prefix(sql_file.name)
                if raw is None:
                    continue
                prefix_to_files.setdefault(raw, []).append(sql_file)

            for raw_prefix, files in prefix_to_files.items():
                if len(files) <= 1:
                    continue
                # First file is the "winner"; every subsequent file is a duplicate.
                for dup in sorted(files, key=lambda f: f.name)[1:]:
                    violations.append(
                        LintViolation(
                            rule_id="GEN001",
                            rule_name="Prefix Uniqueness",
                            severity=RuleSeverity.ERROR,
                            object_type="file",
                            object_name=dup.name,
                            message=(
                                f"Prefix '{raw_prefix}' is shared by multiple files "
                                f"in {directory.name}/: "
                                f"{', '.join(sorted(f.name for f in files))}"
                            ),
                            file_path=str(dup),
                        )
                    )

        return violations


class Gen002VerbSuffix:
    """GEN002 — Every prefixed file must carry a verb after the underscore.

    A file whose stem is entirely digits (or hex digits) with no underscore
    is a prefixed file with no verb — ``00001.sql`` rather than the expected
    ``00001_create.sql``.

    Files with no numeric prefix (e.g. ``helpers.sql``) are ignored.
    """

    def check(self, schema_dir: Path) -> list[LintViolation]:
        """Run the check and return all violations found.

        Args:
            schema_dir: Root of the schema tree to scan.

        Returns:
            List of :class:`~confiture.core.linting.schema_linter.LintViolation`.
        """
        violations: list[LintViolation] = []

        for sql_file in schema_dir.rglob("*.sql"):
            if not sql_file.is_file():
                continue
            stem = sql_file.stem
            # Stem starts with a digit AND has no underscore → prefixed, no verb.
            if stem and stem[0].isdigit() and "_" not in stem:
                violations.append(
                    LintViolation(
                        rule_id="GEN002",
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
                )

        return violations


class Gen003GapPolicy:
    """GEN003 — Consecutive prefix values within a directory must be contiguous.

    Detects gaps in prefix sequences (step > 1 between adjacent values) and
    emits one WARNING per gap found.  A single-file or empty directory is
    always valid.

    This rule assumes a step of 1 between consecutive allocations, which is
    the default for :class:`~confiture.core.tree_allocator.TreeAllocator`.
    """

    def check(self, schema_dir: Path) -> list[LintViolation]:
        """Run the check and return all violations found.

        Args:
            schema_dir: Root of the schema tree to scan.

        Returns:
            List of :class:`~confiture.core.linting.schema_linter.LintViolation`.
        """
        violations: list[LintViolation] = []

        for directory in _all_dirs(schema_dir):
            values: list[int] = []
            for sql_file in _sql_files_in(directory):
                val = _parse_prefix_value(sql_file.name)
                if val is not None:
                    values.append(val)

            if len(values) < 2:
                continue

            values.sort()
            for i in range(1, len(values)):
                if values[i] - values[i - 1] > 1:
                    violations.append(
                        LintViolation(
                            rule_id="GEN003",
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
                    )

        return violations


class Gen004OrphanedOverride:
    """GEN004 — Every file in the overrides mirror must match a schema file.

    When a file exists in ``overrides_dir`` but its counterpart is absent
    from ``schema_dir``, it is an orphaned override — the generated file
    was deleted or moved without cleaning up the override.
    """

    def check(self, schema_dir: Path, overrides_dir: Path) -> list[LintViolation]:
        """Run the check and return all violations found.

        Args:
            schema_dir: Root of the schema tree.
            overrides_dir: Root of the overrides mirror directory.

        Returns:
            List of :class:`~confiture.core.linting.schema_linter.LintViolation`.
        """
        violations: list[LintViolation] = []

        if not overrides_dir.exists():
            return violations

        for override_file in overrides_dir.rglob("*.sql"):
            if not override_file.is_file():
                continue
            try:
                rel = override_file.relative_to(overrides_dir)
            except ValueError:
                continue
            schema_counterpart = schema_dir / rel
            if not schema_counterpart.exists():
                violations.append(
                    LintViolation(
                        rule_id="GEN004",
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
